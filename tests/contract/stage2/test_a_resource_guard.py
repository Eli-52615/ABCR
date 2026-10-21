"""Contract tests for S1.5 resource guard (§3.3).

Coverage:
  1. Lock smoke: acquire + preflight + release
  2. Mutual exclusion: nowait E20, stale reclaim, dual-reclaim one-winner
  3. Soft fuse: debounce, double-warning E19, critical E19, normal resets
  4. Batch guard: consecutive stop, total stop, success resets
  5. Preflight: pressure FAIL, Docker FAIL path
"""

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from abcr.resource_guard import (
    HeavyLock,
    BatchGuard,
    check_pressure_fuse,
    preflight,
    _read_owner,
    PRESSURE_NORMAL,
    PRESSURE_WARNING,
    PRESSURE_CRITICAL,
)


@pytest.fixture
def lock_dir(tmp_path):
    return tmp_path / "heavy.lock"


@pytest.fixture
def make_lock(lock_dir):
    def _make(pkg="test", task="test"):
        return HeavyLock(pkg=pkg, task=task, lock_dir=lock_dir)
    return _make


# ── §3.3.1 Lock smoke ──


class TestLockSmoke:

    def test_acquire_release_cycle(self, make_lock, lock_dir):
        lock = make_lock()
        assert lock.acquire()
        assert lock.held
        assert lock_dir.exists()
        owner = json.loads((lock_dir / "owner.json").read_text())
        assert owner["pkg"] == "test"
        assert owner["pid"] == os.getpid()
        lock.release()
        assert not lock.held
        assert not lock_dir.exists()

    def test_context_manager_releases(self, make_lock, lock_dir):
        lock = make_lock()
        lock.acquire()
        with lock:
            assert lock.held
        assert not lock_dir.exists()

    def test_double_release_safe(self, make_lock):
        lock = make_lock()
        lock.acquire()
        lock.release()
        lock.release()


# ── §3.3.2 Mutual exclusion and recovery ──


class TestMutualExclusion:

    def test_nowait_e20(self, make_lock, lock_dir):
        """Second acquirer with --nowait returns False (E20)."""
        lock1 = make_lock(pkg="holder")
        assert lock1.acquire()
        lock2 = HeavyLock(pkg="waiter", task="wait", lock_dir=lock_dir)
        assert not lock2.acquire(nowait=True)
        lock1.release()

    def test_stale_lock_dead_pid_reclaim(self, lock_dir):
        """Stale lock with dead pid recovered via rename protocol."""
        lock_dir.parent.mkdir(parents=True, exist_ok=True)
        lock_dir.mkdir()
        owner = {
            "pkg": "dead", "pid": 999999,
            "pid_start_time": "Wed Jan  1 00:00:00 2020",
            "task": "dead", "started_at": "2020-01-01T00:00:00Z",
        }
        (lock_dir / "owner.json").write_text(json.dumps(owner))

        lock = HeavyLock(pkg="reclaimer", task="reclaim", lock_dir=lock_dir)
        assert lock.acquire()
        new_owner = json.loads((lock_dir / "owner.json").read_text())
        assert new_owner["pkg"] == "reclaimer"
        lock.release()

    def test_fresh_lock_without_owner_not_stale(self, lock_dir):
        """Lock dir created <10s ago without owner.json is not treated as stale."""
        lock_dir.parent.mkdir(parents=True, exist_ok=True)
        lock_dir.mkdir()

        lock = HeavyLock(pkg="waiter", task="wait", lock_dir=lock_dir)
        assert not lock.acquire(nowait=True)
        lock_dir.rmdir()

    def test_dual_reclaim_one_winner(self, lock_dir):
        """Two concurrent reclaimers — exactly one acquires."""
        lock_dir.parent.mkdir(parents=True, exist_ok=True)
        lock_dir.mkdir()
        owner = {
            "pkg": "dead", "pid": 999999,
            "pid_start_time": "Wed Jan  1 00:00:00 2020",
            "task": "dead", "started_at": "2020-01-01T00:00:00Z",
        }
        (lock_dir / "owner.json").write_text(json.dumps(owner))

        results = []
        barrier = threading.Barrier(2)

        def try_acquire(idx):
            lock = HeavyLock(pkg=f"racer{idx}", task="race", lock_dir=lock_dir)
            barrier.wait()
            got = lock.acquire(nowait=True)
            results.append((idx, got))
            if got:
                time.sleep(0.2)
                lock.release()

        threads = [threading.Thread(target=try_acquire, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        wins = [r for r in results if r[1]]
        assert len(wins) == 1, f"Expected 1 winner, got {len(wins)}: {results}"


# ── §3.3.3 Soft fuse ──


class TestSoftFuse:

    def test_single_warning_no_trigger(self):
        with patch.dict(os.environ, {"ABCR_FAKE_PRESSURE": "warning"}):
            action, count = check_pressure_fuse(0)
        assert action is None
        assert count == 1

    def test_double_warning_triggers_e19(self):
        with patch.dict(os.environ, {"ABCR_FAKE_PRESSURE": "warning"}):
            action, count = check_pressure_fuse(0)
            assert action is None
            assert count == 1
            action, count = check_pressure_fuse(count)
            assert action == "e19_warning"
            assert count == 2

    def test_critical_single_trigger(self):
        with patch.dict(os.environ, {"ABCR_FAKE_PRESSURE": "critical"}):
            action, count = check_pressure_fuse(0)
        assert action == "e19_critical"

    def test_normal_resets_warning_count(self):
        with patch.dict(os.environ, {"ABCR_FAKE_PRESSURE": "normal"}):
            action, count = check_pressure_fuse(1)
        assert action is None
        assert count == 0

    def test_warning_then_normal_then_warning_debounces(self):
        with patch.dict(os.environ, {"ABCR_FAKE_PRESSURE": "warning"}):
            _, count = check_pressure_fuse(0)
        assert count == 1
        with patch.dict(os.environ, {"ABCR_FAKE_PRESSURE": "normal"}):
            _, count = check_pressure_fuse(count)
        assert count == 0
        with patch.dict(os.environ, {"ABCR_FAKE_PRESSURE": "warning"}):
            action, count = check_pressure_fuse(count)
        assert action is None
        assert count == 1


# ── §3.3.4 Batch guard + preflight FAIL ──


class TestBatchGuard:

    def test_3_consecutive_e19_stops(self):
        guard = BatchGuard()
        assert guard.record_e19() is None
        assert guard.record_e19() is None
        result = guard.record_e19()
        assert result == "stop_consecutive"

    def test_success_resets_consecutive(self):
        guard = BatchGuard()
        guard.record_e19()
        guard.record_e19()
        guard.record_success()
        assert guard.record_e19() is None
        assert guard.record_e19() is None
        result = guard.record_e19()
        assert result == "stop_consecutive"

    def test_5_total_e19_stops(self):
        guard = BatchGuard()
        for _ in range(4):
            guard.record_e19()
            guard.record_success()
        result = guard.record_e19()
        assert result == "stop_total"


class TestPreflightFail:

    def test_pressure_critical_fails(self):
        with patch.dict(os.environ, {"ABCR_FAKE_PRESSURE": "critical"}), \
             patch("abcr.resource_guard.time.sleep"):
            ok, issues = preflight(log_fn=lambda x: None)
        assert not ok
        assert any("pressure" in i for i in issues)

    def test_docker_still_running_fails(self):
        with patch.dict(os.environ, {"ABCR_FAKE_PRESSURE": "normal"}), \
             patch("abcr.resource_guard.time.sleep"), \
             patch("abcr.resource_guard._is_docker_running", return_value=True), \
             patch("abcr.resource_guard._quit_docker"):
            ok, issues = preflight(log_fn=lambda x: None)
        assert not ok
        assert any("docker" in i.lower() for i in issues)

    def test_manifest_resource_events(self, tmp_path):
        """finalize_manifest correctly records resource_events."""
        from abcr.logging.manifest import finalize_manifest
        run_dir = tmp_path / "test-run"
        run_dir.mkdir()
        manifest = {
            "run_id": "test",
            "finished_at": None,
            "n_steps_written": 0,
            "repair_events": [],
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest))

        events = [{"ts": "2026-07-12T00:00:00Z", "reason": "e19_warning", "steps_done": 5}]
        finalize_manifest(run_dir, 5, resource_events=events)

        result = json.loads((run_dir / "manifest.json").read_text())
        assert "resource_events" in result
        assert len(result["resource_events"]) == 1
        assert result["resource_events"][0]["reason"] == "e19_warning"
        assert result["n_steps_written"] == 5
