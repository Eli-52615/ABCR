from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from abcr.control.panel import load_snapshot, main


def snapshot_file(tmp_path):
    path = tmp_path / "public-snapshot.json"
    path.write_text(json.dumps({
        "snapshot_id": "SNAP-fixture",
        "generated_at": "2026-07-21T00:00:00+00:00",
        "source_hash": "a" * 64,
        "stale_after": "2026-07-21T00:02:00+00:00",
        "sections": {"待确认目标": []},
        "severity": "info",
    }), encoding="utf-8")
    path.chmod(0o440)
    return path


def test_panel_doctor_reads_snapshot_without_mutation(tmp_path, capsys):
    path = snapshot_file(tmp_path)
    before = path.stat().st_mtime_ns
    assert main(["--doctor", "--snapshot", str(path)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "ok": True, "read_only": True, "snapshot_id": "SNAP-fixture",
        "source_hash": "a" * 64,
    }
    assert path.stat().st_mtime_ns == before


def test_panel_snapshot_rejects_symlink_writable_and_unknown_fields(tmp_path):
    path = snapshot_file(tmp_path)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        load_snapshot(link)
    path.chmod(0o660)
    with pytest.raises(RuntimeError, match="unsafe"):
        load_snapshot(path)
    path.chmod(0o440)
    value = json.loads(path.read_text())
    value["mutation_url"] = "/approve"
    path.chmod(0o600)
    path.write_text(json.dumps(value))
    path.chmod(0o440)
    with pytest.raises(RuntimeError, match="shape"):
        load_snapshot(path)


def test_stale_snapshot_is_rendered_unknown_not_green(tmp_path):
    path = snapshot_file(tmp_path)
    value = json.loads(path.read_text())
    now = datetime.now(timezone.utc)
    value["generated_at"] = (now - timedelta(minutes=3)).isoformat()
    value["stale_after"] = (now - timedelta(minutes=1)).isoformat()
    value["severity"] = "info"
    path.chmod(0o600)
    path.write_text(json.dumps(value))
    path.chmod(0o440)
    snapshot = load_snapshot(path)
    assert snapshot.severity.value == "unknown"
    assert "快照已过期" in snapshot.sections["状态说明"]
