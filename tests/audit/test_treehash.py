"""tests/audit/test_treehash.py —— A2-2 code_tree_hash 计算与三向对账。

文档验收用例：同一临时目录两次 hash 相等；改 1 字节 → drift 指到该文件；删文件 → missing。
"""
from __future__ import annotations

from pathlib import Path

from abcr.audit.treehash import code_tree_hash, diff_trees, hash_tree


def _seed(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "b.py").write_text("x = 1\n", encoding="utf-8")
    (root / "data" / "golden").mkdir(parents=True)
    (root / "data" / "golden" / "g.json").write_text('{"k": 1}', encoding="utf-8")


def test_hash_deterministic_two_runs_equal(tmp_path: Path) -> None:
    _seed(tmp_path)
    assert code_tree_hash(tmp_path) == code_tree_hash(tmp_path)


def test_hash_is_64_hex(tmp_path: Path) -> None:
    _seed(tmp_path)
    h = code_tree_hash(tmp_path)
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)


def test_one_byte_change_drifts_that_file(tmp_path: Path) -> None:
    _seed(tmp_path)
    before = hash_tree(tmp_path)
    (tmp_path / "src" / "a.py").write_text("print('a')  # changed\n", encoding="utf-8")
    after = hash_tree(tmp_path)
    d = diff_trees(before, after)
    assert d["drift"] == ["src/a.py"], d
    assert d["missing"] == [] and d["extra"] == []
    assert code_tree_hash(tmp_path) != _hash_of(before)


def _hash_of(tree: dict) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(tree, sort_keys=True).encode("utf-8")).hexdigest()


def test_delete_file_shows_missing(tmp_path: Path) -> None:
    _seed(tmp_path)
    before = hash_tree(tmp_path)
    (tmp_path / "scripts" / "b.py").unlink()
    after = hash_tree(tmp_path)
    d = diff_trees(before, after)
    assert d["missing"] == ["scripts/b.py"], d


def test_excludes_only_derived_artifacts(tmp_path: Path) -> None:
    """V10：只排派生物（__pycache__ 目录 + *.pyc/*.so 后缀），其余全文件逐字节 hash。

    旧白名单实现会漏掉 .log/无后缀/*.hash/*.sha256 文件（可被替换而树哈希不变）；
    全文件 hash 后这些一律纳入承诺。"""
    _seed(tmp_path)
    (tmp_path / "src" / "__pycache__").mkdir()
    (tmp_path / "src" / "__pycache__" / "x.pyc").write_text("junk", encoding="utf-8")
    (tmp_path / "src" / "note.log").write_text("ignore me", encoding="utf-8")
    (tmp_path / "src" / "ext.so").write_text("binary", encoding="utf-8")
    # 旧白名单外的高危文件型别：无后缀入口 / 锚点文件
    (tmp_path / "scripts" / "abcrctl").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "chat_template.hash").write_text("deadbeef", encoding="utf-8")
    (tmp_path / "data" / "splits").mkdir(parents=True)
    (tmp_path / "data" / "splits" / "dev.sha256").write_text("abc123", encoding="utf-8")
    tree = hash_tree(tmp_path)
    # 派生物：排除
    assert not any("__pycache__" in k for k in tree)
    assert "src/ext.so" not in tree
    # V10：一切非派生物纳入（旧实现会漏掉这四类）
    assert "src/note.log" in tree
    assert "scripts/abcrctl" in tree
    assert "configs/chat_template.hash" in tree
    assert "data/splits/dev.sha256" in tree


def test_only_frozen_roots_scanned(tmp_path: Path) -> None:
    _seed(tmp_path)
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "z.py").write_text("noise", encoding="utf-8")
    tree = hash_tree(tmp_path)
    assert not any(k.startswith("runtime") for k in tree)
