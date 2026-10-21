"""abcr.ops.cloud — 云实例生命周期的账本登记与关机核验（B2-8）。

架构位置：ops(B) 记账层（**非控制层**）。W1 无供应商 API：AutoDL 类网页控制台，
楠开机付费=发射钮。本模块只把实例的 register/start/stop 与实耗登记进账本五链的
instances/costs 链（供 A 的预算对账、C 的同步视图、watchdog 的空转检测消费）。

事件→payload 键名系 AMENDMENT-9 冻结；业务主体 instance_id 落 subject_id
（AMENDMENT-4；watchdog.detect_instance_idle / triage 均按 subject_id 消费）。
"""
from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

from abcr.common import external_seal
from abcr.common.ledger_ref import GENESIS_HASH, RunLedger
from abcr.control.contracts import ContractError
from abcr.governor.envelope import envelope_sha256

LEDGER_DIR = Path("ledger")
COST_BASIS = "控制台账单实读"
# 自述实耗允许低于计量值的比例上限：账单四舍五入/秒级误差留 10%，再低就是"洗账"。
METER_UNDERREPORT_TOLERANCE = 0.10
KIND_STOP_ATTESTATION = "stop_attestation"


def build_cloud_dispatch_payload(envelope: dict) -> dict:
    """Build a cloud handoff that references sealed DevBundles, never corpus roots.

    Item bytes remain in the content-addressed bundle.  The payload carries only
    approved RunConfigs plus the finite bundle/receipt identities needed for the
    remote dispatch to re-verify them after transfer.
    """
    configs = envelope.get("run_configs")
    if not isinstance(configs, list) or not configs or not all(isinstance(cfg, dict) for cfg in configs):
        raise ContractError("cloud_run_configs_invalid", "cloud payload 需要内联 RunConfig 数组")
    forbidden = {"benchmark_root", "dataset_root", "dataset_path", "split_root", "split_path",
                 "full_dataset_roots", "benchmark_items", "items", "prompts"}

    def reject_roots(value: object) -> None:
        if isinstance(value, dict):
            bad = forbidden.intersection(value)
            if bad:
                raise ContractError("cloud_payload_full_corpus_forbidden",
                                    "cloud payload 禁止全量 benchmark/split 或嵌入题面",
                                    {"keys": sorted(bad)})
            for child in value.values():
                reject_roots(child)
        elif isinstance(value, list):
            for child in value:
                reject_roots(child)

    refs = []
    copied = copy.deepcopy(configs)
    for cfg in copied:
        reject_roots(cfg)
        ref = cfg.get("dev_bundle_ref")
        if not isinstance(ref, dict):
            raise ContractError("cloud_dev_bundle_ref_missing",
                                "cloud 证据执行只接受封印 DevBundleRef")
        if any(key in ref for key in ("root", "path")):
            raise ContractError("cloud_bundle_path_injection", "cloud bundle 引用不得携路径")
        refs.append(copy.deepcopy(ref))
    return {
        "schema": "abcr.cloud-dispatch-payload.v1",
        "batch_id": envelope.get("batch_id"),
        "approved_envelope_sha256": envelope_sha256(envelope),
        "dev_bundle_refs": refs,
        "run_configs": copied,
    }


# Stable short name for callers introduced by the 0719 checklist.
build_cloud_payload = build_cloud_dispatch_payload


def _instances(ledger_dir: Path) -> RunLedger:
    return RunLedger(Path(ledger_dir), "instances")


def _parse_ts(v: str | None) -> datetime | None:
    if not isinstance(v, str) or not v:
        return None
    try:
        d = datetime.fromisoformat(v)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def metered_cost_cny(led: RunLedger, instance_id: str,
                     now: datetime | None = None) -> tuple[float | None, str]:
    """按账本自身计量的应付成本：price_cny_per_h × (now − 最早未配对 instance_started)。

    返回 (金额, 说明)；无法计量（无 started / 时间戳非法）→ (None, 原因)。
    取**最早**未配对的 started：重复调 start（伪心跳）不得把计时器拨回去。
    """
    now = now or datetime.now(timezone.utc)
    starts = [e for e in led.events(event="instance_started", subject_id=instance_id)]
    if not starts:
        return None, "无 instance_started 事件，无法计量"
    stops = len(led.events(event="instance_stopped", subject_id=instance_id))
    unpaired = starts[stops:] if stops < len(starts) else []
    if not unpaired:
        return None, "所有 instance_started 均已配对，无进行中计费段"
    first = unpaired[0]
    started = _parse_ts(first.get("started_at")) or _parse_ts(first.get("ts"))
    chain_ts = _parse_ts(first.get("ts"))
    if started is None:
        return None, "instance_started 时间戳非法，无法计量"
    # payload.started_at 是可注入面；链上 ts 是挂链字段。自述晚于挂链时刻 = 篡改，
    # 一律回退到链上 ts（否则"把开机时间写成未来"就能把计量抹成 0）。
    if chain_ts is not None and started > chain_ts:
        started = chain_ts
    price = float(first.get("price_cny_per_h") or 0.0)
    hours = max((now - started).total_seconds(), 0.0) / 3600.0
    return price * hours, f"{price}/h × {hours:.3f}h"


def _costs(ledger_dir: Path) -> RunLedger:
    return RunLedger(Path(ledger_dir), "costs")


def _find_registered(led: RunLedger, instance_id: str) -> dict:
    evs = led.events(event="instance_registered", subject_id=instance_id)
    if not evs:
        raise ValueError(f"实例 {instance_id} 未登记（先 register）")
    return evs[-1]


def register(instance_id: str, vendor: str, spec: str, price_cny_per_h: float,
             batch_id: str, ledger_dir: Path = LEDGER_DIR) -> dict:
    """开机登记 → instances 链 instance_registered。"""
    led = _instances(ledger_dir)
    return led.append("instance_registered", subject_id=instance_id, vendor=vendor,
                      spec=spec, price_cny_per_h=float(price_cny_per_h), batch_id=batch_id)


def start(instance_id: str, ledger_dir: Path = LEDGER_DIR) -> dict:
    """标记实例开始计费 → instance_started（同键集，从 registered 复制）。"""
    led = _instances(ledger_dir)
    reg = _find_registered(led, instance_id)
    return led.append("instance_started", subject_id=instance_id,
                      vendor=reg["vendor"], spec=reg["spec"],
                      price_cny_per_h=reg["price_cny_per_h"], batch_id=reg["batch_id"])


def stop(instance_id: str, amount_cny: float, verified_by: str,
         ledger_dir: Path = LEDGER_DIR) -> tuple[dict, dict]:
    """关机核验后登记：instance_stopped（instances 链）+ run_cost_actual（costs 链）。

    关机核验清单（stop 前须逐项过，记入 verified 字段）：
      ① 产物已回传且 sha256 校验一致；② ssh 拒连或控制台=已关机；③ 账单页实耗已读数。

    入口 fail-closed（对抗根因②/③：空/负值被当合法自述冲减预算）：
      · amount_cny 必须是有限非负数——负成本会经 costs 链 run_cost_actual 直接
        冲减 budget_recon 的 total_actual_cny 求和，等于给预算"回血"，在源头拒掉；
      · verified_by 必须非空——关机核验是"云运动员自述"，至少不容许空白核验字段
        （谁核的、核了什么必须落痕，空字符串不构成核验证据）。

    自述 vs 计量交叉核对（对抗根因③：验船师问运动员）：
      实测击穿——一台已烧 3h（¥2.5/h ⇒ 计量 ¥7.5）的实例，调
      ``stop(iid, 0.0, "trust-me-已核验")`` 被逐字采信：instances 链出现配对、costs 链
      记 ¥0，于是 reconcile 判"配对完整"、running_estimate 归零，¥7.5 真实开销被洗掉。
      verified_by 只被检查非空，是纯自证；amount_cny 从不与"价 × 时长"对表。
      这里把账本自身的计量接成硬判据：自述实耗低于计量值 10% 以上一律拒绝入账。
      （高于计量值放行——账单可能含额外项，多报不构成"洗账"。）
      同时把这次核验自述 seal 进仓级规范锚存储（外部信任根，事后不可抵赖地改写）。
    """
    amt = float(amount_cny)
    if not (amt >= 0.0) or amt != amt or amt in (float("inf"), float("-inf")):
        raise ValueError(f"amount_cny 必须是有限非负数，got {amount_cny!r}（负/非有限成本会冲减预算）")
    if not (verified_by or "").strip():
        raise ValueError("verified_by 不得为空（关机核验证据必须落痕）")
    ins = _instances(ledger_dir)
    reg = _find_registered(ins, instance_id)
    batch_id = reg["batch_id"]

    metered, how = metered_cost_cny(ins, instance_id)
    if metered is not None and metered > 0.0:
        floor_amt = metered * (1.0 - METER_UNDERREPORT_TOLERANCE)
        if amt < floor_amt:
            raise ValueError(
                f"amount_cny={amt} 低于账本计量 ¥{metered:.2f}（{how}）逾 "
                f"{METER_UNDERREPORT_TOLERANCE:.0%}：自述实耗不得冲掉真实计量"
                f"（verified_by={verified_by!r} 是自证，不构成豁免）")

    stopped = ins.append("instance_stopped", subject_id=instance_id,
                         amount_cny=float(amount_cny), batch_id=batch_id,
                         verified=verified_by,
                         metered_cny=(round(metered, 4) if metered is not None else None))
    cost = _costs(ledger_dir).append(
        "run_cost_actual", subject_id=instance_id, amount_cny=float(amount_cny),
        basis=COST_BASIS, batch_id=batch_id, instance_id=instance_id)

    # 核验自述外部锚定 + 两链收口封印（生产调用点）：自述本身进规范锚存储，
    # instances/costs 两链的内容与条目数同时被承诺 → 事后截断/改写立即失配。
    # V09 防洗白：两链收口封印走 external_seal.guarded_reseal（seal-once + 前缀校验），
    # **不**用无条件覆盖的 led.seal_chain()——攻击者不能借下一次 cloud.stop() 触发
    # 无条件重封、把已被截断/改写的链洗成合规。截断/前缀改写 → ResealRefused，
    # 拒绝覆盖旧锚并 stderr 告警（不静默）。锚写入失败绝不吞掉已成功的关机记账。
    try:
        external_seal.guarded_reseal(
            KIND_STOP_ATTESTATION, instance_id, [stopped],
            extra={"verified_by": verified_by, "amount_cny": amt,
                   "metered_cny": metered, "metered_basis": how,
                   "batch_id": batch_id, "entry_hash": stopped.get("entry_hash")})
        for led in (ins, _costs(ledger_dir)):
            evs = led.events()
            tail = evs[-1]["entry_hash"] if evs else GENESIS_HASH
            external_seal.guarded_reseal(
                external_seal.KIND_LEDGER_CHAIN, led.run_id, evs,
                extra={"chain_path": str(led.path), "chain_tail": tail,
                       "sealed_by": "cloud.stop"},
                scope_extra_keys=("chain_path",))
    except external_seal.ResealRefused as e:
        print(f"[cloud.stop] 链重封拒绝（防洗白，锚未被覆盖）: {e}",
              file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001 —— 锚写入失败不得吞掉已成功的关机记账
        pass
    return stopped, cost


def idle_sim(instance_id: str, ledger_dir: Path = LEDGER_DIR) -> dict:
    """演练：写 instance_idle_alert（payload 必带 actor="drill"——AMENDMENT-17，
    演练账目可识别）。供 R2 故障演练三（实例空转模拟→A 预算告警）。"""
    ins = _instances(ledger_dir)
    # 允许未 register 的纯演练；有 register 则带上 batch_id
    evs = ins.events(event="instance_registered", subject_id=instance_id)
    batch_id = evs[-1]["batch_id"] if evs else "drill"
    return ins.append("instance_idle_alert", subject_id=instance_id,
                      actor="drill", batch_id=batch_id)
