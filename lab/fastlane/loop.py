"""最小快道的核心：run / list / show / revise。

这一层是**薄入口**，不是第二套实验引擎。真正的科学工作全部由现有核心完成：

===========================  ===============================================
现有核心（不重写）            它已经提供的东西
===========================  ===============================================
`ProbeRequest.arm_ids`       vanilla 臂是结构性的，调用方无法省略
`run_probe()`                同 item / 同 seed 配对、`row_hash`、
                             `citable=False`、每 run 重验模型指纹
`OllamaProbeEngine`          端点白名单结构性排除 `/api/pull`（不下载模型）
`build_dev_bundle()`         确定性选题 + itempool 封印
`iter_bundle_items()`        读 bundle 必过封印验签与 `split == "dev"`
`ProbeNotebook`              内容寻址、append-only、篡改检测
`score_item()`               全部确定性指标
===========================  ===============================================

本模块只加三件核心没有的东西：**人用的请求形状**、**结果整理**、**轮次历史**。

边界（`08` §5）
--------------
只写 `lab/runs/` 自己的目录树。不碰正式 ledger、控制面、证据目录，
不接 broker/spool，不做 release/finalize，不装 launchd，不执行 genesis。
③L 与 judge 全程关闭。所有产物 `citable=false`。

为什么快道自建封印密钥
--------------------
`build_dev_bundle()` 的 `sealer_private_key` 无默认值（no default = no backdoor），
而系统信任根 `/Library/Application Support/ABCR-Trust/` 下**并没有**
`dev-bundle-sealer.pub`——安装它属于 root 部署，本轮明确不做。
故快道在自己的 `lab/runs/keys/` 下生成一对本地封印密钥，自签自验。
这与仓库现有全部非生产调用点（`tests/**` 十余处）的做法一致，
封印的科学语义（防 holdout 冒充 dev）在快道内部完整保留。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from abcr.control.contracts import ContractError, canonical_json, sha256, utc_now
from abcr.control.ed25519 import generate_keypair, public_fingerprint
from abcr.explore.item_pool import (DevBundleRef, SelectionRequest, build_dev_bundle,
                                    iter_bundle_items)
from abcr.probe.contracts import ProbePersona, ProbeRequest
from abcr.probe.engine import run_probe
from abcr.probe.notebook import ProbeNotebook
from abcr.probe.ollama_engine import OllamaEngineError, OllamaProbeEngine
from abcr.rig.scorer import SCORER_ID, SCORER_VERSION, score_item

from lab.fastlane.errors import FastlaneError
from lab.fastlane.split_adapter import (FROZEN_DATASET_PATH, FROZEN_FAMILY,
                                        FROZEN_SPLIT_PATH, assert_frozen_dataset,
                                        load_frozen_split, materialize_split)

#: 引擎侧可能冒出来、但**不是** `OllamaEngineError` 的异常。
#: `generate()` 里 `urlopen(timeout=600.0)` 读超时抛的是 builtins 的
#: `TimeoutError`（`OSError` 子类），不在引擎自己的异常层级里；socket 层的
#: 连接错误同理。不把这两类接住，一次坏请求会以未分类异常逃逸出去。
ENGINE_FAILURES = (OllamaEngineError, TimeoutError, OSError)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 快道的固定坐标。页面**不允许**临时改这些，避免实验之间漂移（`08` §1）。
#: 题集与数据路径**转引** `split_adapter` 的冻结常量，不在这里另抄一份——
#: 两处各写一份就会出现"校验用 A、跑实验用 B"的缝，那正是本轮要闭合的形态。
FAMILY = FROZEN_FAMILY
MODEL_PROFILE = "qwen25-7b-q4-v1"
PROFILE_PATH = REPO_ROOT / "configs" / "probe" / "profiles" / f"{MODEL_PROFILE}.json"
DATASET_PATH = FROZEN_DATASET_PATH
SPLIT_PATH = FROZEN_SPLIT_PATH

#: 快道全部轮次共用一个 goal。`build_dev_bundle()` 的选题排序是
#: ``sha256(f"{goal_hash}:{seed}:{item_id}")``，goal 固定后
#: 同 seed + 同题量恒选同一批题——改假设时题目不漂移，两轮才可比。
GOAL_HASH = sha256(b"abcr.fastlane.local-learning.v1")

#: `bundle_id = sha256(manifest_core)`，而 `manifest_core` 含 `created_at`，
#: 缺省是 `utc_now()`。不钉死它，同一请求每次都会造出新 bundle——
#: "重复提交不重复造实验" 会在这里静默失守。这个常量就是钉子。
BUNDLE_CREATED_AT = "2026-01-01T00:00:00+00:00"

MAX_ITEMS = 20
MIN_ITEMS = 1
DEFAULT_ITEMS = 20
DEFAULT_SEED = 1
MAX_OUTPUT_TOKENS = 256

#: 真实轮次的 probe_id 前缀；夹具轮次用另一个前缀，见 `probe_id_for()`。
REAL_PREFIX = "fl-"
FIXTURE_PREFIX = "fx-"

#: 页面与每一行都必须带的性质标签。核心已把 `citable=False` 写死在行里，
#: 这里只是把同一句话带到人眼前。
NOT_CITABLE_LABEL = "学习数据 · 不可引用"

#: `ProbeRequest.prediction` 契约：单行、非空、UTF-8 ≤ 8192 字节。
#: 人在页面上会自然地按多行写假设，故要有一个看得懂的折叠符。
#: 注意它**不是单射**：`"a\n b"` 与 `"a / b"` 折叠后完全相同，因而是同一次实验、
#: 同一个 probe_id。这是有意的（排版差异不构成新实验），但也意味着不能
#: 从折叠结果反推原始换行——原文另存在轮次记录的 `hypothesis_raw` 里。
_LINE_JOINER = " / "
_PREDICTION_MAX_BYTES = 8192
_PERSONA_MAX_CHARS = 65536


def lab_root() -> Path:
    """快道数据根。`ABCR_FASTLANE_ROOT` 可覆盖（测试用），默认 `<repo>/lab/runs`。"""
    override = os.environ.get("ABCR_FASTLANE_ROOT")
    return Path(override) if override else REPO_ROOT / "lab" / "runs"


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def keys(self) -> Path: return self.root / "keys"
    @property
    def sealer_private(self) -> Path: return self.keys / "sealer.key"
    @property
    def sealer_public(self) -> Path: return self.keys / "sealer.pub"
    @property
    def splits(self) -> Path: return self.root / "splits"
    @property
    def bundles(self) -> Path: return self.root / "bundles"
    @property
    def notebook(self) -> Path: return self.root / "notebook"
    @property
    def rounds(self) -> Path: return self.root / "rounds"
    @property
    def index(self) -> Path: return self.rounds / "index.jsonl"
    @property
    def keyid(self) -> Path: return self.keys / "KEYID"

    def round_file(self, probe_id: str) -> Path:
        return self.rounds / f"{probe_id}.json"


def paths() -> Paths:
    return Paths(lab_root())


def ensure_sealer_keys(p: Paths) -> tuple[Path, Path]:
    """确保快道本地封印密钥存在（首次运行时生成）。私钥 0600，`.gitignore` 已挡。

    这里有一个不那么显然的坑：`bundle_id` 只由选题内容决定，**不含密钥**。
    所以密钥丢了以后重新铸一把，`build_dev_bundle()` 会发现同名 bundle 目录
    内容一致而直接复用——**连同用旧密钥签的 `seal.json`**。于是不仅旧轮次
    读不出来，同 count/seed 的**新实验也跑不了**（`bundle_seal_invalid`），
    整个 lab 目录被静默砖化，且没有任何提示告诉人发生了什么。

    对策：把公钥指纹钉在 `keys/KEYID` 上。要铸新钥而 `bundles/` 里已有东西时，
    与其闷声铸一把注定验不过的钥，不如当场说清楚该清哪个目录。
    """
    have_private, have_public = p.sealer_private.exists(), p.sealer_public.exists()
    if have_private and have_public:
        _assert_key_identity(p)
        return p.sealer_private, p.sealer_public
    if have_private or have_public:
        raise FastlaneError("sealer_keypair_incomplete",
                            "快道封印密钥只剩半对，拒绝在残缺信任根上继续；"
                            f"请检查并清理 {p.keys}")
    if p.bundles.exists() and any(p.bundles.iterdir()):
        raise FastlaneError(
            "sealer_key_lost",
            "封印密钥不见了，但 bundles/ 里还有用旧密钥签过的 dev bundle。"
            "现在铸新钥只会得到一堆验不过的 bundle（旧轮读不出、新实验也跑不了）。"
            f"请先删除 {p.bundles} 后重来——那里只有可重建的题目副本，没有实验结果。",
            {"bundles": str(p.bundles), "keys": str(p.keys)})
    p.keys.mkdir(parents=True, exist_ok=True)
    generate_keypair(p.sealer_private, p.sealer_public)
    os.chmod(p.keys, 0o700)
    p.keyid.write_text(public_fingerprint(p.sealer_public) + "\n", encoding="utf-8")
    return p.sealer_private, p.sealer_public


def _assert_key_identity(p: Paths) -> None:
    """公钥换过而 KEYID 没换 → 所有既有 bundle 都会验不过，提前说清楚。"""
    fingerprint = public_fingerprint(p.sealer_public)
    if not p.keyid.exists():
        p.keyid.write_text(fingerprint + "\n", encoding="utf-8")
        return
    recorded = p.keyid.read_text(encoding="utf-8").strip()
    if recorded != fingerprint:
        raise FastlaneError(
            "sealer_key_rotated",
            "封印公钥与 keys/KEYID 记录的不是同一把——既有 dev bundle 会全部验不过。"
            f"要换钥就连同 {p.bundles} 一起清掉。",
            {"recorded": recorded, "observed": fingerprint})


def sealer_fingerprint(p: Paths) -> str:
    ensure_sealer_keys(p)
    return public_fingerprint(p.sealer_public)


# ────────────────────────── 请求规范化 ──────────────────────────
def normalize_prediction(raw: str) -> str:
    """把人写的多行假设折成 `ProbeRequest` 要的单行，不静默截断。

    核心契约拒绝含换行的 prediction，也拒绝超 8192 字节的。二者都是硬边界：
    超长时**报错**而不是砍掉尾巴——砍掉的那半句正是假设最关键的部分。
    """
    if not isinstance(raw, str):
        raise FastlaneError("bad_prediction", "假设必须是文本")
    lines = [seg.strip() for seg in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    folded = _LINE_JOINER.join(seg for seg in lines if seg)
    if not folded:
        raise FastlaneError("bad_prediction", "本轮假设/预测必填，不能为空")
    size = len(folded.encode("utf-8"))
    if size > _PREDICTION_MAX_BYTES:
        raise FastlaneError("prediction_too_long",
                            f"假设折成单行后 {size} 字节，超过核心契约上限 "
                            f"{_PREDICTION_MAX_BYTES} 字节，请自行精简（快道不替你截断）",
                            {"bytes": size, "limit": _PREDICTION_MAX_BYTES})
    return folded


def normalize_persona(raw: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise FastlaneError("bad_persona", "人格文本必填，不能为空")
    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) > _PERSONA_MAX_CHARS:
        raise FastlaneError("persona_too_long",
                            f"人格文本 {len(text)} 字符，超过核心契约上限 {_PERSONA_MAX_CHARS}",
                            {"chars": len(text), "limit": _PERSONA_MAX_CHARS})
    return text


def persona_ref_for(persona_text: str) -> str:
    """人格引用由**内容**派生，不靠递增计数器。

    同一段人格文本永远得到同一个 `persona_ref`，改一个字就换 ref。
    `ProbePersona.arm_id` 是 `persona:{persona_ref}`，所以这条保证了
    "两个不同人格被藏在同一个臂标签下" 结构上不可能发生。
    """
    return f"fastlane-p@{sha256(persona_text.encode('utf-8'))[:12]}"


def normalize_count(raw: Any) -> int:
    """题量必须是**整数**。

    刻意不写 `int(raw)`：那会把 `2.9` 悄悄变成 `2`，把 `True` 变成 `1`。
    "少跑了一题而没人知道" 正是本轮最不能接受的失败形态（完成标准 5），
    在入口处就不能给它留缝。核心 `contracts.py` 到处显式排除 bool，同一口径。
    """
    if isinstance(raw, bool):
        raise FastlaneError("bad_count", f"题量必须是 {MIN_ITEMS}–{MAX_ITEMS} 的整数")
    if isinstance(raw, float) and not raw.is_integer():
        raise FastlaneError("bad_count", f"题量必须是整数，收到 {raw!r}（快道不替你取整）")
    if isinstance(raw, str):
        text = raw.strip()
        if not text.lstrip("+-").isdigit():
            raise FastlaneError("bad_count", f"题量必须是整数，收到 {raw!r}")
        raw = text
    try:
        count = int(raw)
    except (TypeError, ValueError):
        raise FastlaneError("bad_count", f"题量必须是 {MIN_ITEMS}–{MAX_ITEMS} 的整数") from None
    if not MIN_ITEMS <= count <= MAX_ITEMS:
        raise FastlaneError("bad_count",
                            f"题量必须在 {MIN_ITEMS}–{MAX_ITEMS} 之间，收到 {count}",
                            {"count": count})
    return count


def normalize_seed(raw: Any) -> int:
    if raw is None or raw == "":
        return DEFAULT_SEED
    if isinstance(raw, bool):
        raise FastlaneError("bad_seed", "seed 必须是整数")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise FastlaneError("bad_seed", f"seed 必须是整数，收到 {raw!r}") from None


@dataclass(frozen=True)
class RoundSpec:
    """一轮实验的人类输入，规范化后的形态。"""

    prediction: str
    persona_text: str
    count: int = DEFAULT_ITEMS
    seed: int = DEFAULT_SEED
    hypothesis_raw: str = ""
    parent_probe_id: str | None = None

    @property
    def persona_ref(self) -> str:
        return persona_ref_for(self.persona_text)


def build_spec(*, hypothesis: str, persona_text: str, count: Any = DEFAULT_ITEMS,
               seed: Any = DEFAULT_SEED, parent_probe_id: str | None = None) -> RoundSpec:
    return RoundSpec(
        prediction=normalize_prediction(hypothesis),
        persona_text=normalize_persona(persona_text),
        count=normalize_count(count),
        seed=normalize_seed(seed),
        hypothesis_raw=hypothesis if isinstance(hypothesis, str) else "",
        parent_probe_id=parent_probe_id or None,
    )


def _file_sha256(path: Path) -> str:
    return sha256(Path(path).read_bytes())


def request_fingerprint(spec: RoundSpec, *, engine_profile: str = MODEL_PROFILE) -> str:
    """一次实验请求的身份。

    **`parent_probe_id` 刻意不在指纹里**：血缘是历史记录，不是实验条件。
    "复制上一轮但一个字都没改" 应当回到原来那一轮（这正是完成标准 4 要的
    "重复提交同一次请求不会重复造实验"），而不是造一条内容全同、只有父指针
    不同的孪生轮。

    `hypothesis_raw` 同样不在指纹里：进入实验的是折叠后的 `prediction`，
    只改假设的排版不构成新实验。

    **`engine_profile` 与判分器版本在指纹里**：换了模型或换了判分口径，
    同一句假设就是另一次实验，不能复用旧结果。
    """
    return sha256({
        "schema": "abcr.fastlane.request/v2",
        "family": FAMILY,
        "goal_hash": GOAL_HASH,
        "model_profile": engine_profile,
        "scorer_id": SCORER_ID,
        "scorer_version": SCORER_VERSION,
        "prediction": spec.prediction,
        "persona_ref": spec.persona_ref,
        "persona_sha256": sha256(spec.persona_text.encode("utf-8")),
        "count": spec.count,
        "seed": spec.seed,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "with_length_control": False,
        "dataset_sha256": _file_sha256(DATASET_PATH),
        "split_sha256": _file_sha256(SPLIT_PATH),
    })


def probe_id_for(spec: RoundSpec, *, engine_profile: str = MODEL_PROFILE) -> str:
    """轮次身份。夹具轮与真机轮**物理隔离**，前缀不同、指纹也不同。

    没有这条隔离会出一个很难发现的事故：夹具跑一轮后，人提交同一份请求，
    `read_round()` 直接命中并返回 `reused=True`——**夹具数字被当成真机结果
    交付出去**，而且交付路径上模型根本没被调用过。这正是"夹具的绿灯冒充
    真实验证"。用不同前缀 + 把 `engine_profile` 写进指纹，让它在结构上不可能发生。
    """
    prefix = REAL_PREFIX if engine_profile == MODEL_PROFILE else FIXTURE_PREFIX
    return f"{prefix}{request_fingerprint(spec, engine_profile=engine_profile)[:24]}"


# ────────────────────────── 运行 ──────────────────────────
def _dev_bundle(p: Paths, spec: RoundSpec) -> DevBundleRef:
    private, public = ensure_sealer_keys(p)
    # 两份仓内冻结件都要过身份闸再进 bundle：split 钉住"哪些题是 dev"，
    # dataset 钉住"这些题的题面是什么"。少一边，另一边就能被静默换掉。
    assert_frozen_dataset(DATASET_PATH)
    split_file = materialize_split(SPLIT_PATH, p.splits)
    request = SelectionRequest(
        request_id=f"fastlane-dev-{spec.count}-s{spec.seed}",
        goal_hash=GOAL_HASH,
        count=spec.count,
        seed=spec.seed,
        excluded_item_ids=(),
        created_at=BUNDLE_CREATED_AT,   # 钉死，见 BUNDLE_CREATED_AT 注释
    )
    return build_dev_bundle(request, dataset_path=DATASET_PATH, split_path=split_file,
                            output_root=p.bundles, sealer_private_key=private,
                            sealer_public_key=public)


def _bundle_items(p: Paths, ref: DevBundleRef) -> dict[str, dict[str, Any]]:
    """按 item_id 索引 bundle 里的题。读路径必过封印验签（`iter_bundle_items`）。"""
    _, public = ensure_sealer_keys(p)
    return {item["item_id"]: item
            for item in iter_bundle_items(ref, p.bundles, sealer_public_key=public)}


def assert_frozen_inputs() -> dict[str, str]:
    """**提交/复用路径的入口闸**：当前冻结 dataset + split 必须与仓内权威坐标相符。

    为什么必须在"这轮跑过没有"之前
    ------------------------------
    身份闸原本只长在 `_dev_bundle()` 上，而三条提交路径
    （`run_round()` / `web.start_round()` / CLI `cmd_run`）都在造 bundle **之前**
    就先 `read_round()`——已经跑过就直接返回。于是坏数据下会出现这一幕：

        坏 split 就位 → check 报 FAIL(rc=1) → 重提同一请求 → rc=0
        "该请求已经跑过，直接复用：fl-5954e857…"

    那一轮**恰恰是在这份坏 split 下产出的**（`request_fingerprint` 吃进
    `split_sha256`，所以坏 split 下算出的 probe_id 与旧轮一致，命中复用）。
    闸挡住了"再跑一次"，却挡不住"把上次坏数据的结果再交付一次"——
    交付一个数字和产生一个数字，在这里是同一件事。

    所以闸要前移到**任何可能交付结果的动作之前**，包括复用。

    读路径**刻意不挂这道闸**
    ----------------------
    `list_rounds()` / `read_round()` / `show` / `GET /round` 都不调用它。
    旧轮是历史事实，它的可读性不该取决于今天的冻结件是什么样——
    否则数据一坏，连"回去看当初到底跑了什么"都做不到，而那正是查清问题需要的。
    旧轮自身的可信度由 `record_hash` 与 notebook/bundle 的验签各自负责。
    """
    dataset_sha256 = assert_frozen_dataset(DATASET_PATH)
    split = load_frozen_split(SPLIT_PATH)
    return {"dataset_sha256": dataset_sha256, "split_sha256": split["source_sha256"]}


def make_engine() -> OllamaProbeEngine:
    """构造探针引擎。

    注意构造本身**不触网**：它只读冻结 profile 并核验后端二进制摘要。
    Ollama 到底可不可达，要到 `fingerprint()` / `generate()` 才知道，
    所以这里的失败一律是"profile 或后端二进制对不上"，不是"daemon 没起"。
    """
    if not PROFILE_PATH.exists():
        raise FastlaneError("profile_missing", f"冻结 profile 不存在: {PROFILE_PATH}")
    try:
        return OllamaProbeEngine(PROFILE_PATH)
    except OllamaEngineError as exc:
        raise FastlaneError("engine_profile_rejected",
                            f"冻结 profile 与本机后端对不上：{exc}") from exc
    except (OSError, ValueError) as exc:
        # profile 文件在 exists() 之后被删/被改坏（TOCTOU），或 JSON 解析失败。
        raise FastlaneError("profile_unreadable",
                            f"冻结 profile 读不出来：{type(exc).__name__}: {exc}") from exc


def run_round(spec: RoundSpec, *, engine: Any | None = None) -> dict[str, Any]:
    """跑一轮实验；已跑过的同一请求直接返回旧轮，不重复造实验。

    `engine` 只在测试里注入（`FakeProbeEngine`）。注入夹具引擎时轮次会落在
    `fx-` 前缀下、与真机轮次物理隔离，见 `probe_id_for()`。
    模型指纹由 `run_probe()` 每 run 重验一次。
    """
    # 第一件事就是身份闸，**在"跑过没有"之前**。复用也是一次交付，
    # 坏数据下不能因为"上次已经跑过"就把结果再端出来一次。见 assert_frozen_inputs()。
    assert_frozen_inputs()
    p = paths()
    engine = engine if engine is not None else make_engine()
    # probe_id 用**实际引擎**的 profile 算，不是配置常量——否则夹具轮会
    # 落在真机轮的身份上，并在下一次真实提交时被当作"已经跑过"复用。
    probe_id = probe_id_for(spec, engine_profile=engine.profile_id)
    existing = read_round(probe_id)
    if existing is not None:
        return dict(existing, reused=True)

    bundle = _dev_bundle(p, spec)
    items = _bundle_items(p, bundle)

    request = ProbeRequest(
        probe_id=probe_id,
        goal_hash=GOAL_HASH,
        dev_bundle=bundle,
        personas=(ProbePersona(spec.persona_ref, spec.persona_text),),
        prediction=spec.prediction,
        seed=spec.seed,
        model_profile=engine.profile_id,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        with_length_control=False,      # ③L 关闭（`08` §1/§5）
    )

    wall_started = time.monotonic()
    try:
        run = run_probe(request, engine, trusted_dev_bundle_root=p.bundles,
                        bundle_sealer_public_key=p.sealer_public)
    except ENGINE_FAILURES as exc:
        # 指纹漂移 / 模型缺失 / 后端不可达 / 600s 读超时：明确停止。
        # 不换模型、不下载、不上云、不降级为夹具。
        raise FastlaneError("engine_stopped", f"实验已停止：{exc}",
                            {"exception": type(exc).__name__}) from exc
    elapsed_ms = int((time.monotonic() - wall_started) * 1000)

    expected_rows = spec.count * len(request.arm_ids)
    if len(run.rows) != expected_rows:
        # 静默缩题是本轮最不能接受的失败形态（完成标准 5）。宁可整轮失败，
        # 而且要在写盘**之前**失败——半轮结果留在 notebook 里比没有更糟。
        raise FastlaneError(
            "row_count_mismatch",
            f"预期 {expected_rows} 行（{spec.count} 题 × {len(request.arm_ids)} 臂），"
            f"实得 {len(run.rows)} 行",
            {"expected": expected_rows, "actual": len(run.rows)})

    scored: list[dict[str, Any]] = []
    for row in run.rows:
        item = items.get(row["item_id"])
        if item is None:
            # bundle 与 notebook 行对不上说明状态已经错乱。给默认空 dict 只会
            # 让它在 score_item 里变成一个没有 code 的裸 KeyError('check_type')。
            raise FastlaneError(
                "item_missing_from_bundle",
                f"行引用的题 {row['item_id']!r} 不在本轮 dev bundle 里",
                {"item_id": row["item_id"], "bundle_id": bundle.bundle_id})
        metrics = score_item(FAMILY, item, row["output_text"], int(row["output_tokens"]))
        scored.append({"row_hash": row["row_hash"], "metrics": metrics})

    notebook = ProbeNotebook(p.notebook)
    for row in run.rows:
        notebook.append(row)                       # 内容寻址，重放不重复写

    record = {
        "schema_version": 2,
        "probe_id": probe_id,
        "parent_probe_id": spec.parent_probe_id,
        "request_fingerprint": request_fingerprint(spec, engine_profile=engine.profile_id),
        "family": FAMILY,
        "goal_hash": GOAL_HASH,
        # 如实记录**实际跑的引擎**，而不是配置里期望的那个。夹具轮已经靠
        # `fx-` 前缀与真机轮物理隔离，这里再留一道人眼可见的痕：页面见到
        # `fixture_engine` 会挂红字，不让夹具数字看起来像真机结果。
        "model_profile": engine.profile_id,
        "configured_model_profile": MODEL_PROFILE,
        "fixture_engine": engine.profile_id != MODEL_PROFILE,
        "scorer_id": SCORER_ID,
        "scorer_version": SCORER_VERSION,
        "sealer_fingerprint": public_fingerprint(p.sealer_public),
        "prediction": spec.prediction,
        "hypothesis_raw": spec.hypothesis_raw or spec.prediction,
        "persona_ref": spec.persona_ref,
        "persona_text": spec.persona_text,
        "persona_sha256": sha256(spec.persona_text.encode("utf-8")),
        "count": spec.count,
        "seed": spec.seed,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "with_length_control": False,
        "bundle_id": bundle.bundle_id,
        # manifest_hash / source_hash 必须存全：`verify_dev_bundle()` 逐字段比对
        # 引用与 manifest，少一个字段就无法在事后重建可信的 DevBundleRef。
        "bundle_manifest_hash": bundle.manifest_hash,
        "bundle_source_hash": bundle.source_hash,
        "item_ids": list(bundle.item_ids),
        "arm_ids": list(request.arm_ids),
        "row_hashes": [row["row_hash"] for row in run.rows],
        "row_count": len(run.rows),
        "expected_row_count": expected_rows,
        "scores": scored,
        "engine_fingerprint_sha256": run.rows[0]["engine_fingerprint_sha256"] if run.rows else "",
        "dataset_sha256": _file_sha256(DATASET_PATH),
        "split_sha256": _file_sha256(SPLIT_PATH),
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "elapsed_ms": elapsed_ms,
        "latency_ms_total": sum(int(row["latency_ms"]) for row in run.rows),
        "citable": run.citable,
        "label": NOT_CITABLE_LABEL,
        "evidence_class": "exploratory_learning_only",
        "recorded_at": utc_now(),
    }
    _write_round(p, record)
    return dict(record, reused=False)


def record_hash(record: dict[str, Any]) -> str:
    """轮次记录自身的内容摘要（排除 `record_hash` 字段本身后重算）。

    notebook 只锚定原始行，而人在页面上看的汇总数字（`scores`）住在这个
    轮次文件里。不给它一个 hash，改这里的数字不留任何痕迹。口径与
    `ProbeNotebook` 的 `row_hash` 一致：排除自身后 `sha256(canonical_json)`。
    """
    return sha256({k: v for k, v in record.items() if k != "record_hash"})


def _write_round(p: Paths, record: dict[str, Any]) -> Path:
    """原子落盘一条轮次记录并追加索引。已存在则不覆盖（append-only）。"""
    p.rounds.mkdir(parents=True, exist_ok=True)
    target = p.round_file(record["probe_id"])
    if not target.exists():
        sealed = dict(record, record_hash=record_hash(record))
        blob = canonical_json(sealed) + b"\n"
        # `with_suffix(".json.tmp")` 会把 `fl-x.json` 变成 `fl-x.json.tmp`，
        # 而 `glob("*-*.json")` 不匹配它——半写文件不会被 list_rounds 捡起。
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(blob)
        tmp.replace(target)
        entry = {"probe_id": record["probe_id"],
                 "parent_probe_id": record.get("parent_probe_id"),
                 "recorded_at": record["recorded_at"]}
        with p.index.open("ab") as fh:
            fh.write(canonical_json(entry) + b"\n")
    return target


# ────────────────────────── 读取 ──────────────────────────
#: 轮次记录必须有的字段与类型。
#:
#: 这份清单不是形式主义：列出来的每一项都是页面或 CLI **真的会去解引用**的东西
#: （`record["probe_id"]`、`record["bundle_id"]`、`for h in record["row_hashes"]` …）。
#: 少一项，坏轮就会以"看起来正常"的样子混进历史列表，直到点开详情才炸出一个
#: 没头没脑的 `KeyError: 'bundle_id'`——那时人已经把它当成一轮真实验看了。
#:
#: `record_hash` 也在必需之列。它缺席时旧版本走的是"没写就不查"，
#: 那是一条把 fail-closed 自己消解掉的出口：验不了就是不可信，不是默认可信。
_REQUIRED_ROUND_FIELDS: tuple[tuple[str, Any], ...] = (
    ("probe_id", str), ("record_hash", str), ("recorded_at", str),
    ("prediction", str), ("persona_text", str), ("count", int), ("seed", int),
    ("arm_ids", list), ("item_ids", list), ("row_hashes", list),
    ("bundle_id", str), ("citable", bool),
)


def _type_ok(value: Any, expected: Any) -> bool:
    """类型核对。`bool` 是 `int` 的子类，所以 `count=True` 必须算类型不对。"""
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, expected)


def _load_record(target: Path) -> dict[str, Any]:
    """读一条轮次记录，把**一切结构异常归一成 `FastlaneError`**。

    这里是历史页的边界。边界上漏掉一种形状，代价不是"那一条打不开"，而是
    **整个历史页打不开**：`json.loads` 对 `[]` 完全满意，随后 `record.get(...)`
    抛 `AttributeError`，异常穿过 `scan_rounds()`（它只接 `FastlaneError`/`OSError`）
    一路到兜底页——首页 500，两条好轮和那条坏轮一起从人眼前消失。
    一条文件写坏，等于整段历史不可见。

    所以顺序是：顶层形状 → 必需字段 → 类型 → 文件名与 `probe_id` 一致 →
    `record_hash` 复算。每一步都有稳定错误码，页面照着它说人话。
    """
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise FastlaneError("round_unreadable",
                            f"轮次文件读不出来: {target.name}（{exc}）") from exc
    try:
        record = json.loads(raw)
    except ValueError as exc:
        raise FastlaneError("round_unreadable", f"轮次文件无法解析: {target.name}") from exc

    if not isinstance(record, dict):
        raise FastlaneError(
            "round_malformed",
            f"轮次文件顶层不是对象（实际是 {type(record).__name__}）: {target.name}",
            {"file": target.name, "top_level_type": type(record).__name__})

    missing = [name for name, _ in _REQUIRED_ROUND_FIELDS if name not in record]
    if missing:
        raise FastlaneError(
            "round_incomplete",
            f"轮次记录缺少必需字段：{', '.join(missing)}——残缺的记录不能当作一轮实验",
            {"file": target.name, "missing": missing})

    wrong = [name for name, expected in _REQUIRED_ROUND_FIELDS
             if not _type_ok(record[name], expected)]
    if wrong:
        raise FastlaneError(
            "round_malformed",
            f"轮次记录的字段类型不对：{', '.join(wrong)}",
            {"file": target.name, "fields": wrong})

    if record["probe_id"] != target.stem:
        # 文件名与内容自述的 probe_id 不一致：按 `rounds/<probe_id>.json` 取回来的
        # 会是另一轮，页面上的链接与内容对不上。
        raise FastlaneError(
            "round_id_mismatch",
            f"轮次文件名与记录里的 probe_id 不一致：{target.name} vs {record['probe_id']}",
            {"file": target.name, "probe_id": record["probe_id"]})

    if record["record_hash"] != record_hash(record):
        raise FastlaneError("round_tampered",
                            f"轮次记录已被修改: {record['probe_id']}",
                            {"probe_id": record["probe_id"]})
    return record


def read_round(probe_id: str) -> dict[str, Any] | None:
    target = paths().round_file(probe_id)
    if not target.exists():
        return None
    return _load_record(target)


def scan_rounds() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """扫 rounds/ 目录，返回 `(可读轮次, 读不出来的轮次)`，最新在前。

    **坏轮不被丢掉。** 上一版这里把校验失败的记录 `continue` 掉了：一条被改过的
    轮次会从历史页上**整条消失**，而页面看起来一切正常——篡改的效果因此是
    "让证据无声地不存在"，比报错更糟。现在它照样出现在历史里，只是带着错误码，
    内容不予展示。

    单条坏记录也不该让整个历史页打不开，所以失败被降级成一条**可见的**条目，
    而不是异常。详情页仍会为它给出完整的人类错误页。
    """
    p = paths()
    if not p.rounds.exists():
        return [], []
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for target in sorted(p.rounds.iterdir()):
        if target.suffix != ".json" or not target.name.startswith((REAL_PREFIX, FIXTURE_PREFIX)):
            continue
        try:
            records.append(_load_record(target))
        except FastlaneError as exc:
            failures.append({"probe_id": target.stem, "code": exc.code,
                             "message": exc.message, "file": target.name})
        except Exception as exc:  # noqa: BLE001 - 见下
            # `_load_record()` 已经把已知的坏形状归一成 `FastlaneError` 了，
            # 这一条是最后一道：**一条文件写坏，绝不允许整段历史不可见**。
            # 兜底不是"当作没事"——它照样落成一条带错误码的可见失败，
            # 只是把异常类型也带上，方便查是哪种没被归一的新形状。
            failures.append({"probe_id": target.stem, "code": "round_unreadable",
                             "message": f"轮次文件读不出来：{type(exc).__name__}: {exc}",
                             "file": target.name})
    records.sort(key=lambda r: r.get("recorded_at", ""), reverse=True)
    failures.sort(key=lambda f: f["probe_id"], reverse=True)
    return records, failures


def list_rounds() -> list[dict[str, Any]]:
    """全部**可读**轮次，最新在前。读不出来的那些见 `scan_rounds()` 的第二项。

    夹具轮（`fx-`）与真机轮（`fl-`）都会列出来，页面按 `fixture_engine` 标红。
    """
    return scan_rounds()[0]


def round_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    """从 notebook 取回该轮全部原始行。每次读都做篡改校验（`ProbeNotebook.read`）。

    把 notebook 的三种失败翻译成快道自己的错误：不存在的 hash 抛的是
    `FileNotFoundError` 而**不是** `ContractError`，不映射的话页面上会看到
    一个没头没脑的 Errno 2。
    """
    notebook = ProbeNotebook(paths().notebook)
    rows = []
    for row_hash in record.get("row_hashes", []):
        try:
            rows.append(notebook.read(row_hash))
        except FileNotFoundError as exc:
            raise FastlaneError("row_missing",
                                f"notebook 里找不到这一行: {row_hash[:16]}…；"
                                "lab/runs/notebook 可能被清理过",
                                {"row_hash": row_hash}) from exc
        except ContractError as exc:
            raise FastlaneError(f"row_{exc.code}", f"notebook 行校验失败：{exc}",
                                {"row_hash": row_hash}) from exc
    return rows


def revise_spec(probe_id: str) -> RoundSpec:
    """"基于本轮新建"：把旧轮的输入原样预填，父指针指向它。

    只造 spec，不跑。人改完才跑——快道不自动改假设、不自动开下一轮（`08` §5）。
    """
    record = read_round(probe_id)
    if record is None:
        raise FastlaneError("round_not_found", f"没有这一轮: {probe_id}")
    return RoundSpec(
        prediction=record["prediction"],
        persona_text=record["persona_text"],
        count=int(record["count"]),
        seed=int(record["seed"]),
        hypothesis_raw=record.get("hypothesis_raw", record["prediction"]),
        parent_probe_id=probe_id,
    )


# ────────────────────────── 结果整理 ──────────────────────────
_MEAN_METRICS = ("is_correct", "parse_ok", "output_len_chars", "output_len_tokens",
                 "hedging_rate", "self_check_marker_rate")


def summarize(record: dict[str, Any], rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """按臂汇总确定性指标，并给出 persona − vanilla 的差值。

    只呈现观察结果。**不判断人格理论成立或失败**（`08` §2）——
    没有显著性检验、没有结论文案，差值就是差值。
    """
    by_hash = {row["row_hash"]: row for row in rows}
    scores = {entry["row_hash"]: entry["metrics"] for entry in record.get("scores", [])}
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row_hash, metrics in scores.items():
        row = by_hash.get(row_hash)
        if row is None:
            continue
        buckets.setdefault(row["arm_id"], []).append(metrics)

    arms: dict[str, dict[str, Any]] = {}
    for arm_id, entries in buckets.items():
        summary: dict[str, Any] = {"arm_id": arm_id, "n": len(entries), "metrics": {}}
        for name in _MEAN_METRICS:
            values = [float(entry[name]) for entry in entries if name in entry]
            summary["metrics"][name] = (sum(values) / len(values)) if values else None
        arms[arm_id] = summary

    persona_arm = next((a for a in record.get("arm_ids", []) if a.startswith("persona:")), None)
    deltas: dict[str, float | None] = {}
    if persona_arm and "vanilla" in arms and persona_arm in arms:
        for name in _MEAN_METRICS:
            base = arms["vanilla"]["metrics"].get(name)
            treat = arms[persona_arm]["metrics"].get(name)
            deltas[name] = None if base is None or treat is None else treat - base
    return {"arms": arms, "vanilla_arm": "vanilla", "persona_arm": persona_arm,
            "deltas": deltas, "citable": False, "label": NOT_CITABLE_LABEL}


def paired_items(record: dict[str, Any], rows: Iterable[dict[str, Any]],
                 items: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """逐题把两臂并排，附题目原文、原始输出、判分与 row hash。"""
    scores = {entry["row_hash"]: entry["metrics"] for entry in record.get("scores", [])}
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = grouped.setdefault(row["item_id"], {"item_id": row["item_id"], "arms": {}})
        entry["arms"][row["arm_id"]] = {
            "row_hash": row["row_hash"],
            "arm_kind": row["arm_kind"],
            "persona_ref": row.get("persona_ref"),
            "output_text": row["output_text"],
            "output_tokens": row["output_tokens"],
            "input_tokens": row["input_tokens"],
            "latency_ms": row["latency_ms"],
            "prompt_hash": row["prompt_hash"],
            "metrics": scores.get(row["row_hash"], {}),
        }
    items = items or {}
    ordered = []
    for item_id in record.get("item_ids", []):
        entry = grouped.get(item_id)
        if entry is None:
            continue
        item = items.get(item_id, {})
        entry["prompt"] = item.get("prompt", "")
        entry["check_type"] = item.get("check_type", "")
        ordered.append(entry)
    return ordered


def load_items_for(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """取回该轮的题目原文。

    刻意**不**直接读 `data/benchmarks/`：那条路绕过封印。这里重建完整的
    `DevBundleRef` 再走 `iter_bundle_items()`，于是 bundle 被改过、封印失效、
    或 split 标签被换成非 dev，都会在这里 fail-closed 而不是安静地显示旧题面。
    """
    p = paths()
    ref = DevBundleRef(
        bundle_id=record["bundle_id"],
        root=p.bundles / record["bundle_id"],
        manifest_hash=record.get("bundle_manifest_hash", ""),
        item_ids=tuple(record["item_ids"]),
        source_hash=record.get("bundle_source_hash", ""),
    )
    try:
        return _bundle_items(p, ref)
    except ContractError as exc:
        if exc.code == "bundle_files_unexpected":
            # 这个默认落在仓内 `lab/runs/bundles/`，是人会用 Finder 打开的目录，
            # 而 Finder 会往里丢 .DS_Store。核心要求文件集合**精确**，多一个就拒。
            raise FastlaneError(
                "bundle_files_unexpected",
                f"dev bundle 目录里混进了多余文件（常见是 Finder 留下的 .DS_Store）。"
                f"删掉 {ref.root} 里除 manifest.json / items.jsonl / seal.json "
                "以外的东西即可，题目会在下次运行时重建。",
                {"bundle": str(ref.root)}) from exc
        raise FastlaneError(f"bundle_{exc.code}", f"dev bundle 校验失败：{exc}",
                            {"bundle": str(ref.root)}) from exc
