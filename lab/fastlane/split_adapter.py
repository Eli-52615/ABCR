"""真实 split 文件 → `item_pool._read_split()` 期望形状的**单向**适配层。

`data/splits/ifeval_zh_v1.json` 的真实结构是::

    {family, salt, split_hash, distribution, assignments}
    assignments: {"ifzh-0001": "calibration", "ifzh-0002": "dev", ...}   # 共 250 条

而 `abcr.explore.item_pool._read_split()` 要求::

    {"dev": [...], "calibration": [...], "holdout": [...]}

两者不兼容：原样 `build_dev_bundle(split_path=真实split)` 抛
`ContractError("bad_split", "split 必须包含 dev/calibration/holdout 列表")`。

适配方向是**单向**的：本模块把真实文件翻译成科学核心期望的形状，
**绝不修改 `item_pool._read_split()` 去迁就快道** —— 那是科学核心，
改它会波及正式 probe/qualification 链路。依赖只从 `lab/` 指向 `src/`。

为什么"三道闸自洽"曾经不够（V1 的阻断级缺陷）
--------------------------------------------
上一版只有内容自洽三道闸，其中最硬的一道是"用 `assign_split(family, item_id)`
逐条复算"。它的判据 `family` **读自那份不可信文件本身**——于是这道闸是用锁自己的
钥匙去验锁：

    把 family 改成 "not-ifeval"，再按这个 family 重算 assignments、
    distribution、split_hash 三处 → 三道闸全部 ACCEPTED。

实测后果不是抽象的：dev 桶从 42 题变成 47 题，其中 **40 题不是真正的 dev，
25 题原本属于 holdout**。"一切只碰 dev split" 与"数据异常明确停止"两条同时失守，
而页面上不会有任何异样。

结论：**自洽 ≠ 正确**。一份内部完全自洽的 split 可以描述任何一次切分；
要判断它是不是**我们这次实验该用的那一次**切分，判据必须来自文件之外。

仓内权威坐标（判据的来源）
------------------------
本模块把判据钉在三类**不受被校验文件影响**的坐标上：

===============  ==========================================================
坐标             权威来源
===============  ==========================================================
family           `FROZEN_FAMILY` —— 快道的固定题集（`08` §1「题集：
                 ifeval_zh_v1 的 dev」），代码常量，不从文件读
salt             `abcr.rig.splits.SALT` —— **协议常量**，在 src 里，
                 与 `constants.SPLIT_SALT` 同值；文件自述的 salt 只是待验值
dataset / split  仓内冻结件的字节身份（`FROZEN_SPLIT_SHA256` /
身份             `FROZEN_DATASET_SHA256`）与语义身份（`split_hash`、
                 distribution、题数、dev 桶摘要）
===============  ==========================================================

这些常量不是"我随手抄的数字"：`tests/probe/test_quick_loop.py` 里有一条回归
直接拿 `git cat-file blob HEAD:<路径>` 复算，确保它们与仓内**已提交**的冻结件
逐字节一致——常量一旦与仓库漂移，测试当场红。

两层 API，职责分明
----------------
``load_real_split(path, *, expected_family=FROZEN_FAMILY)``
    **内容级**校验：family / salt / 计数 / split_hash / 切分规则五道闸。
    判据 `expected_family` 由调用方从仓内常量给出，**缺省也是仓内常量**——
    没有任何一条路径会退回"读文件里的 family"。

``load_frozen_split(path=None → 仓内冻结 split)``
    **身份级**校验：先钉死"这就是仓内那一份冻结 split"（路径 + 字节 + 语义
    坐标），再走上面全部内容闸。快道运行路径只用这一个入口。

确定性要求
----------
`build_dev_bundle()` 用 ``source_hash = sha256(dataset_raw + b"\\0" + split_raw)``
参与 `bundle_id`。`split_raw` 是**本模块落盘文件的确切字节**，所以翻译必须
逐字节确定：一律走 `canonical_json`，键有序，不含时间戳。否则同一请求每次
产生不同 `bundle_id`，快道的幂等（"重复提交不重复造实验"）当场失效。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from abcr.control.contracts import canonical_json, sha256
from abcr.rig.splits import SALT, assign_split, split_hash

from lab.fastlane.errors import FastlaneError

#: `_read_split()` 强制要求的三个桶。顺序无关，缺一即 `bad_split`。
SPLIT_NAMES = ("calibration", "dev", "holdout")

REPO_ROOT = Path(__file__).resolve().parents[2]

# ─────────────────── 仓内权威坐标（判据来源，不从被校验文件读） ───────────────────
#: 快道的固定题集。`08` §1：「题集：ifeval_zh_v1 的 dev」，页面不允许改。
FROZEN_FAMILY = "ifeval_zh_v1"

#: 协议 salt。**取自 `abcr.rig.splits`（src 内的协议常量）**，不是文件自述值。
#: 文件里的 `salt` 字段只是一个待验字符串，对不上就是数据被改过。
FROZEN_SALT = SALT

FROZEN_SPLIT_PATH = REPO_ROOT / "data" / "splits" / f"{FROZEN_FAMILY}.json"
FROZEN_DATASET_PATH = REPO_ROOT / "data" / "benchmarks" / f"{FROZEN_FAMILY}.json"

#: 仓内冻结件的字节身份。与 `git cat-file blob HEAD:<路径>` 逐字节相符，
#: 由 `test_frozen_constants_match_the_committed_blobs` 每次回归复算守着。
FROZEN_SPLIT_SHA256 = "95be69231c2183b44fbdcdedb38398fcb48c699f8d573644ee31028c4db27b03"
FROZEN_DATASET_SHA256 = "d0642d787cab167485e718c41c5c01e454d5a623ce5ef85b1b39402730c5799f"

#: 语义身份：即便有人把 split 重新序列化（字节变了但内容没变），这几条也钉着。
FROZEN_SPLIT_HASH = "7d91ac0b415c95a4be2584071ac45d37ab938e85f6158903119f424749d70de7"
FROZEN_DISTRIBUTION = {"calibration": 91, "dev": 42, "holdout": 117}
FROZEN_ITEM_COUNT = 250
#: `sha256(canonical_json(sorted(dev_item_ids)))` —— 直接钉死"dev 就是这 42 题"。
#: 上一版缺陷里 dev 变成 47 题，这一条会当场发现。
FROZEN_DEV_DIGEST = "2ed213e6fdf364bfb8769b005be5c6962bd12c53d6387587d154267745e6fdc5"


def dev_digest(dev_item_ids_: list[str] | tuple[str, ...]) -> str:
    """dev 桶身份摘要。排序后 canonical_json，与顺序无关。"""
    return sha256(canonical_json(sorted(dev_item_ids_)))


def frozen_coordinates() -> dict[str, Any]:
    """把权威坐标摊开给体检页看。纯常量，不读盘。"""
    return {
        "family": FROZEN_FAMILY,
        "salt": FROZEN_SALT,
        "split_path": str(FROZEN_SPLIT_PATH),
        "split_sha256": FROZEN_SPLIT_SHA256,
        "split_hash": FROZEN_SPLIT_HASH,
        "dataset_path": str(FROZEN_DATASET_PATH),
        "dataset_sha256": FROZEN_DATASET_SHA256,
        "distribution": dict(FROZEN_DISTRIBUTION),
        "item_count": FROZEN_ITEM_COUNT,
        "dev_digest": FROZEN_DEV_DIGEST,
    }


def _assert_frozen_file(path: Path, *, expected_path: Path, expected_sha256: str,
                        label: str, missing_code: str, path_code: str,
                        bytes_code: str) -> bytes:
    """确认 `path` 就是仓内那一份冻结件，返回其字节。

    两道：**路径**必须是仓内冻结位置（防止把适配层指向一份长得像的替身），
    **字节**必须与冻结 sha256 相符（防止就地改仓内那一份）。
    两道都不看文件内容自述的任何字段——判据全部来自文件之外。
    """
    path = Path(path)
    resolved, expected_resolved = path.resolve(), Path(expected_path).resolve()
    if resolved != expected_resolved:
        raise FastlaneError(
            path_code,
            f"{label}只接受仓内冻结路径，收到别处的文件——快道不跑仓外数据",
            {"given": str(resolved), "frozen": str(expected_resolved)})
    if not path.exists():
        raise FastlaneError(missing_code, f"仓内冻结{label}不存在: {path}",
                            {"path": str(path)})
    raw = path.read_bytes()
    observed = sha256(raw)
    if observed != expected_sha256:
        raise FastlaneError(
            bytes_code,
            f"{label}与仓内冻结身份不符——文件被改过，实验必须停止",
            {"path": str(path), "frozen_sha256": expected_sha256,
             "observed_sha256": observed, "observed_bytes": len(raw)})
    return raw


def assert_frozen_dataset(dataset_path: Path | None = None) -> str:
    """数据集身份闸。返回其 sha256。

    split 钉住了"哪些 item_id 属于 dev"，**钉不住那些 item 的题面**。
    题面被换掉时 item_id 一个字不变，两轮实验看起来完全可比，实际跑的却是
    另一批题。所以数据集要有自己的身份闸，与 split 同级。
    """
    # 缺省值在**调用时**取，不写进函数签名：签名里的默认值是 def 时就绑死的，
    # 测试改了 `FROZEN_DATASET_PATH` 而这里仍指向旧对象，会得到一条看起来通过
    # 实则验错了文件的绿灯。
    dataset_path = FROZEN_DATASET_PATH if dataset_path is None else dataset_path
    _assert_frozen_file(dataset_path, expected_path=FROZEN_DATASET_PATH,
                        expected_sha256=FROZEN_DATASET_SHA256, label="数据集",
                        missing_code="dataset_missing",
                        path_code="dataset_not_frozen_path",
                        bytes_code="dataset_bytes_not_frozen")
    return FROZEN_DATASET_SHA256


def load_real_split(split_path: Path, *,
                    expected_family: str = FROZEN_FAMILY) -> dict[str, Any]:
    """读一份 split 文件并过**内容五道闸**，返回原始 dict 与反转后的三个桶。

    `expected_family` 是判据，**永远来自调用方（仓内常量）**，绝不从文件里读。
    上一版正是在这里失守：拿文件自述的 family 去复算文件自述的 assignments，
    自洽即通过，于是 holdout 可以被改名成 dev。

    全程 fail-closed。**缺字段不等于通过**：`distribution` / `split_hash` /
    `family` / `salt` 任何一项缺席或类型不对都是失败，而不是"这条闸这次不查"。
    """
    if not isinstance(expected_family, str) or not expected_family:
        raise FastlaneError("bad_expected_family",
                            "expected_family 必须是非空字符串（判据不能为空）")
    raw = Path(split_path).read_bytes()
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise FastlaneError("bad_split", f"split JSON 无法解析: {exc}") from exc
    if not isinstance(data, dict):
        raise FastlaneError("bad_split", "split 顶层必须是对象")

    # ── 闸 0a：family 必须是快道固定的那个题集（判据在仓内，不在文件里）──
    family = data.get("family")
    if not isinstance(family, str) or not family:
        raise FastlaneError("bad_split", "split 缺少 family 字段，无法复算切分规则")
    if family != expected_family:
        raise FastlaneError(
            "split_family_mismatch",
            f"split 声明的 family 是 {family!r}，而快道只跑 {expected_family!r}。"
            "换 family 会整体改变切分结果——holdout 会被算成 dev，实验必须停止",
            {"declared": family, "expected": expected_family})

    # ── 闸 0b：salt 必须是协议常量（同样是仓内判据）──
    salt = data.get("salt")
    if salt != FROZEN_SALT:
        raise FastlaneError(
            "split_salt_mismatch",
            f"split 声明的 salt 与协议常量不符（协议 salt 定义在 abcr.rig.splits）",
            {"declared": salt, "expected": FROZEN_SALT})

    assignments = data.get("assignments")
    if not isinstance(assignments, dict) or not assignments:
        raise FastlaneError("bad_split", "split 缺少非空 assignments 映射")

    # ── 闸 1：反转，并与文件自述的 distribution 交叉核对 ──
    buckets: dict[str, list[str]] = {name: [] for name in SPLIT_NAMES}
    for item_id, bucket in sorted(assignments.items()):
        if not isinstance(item_id, str) or not item_id:
            raise FastlaneError("bad_split", "assignments 的 item_id 必须是非空字符串")
        if bucket not in buckets:
            raise FastlaneError("bad_split",
                                f"未知的 split 桶名: {bucket!r}（合法值 {SPLIT_NAMES}）")
        buckets[bucket].append(item_id)

    observed = {name: len(ids) for name, ids in buckets.items()}
    distribution = data.get("distribution")
    if not isinstance(distribution, dict):
        raise FastlaneError("split_distribution_missing",
                            "split 缺少 distribution 字段——缺失不是通过，拒绝继续",
                            {"observed": observed})
    declared = {name: distribution.get(name) for name in SPLIT_NAMES}
    if declared != observed:
        raise FastlaneError("split_distribution_mismatch",
                            "assignments 反转结果与文件自带 distribution 不一致",
                            {"declared": declared, "observed": observed})

    # ── 闸 2：split_hash 自洽 ──
    declared_hash = data.get("split_hash")
    recomputed_hash = split_hash(assignments)
    if not isinstance(declared_hash, str) or declared_hash != recomputed_hash:
        raise FastlaneError("split_hash_mismatch",
                            "split_hash 与 assignments 复算结果不符",
                            {"declared": declared_hash, "recomputed": recomputed_hash})

    # ── 闸 3：切分规则复算 —— 判据用 expected_family，不用文件自述的 family ──
    # 用 expected_family 复算是这一版与上一版的分水岭：即便闸 0a 被绕过，
    # 这里也只认仓内那个题集算出来的切分。
    mismatched = [item_id for item_id, bucket in assignments.items()
                  if assign_split(expected_family, item_id) != bucket]
    if mismatched:
        raise FastlaneError(
            "split_rule_mismatch",
            f"{len(mismatched)} 条 assignment 与确定性切分规则不符——"
            f"切分只由 sha256({expected_family}:item_id:{FROZEN_SALT}) 决定，"
            "对不上即数据被改过",
            {"count": len(mismatched), "sample": sorted(mismatched)[:5]})

    return {"data": data, "buckets": buckets, "family": expected_family,
            "salt": FROZEN_SALT, "split_hash": recomputed_hash,
            "source_sha256": sha256(raw), "source_bytes": len(raw),
            "dev_digest": dev_digest(buckets["dev"])}


def load_frozen_split(split_path: Path | None = None) -> dict[str, Any]:
    """快道运行路径**唯一**的 split 入口：先钉身份，再过内容闸。

    顺序是有意的。身份闸（路径 + 字节）先跑，所以"仓内那一份被就地改了"
    在读出任何内容之前就被拦下；内容闸随后仍然全跑，因为字节相同不代表
    我们对内容的理解正确——两层都要在。
    """
    split_path = FROZEN_SPLIT_PATH if split_path is None else split_path
    _assert_frozen_file(split_path, expected_path=FROZEN_SPLIT_PATH,
                        expected_sha256=FROZEN_SPLIT_SHA256, label="split",
                        missing_code="split_missing",
                        path_code="split_not_frozen_path",
                        bytes_code="split_bytes_not_frozen")
    loaded = load_real_split(split_path, expected_family=FROZEN_FAMILY)

    # 语义坐标：字节闸已经很硬，这一层管的是"字节相同但我们读错了"以及
    # 将来有人重新序列化冻结件的情形。逐项列出分歧，不只说一句"不匹配"。
    counts = {name: len(ids) for name, ids in loaded["buckets"].items()}
    divergent: dict[str, dict[str, Any]] = {}
    for name, observed, expected in (
            ("split_hash", loaded["split_hash"], FROZEN_SPLIT_HASH),
            ("distribution", counts, dict(FROZEN_DISTRIBUTION)),
            ("item_count", sum(counts.values()), FROZEN_ITEM_COUNT),
            ("dev_digest", loaded["dev_digest"], FROZEN_DEV_DIGEST)):
        if observed != expected:
            divergent[name] = {"observed": observed, "expected": expected}
    if divergent:
        raise FastlaneError(
            "split_identity_mismatch",
            "split 内容自洽，但**不是**仓内冻结的那一次切分——"
            "自洽只说明它描述了某一次切分，不说明是我们该跑的那一次",
            divergent)
    return loaded


def materialize_split(split_path: Path, output_dir: Path) -> Path:
    """把仓内冻结 split 翻译成 `_read_split()` 认得的形状并落盘，返回落盘路径。

    落盘内容除三个必需列表外，另带一个 `_source` 块，记录**已验证的**权威坐标：
    family / salt 写的是仓内常量（不是文件自述值），并带原文件完整字节的 sha256
    与 dev 桶摘要。

    `_source` 不是装饰：它进入 `split_raw`，因而进入 `build_dev_bundle()` 的
    `source_hash` 与 `bundle_id`。原 split 文件被改动一个字节，`source_sha256`
    就变，`bundle_id` 随之变——旧 bundle 不会被静默复用。
    """
    loaded = load_frozen_split(split_path)
    payload: dict[str, Any] = {name: loaded["buckets"][name] for name in SPLIT_NAMES}
    payload["_source"] = {
        "adapter": "lab.fastlane.split_adapter/v3",
        "family": loaded["family"],            # 仓内常量，已与文件核对一致
        "salt": loaded["salt"],                # 协议常量，已与文件核对一致
        "split_hash": loaded["split_hash"],
        "source_sha256": loaded["source_sha256"],
        "source_bytes": loaded["source_bytes"],
        "dataset_sha256": assert_frozen_dataset(),
        "dev_digest": loaded["dev_digest"],
        "counts": {name: len(loaded["buckets"][name]) for name in SPLIT_NAMES},
    }
    blob = canonical_json(payload) + b"\n"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # 内容寻址：同一原始 split 永远映射到同一个文件名，重跑不产生新字节。
    target = output_dir / f"split-{sha256(blob)[:16]}.json"
    if not target.exists():
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(blob)
        tmp.replace(target)
    elif target.read_bytes() != blob:  # pragma: no cover - 只可能在 sha256 碰撞时发生
        raise FastlaneError("split_collision", "同名适配 split 内容冲突")
    return target


def dev_item_ids(split_path: Path | None = None) -> tuple[str, ...]:
    """仓内冻结 split 中 dev 桶的全部 item_id（已排序）。供容量检查与体检展示。"""
    return tuple(load_frozen_split(split_path)["buckets"]["dev"])
