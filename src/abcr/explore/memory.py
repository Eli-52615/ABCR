"""Append-only research memory for human goals, reflections and round lineage."""
from __future__ import annotations

import json
import errno
import fcntl
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from abcr.control.attestation import (DOMAIN_RESEARCH_MEMORY, sign_attestation,
                                      verify_attestation)
from abcr.control.contracts import ContractError, canonical_json, require_sha, sha256, utc_now


RESEARCH_MEMORY_SEAL_SCHEMA = "abcr.research-memory-seal.v1"


def _json_no_duplicates(raw: bytes | str) -> Any:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in values:
            if key in out:
                raise ValueError(f"duplicate JSON key: {key}")
            out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=pairs)


class ResearchMemory:
    def __init__(self, path: Path, *, owner_uid: int | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.owner_uid = os.geteuid() if owner_uid is None else owner_uid

    def _check_parent(self) -> None:
        info = self.path.parent.lstat()
        if (self.path.parent.is_symlink() or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != self.owner_uid or info.st_mode & 0o022):
            raise ContractError("research_memory_parent_unsafe",
                                "ResearchMemory 父目录 owner/mode 不安全")

    def _open_lock(self) -> int:
        self._check_parent()
        lock_path = self.path.with_name(self.path.name + ".lock")
        flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        if os.geteuid() == self.owner_uid:
            flags |= os.O_CREAT
        try:
            fd = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise ContractError("research_memory_lock_unsafe", "ResearchMemory lock 不可达") from exc
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != self.owner_uid or info.st_mode & 0o077):
            os.close(fd)
            raise ContractError("research_memory_lock_unsafe",
                                "ResearchMemory lock owner/mode/link 不安全")
        return fd

    @contextmanager
    def exclusive_lock(self):
        """Lock shared by the ledger writer and root seal refresh operation."""
        fd = self._open_lock()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _open_ledger(self, *, create: bool, writable: bool) -> int:
        flags = (os.O_RDWR | os.O_APPEND) if writable else os.O_RDONLY
        flags |= getattr(os, "O_NOFOLLOW", 0)
        if create:
            flags |= os.O_CREAT
        try:
            fd = os.open(self.path, flags, 0o600)
        except OSError as exc:
            if not create and exc.errno == errno.ENOENT:
                return -1
            raise ContractError("research_memory_file_unsafe", "ResearchMemory 文件不可达") from exc
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != self.owner_uid or info.st_mode & 0o022):
            os.close(fd)
            raise ContractError("research_memory_file_unsafe",
                                "ResearchMemory owner/mode/link 不安全")
        return fd

    @staticmethod
    def _read_fd(fd: int) -> bytes:
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)

    @staticmethod
    def _verify_raw(raw: bytes) -> list[dict[str, Any]]:
        previous = "0" * 64
        rows: list[dict[str, Any]] = []
        for line in raw.splitlines():
            row = _json_no_duplicates(line)
            required = {"event_type", "subject_id", "actor_id", "payload", "created_at",
                        "prev_hash", "entry_hash"}
            if (not isinstance(row, dict) or set(row) != required
                    or not all(isinstance(row.get(key), str) and row[key]
                               for key in ("event_type", "subject_id", "actor_id", "created_at"))
                    or not isinstance(row.get("payload"), dict)
                    or not isinstance(row.get("entry_hash"), str)):
                raise ValueError("research memory row shape invalid")
            entry = row.pop("entry_hash")
            if row.get("prev_hash") != previous or sha256(row) != entry:
                raise ValueError("research memory hash chain invalid")
            row["entry_hash"] = entry
            rows.append(row)
            previous = entry
        return rows

    def append(self, event_type: str, subject_id: str, payload: dict[str, Any],
               *, actor_id: str) -> dict[str, Any]:
        if self.owner_uid != os.geteuid():
            raise ContractError("research_memory_writer_uid", "只有登记 owner 可追加 ResearchMemory")
        with self.exclusive_lock():
            fd = self._open_ledger(create=True, writable=True)
            try:
                rows = self._verify_raw(self._read_fd(fd))
                previous = rows[-1]["entry_hash"] if rows else "0" * 64
                core = {"event_type": event_type, "subject_id": subject_id, "actor_id": actor_id,
                        "payload": payload, "created_at": utc_now(), "prev_hash": previous}
                row = dict(core, entry_hash=sha256(core))
                raw = canonical_json(row) + b"\n"
                view = memoryview(raw)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("short write while appending ResearchMemory")
                    view = view[written:]
                os.fsync(fd)
                return row
            finally:
                os.close(fd)

    def verify(self) -> list[dict[str, Any]]:
        fd = self._open_ledger(create=False, writable=False)
        if fd < 0:
            return []
        try:
            return self._verify_raw(self._read_fd(fd))
        finally:
            os.close(fd)

    def seal_core(self) -> dict[str, Any]:
        """Return the exact current ledger commitment used by the external signer.

        The resolved path is part of the commitment so a valid seal for a fixture or
        shadow ledger cannot be replayed for the configured production ledger.
        """
        fd = self._open_ledger(create=False, writable=False)
        if fd < 0:
            raise ContractError("research_memory_empty", "空 ResearchMemory 不可封印")
        try:
            raw = self._read_fd(fd)
        finally:
            os.close(fd)
        rows = self._verify_raw(raw)
        if not rows:
            raise ContractError("research_memory_empty", "空 ResearchMemory 不可封印")
        return {
            "schema": RESEARCH_MEMORY_SEAL_SCHEMA,
            "ledger_path": str(self.path.resolve(strict=True)),
            "length": len(rows),
            "head_entry_hash": rows[-1]["entry_hash"],
            "ledger_sha256": sha256(raw),
        }

    def write_external_seal(self, seal_path: Path, *, private_key: Path,
                            public_key: Path) -> dict[str, Any]:
        """Write a detached, domain-separated seal for the current complete ledger.

        Production calls belong in the root-owned signer/bootstrap boundary.  The
        ledger writer must not possess ``private_key``.  This method is also the
        deterministic fixture helper used to exercise the same wire format.
        """
        core = self.seal_core()
        sealed = sign_attestation(private_key=Path(private_key), public_key=Path(public_key),
                                  domain=DOMAIN_RESEARCH_MEMORY, core=core)
        document = {"core": core, "sealed": sealed}
        target = Path(seal_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        parent = target.parent.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or target.parent.is_symlink()
                or parent.st_uid != os.geteuid() or parent.st_mode & 0o022):
            raise ContractError("research_memory_seal_path", "seal 父目录不安全")
        if target.exists() or target.is_symlink():
            info = target.lstat()
            if target.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ContractError("research_memory_seal_path", "seal 必须是单链接 regular file")
        fd, tmp_name = tempfile.mkstemp(prefix=".research-seal-", dir=target.parent)
        tmp = Path(tmp_name)
        try:
            os.fchmod(fd, 0o600)
            raw = canonical_json(document) + b"\n"
            view = memoryview(raw)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write while sealing ResearchMemory")
                view = view[written:]
            os.fsync(fd)
            os.close(fd); fd = -1
            os.replace(tmp, target)
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
        return document

    def verify_external_seal(self, seal_path: Path, *, public_key: Path,
                             expected_owner_uid: int) -> dict[str, Any]:
        """Verify the root-owned seal against the *entire current* ledger.

        Missing, stale, copied, writable, symlinked, or hard-linked seals fail closed.
        Requiring an expected owner keeps a valid attacker-owned fixture seal outside
        the production trust boundary.
        """
        document = self.read_external_seal(
            seal_path, public_key=public_key, expected_owner_uid=expected_owner_uid)
        current = self.seal_core()
        if document["core"] != current:
            raise ContractError("research_memory_seal_stale", "ResearchMemory 当前完整链与外部 seal 不一致")
        return current

    def read_external_seal(self, seal_path: Path, *, public_key: Path,
                           expected_owner_uid: int) -> dict[str, Any]:
        """Read and authenticate a seal document without assuming it is current.

        The broker uses this to authenticate the prior commitment before allowing a
        guarded append-only refresh.  Consumers should normally call
        :meth:`verify_external_seal`, which additionally requires exact current state.
        """
        target = Path(seal_path)
        try:
            parent = target.parent.lstat()
            info = target.lstat()
            key_info = Path(public_key).lstat()
        except OSError as exc:
            raise ContractError("research_memory_seal_missing", "ResearchMemory 外部 seal 不可达") from exc
        if (target.parent.is_symlink() or not stat.S_ISDIR(parent.st_mode)
                or parent.st_uid != expected_owner_uid or parent.st_mode & 0o022):
            raise ContractError("research_memory_seal_permissions", "seal 父目录 owner/mode 不可信")
        if (target.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != expected_owner_uid or info.st_mode & 0o022):
            raise ContractError("research_memory_seal_permissions", "seal owner/mode/link 不可信")
        if (Path(public_key).is_symlink() or not stat.S_ISREG(key_info.st_mode)
                or key_info.st_nlink != 1 or key_info.st_uid != expected_owner_uid
                or key_info.st_mode & 0o022):
            raise ContractError("research_memory_seal_permissions",
                                "ResearchMemory seal 公钥 owner/mode/link 不可信")
        try:
            document = _json_no_duplicates(target.read_bytes())
        except (OSError, ValueError, TypeError) as exc:
            raise ContractError("research_memory_seal_invalid", "ResearchMemory seal 无法解析") from exc
        if not isinstance(document, dict) or set(document) != {"core", "sealed"}:
            raise ContractError("research_memory_seal_invalid", "ResearchMemory seal 字段不精确")
        core = document["core"]
        if (not isinstance(core, dict)
                or set(core) != {"schema", "ledger_path", "length", "head_entry_hash",
                                 "ledger_sha256"}
                or core.get("schema") != RESEARCH_MEMORY_SEAL_SCHEMA
                or not isinstance(core.get("length"), int) or core["length"] <= 0):
            raise ContractError("research_memory_seal_invalid", "ResearchMemory seal core 非法")
        try:
            require_sha(core.get("head_entry_hash"), "head_entry_hash")
            require_sha(core.get("ledger_sha256"), "ledger_sha256")
        except ContractError as exc:
            raise ContractError("research_memory_seal_invalid", "ResearchMemory seal hash 非法") from exc
        if (not isinstance(core.get("ledger_path"), str)
                or not Path(core["ledger_path"]).is_absolute()):
            raise ContractError("research_memory_seal_invalid", "ResearchMemory seal ledger_path 非法")
        ok, reason = verify_attestation(document["sealed"], public_key=Path(public_key),
                                        domain=DOMAIN_RESEARCH_MEMORY,
                                        expected_core=core)
        if not ok:
            raise ContractError("research_memory_seal_unverified",
                                "ResearchMemory 外部 seal 验签失败", {"reason": reason})
        return document
