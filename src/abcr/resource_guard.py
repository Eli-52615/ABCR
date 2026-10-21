"""ABCR resource guard — heavy.lock protocol, preflight, soft fuse (F14/S1.5).

stdlib-only module. torch lazily imported only for MPS helpers.
CLI: python -m abcr.resource_guard {smoke|smoke-3b|run [--nowait] -- <cmd>}
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESOURCE_DIR = _PROJECT_ROOT / ".resource"
LOCK_DIR = RESOURCE_DIR / "heavy.lock"

PRESSURE_NORMAL = 1
PRESSURE_WARNING = 2
PRESSURE_CRITICAL = 4
# Sentinel for "probe unreliable / result untrustworthy" (F-A-03 fail-closed).
# Distinct from NORMAL so preflight/fuse treat probe failure as a blocking
# condition (E21 / E19), never as "no pressure".
PRESSURE_UNKNOWN = -1
_PRESSURE_NAMES = {1: "normal", 2: "warning", 4: "critical", -1: "unknown"}

# Disk preflight threshold — frozen spec L-13: free_bytes >= 50_000_000_000 (SI GB),
# NOT GiB. Comparing raw bytes keeps the gate on the frozen SI boundary (F-A-14).
DISK_FREE_MIN_BYTES = 50_000_000_000


class ProbeError(Exception):
    """Raised when a resource probe cannot produce a trustworthy result.

    Probe failure (timeout, permission, missing tool, unparseable output) must
    NOT be silently mapped to a benign value (no pressure / no heavy proc / no
    Docker). Callers convert this into E21 preflight failure (fail-closed).
    """


class LockFencingError(Exception):
    """Raised when a lock operation detects it no longer owns the lock dir.

    The lock directory's inode changed out from under us (another holder
    reclaimed it), so we must not write owner metadata into or delete a
    directory that now belongs to a different, possibly-live owner.
    """


def get_lock_dir() -> Path:
    override = os.environ.get("ABCR_LOCK_DIR")
    if override:
        p = Path(override) / "heavy.lock"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return LOCK_DIR


# ── Probes (stdlib only) ──


def get_pressure_level() -> int:
    """Return macOS memory pressure level, or PRESSURE_UNKNOWN if unprobeable.

    Fail-closed (F-A-03): a probe timeout / permission error / unparseable
    output returns PRESSURE_UNKNOWN (not PRESSURE_NORMAL), so downstream gates
    treat an untrustworthy probe as a blocking condition rather than "no
    pressure". An unrecognized ABCR_FAKE_PRESSURE value also maps to UNKNOWN.
    """
    fake = os.environ.get("ABCR_FAKE_PRESSURE")
    if fake:
        return {"normal": PRESSURE_NORMAL, "warning": PRESSURE_WARNING,
                "critical": PRESSURE_CRITICAL,
                "unknown": PRESSURE_UNKNOWN}.get(fake.lower(), PRESSURE_UNKNOWN)
    try:
        out = subprocess.check_output(
            ["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
            text=True, timeout=5,
        ).strip()
        return int(out)
    except Exception:
        return PRESSURE_UNKNOWN


def get_swap_usage() -> dict[str, float]:
    """Return swap usage in MB. Empty dict means unprobeable.

    Swap is logged only (non-gating), so an empty result is acceptable here;
    callers that log it must treat {} as "unknown", not "0MB used".
    """
    try:
        out = subprocess.check_output(
            ["sysctl", "vm.swapusage"], text=True, timeout=5,
        ).strip()
        result = {}
        for m in re.finditer(r"(\w+)\s*=\s*([\d.]+)M", out):
            result[m.group(1)] = float(m.group(2))
        return result
    except Exception:
        return {}


def get_disk_free_bytes(path: str | None = None) -> int:
    """Free bytes on the filesystem holding `path` (default project root).

    Raises OSError if statvfs fails — callers must treat that as a probe
    failure (fail-closed), never as "enough disk".
    """
    st = os.statvfs(path or str(_PROJECT_ROOT))
    return st.f_bavail * st.f_frsize


def get_disk_free_gb(path: str | None = None) -> float:
    """Free space in GiB (for display/logging only).

    The preflight gate compares raw bytes against DISK_FREE_MIN_BYTES (frozen
    SI spec, F-A-14); this GiB helper is retained for human-readable output.
    """
    return get_disk_free_bytes(path) / (1024**3)


def get_pid_start_time(pid: int) -> str:
    try:
        return subprocess.check_output(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            text=True, timeout=5,
        ).strip()
    except Exception:
        return ""


def _find_heavy_processes(rss_threshold_gb: float = 2.0) -> list[dict]:
    """List heavy python/torch processes. Raises ProbeError if `ps` is unusable.

    Fail-closed (F-A-03): a `ps` timeout / crash / unparseable line must not be
    swallowed into an empty list ("no heavy processes"), which would let a heavy
    task launch amid real contention. An unreadable probe is a ProbeError.
    """
    result = []
    my_pid = os.getpid()
    try:
        out = subprocess.check_output(["ps", "-eo", "pid,rss,comm"], text=True, timeout=10)
    except Exception as e:
        raise ProbeError(f"ps probe failed: {e}") from e
    for line in out.strip().splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            rss_kb = int(parts[1])
        except ValueError:
            # A single malformed row is skipped, but the probe as a whole
            # already succeeded (ps ran); this is not a probe failure.
            continue
        comm = parts[2]
        if pid == my_pid:
            continue
        rss_gb = rss_kb / (1024 * 1024)
        if rss_gb >= rss_threshold_gb and ("python" in comm.lower() or "torch" in comm.lower()):
            result.append({"pid": pid, "rss_gb": round(rss_gb, 2), "comm": comm})
    return result


def _is_docker_running() -> bool:
    """True if the Docker VM is running. Raises ProbeError if undetectable.

    Fail-closed (F-A-03): only pgrep's exit-code-1 (no matching process) is the
    legitimate "Docker not running" answer. A timeout, missing pgrep, or other
    error means we cannot tell — that must surface as ProbeError, not a False
    that silently skips the Docker gate.
    """
    try:
        subprocess.check_output(["pgrep", "-f", "com.docker.virtualization"], timeout=5)
        return True
    except subprocess.CalledProcessError as e:
        # pgrep exits 1 when no process matches → Docker genuinely not running.
        if e.returncode == 1:
            return False
        raise ProbeError(f"pgrep probe failed (rc={e.returncode})") from e
    except Exception as e:
        raise ProbeError(f"pgrep probe failed: {e}") from e


def _quit_docker() -> None:
    try:
        subprocess.run(
            ["osascript", "-e", 'quit app "Docker"'],
            timeout=10, capture_output=True,
        )
    except Exception:
        pass


# ── Lock internals ──


def _pid_alive(pid: int, expected_start: str) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    if expected_start:
        actual = get_pid_start_time(pid)
        if actual and actual != expected_start:
            return False
    return True


def _read_owner(lock_dir: Path) -> dict | None:
    try:
        return json.loads((lock_dir / "owner.json").read_text())
    except Exception:
        return None


def _write_owner(lock_dir: Path, pkg: str, task: str,
                 fence_ino: int | None = None) -> None:
    """Write owner metadata, refusing to clobber a reclaimed lock dir (F-A-09).

    `fence_ino` is the inode of the lock dir captured at mkdir time. Before
    writing, we verify the current lock dir still has that inode. If it does
    not, another process reclaimed the lock (rename + fresh mkdir), so writing
    owner.json here would overwrite the live new owner's metadata — we raise
    LockFencingError instead of clobbering it.
    """
    if fence_ino is not None:
        try:
            cur_ino = lock_dir.stat().st_ino
        except OSError as e:
            raise LockFencingError(
                f"lock dir vanished before owner write: {e}") from e
        if cur_ino != fence_ino:
            raise LockFencingError(
                f"lock dir inode changed ({fence_ino}->{cur_ino}); "
                "lock was reclaimed by another holder")
    pid = os.getpid()
    data = {
        "pkg": pkg,
        "pid": pid,
        "pid_start_time": get_pid_start_time(pid),
        "task": task,
        "lock_ino": fence_ino,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (lock_dir / "owner.json").write_text(json.dumps(data, indent=2))


# ── HeavyLock ──


class HeavyLock:
    """Atomic directory-based lock with lease semantics (F14.2)."""

    def __init__(self, pkg: str = "A", task: str = "",
                 lock_dir: Path | None = None):
        self.pkg = pkg
        self.task = task
        self.lock_dir = lock_dir or LOCK_DIR
        self.resource_dir = self.lock_dir.parent
        self._held = False
        self._fence_ino: int | None = None

    @property
    def held(self) -> bool:
        return self._held

    def owner_info(self) -> dict | None:
        return _read_owner(self.lock_dir)

    def acquire(self, nowait: bool = False, timeout_h: float = 8.0) -> bool:
        self.resource_dir.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        last_log = -300.0

        while True:
            try:
                self.lock_dir.mkdir()
                # Capture the inode we just created so a later reclaim (rename +
                # fresh mkdir by another process) can be detected before we
                # write owner metadata or delete the dir (F-A-09 fencing).
                self._fence_ino = self.lock_dir.stat().st_ino
                _write_owner(self.lock_dir, self.pkg, self.task,
                             fence_ino=self._fence_ino)
                self._held = True
                return True
            except FileExistsError:
                pass
            except LockFencingError:
                # We created the dir but lost it to a reclaim before writing
                # owner metadata. Do not hold; fall through and retry/queue.
                self._fence_ino = None

            if self._is_stale():
                if self._reclaim():
                    continue

            if nowait:
                return False

            elapsed = time.monotonic() - start
            if elapsed / 3600 >= timeout_h:
                return False

            if elapsed - last_log >= 300:
                owner = _read_owner(self.lock_dir)
                info = ""
                if owner:
                    info = f" (held by {owner['pkg']}:{owner['task']} pid={owner['pid']})"
                print(f"[resource_guard] Queued {elapsed/60:.0f}min{info}")
                last_log = elapsed

            time.sleep(30)

    def _is_stale(self) -> bool:
        # Fail-closed (F-A-09 / L-12): with no verifiable owner (missing OR
        # corrupt owner.json → _read_owner returns None) we must NOT steal the
        # lock purely on directory age. Age-only reclaim can wrongly evict a
        # live holder that has mkdir'd but not yet written owner.json (or whose
        # metadata is momentarily unreadable). A lock is only stale when we can
        # positively confirm its recorded owner PID is dead.
        try:
            self.lock_dir.stat()
        except OSError:
            # Directory no longer exists → nothing to reclaim; not "stale-held".
            return False
        owner = _read_owner(self.lock_dir)
        if owner is None:
            return False
        pid = owner.get("pid")
        if not isinstance(pid, int):
            # Owner record present but has no usable PID → cannot verify death;
            # refuse to steal (fail-closed).
            return False
        return not _pid_alive(pid, owner.get("pid_start_time", ""))

    def _reclaim(self) -> bool:
        ts = int(time.time())
        reclaim_path = self.resource_dir / f"heavy.lock.reclaimed-{os.getpid()}-{ts}"
        try:
            self.lock_dir.rename(reclaim_path)
        except OSError:
            return False
        shutil.rmtree(reclaim_path, ignore_errors=True)
        return True

    def release(self) -> None:
        if not self._held:
            return
        # Fail-closed (F-A-09): only delete the lock dir if it is still the exact
        # inode we acquired. If it was reclaimed (rename + fresh mkdir by another
        # holder), the current dir belongs to a possibly-live new owner — deleting
        # it would drop their lock and let a concurrent heavy task in.
        if self._fence_ino is not None:
            try:
                cur_ino = self.lock_dir.stat().st_ino
            except OSError:
                self._held = False
                self._fence_ino = None
                return
            if cur_ino != self._fence_ino:
                # Not our directory anymore — leave it untouched.
                self._held = False
                self._fence_ino = None
                return
        try:
            owner_path = self.lock_dir / "owner.json"
            if owner_path.exists():
                owner_path.unlink()
            self.lock_dir.rmdir()
        except OSError:
            shutil.rmtree(self.lock_dir, ignore_errors=True)
        self._held = False
        self._fence_ino = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.release()


# ── Preflight ──


def preflight(log_fn=print) -> tuple[bool, list[str]]:
    """Run preflight checks inside the lock (§3.2). Returns (passed, issues)."""
    issues: list[str] = []

    log_fn("[preflight] Sampling memory pressure for 60s...")
    for i in range(12):
        level = get_pressure_level()
        if level == PRESSURE_UNKNOWN:
            # Fail-closed (F-A-03/E21): an unreadable pressure probe is a block,
            # never treated as "normal / no pressure".
            issues.append(f"E21 memory pressure probe UNKNOWN at sample {i+1}/12 "
                          "(fail-closed)")
            return False, issues
        if level != PRESSURE_NORMAL:
            name = _PRESSURE_NAMES.get(level, f"unknown({level})")
            issues.append(f"memory pressure {name} at sample {i+1}/12")
            return False, issues
        if i < 11:
            time.sleep(5)
    log_fn("[preflight] Memory pressure: 12/12 normal ✓")

    # Disk gate on the frozen SI byte threshold (F-A-14). A statvfs failure is a
    # probe failure → E21, not a pass.
    try:
        free_bytes = get_disk_free_bytes()
    except OSError as e:
        issues.append(f"E21 disk probe failed: {e} (fail-closed)")
        return False, issues
    if free_bytes < DISK_FREE_MIN_BYTES:
        issues.append(f"disk free {free_bytes/1e9:.1f}GB < "
                      f"{DISK_FREE_MIN_BYTES/1e9:.0f}GB")
        return False, issues
    log_fn(f"[preflight] Disk free: {free_bytes/1e9:.1f}GB ✓")

    # Heavy-process gate. An unreadable `ps` is E21, never "no heavy procs".
    try:
        heavy = _find_heavy_processes()
    except ProbeError as e:
        issues.append(f"E21 heavy-process probe failed: {e} (fail-closed)")
        return False, issues
    if heavy:
        for p in heavy:
            issues.append(f"heavy process pid={p['pid']} RSS={p['rss_gb']:.2f}GB {p['comm']}")
        return False, issues
    log_fn("[preflight] No heavy python/torch processes ✓")

    # Docker gate. An unreadable pgrep is E21, never "no Docker".
    try:
        docker_up = _is_docker_running()
    except ProbeError as e:
        issues.append(f"E21 Docker probe failed: {e} (fail-closed)")
        return False, issues
    if docker_up:
        log_fn("[preflight] Docker detected, attempting quit...")
        _quit_docker()
        time.sleep(30)
        try:
            still_up = _is_docker_running()
        except ProbeError as e:
            issues.append(f"E21 Docker re-probe failed after quit: {e} (fail-closed)")
            return False, issues
        if still_up:
            issues.append("Docker VM still running after quit attempt")
            return False, issues
        log_fn("[preflight] Docker quit successfully ✓")
    else:
        log_fn("[preflight] No Docker VM ✓")

    swap = get_swap_usage()
    if swap:
        log_fn(f"[preflight] Swap used: {swap.get('used', 0):.0f}MB (logged)")
    else:
        log_fn("[preflight] Swap usage: unknown (probe unavailable, logged)")

    return True, issues


# ── Soft fuse ──


def check_pressure_fuse(consecutive_warnings: int) -> tuple[str | None, int]:
    """Sample-between pressure check (F14.6).
    Returns (action, updated_warning_count).
    action: None=continue, 'e19_warning', 'e19_critical'.
    """
    level = get_pressure_level()
    if level == PRESSURE_UNKNOWN:
        # Fail-closed (F-A-03): between-chunk pressure probe unreadable → stop
        # the batch rather than continue blind. Treated as a hard (critical)
        # stop so run.py exits the batch immediately.
        return "e19_critical", 0
    if level == PRESSURE_CRITICAL:
        return "e19_critical", 0
    if level == PRESSURE_WARNING:
        consecutive_warnings += 1
        if consecutive_warnings >= 2:
            return "e19_warning", consecutive_warnings
        return None, consecutive_warnings
    return None, 0


# ── Batch guard ──


class BatchGuard:
    """Tracks E19 events and enforces stop-batch thresholds (F14.6)."""

    def __init__(self):
        self._consecutive = 0
        self._consecutive_times: list[float] = []
        self._total = 0

    def record_e19(self) -> str | None:
        """Record an E19 event. Returns stop reason or None."""
        now = time.monotonic()
        self._consecutive += 1
        self._consecutive_times.append(now)
        self._total += 1

        if self._consecutive >= 3:
            if now - self._consecutive_times[-3] < 3600:
                return "stop_consecutive"

        if self._total >= 5:
            return "stop_total"

        return None

    def record_success(self) -> None:
        """Record a successful chunk, resetting consecutive counter."""
        self._consecutive = 0
        self._consecutive_times = []


# ── MPS helpers (lazy import torch) ──


def set_mps_memory_limit() -> float | None:
    """Set MPS per-process memory fraction to cap at 8GiB (F14.4)."""
    try:
        import torch
        if not torch.backends.mps.is_available():
            return None
        recommended = torch.mps.recommended_max_memory()
        target = 8 * (2**30)
        fraction = min(1.0, target / recommended)
        torch.mps.set_per_process_memory_fraction(fraction)
        return fraction
    except Exception:
        return None


def mps_cleanup() -> int | None:
    """Post-chunk MPS cleanup (F14.4). Returns driver_allocated_memory bytes."""
    try:
        import gc
        import torch
        if not torch.backends.mps.is_available():
            return None
        gc.collect()
        torch.mps.empty_cache()
        return torch.mps.driver_allocated_memory()
    except Exception:
        return None


# ── CLI ──


def _cli_smoke() -> None:
    print("[smoke] Acquiring heavy.lock...")
    ld = get_lock_dir()
    lock = HeavyLock(pkg="smoke", task="smoke", lock_dir=ld)
    if not lock.acquire(nowait=True):
        owner = lock.owner_info()
        print(f"FAIL: lock held by {json.dumps(owner)}", file=sys.stderr)
        sys.exit(1)
    try:
        print("[smoke] Lock acquired, running preflight...")
        ok, issues = preflight()
        if not ok:
            print(f"FAIL: {'; '.join(issues)}", file=sys.stderr)
            sys.exit(1)
        print("PASS")
    finally:
        lock.release()
        print("[smoke] Lock released")


def _cli_smoke_3b() -> None:
    import torch

    ld = get_lock_dir()
    lock = HeavyLock(pkg="smoke-3b", task="smoke-3b", lock_dir=ld)
    if not lock.acquire():
        print("FAIL: Could not acquire lock", file=sys.stderr)
        sys.exit(1)

    try:
        ok, issues = preflight()
        if not ok:
            print(f"FAIL: preflight: {'; '.join(issues)}", file=sys.stderr)
            sys.exit(1)

        fraction = set_mps_memory_limit()
        if fraction is not None:
            print(f"[smoke-3b] MPS fraction: {fraction:.3f}")

        from abcr.models import load
        model, tokenizer, meta = load("qwen2.5-3b-instruct")

        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": "Hello, how are you?"}],
            tokenize=False, add_generation_prompt=True,
        )

        for i in range(2):
            torch.manual_seed(42)
            inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
            with torch.inference_mode():
                out = model.generate(**inputs, max_new_tokens=20, do_sample=False,
                                     pad_token_id=tokenizer.eos_token_id)
            text = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:],
                                    skip_special_tokens=True)
            if torch.backends.mps.is_available():
                mem = torch.mps.driver_allocated_memory()
                print(f"[smoke-3b] Item {i+1}: {len(text)} chars, MPS: {mem/(1024**3):.2f}GB")
            else:
                print(f"[smoke-3b] Item {i+1}: {len(text)} chars")

        del model, tokenizer
        allocated = mps_cleanup()
        if allocated is not None:
            print(f"[smoke-3b] Post-cleanup MPS: {allocated/(1024**3):.2f}GB")

        time.sleep(5)
        level = get_pressure_level()
        name = _PRESSURE_NAMES.get(level, str(level))
        print(f"[smoke-3b] Post-unload pressure: {name}")
        print("PASS")
    finally:
        lock.release()


def _cli_run(args: list[str]) -> None:
    nowait = "--nowait" in args
    cmd_args = list(args)
    if nowait:
        cmd_args.remove("--nowait")
    if "--" in cmd_args:
        cmd_args = cmd_args[cmd_args.index("--") + 1:]
    if not cmd_args:
        print("Usage: python -m abcr.resource_guard run [--nowait] -- <cmd>",
              file=sys.stderr)
        sys.exit(1)

    from abcr.logging.errors import E20_RESOURCE_LEASE_BUSY, E21_PREFLIGHT_RESOURCE_FAIL

    ld = get_lock_dir()
    lock = HeavyLock(pkg="CLI", task=" ".join(cmd_args), lock_dir=ld)
    if not lock.acquire(nowait=nowait):
        if nowait:
            owner = lock.owner_info()
            print(f"{E20_RESOURCE_LEASE_BUSY}: heavy.lock held\n"
                  f"{json.dumps(owner, indent=2) if owner else 'unknown'}",
                  file=sys.stderr)
            sys.exit(20)
        print(f"{E20_RESOURCE_LEASE_BUSY}: lease timeout (8h)", file=sys.stderr)
        sys.exit(20)

    try:
        ok, issues = preflight()
        if not ok:
            print(f"{E21_PREFLIGHT_RESOURCE_FAIL}: {'; '.join(issues)}",
                  file=sys.stderr)
            lock.release()
            sys.exit(21)
        result = subprocess.run(cmd_args)
        sys.exit(result.returncode)
    finally:
        lock.release()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m abcr.resource_guard {smoke|smoke-3b|run} ...",
              file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "smoke":
        _cli_smoke()
    elif cmd == "smoke-3b":
        _cli_smoke_3b()
    elif cmd == "run":
        _cli_run(sys.argv[2:])
    else:
        print(f"Unknown subcommand: {cmd}", file=sys.stderr)
        sys.exit(1)
