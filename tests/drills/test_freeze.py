"""tests/drills/test_freeze.py —— A2-5 定稿仪式（scripts/a_freeze.py::freeze）端到端。

在临时 git 仓上跑，不触碰真链/真 tag。断言：协议事件入第五链（actor=human/tree_hash/git_tag）、
git tag 生成、非冻结区/未跟踪/脏树三种拦截、supersede 事件名。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from abcr.common.ledger_ref import RunLedger

REPO = Path(__file__).resolve().parents[2]


def _load_freeze():
    path = REPO / "scripts" / "a_freeze.py"
    spec = importlib.util.spec_from_file_location("_a_freeze", path)
    mod = importlib.util.module_from_spec(spec)
    if str(REPO / "src") not in sys.path:
        sys.path.insert(0, str(REPO / "src"))
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    golden = tmp_path / "data" / "golden"
    golden.mkdir(parents=True)
    (golden / "golden10.json").write_text('{"items": [1]}\n', encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    return tmp_path


def test_freeze_records_protocol_event_and_tag(git_repo: Path) -> None:
    fr = _load_freeze()
    sb = str(git_repo / "prof.sb")
    rc = fr.freeze(git_repo, "data/golden", profile_path=sb)
    assert rc == 0
    evs = [e for e in RunLedger(git_repo / "ledger", "protocol").events()
           if e["event"] == "artifact_frozen"]
    assert len(evs) == 1
    e = evs[0]
    assert e["actor"] == "human"
    assert e["artifact"] == "data/golden"
    assert len(e["tree_hash"]) == 64
    assert e["git_tag"].startswith("freeze/golden-")
    # git tag 存在
    tags = _git(git_repo, "tag").stdout.split()
    assert any(t.startswith("freeze/golden-") for t in tags), tags
    # 第五链自验通过
    assert RunLedger(git_repo / "ledger", "protocol").verify_chain()


def test_freeze_supersede_event(git_repo: Path) -> None:
    fr = _load_freeze()
    rc = fr.freeze(git_repo, "data/golden", supersede=True,
                   profile_path=str(git_repo / "p.sb"))
    assert rc == 0
    evs = [e["event"] for e in RunLedger(git_repo / "ledger", "protocol").events()]
    assert "artifact_superseded" in evs


def test_freeze_rejects_non_frozen_zone(git_repo: Path) -> None:
    fr = _load_freeze()
    (git_repo / "src").mkdir()
    (git_repo / "src" / "x.py").write_text("x=1\n", encoding="utf-8")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-q", "-m", "src")
    assert fr.freeze(git_repo, "src", profile_path=str(git_repo / "p.sb")) == 2


def test_freeze_rejects_untracked(git_repo: Path) -> None:
    fr = _load_freeze()
    (git_repo / "data" / "traits").mkdir(parents=True)
    (git_repo / "data" / "traits" / "u.txt").write_text("x", encoding="utf-8")
    # data/traits 未 git add
    assert fr.freeze(git_repo, "data/traits", profile_path=str(git_repo / "p.sb")) == 2


def test_freeze_rejects_dirty_tree(git_repo: Path) -> None:
    fr = _load_freeze()
    (git_repo / "data" / "golden" / "golden10.json").write_text(
        '{"items": [1,2]}\n', encoding="utf-8")  # 改动未提交
    assert fr.freeze(git_repo, "data/golden", profile_path=str(git_repo / "p.sb")) == 2


def test_freeze_seals_items_source(git_repo: Path, monkeypatch, tmp_path: Path) -> None:
    """V05 生产端封印点：冻结 data/items 时对 items.jsonl 落 KIND_ITEMS_SOURCE 锚，
    且摘要口径与 review._check_items_source 完全一致（review 有锚可验）。"""
    from abcr.common import external_seal
    from abcr.review import KIND_ITEMS_SOURCE

    store = tmp_path / "anchors" / "seals.jsonl"
    monkeypatch.setenv(external_seal.ANCHOR_STORE_ENV, str(store))

    items_dir = git_repo / "data" / "items" / "ifeval_style"
    items_dir.mkdir(parents=True)
    entries = [
        {"item_id": "a1", "checks": [{"name": "length_words",
                                      "kwargs": {"num_words": 3, "relation": "at least"}}]},
        {"item_id": "a2", "checks": [{"name": "keywords_existence",
                                      "kwargs": {"keywords": ["hello"]}}]},
    ]
    (items_dir / "items.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
        encoding="utf-8")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-q", "-m", "items")

    fr = _load_freeze()
    rc = fr.freeze(git_repo, "data/items", profile_path=str(git_repo / "p.sb"))
    assert rc == 0

    # 锚已写入，subject_id 用 basename（与 review items_file.name 同口径）
    sealed = external_seal.latest_seal(KIND_ITEMS_SOURCE, "items.jsonl")
    assert sealed is not None
    # 与 review 侧重算完全一致（同一 chain_digest_and_length 口径）
    digest, length = external_seal.chain_digest_and_length(entries)
    ok, why = external_seal.verify(KIND_ITEMS_SOURCE, "items.jsonl", digest, length)
    assert ok, why
    assert sealed["length"] == length == 2


def test_freeze_golden_seals_no_items(git_repo: Path, monkeypatch, tmp_path: Path) -> None:
    """冻结不含 items.jsonl 的子树（data/golden）→ 不写任何 items 锚（无副作用）。"""
    from abcr.common import external_seal
    from abcr.review import KIND_ITEMS_SOURCE

    store = tmp_path / "anchors" / "seals.jsonl"
    monkeypatch.setenv(external_seal.ANCHOR_STORE_ENV, str(store))
    fr = _load_freeze()
    assert fr.freeze(git_repo, "data/golden", profile_path=str(git_repo / "p.sb")) == 0
    assert external_seal.latest_seal(KIND_ITEMS_SOURCE, "golden10.json") is None
    assert external_seal.latest_seal(KIND_ITEMS_SOURCE, "items.jsonl") is None
