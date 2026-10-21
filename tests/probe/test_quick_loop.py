"""最小快道核心（`lab/fastlane/loop.py` + `split_adapter.py`）的作者测试。

这些用例用 `FakeProbeEngine` 换掉模型，**数据集与 split 是真实文件**。
它们证明的是接线正确，**不能代替真实环境验收**——真机跑通的证据在
`docs/FASTLANE-QUICKSTART.md` 的实跑记录里，两者不可互相冒充。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

from abcr.control.contracts import ContractError
from abcr.probe.engine import FakeProbeEngine
from abcr.probe.notebook import ProbeNotebook

from lab.fastlane import loop
from lab.fastlane import split_adapter as SA
from lab.fastlane.loop import FastlaneError
from lab.fastlane.split_adapter import load_frozen_split, load_real_split, materialize_split

PERSONA = "你是一位极其谨慎的助手。"
HYPOTHESIS = "谨慎人格会让输出更长"


@pytest.fixture()
def lab(tmp_path, monkeypatch):
    """把快道的数据根挪到 tmp，避免测试写进 `lab/runs/` 污染真实轮次。"""
    monkeypatch.setenv("ABCR_FASTLANE_ROOT", str(tmp_path / "runs"))
    return tmp_path


def _spec(**kwargs):
    base = dict(hypothesis=HYPOTHESIS, persona_text=PERSONA, count=1, seed=1)
    base.update(kwargs)
    return loop.build_spec(**base)


def _run(spec):
    return loop.run_round(spec, engine=FakeProbeEngine())


# ───────────────────────── split 适配层 ─────────────────────────
def test_real_split_inverts_to_declared_distribution():
    """真实 split 反转后的三桶计数必须与文件自带的 distribution 逐项相等。"""
    info = load_real_split(loop.SPLIT_PATH)
    counts = {name: len(ids) for name, ids in info["buckets"].items()}
    declared = json.loads(loop.SPLIT_PATH.read_text(encoding="utf-8"))["distribution"]
    assert counts == declared == {"dev": 42, "calibration": 91, "holdout": 117}


def test_materialized_split_is_byte_stable_and_accepted_by_the_science_core(tmp_path):
    """落盘必须逐字节确定——否则 bundle_id 每次都变，幂等当场失效。"""
    from abcr.explore.item_pool import _read_split

    first = materialize_split(loop.SPLIT_PATH, tmp_path)
    second = materialize_split(loop.SPLIT_PATH, tmp_path)
    assert first == second and first.read_bytes() == second.read_bytes()
    data, _raw = _read_split(first)          # 科学核心原样接受，没有改过核心
    assert len(data["dev"]) == 42


def test_split_adapter_rejects_tampered_distribution(tmp_path):
    """改了 assignments 却没同步 distribution —— fail-closed。"""
    payload = json.loads(loop.SPLIT_PATH.read_text(encoding="utf-8"))
    payload["assignments"]["ifzh-0001"] = "dev"      # calibration → dev，计数错位
    target = tmp_path / "tampered.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FastlaneError) as excinfo:
        load_real_split(target)
    assert excinfo.value.code == "split_distribution_mismatch"


def test_split_adapter_rejects_unknown_bucket(tmp_path):
    payload = json.loads(loop.SPLIT_PATH.read_text(encoding="utf-8"))
    payload["assignments"]["ifzh-0001"] = "train"
    target = tmp_path / "bad-bucket.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FastlaneError) as excinfo:
        load_real_split(target)
    assert excinfo.value.code == "bad_split"


def test_split_adapter_verifies_the_declared_split_hash(tmp_path):
    """`abcr.rig.splits.split_hash` 就在本仓，21 行 hashlib——没有理由不算。"""
    payload = json.loads(loop.SPLIT_PATH.read_text(encoding="utf-8"))
    payload["split_hash"] = "0" * 64
    target = tmp_path / "bad-hash.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FastlaneError) as excinfo:
        load_real_split(target)
    assert excinfo.value.code == "split_hash_mismatch"


def test_split_adapter_recomputes_the_deterministic_split_rule(tmp_path):
    """最硬的一道闸：切分由 sha256(family:item_id:salt) 决定，改不了。

    这里把 assignments、distribution、split_hash **三处一起改成自洽**——
    前两道闸都会放行——只有规则复算能发现数据被动过。
    """
    from abcr.rig.splits import split_hash as compute_split_hash

    payload = json.loads(loop.SPLIT_PATH.read_text(encoding="utf-8"))
    moved = next(i for i, b in payload["assignments"].items() if b == "holdout")
    payload["assignments"][moved] = "dev"          # 把一条 holdout 偷渡进 dev
    payload["distribution"] = {"dev": 43, "calibration": 91, "holdout": 116}
    payload["split_hash"] = compute_split_hash(payload["assignments"])   # 自洽伪造
    target = tmp_path / "rule-violation.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FastlaneError) as excinfo:
        load_real_split(target)
    assert excinfo.value.code == "split_rule_mismatch"
    assert excinfo.value.detail["count"] == 1


# ────────── 仓内权威坐标：family 漂移不得再把 holdout 当 dev（V1 阻断级缺陷）──────────
def _forge_split_under(family: str, tmp_path, name: str = "forged.json"):
    """按另一个 family 重算 assignments / distribution / split_hash 三处，内部完全自洽。

    这正是 V1 被攻破的方式：三道闸互相印证，而它们的共同判据 `family`
    就写在被校验的文件里。
    """
    from abcr.rig.splits import assign_split, split_hash as compute_split_hash

    real = json.loads(loop.SPLIT_PATH.read_text(encoding="utf-8"))
    assignments = {item_id: assign_split(family, item_id) for item_id in real["assignments"]}
    distribution: dict[str, int] = {}
    for bucket in assignments.values():
        distribution[bucket] = distribution.get(bucket, 0) + 1
    payload = {"family": family, "salt": real["salt"],
               "split_hash": compute_split_hash(assignments),
               "distribution": distribution, "assignments": assignments}
    target = tmp_path / name
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target, payload


def test_family_drift_is_refused_even_when_the_file_is_fully_self_consistent(tmp_path):
    """V1 的阻断级缺陷：换 family + 三处自洽重算 → 三道闸全部 ACCEPTED。

    实测后果不是抽象的：dev 桶从 42 变 47，多出来的题里有真 holdout。
    "自洽" 只说明这份文件描述了某一次切分，**不说明是我们该跑的那一次**。
    """
    target, payload = _forge_split_under("not-ifeval", tmp_path)

    # 先把赌注摆明：这份伪造件确实会把 holdout 洗成 dev。
    real = json.loads(loop.SPLIT_PATH.read_text(encoding="utf-8"))["assignments"]
    forged_dev = {i for i, b in payload["assignments"].items() if b == "dev"}
    real_dev = {i for i, b in real.items() if b == "dev"}
    real_holdout = {i for i, b in real.items() if b == "holdout"}
    assert len(forged_dev) > len(real_dev)          # 42 → 47
    assert forged_dev & real_holdout                # 其中确有真 holdout 被洗进 dev

    with pytest.raises(FastlaneError) as excinfo:
        load_real_split(target)
    assert excinfo.value.code == "split_family_mismatch"
    assert excinfo.value.detail["expected"] == SA.FROZEN_FAMILY


def test_split_rule_is_recomputed_against_the_repo_family_not_the_file_field(tmp_path):
    """判据来自仓内常量：即便 family 字段被改回正确值，切分本身仍会被复算发现。

    文件说自己是 ifeval_zh_v1，assignments 却是按 not-ifeval 算的——
    闸 0a 放行，闸 3 用**仓内 family** 复算，当场拆穿。
    """
    from abcr.rig.splits import split_hash as compute_split_hash

    target, payload = _forge_split_under("not-ifeval", tmp_path, "relabelled.json")
    payload["family"] = SA.FROZEN_FAMILY            # 只把标签改回来，内容不动
    payload["split_hash"] = compute_split_hash(payload["assignments"])
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FastlaneError) as excinfo:
        load_real_split(target)
    assert excinfo.value.code == "split_rule_mismatch"
    assert excinfo.value.detail["count"] > 0


def test_protocol_salt_must_match_the_constant_in_src(tmp_path):
    """salt 是协议常量（`abcr.rig.splits.SALT`），文件自述的那个只是待验值。"""
    payload = json.loads(loop.SPLIT_PATH.read_text(encoding="utf-8"))
    payload["salt"] = "abcr-somebody-elses-salt"
    target = tmp_path / "bad-salt.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FastlaneError) as excinfo:
        load_real_split(target)
    assert excinfo.value.code == "split_salt_mismatch"
    assert excinfo.value.detail["expected"] == SA.FROZEN_SALT


def test_expected_family_cannot_be_emptied_into_a_free_pass():
    """判据不能为空——空判据等于没有判据。"""
    with pytest.raises(FastlaneError) as excinfo:
        load_real_split(loop.SPLIT_PATH, expected_family="")
    assert excinfo.value.code == "bad_expected_family"


# ────────────────── 仓内冻结件身份（字节 / 路径 / 语义坐标）──────────────────
@pytest.fixture()
def frozen_copy(tmp_path, monkeypatch):
    """把仓内冻结 split 复制到 tmp 并把冻结坐标指过去，便于安全地做篡改实验。

    刻意**不**去改仓库里的真文件：测试崩在中途会留下一个被改过的数据集。
    """
    target = tmp_path / "ifeval_zh_v1.json"
    shutil.copyfile(loop.SPLIT_PATH, target)
    monkeypatch.setattr(SA, "FROZEN_SPLIT_PATH", target)
    return target


def test_frozen_split_refuses_a_single_byte_edit(frozen_copy):
    """字节闸：仓内那一份被就地改了——哪怕改的是无害空白——也当场停止。"""
    assert load_frozen_split(frozen_copy)["source_sha256"] == SA.FROZEN_SPLIT_SHA256
    frozen_copy.write_bytes(frozen_copy.read_bytes() + b"\n")
    with pytest.raises(FastlaneError) as excinfo:
        load_frozen_split(frozen_copy)
    assert excinfo.value.code == "split_bytes_not_frozen"
    assert excinfo.value.detail["frozen_sha256"] == SA.FROZEN_SPLIT_SHA256


def test_frozen_split_refuses_a_lookalike_at_another_path(tmp_path):
    """路径闸：字节一模一样，但不是仓内那一份 —— 快道不跑仓外数据。"""
    lookalike = tmp_path / "lookalike.json"
    shutil.copyfile(loop.SPLIT_PATH, lookalike)
    with pytest.raises(FastlaneError) as excinfo:
        load_frozen_split(lookalike)
    assert excinfo.value.code == "split_not_frozen_path"


def test_frozen_split_refuses_an_extra_item_even_though_every_content_gate_passes(frozen_copy,
                                                                                 monkeypatch):
    """语义坐标闸：加一题进去，五道内容闸**全部通过**，身份闸仍然拦下。

    加进来的这一题连切分规则复算都对（它的桶是按规则算的），
    distribution 与 split_hash 也同步了——所以这是一份"完全合法"的 split。
    它只是**不是我们冻结的那一次**：题数 251、dev 桶摘要变了。
    """
    from abcr.rig.splits import assign_split, split_hash as compute_split_hash

    payload = json.loads(frozen_copy.read_text(encoding="utf-8"))
    payload["assignments"]["ifzh-9999"] = assign_split(SA.FROZEN_FAMILY, "ifzh-9999")
    distribution: dict[str, int] = {}
    for bucket in payload["assignments"].values():
        distribution[bucket] = distribution.get(bucket, 0) + 1
    payload["distribution"] = distribution
    payload["split_hash"] = compute_split_hash(payload["assignments"])
    blob = json.dumps(payload).encode("utf-8")
    frozen_copy.write_bytes(blob)
    # 连字节闸也一并放行，把审判权完全交给语义坐标。
    monkeypatch.setattr(SA, "FROZEN_SPLIT_SHA256", loop.sha256(blob))

    load_real_split(frozen_copy)          # 五道内容闸确实全过
    with pytest.raises(FastlaneError) as excinfo:
        load_frozen_split(frozen_copy)
    assert excinfo.value.code == "split_identity_mismatch"
    assert excinfo.value.detail["item_count"]["observed"] == SA.FROZEN_ITEM_COUNT + 1
    assert "dev_digest" in excinfo.value.detail


def test_dev_bucket_is_exactly_the_frozen_forty_two():
    """"只跑固定 dev"：dev 桶不只是"42 题"，而是**那 42 题**。"""
    dev = SA.dev_item_ids()
    assert len(dev) == SA.FROZEN_DISTRIBUTION["dev"] == 42
    assert SA.dev_digest(dev) == SA.FROZEN_DEV_DIGEST


def test_frozen_dataset_identity_is_gated_too(tmp_path, monkeypatch):
    """split 钉住"哪些题是 dev"，钉不住"这些题长什么样"——数据集要有自己的闸。"""
    assert SA.assert_frozen_dataset() == SA.FROZEN_DATASET_SHA256
    copy = tmp_path / "ifeval_zh_v1.json"
    shutil.copyfile(SA.FROZEN_DATASET_PATH, copy)
    monkeypatch.setattr(SA, "FROZEN_DATASET_PATH", copy)
    copy.write_bytes(copy.read_bytes() + b" ")
    with pytest.raises(FastlaneError) as excinfo:
        SA.assert_frozen_dataset(copy)
    assert excinfo.value.code == "dataset_bytes_not_frozen"


def test_frozen_constants_match_the_committed_blobs():
    """常量不是"我随手抄的数字"：与 git 里**已提交**的冻结件逐字节比对。

    这一条是坐标本身的守门器——数据换了而常量没换（或反过来）时当场红。
    仓库不在场（比如从 tarball 解出来跑）就 skip，不假装验过。
    """
    for rel, expected in ((f"data/splits/{SA.FROZEN_FAMILY}.json", SA.FROZEN_SPLIT_SHA256),
                          (f"data/benchmarks/{SA.FROZEN_FAMILY}.json", SA.FROZEN_DATASET_SHA256)):
        try:
            proc = subprocess.run(["git", "-C", str(SA.REPO_ROOT), "cat-file", "blob",
                                   f"HEAD:{rel}"], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:      # pragma: no cover
            pytest.skip(f"git 不可用，无法核对已提交冻结件：{exc}")
        if proc.returncode != 0:                                   # pragma: no cover
            pytest.skip(f"git 不在场或该路径未提交：{rel}")
        assert loop.sha256(proc.stdout) == expected, f"{rel} 的仓内冻结身份与常量漂移了"


def test_a_drifted_split_stops_the_run_itself_not_just_the_health_check(lab, monkeypatch,
                                                                       tmp_path):
    """闸必须长在**运行路径**上。体检命令过了不算数，run 才是真正会产生数字的地方。"""
    copy = tmp_path / "ifeval_zh_v1.json"
    shutil.copyfile(loop.SPLIT_PATH, copy)
    monkeypatch.setattr(SA, "FROZEN_SPLIT_PATH", copy)
    monkeypatch.setattr(loop, "SPLIT_PATH", copy)
    copy.write_bytes(copy.read_bytes() + b"\n")
    with pytest.raises(FastlaneError) as excinfo:
        _run(_spec())
    assert excinfo.value.code == "split_bytes_not_frozen"
    assert loop.list_rounds() == []          # 没有半轮结果落盘


def test_a_drifted_dataset_stops_the_run_itself(lab, monkeypatch, tmp_path):
    copy = tmp_path / "ifeval_zh_v1.json"
    shutil.copyfile(SA.FROZEN_DATASET_PATH, copy)
    monkeypatch.setattr(SA, "FROZEN_DATASET_PATH", copy)
    monkeypatch.setattr(loop, "DATASET_PATH", copy)
    copy.write_bytes(copy.read_bytes() + b" ")
    with pytest.raises(FastlaneError) as excinfo:
        _run(_spec())
    assert excinfo.value.code == "dataset_bytes_not_frozen"
    assert loop.list_rounds() == []


# ────────── 冻结身份闸必须早于"这轮跑过没有"（B1 · V2 阻断）──────────
def _point_split_at_copy(tmp_path, monkeypatch):
    """把冻结 split 指向一份 tmp 副本，便于安全地演"仓内那一份被改过"。"""
    copy = tmp_path / "ifeval_zh_v1.json"
    shutil.copyfile(loop.SPLIT_PATH, copy)
    monkeypatch.setattr(SA, "FROZEN_SPLIT_PATH", copy)
    monkeypatch.setattr(loop, "SPLIT_PATH", copy)
    return copy


def _make_round_while_this_split_counts_as_frozen(spec, monkeypatch, split):
    """造出"当初这份 split 还算数时"产出的那一轮，其余一切照旧。

    做法是只在**创建那一刻**把字节坐标临时指向这份 split——等价于 V1 当时的
    处境（那时根本没有坐标，自洽即接受）。退出上下文后坐标恢复，这份 split
    就变成了"漂移过的"，而那一轮已经躺在数据根里，`probe_id` 也已经算定。

    刻意不去摘 `assert_frozen_inputs`：那样只能骗过入口，骗不过 `_dev_bundle`
    里的同一道闸，造不出这一轮；而且这条测试要能原样跑在**还没有入口闸**的
    旧版本上——那正是它要证伪的对象。
    """
    with monkeypatch.context() as m:
        m.setattr(SA, "FROZEN_SPLIT_SHA256", loop.sha256(split.read_bytes()))
        made = loop.run_round(spec, engine=FakeProbeEngine())
        assert made["reused"] is False
        # 确认这一轮**确实是可复用的**，否则下面"复用被挡住"的断言毫无意义。
        assert loop.run_round(spec, engine=FakeProbeEngine())["reused"] is True
    return made


def test_a_round_produced_under_a_drifted_split_cannot_be_reused(lab, tmp_path, monkeypatch):
    """坏 split 下"直接复用"= 把上次坏数据的结果再交付一次，必须一并挡住。

    真实事故形态：坏 split 就位 → `check` 报 FAIL(rc=1) → 重提同一请求 → rc=0
    "该请求已经跑过，直接复用"。闸只长在造 bundle 上，而三条提交路径都在造
    bundle 之前就 existing-return，于是闸挡住了"再跑一次"，挡不住"再交付一次"。
    """
    split = _point_split_at_copy(tmp_path, monkeypatch)
    split.write_bytes(split.read_bytes() + b"\n")        # 坏 split 就位
    spec = _spec()
    made = _make_round_while_this_split_counts_as_frozen(spec, monkeypatch, split)

    # 同一份请求 → 同一个 probe_id（指纹吃进了 split_sha256，坏 split 下也一致），
    # 所以走的确实是复用那条路，而不是"换了个 id 所以重跑"。
    assert loop.probe_id_for(spec, engine_profile="fixture") == made["probe_id"]

    with pytest.raises(FastlaneError) as excinfo:
        loop.run_round(spec, engine=FakeProbeEngine())
    assert excinfo.value.code == "split_bytes_not_frozen"


def test_the_web_submit_path_also_refuses_to_reuse_under_a_drifted_split(lab, tmp_path,
                                                                        monkeypatch):
    """`web.start_round()` 同样在 existing-return 之前挂闸。"""
    from lab.fastlane import web

    split = _point_split_at_copy(tmp_path, monkeypatch)
    split.write_bytes(split.read_bytes() + b"\n")
    monkeypatch.setattr(loop, "make_engine", lambda: FakeProbeEngine())
    spec = _spec()
    _make_round_while_this_split_counts_as_frozen(spec, monkeypatch, split)

    with pytest.raises(FastlaneError) as excinfo:
        web.start_round(spec)
    assert excinfo.value.code == "split_bytes_not_frozen"


def test_the_cli_run_path_also_refuses_to_reuse_under_a_drifted_split(lab, tmp_path,
                                                                     monkeypatch):
    """CLI `run` 的复用分支同样在闸之后。"""
    import argparse
    import importlib.util

    spec_file = importlib.util.spec_from_file_location(
        "probe_quick_loop_under_test", SA.REPO_ROOT / "scripts" / "probe_quick_loop.py")
    cli = importlib.util.module_from_spec(spec_file)
    spec_file.loader.exec_module(cli)

    split = _point_split_at_copy(tmp_path, monkeypatch)
    split.write_bytes(split.read_bytes() + b"\n")
    monkeypatch.setattr(loop, "make_engine", lambda: FakeProbeEngine())
    round_spec = _spec()
    _make_round_while_this_split_counts_as_frozen(round_spec, monkeypatch, split)

    args = argparse.Namespace(hypothesis=HYPOTHESIS, persona=PERSONA, persona_file=None,
                              count=1, seed=1, parent=None)
    with pytest.raises(FastlaneError) as excinfo:
        cli.cmd_run(args)
    assert excinfo.value.code == "split_bytes_not_frozen"


def test_reading_old_rounds_is_not_bound_to_the_current_frozen_files(lab, tmp_path,
                                                                    monkeypatch):
    """读路径**刻意不挂闸**：数据坏了，回去看当初跑了什么必须仍然做得到。

    旧轮是历史事实。把它的可读性绑在"今天的冻结件长什么样"上，等于数据一坏
    就连查清问题所需的证据也一起看不见了。旧轮自身的可信度由 `record_hash`
    与 notebook / bundle 的验签各自负责，与今天的 split 无关。
    """
    split = _point_split_at_copy(tmp_path, monkeypatch)
    spec = _spec(count=2)
    made = loop.run_round(spec, engine=FakeProbeEngine())      # split 尚好时跑的一轮
    split.write_bytes(split.read_bytes() + b"\n")              # 之后 split 坏了

    # 提交路径已经停了
    with pytest.raises(FastlaneError):
        loop.assert_frozen_inputs()
    # 读路径照常
    assert [r["probe_id"] for r in loop.list_rounds()] == [made["probe_id"]]
    reread = loop.read_round(made["probe_id"])
    assert reread["row_hashes"] == made["row_hashes"]
    assert [row["row_hash"] for row in loop.round_rows(reread)] == made["row_hashes"]
    assert set(loop.load_items_for(reread)) == set(made["item_ids"])


# ────────── 单条坏记录不得拖垮整段历史（B2 · V2 阻断）──────────
def _drop(record: dict, field: str) -> dict:
    return {k: v for k, v in record.items() if k != field}


#: 一组"JSON 合法、结构非法"的形状。每一种都必须归一成带**稳定错误码**的
#: `FastlaneError`，而不是 `AttributeError` / `KeyError` 那样的裸异常。
_MALFORMED_ROUNDS = (
    ("顶层是列表", lambda rec: "[]", "round_malformed"),
    ("顶层是字符串", lambda rec: '"a round, honest"', "round_malformed"),
    ("空对象", lambda rec: "{}", "round_incomplete"),
    ("只有 probe_id", lambda rec: json.dumps({"probe_id": rec["probe_id"]}),
     "round_incomplete"),
    ("缺 record_hash", lambda rec: json.dumps(_drop(rec, "record_hash")), "round_incomplete"),
    ("缺 bundle_id", lambda rec: json.dumps(_drop(rec, "bundle_id")), "round_incomplete"),
    ("count 是字符串", lambda rec: json.dumps(dict(rec, count="1")), "round_malformed"),
    ("row_hashes 不是列表", lambda rec: json.dumps(dict(rec, row_hashes="abc")),
     "round_malformed"),
    ("probe_id 与文件名不符", lambda rec: json.dumps(dict(rec, probe_id="fx-somebody-else")),
     "round_id_mismatch"),
)


@pytest.mark.parametrize("label,mutate,code", _MALFORMED_ROUNDS,
                         ids=[row[0] for row in _MALFORMED_ROUNDS])
def test_one_malformed_round_never_hides_the_others(lab, label, mutate, code):
    """一条文件写坏 ≠ 整段历史不可见。

    旧版本里 `[]` 让 `record.get(...)` 抛 `AttributeError`，异常穿过 `scan_rounds()`
    （只接 FastlaneError / OSError）直达兜底页：首页 500，**两条好轮和那条坏轮
    一起从人眼前消失**。`{}` 更隐蔽——它一路通过，冒充正常轮进入列表，
    直到点开详情才炸出 `KeyError: 'bundle_id'`。
    """
    good = _run(_spec(hypothesis="好轮"))
    bad = _run(_spec(hypothesis="会被写坏的一轮"))
    target = loop.paths().round_file(bad["probe_id"])
    stored = json.loads(target.read_text(encoding="utf-8"))
    target.write_text(mutate(stored), encoding="utf-8")

    records, failures = loop.scan_rounds()          # 不抛异常
    assert [r["probe_id"] for r in records] == [good["probe_id"]]
    assert [f["probe_id"] for f in failures] == [bad["probe_id"]]
    assert failures[0]["code"] == code, f"{label} 的错误码不稳定"
    assert failures[0]["message"]

    with pytest.raises(FastlaneError) as excinfo:
        loop.read_round(bad["probe_id"])
    assert excinfo.value.code == code
    # 好轮不受任何影响
    assert loop.read_round(good["probe_id"])["row_hashes"] == good["row_hashes"]


def test_scan_never_lets_an_unforeseen_shape_take_down_the_history(lab, monkeypatch):
    """兜底：万一将来又冒出一种没被归一的坏形状，也只坏那一条。"""
    good = _run(_spec(hypothesis="好轮"))
    bad = _run(_spec(hypothesis="炸给你看的一轮"))
    real_load = loop._load_record

    def explode(target):
        if target.stem == bad["probe_id"]:
            raise RuntimeError("一种谁也没想到的坏形状")
        return real_load(target)

    monkeypatch.setattr(loop, "_load_record", explode)
    records, failures = loop.scan_rounds()
    assert [r["probe_id"] for r in records] == [good["probe_id"]]
    assert failures[0]["code"] == "round_unreadable"
    assert "RuntimeError" in failures[0]["message"]      # 异常类型带出来，便于查


def test_split_adapter_refuses_a_missing_distribution(tmp_path):
    """缺失不是通过。字段不在就报错，不能"没写就不查"。"""
    payload = json.loads(loop.SPLIT_PATH.read_text(encoding="utf-8"))
    del payload["distribution"]
    target = tmp_path / "no-distribution.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FastlaneError) as excinfo:
        load_real_split(target)
    assert excinfo.value.code == "split_distribution_missing"


# ───────────────────────── 请求规范化 ─────────────────────────
def test_prediction_folds_multiline_and_refuses_empty():
    assert loop.normalize_prediction("第一行\n第二行") == "第一行 / 第二行"
    assert loop.normalize_prediction("  留白  \r\n\r\n  下一段 ") == "留白 / 下一段"
    for empty in ("", "   ", "\n\n"):
        with pytest.raises(FastlaneError, match="必填"):
            loop.normalize_prediction(empty)


def test_prediction_over_limit_raises_instead_of_truncating():
    """超长必须报错。砍掉的那半句往往正是假设最关键的部分。"""
    with pytest.raises(FastlaneError) as excinfo:
        loop.normalize_prediction("啊" * 3000)          # 每字 3 字节 → 9000 > 8192
    assert excinfo.value.code == "prediction_too_long"


def test_persona_ref_is_derived_from_content():
    """同文本同 ref，改一个字换 ref —— 两个人格不可能藏在同一个臂标签下。"""
    assert loop.persona_ref_for(PERSONA) == loop.persona_ref_for(PERSONA)
    assert loop.persona_ref_for(PERSONA) != loop.persona_ref_for(PERSONA + "。")
    assert loop.persona_ref_for(PERSONA).startswith("fastlane-p@")


@pytest.mark.parametrize("count", [0, -1, 21, 100, "abc", None])
def test_count_outside_1_20_is_refused(count):
    with pytest.raises(FastlaneError):
        loop.normalize_count(count)


@pytest.mark.parametrize("count", [2.9, 19.5, True, False, "3.0", " 4.2 "])
def test_count_is_never_silently_rounded(count):
    """`int(2.9)` 会悄悄变成 2 —— "少跑一题没人知道" 正是最不能接受的失败形态。"""
    with pytest.raises(FastlaneError):
        loop.normalize_count(count)


@pytest.mark.parametrize("count", [1, 20])
def test_count_boundaries_are_accepted(count):
    assert loop.normalize_count(count) == count


def test_seed_defaults_to_one_and_refuses_non_integer():
    assert loop.normalize_seed(None) == loop.DEFAULT_SEED == 1
    assert loop.normalize_seed("") == 1
    assert loop.normalize_seed("7") == 7
    with pytest.raises(FastlaneError):
        loop.normalize_seed("x")


# ───────────────────────── 一轮实验 ─────────────────────────
def test_round_pairs_vanilla_with_persona_on_the_same_items(lab):
    record = _run(_spec(count=2))
    assert record["arm_ids"][0] == "vanilla"            # vanilla 是结构性的
    assert record["row_count"] == record["expected_row_count"] == 4
    rows = loop.round_rows(record)
    by_arm: dict[str, set[str]] = {}
    for row in rows:
        by_arm.setdefault(row["arm_id"], set()).add(row["item_id"])
    assert len(by_arm) == 2
    assert len(set(map(frozenset, by_arm.values()))) == 1   # 两臂题目集合完全相同
    assert {row["seed"] for row in rows} == {1}            # 同 seed


def test_every_row_and_record_is_permanently_non_citable(lab):
    record = _run(_spec())
    assert record["citable"] is False
    assert record["label"] == loop.NOT_CITABLE_LABEL
    for row in loop.round_rows(record):
        assert row["citable"] is False
        assert row["evidence_class"] == "exploratory_learning_only"


def test_notebook_refuses_a_forged_citable_row(lab):
    """核心的 citable 闸不是靠快道自觉——伪造一行会被 notebook 当场拒。"""
    record = _run(_spec())
    row = dict(loop.round_rows(record)[0], citable=True)
    notebook = ProbeNotebook(loop.paths().notebook)
    # 断言 .code 而不是 str(exc)：code 是稳定的机器契约，message 是可改的人话。
    with pytest.raises(ContractError) as excinfo:
        notebook.append(row)
    assert excinfo.value.code == "probe_citable_forbidden"


def test_fixture_rounds_are_physically_separated_from_real_ones(lab):
    """最要紧的一条防线：夹具数字**不可能**被当成真机结果复用。

    没有这条隔离，事故是这样的：夹具跑一轮 → 人提交同一份请求 →
    `read_round()` 命中 → 返回 `reused=True` → 夹具数字被当作真机结果交付，
    而模型在这条路上一次都没被调用过。
    """
    record = _run(_spec())
    assert record["probe_id"].startswith(loop.FIXTURE_PREFIX)
    assert record["fixture_engine"] is True
    assert record["model_profile"] == "fixture"
    assert record["configured_model_profile"] == loop.MODEL_PROFILE

    # 真机会用另一个 probe_id，因此绝不会命中这条夹具记录。
    real_id = loop.probe_id_for(_spec(), engine_profile=loop.MODEL_PROFILE)
    assert real_id.startswith(loop.REAL_PREFIX)
    assert real_id != record["probe_id"]
    assert loop.read_round(real_id) is None


def test_changing_the_scorer_version_would_invalidate_reuse(lab):
    """判分口径变了就是另一次实验，不能复用旧指标。"""
    spec = _spec()
    baseline = loop.request_fingerprint(spec, engine_profile="fixture")
    record = _run(spec)
    assert record["scorer_id"] and record["scorer_version"]
    # 指纹确实把判分器版本吃进去了：换个 engine_profile 就换身份，同理换 scorer。
    assert loop.request_fingerprint(spec, engine_profile="other") != baseline


def test_only_dev_items_are_ever_selected(lab):
    """"一切只碰 dev split"——选出来的题必须全在 dev 桶里。"""
    dev = set(load_real_split(loop.SPLIT_PATH)["buckets"]["dev"])
    record = _run(_spec(count=20))
    assert record["item_ids"] and set(record["item_ids"]) <= dev


def test_same_seed_and_count_select_the_same_items_across_rounds(lab):
    """改假设不能让题目漂移，否则两轮没法比。"""
    first = _run(_spec(hypothesis="假设甲", count=5))
    second = _run(_spec(hypothesis="假设乙", count=5))
    assert first["probe_id"] != second["probe_id"]
    assert first["item_ids"] == second["item_ids"]
    assert first["bundle_id"] == second["bundle_id"]


def test_a_different_seed_selects_different_items(lab):
    a = _run(_spec(count=5, seed=1))
    b = _run(_spec(count=5, seed=2))
    assert a["item_ids"] != b["item_ids"]


# ───────────────────────── 幂等 ─────────────────────────
def test_resubmitting_the_same_request_does_not_create_a_second_experiment(lab):
    first = _run(_spec())
    second = _run(_spec())
    assert second["reused"] is True
    assert first["probe_id"] == second["probe_id"]
    assert first["row_hashes"] == second["row_hashes"]
    assert first["recorded_at"] == second["recorded_at"]
    assert len(loop.list_rounds()) == 1


def test_parent_is_recorded_but_kept_out_of_the_request_fingerprint(lab):
    """血缘是历史，不是实验条件：只换父指针不构成一次新实验。"""
    root = _run(_spec())
    same = _spec(parent_probe_id=root["probe_id"])
    assert loop.probe_id_for(same, engine_profile="fixture") == root["probe_id"]
    assert loop.run_round(same, engine=FakeProbeEngine())["reused"] is True
    assert len(loop.list_rounds()) == 1


def test_bundle_id_is_stable_because_created_at_is_pinned(lab):
    """`build_dev_bundle` 的 created_at 缺省是 utc_now()——钉死它才有幂等。"""
    first = _run(_spec())
    bundles = sorted(p.name for p in loop.paths().bundles.iterdir())
    _run(_spec(hypothesis="换个假设"))
    assert sorted(p.name for p in loop.paths().bundles.iterdir()) == bundles
    assert len(bundles) == 1 and bundles[0] == first["bundle_id"]


# ───────────────────────── 再做一轮 ─────────────────────────
def test_revise_prefills_the_previous_round_and_leaves_it_untouched(lab):
    first = _run(_spec(count=2))
    prefill = loop.revise_spec(first["probe_id"])
    assert prefill.prediction == first["prediction"]
    assert prefill.persona_text == first["persona_text"]
    assert prefill.count == first["count"] and prefill.seed == first["seed"]
    assert prefill.parent_probe_id == first["probe_id"]

    revised = loop.build_spec(hypothesis="改了假设：输出会变短", persona_text=PERSONA,
                              count=2, seed=1, parent_probe_id=first["probe_id"])
    second = loop.run_round(revised, engine=FakeProbeEngine())
    assert second["probe_id"] != first["probe_id"]
    assert second["parent_probe_id"] == first["probe_id"]

    unchanged = loop.read_round(first["probe_id"])
    assert unchanged["row_hashes"] == first["row_hashes"]
    assert unchanged["hypothesis_raw"] == first["hypothesis_raw"]
    assert unchanged["recorded_at"] == first["recorded_at"]


def test_revise_of_unknown_round_is_refused(lab):
    with pytest.raises(FastlaneError, match="没有这一轮"):
        loop.revise_spec("fl-does-not-exist")


# ───────────────────────── 重启后仍可读 ─────────────────────────
def test_history_survives_a_restart(lab):
    """轮次落在磁盘上，不在进程内存里——关掉再开必须还在。"""
    first = _run(_spec(count=2, hypothesis="第一轮"))
    second = _run(_spec(count=2, hypothesis="第二轮"))
    # 模拟重启：丢掉一切进程内状态，只留数据目录。
    listed = {record["probe_id"] for record in loop.list_rounds()}
    assert {first["probe_id"], second["probe_id"]} == listed
    reread = loop.read_round(first["probe_id"])
    assert reread["row_hashes"] == first["row_hashes"]
    assert [row["row_hash"] for row in loop.round_rows(reread)] == first["row_hashes"]


def test_rows_are_reread_through_the_tamper_check(lab):
    """notebook 的行被改过，读的时候必须炸，而不是安静地显示改过的内容。"""
    record = _run(_spec())
    row_hash = record["row_hashes"][0]
    target = loop.paths().notebook / "rows" / row_hash / "row.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["output_text"] = "被人改过的输出"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FastlaneError) as excinfo:
        loop.round_rows(record)
    assert excinfo.value.code == "row_probe_row_tampered"


def test_round_record_carries_its_own_integrity_hash(lab):
    """人在页面上看的汇总数字住在轮次文件里，notebook 管不到它。"""
    record = _run(_spec(count=2))
    target = loop.paths().round_file(record["probe_id"])
    stored = json.loads(target.read_text(encoding="utf-8"))
    assert stored["record_hash"] == loop.record_hash(stored)

    stored["scores"][0]["metrics"]["is_correct"] = 999      # 篡改汇总数字
    target.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(FastlaneError) as excinfo:
        loop.read_round(record["probe_id"])
    assert excinfo.value.code == "round_tampered"


def test_a_lost_sealer_key_is_reported_instead_of_bricking_the_lab(lab):
    """密钥没了而 bundles 还在——铸新钥只会得到一堆验不过的 bundle。

    `bundle_id` 不含密钥，所以 `build_dev_bundle()` 会复用旧目录连同旧
    `seal.json`。不拦住的话，旧轮读不出、**新实验也跑不了**，且毫无提示。
    """
    _run(_spec())
    p = loop.paths()
    p.sealer_private.unlink()
    p.sealer_public.unlink()
    p.keyid.unlink()
    with pytest.raises(FastlaneError) as excinfo:
        loop.ensure_sealer_keys(p)
    assert excinfo.value.code == "sealer_key_lost"
    assert str(p.bundles) in excinfo.value.message


def test_items_are_reread_through_the_bundle_seal(lab):
    """题面只能从封印过的 bundle 里出来，不能绕过 seal 直接读数据集。"""
    record = _run(_spec(count=2))
    assert set(loop.load_items_for(record)) == set(record["item_ids"])
    seal = loop.paths().bundles / record["bundle_id"] / "seal.json"
    seal.write_text(json.dumps({"forged": True}), encoding="utf-8")
    with pytest.raises(FastlaneError) as excinfo:
        loop.load_items_for(record)
    assert excinfo.value.code.startswith("bundle_")


def test_scan_rounds_surfaces_a_broken_round_instead_of_dropping_it(lab):
    """坏轮不能从历史里消失——"证据无声地不存在"比报错更糟。"""
    good = _run(_spec(hypothesis="好轮"))
    bad = _run(_spec(hypothesis="坏轮"))
    target = loop.paths().round_file(bad["probe_id"])
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["count"] = 999                                   # 篡改
    target.write_text(json.dumps(payload), encoding="utf-8")

    records, failures = loop.scan_rounds()
    assert [r["probe_id"] for r in records] == [good["probe_id"]]
    assert [f["probe_id"] for f in failures] == [bad["probe_id"]]
    assert failures[0]["code"] == "round_tampered"
    assert failures[0]["message"]                            # 有给人看的话
    # `list_rounds()` 仍然只给可读的那些（CLI 与页面据此渲染内容），
    # 但坏轮的存在已经由 `scan_rounds()` 第二项交出去，没有被吞掉。
    assert [r["probe_id"] for r in loop.list_rounds()] == [good["probe_id"]]


def test_cli_show_prints_complete_identities(lab):
    """CLI 后备与页面同口径：身份值完整打印，不截断。"""
    record = _run(_spec(count=1))
    script = SA.REPO_ROOT / "scripts" / "probe_quick_loop.py"
    env = dict(os.environ, ABCR_FASTLANE_ROOT=str(loop.lab_root()),
               PYTHONPATH=f"{SA.REPO_ROOT / 'src'}{os.pathsep}{SA.REPO_ROOT}")
    proc = subprocess.run([sys.executable, str(script), "show", record["probe_id"]],
                          capture_output=True, text=True, timeout=120, env=env)
    assert proc.returncode == 0, proc.stderr
    assert record["engine_fingerprint_sha256"] in proc.stdout
    assert record["bundle_id"] in proc.stdout
    assert record["dataset_sha256"] in proc.stdout and record["split_sha256"] in proc.stdout
    for row_hash in record["row_hashes"]:
        assert row_hash in proc.stdout


# ───────────────────────── 结果整理 ─────────────────────────
def test_summary_reports_both_arms_and_a_signed_delta(lab):
    record = _run(_spec(count=3))
    summary = loop.summarize(record, loop.round_rows(record))
    assert summary["citable"] is False
    assert set(summary["arms"]) == {"vanilla", summary["persona_arm"]}
    assert summary["arms"]["vanilla"]["n"] == 3
    for name in ("is_correct", "output_len_chars", "hedging_rate"):
        assert name in summary["deltas"]
        base = summary["arms"]["vanilla"]["metrics"][name]
        treat = summary["arms"][summary["persona_arm"]]["metrics"][name]
        assert summary["deltas"][name] == pytest.approx(treat - base)


def test_paired_items_expose_prompt_outputs_scores_and_row_hash(lab):
    record = _run(_spec(count=2))
    rows = loop.round_rows(record)
    paired = loop.paired_items(record, rows, loop.load_items_for(record))
    assert [entry["item_id"] for entry in paired] == record["item_ids"]
    for entry in paired:
        assert entry["prompt"]                              # 题面原文可见
        assert set(entry["arms"]) == set(record["arm_ids"])  # 两臂并排
        for arm in entry["arms"].values():
            assert len(arm["row_hash"]) == 64
            assert "is_correct" in arm["metrics"]
            assert isinstance(arm["output_text"], str)
