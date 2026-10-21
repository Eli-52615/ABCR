#!/usr/bin/env python3
"""Finite importer for the separately reviewed W1 scientific dataset.

The ordinary ABCR code release deliberately excludes benchmark/split bytes.
This tool therefore consumes exactly two root-staged files named by a frozen
authority document.  It validates their byte identities and scientific
invariants, normalizes them for ``item_pool``, and publishes one immutable
content-addressed directory.  It never reads a checkout or accepts caller-
selected source/output paths in production mode.
"""
from __future__ import annotations

import argparse
import errno
import grp
import hashlib
import json
import os
import plistlib
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable


REVIEWED_AUTHORITY_SHA = "40fd5fb21ff33d7da84648562c6dc12d68f15444dfea60379132af820510d0d1"
DATASET_AUTHORITY_SHA256 = "5b15465d247d2374d188eaf0665164b11e97537632fa223370665299924d05b1"
AUTHORITY_RELATIVE = Path("ops/install/dataset-authority-ifeval-zh-v1.json")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
RELEASE_ID = re.compile(r"^REL-[0-9a-f]{64}$")
SPLITS = ("dev", "calibration", "holdout")
_ACL_SENSITIVE_PERMISSIONS = frozenset({
    "read", "read_data", "list", "list_directory", "search", "execute",
})
_ACL_ENTRY = re.compile(r"^\s*\d+:\s+(user|group):([^\s]+)\s+(.+)$")
_DATASET_READER_GROUP = "abcr-dataset-read"
_DIRECTORY_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class DatasetImportBlocked(RuntimeError):
    """A trust, schema, scientific, or no-clobber gate failed."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DatasetImportBlocked("duplicate JSON key")
        result[key] = value
    return result


def _decode_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_unique,
                           parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, DatasetImportBlocked):
            raise
        raise DatasetImportBlocked(f"invalid JSON: {label}") from exc
    if not isinstance(value, dict):
        raise DatasetImportBlocked(f"JSON must be an object: {label}")
    return value


def _read_regular(path: Path, *, owner_uid: int, allowed_modes: set[int],
                  expected_size: int | None = None,
                  expected_sha256: str | None = None,
                  required_gid: int | None = None) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise DatasetImportBlocked(f"trusted file unavailable: {path}") from exc
    try:
        before = os.fstat(fd)
        mode = stat.S_IMODE(before.st_mode)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != owner_uid or mode not in allowed_modes
                or (required_gid is not None and before.st_gid != required_gid)
                or (expected_size is not None and before.st_size != expected_size)):
            raise DatasetImportBlocked(f"unsafe trusted file: {path}")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size,
                                 item.st_nlink, item.st_uid, item.st_gid,
                                 stat.S_IMODE(item.st_mode))
        if len(raw) != before.st_size or identity(before) != identity(after):
            raise DatasetImportBlocked(f"trusted file changed while reading: {path}")
        if expected_sha256 is not None and digest(raw) != expected_sha256:
            raise DatasetImportBlocked(f"trusted file hash mismatch: {path}")
        return raw
    finally:
        os.close(fd)


def _require_directory(path: Path, *, owner_uid: int, exact_mode: int | None = None,
                       required_gid: int | None = None) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise DatasetImportBlocked(f"trusted directory unavailable: {path}") from exc
    mode = stat.S_IMODE(info.st_mode)
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != owner_uid or mode & 0o022
            or (exact_mode is not None and mode != exact_mode)
            or (required_gid is not None and info.st_gid != required_gid)):
        raise DatasetImportBlocked(f"unsafe trusted directory: {path}")
    return info


def _require_no_symlink_components(path: Path, *, label: str) -> None:
    """Reject a real leaf reached through a redirected ancestor."""
    raw = Path(path)
    if not raw.is_absolute() or raw.resolve(strict=False) != raw:
        raise DatasetImportBlocked(f"{label} must be an absolute non-symlink path")


def _mac_acl_text(path: Path) -> str:
    """Read one macOS ACL without a shell or caller-selected executable."""
    try:
        result = subprocess.run(
            ["/bin/ls", "-lde", "--", str(path)], check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DatasetImportBlocked(f"cannot inspect dataset ACL: {path}") from exc
    if result.returncode != 0:
        raise DatasetImportBlocked(f"cannot inspect dataset ACL: {path}")
    return result.stdout


def _acl_entries(raw: str) -> tuple[tuple[str, str, str, frozenset[str]], ...]:
    """Parse the finite `ls -lde` named-ACL surface used by macOS.

    Unknown numbered lines fail closed.  Flags such as ``inherited`` and
    ``file_inherit`` are retained in the permission set; an inherited allow is
    therefore treated exactly like an explicit allow.
    """
    entries: list[tuple[str, str, str, frozenset[str]]] = []
    for line in raw.splitlines()[1:]:
        if not re.match(r"^\s*\d+:", line):
            continue
        match = _ACL_ENTRY.fullmatch(line)
        if match is None:
            raise DatasetImportBlocked("unrecognized macOS dataset ACL entry")
        kind, principal, tail = match.groups()
        words = tail.split()
        try:
            action_index = next(index for index, word in enumerate(words)
                                if word in {"allow", "deny"})
        except StopIteration as exc:
            raise DatasetImportBlocked("unrecognized macOS dataset ACL action") from exc
        if action_index == len(words) - 1:
            raise DatasetImportBlocked("empty macOS dataset ACL permission set")
        permissions = frozenset(
            token for word in words[action_index + 1:] for token in word.split(",") if token)
        entries.append((kind, principal, words[action_index], permissions))
    return tuple(entries)


_GID_MODULUS = 1 << 32
_GID_C_INT_MAX = 0x7FFFFFFF


def _canonical_gid(value: int) -> int:
    """Normalize a gid to its unsigned 32-bit spelling.

    macOS ships ~28 built-in service accounts (``nobody``, ``_installer``,
    ``_ftp``, ``_krbtgt`` …) whose primary gid is the ``nobody`` sentinel −2.
    The same identity surfaces as −2, 4294967294 or 18446744073709551614
    depending on which C call produced it, and ``grp`` accepts only the
    unsigned 32-bit spelling.
    """
    return value % _GID_MODULUS


def _c_int_gid(value: int) -> int:
    """Spell a gid the way ``os.getgrouplist`` wants it: a signed C int.

    Passing the unsigned sentinel raises ``OverflowError`` in CPython, which is
    why every visible-user sweep must convert first.
    """
    canonical = _canonical_gid(value)
    return canonical - _GID_MODULUS if canonical > _GID_C_INT_MAX else canonical


def _identity(name: str) -> tuple[str, int, frozenset[str]]:
    try:
        account = pwd.getpwnam(name)
        gids = os.getgrouplist(name, _c_int_gid(account.pw_gid))
    except (KeyError, OSError, OverflowError, ValueError) as exc:
        raise DatasetImportBlocked(f"dataset ACL identity unavailable: {name}") from exc
    groups: set[str] = {str(_canonical_gid(gid)) for gid in gids}
    for gid in gids:
        try:
            groups.add(grp.getgrgid(_canonical_gid(gid)).gr_name)
        except KeyError:
            continue
    return name, account.pw_uid, frozenset(groups)


def _directory_plist(record: str, attributes: tuple[str, ...]) -> dict[str, Any]:
    """Read a finite local OpenDirectory record with a fixed executable."""
    try:
        result = subprocess.run(
            ["/usr/bin/dscl", "-plist", ".", "-read", record, *attributes],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DatasetImportBlocked(f"cannot inspect directory record: {record}") from exc
    if result.returncode != 0 or len(result.stdout) > 64 * 1024:
        raise DatasetImportBlocked(f"cannot inspect directory record: {record}")
    try:
        value = plistlib.loads(result.stdout)
    except (plistlib.InvalidFileException, ValueError) as exc:
        raise DatasetImportBlocked(f"invalid directory record: {record}") from exc
    if not isinstance(value, dict):
        raise DatasetImportBlocked(f"invalid directory record: {record}")
    return value


def _record_values(record: dict[str, Any], attribute: str) -> tuple[str, ...]:
    raw = record.get(f"dsAttrTypeStandard:{attribute}", [])
    if (not isinstance(raw, list) or any(not isinstance(item, str) or not item
                                         for item in raw)
            or len(raw) != len(set(raw))):
        raise DatasetImportBlocked(f"invalid directory attribute: {attribute}")
    return tuple(raw)


def _dataset_group_record(_group: str) -> tuple[tuple[str, ...],
                                                 tuple[str, ...],
                                                 tuple[str, ...]]:
    record = _directory_plist(
        f"/Groups/{_group}", ("GroupMembership", "GroupMembers", "NestedGroups"))
    return (_record_values(record, "GroupMembership"),
            _record_values(record, "GroupMembers"),
            _record_values(record, "NestedGroups"))


def _directory_user_guid(name: str) -> str:
    if _DIRECTORY_NAME.fullmatch(name) is None:
        raise DatasetImportBlocked(f"invalid dataset reader identity: {name}")
    record = _directory_plist(f"/Users/{name}", ("GeneratedUID",))
    values = _record_values(record, "GeneratedUID")
    if len(values) != 1:
        raise DatasetImportBlocked(f"dataset reader GUID unavailable: {name}")
    return values[0]


def _visible_directory_users() -> tuple[str, ...]:
    """Enumerate the macOS search node, including non-local visible users."""
    try:
        result = subprocess.run(
            ["/usr/bin/dscl", "/Search", "-list", "/Users", "UniqueID"],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DatasetImportBlocked("cannot enumerate directory users") from exc
    if result.returncode != 0 or len(result.stdout) > 4 * 1024 * 1024:
        raise DatasetImportBlocked("cannot enumerate directory users")
    users: list[str] = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if (len(fields) != 2 or _DIRECTORY_NAME.fullmatch(fields[0]) is None
                or re.fullmatch(r"-?[0-9]+", fields[1]) is None):
            raise DatasetImportBlocked("invalid directory user enumeration")
        users.append(fields[0])
    if not users or len(users) != len(set(users)):
        raise DatasetImportBlocked("ambiguous directory user enumeration")
    return tuple(users)


def _effective_groups(name: str) -> frozenset[str]:
    return _identity(name)[2]


def validate_exact_dataset_reader_group(
        access: dict[str, Any], *,
        group_record_reader: Callable[[str], tuple[tuple[str, ...],
                                                    tuple[str, ...],
                                                    tuple[str, ...]]] = _dataset_group_record,
        user_guid_resolver: Callable[[str], str] = _directory_user_guid,
        visible_users_resolver: Callable[[], tuple[str, ...]] = _visible_directory_users,
        effective_groups_resolver: Callable[[str], frozenset[str]] = _effective_groups,
) -> None:
    """Require the reader group to contain exactly the two reviewed readers.

    Direct short-name and GUID membership are independently bound, nested
    groups are forbidden, and every identity visible through the macOS search
    node is checked for effective (including primary/nested) membership.  This
    function only observes state; it never removes an unreviewed member.
    """
    readers = access.get("readers")
    group = access.get("group")
    if group != _DATASET_READER_GROUP or readers != ["abcr-itempool", "abcr-auditor"]:
        raise DatasetImportBlocked("dataset reader authority mismatch")
    expected = frozenset(readers)
    try:
        direct_names, direct_guids, nested_guids = group_record_reader(group)
        expected_guids = tuple(user_guid_resolver(name) for name in readers)
        visible_users = visible_users_resolver()
    except DatasetImportBlocked:
        raise
    except Exception as exc:
        raise DatasetImportBlocked("dataset reader group inspection failed") from exc
    for label, values in (("direct names", direct_names),
                          ("direct GUIDs", direct_guids),
                          ("nested groups", nested_guids),
                          ("visible users", visible_users)):
        if (not isinstance(values, tuple)
                or any(not isinstance(item, str) or not item for item in values)
                or len(values) != len(set(values))):
            raise DatasetImportBlocked(f"invalid dataset reader {label}")
    if frozenset(direct_names) != expected:
        raise DatasetImportBlocked("dataset reader group direct membership is not exact")
    if nested_guids:
        raise DatasetImportBlocked("dataset reader group contains nested membership")
    if (len(expected_guids) != len(set(expected_guids))
            or frozenset(direct_guids) != frozenset(expected_guids)):
        raise DatasetImportBlocked("dataset reader group GUID membership is not exact")

    effective: set[str] = set()
    universe = tuple(dict.fromkeys((*visible_users, *readers)))
    for name in universe:
        try:
            groups = effective_groups_resolver(name)
        except DatasetImportBlocked:
            raise
        except Exception as exc:
            raise DatasetImportBlocked(
                f"effective dataset group membership unavailable: {name}") from exc
        if not isinstance(groups, frozenset) or any(
                not isinstance(item, str) or not item for item in groups):
            raise DatasetImportBlocked(
                f"invalid effective dataset group membership: {name}")
        if group in groups:
            effective.add(name)
    if effective != expected:
        raise DatasetImportBlocked("dataset reader group effective membership is not exact")


def require_no_must_deny_acl_grant(
        paths: Iterable[Path], must_deny: Iterable[str], *,
        acl_reader: Callable[[Path], str] = _mac_acl_text,
        identity_resolver: Callable[[str], tuple[str, int, frozenset[str]]] = _identity,
        posix_reader_groups: Iterable[str] = (),
) -> None:
    """Reject named ACLs that can expose frozen bytes to a denied identity."""
    identities = []
    for name in must_deny:
        try:
            identity = identity_resolver(name)
        except DatasetImportBlocked:
            raise
        except Exception as exc:
            raise DatasetImportBlocked(f"dataset ACL identity unavailable: {name}") from exc
        if (not isinstance(identity, tuple) or len(identity) != 3
                or identity[0] != name or type(identity[1]) is not int
                or not isinstance(identity[2], frozenset)):
            raise DatasetImportBlocked(f"invalid dataset ACL identity: {name}")
        identities.append(identity)
    reader_groups = frozenset(posix_reader_groups)
    for name, _uid, groups in identities:
        if groups & reader_groups:
            raise DatasetImportBlocked(
                f"dataset POSIX reader group includes must-deny identity {name}")
    for path in paths:
        try:
            entries = _acl_entries(acl_reader(path))
        except DatasetImportBlocked:
            raise
        except Exception as exc:
            raise DatasetImportBlocked(f"cannot inspect dataset ACL: {path}") from exc
        for kind, principal, action, permissions in entries:
            if action != "allow" or not permissions & _ACL_SENSITIVE_PERMISSIONS:
                continue
            for name, uid, groups in identities:
                applies = ((kind == "user" and principal in {name, str(uid)})
                           or (kind == "group"
                               and (principal == "everyone" or principal in groups)))
                if applies:
                    raise DatasetImportBlocked(
                        f"dataset ACL grants frozen-data access to must-deny identity "
                        f"{name}: {path}")


def _production_acl_required(*paths: Path) -> bool:
    """Only a root macOS check can make a production ACL assertion."""
    production = (Path("/Library/Application Support/ABCR-Datasets"),
                  Path("/Library/Application Support/ABCR-Dataset-Sources"))
    return (sys.platform == "darwin" and os.geteuid() == 0
            and any(path == root or root in path.parents
                    for path in paths for root in production))


def _check_dataset_acl(paths: Iterable[Path], authority: dict[str, Any], *,
                       enforce_acl: bool | None,
                       acl_reader: Callable[[Path], str] | None,
                       identity_resolver: Callable[[str], tuple[str, int, frozenset[str]]] | None,
                       posix_reader_groups: Iterable[str] = (),
                       ) -> bool:
    checked = tuple(paths)
    required = _production_acl_required(*checked) if enforce_acl is None else enforce_acl
    if not required:
        return False
    require_no_must_deny_acl_grant(
        checked, authority["access_policy"]["must_deny"],
        acl_reader=_mac_acl_text if acl_reader is None else acl_reader,
        identity_resolver=_identity if identity_resolver is None else identity_resolver,
        posix_reader_groups=posix_reader_groups,
    )
    return True


def load_authority(path: Path, *, owner_uid: int,
                   allowed_modes: set[int] = {0o440, 0o444}) -> dict[str, Any]:
    raw = _read_regular(path, owner_uid=owner_uid, allowed_modes=allowed_modes)
    if digest(raw) != DATASET_AUTHORITY_SHA256:
        raise DatasetImportBlocked("dataset authority byte identity mismatch")
    value = _decode_object(raw, label="dataset authority")
    expected = {
        "schema_version", "authority_id", "reviewed_authority_sha256",
        "dataset_family", "source_commit", "source_combined_sha256",
        "source_staging_root", "dataset_root",
        "sources", "invariants", "output", "access_policy",
    }
    if set(value) != expected or value.get("schema_version") != 1:
        raise DatasetImportBlocked("dataset authority shape/version mismatch")
    if (value.get("reviewed_authority_sha256") != REVIEWED_AUTHORITY_SHA
            or not isinstance(value.get("source_commit"), str)
            or HEX40.fullmatch(value["source_commit"]) is None):
        raise DatasetImportBlocked("dataset authority review binding mismatch")
    sources = value.get("sources")
    if (not isinstance(sources, list) or len(sources) != 2
            or {item.get("staged_name") for item in sources if isinstance(item, dict)}
            != {"benchmark.json", "split-source.json"}):
        raise DatasetImportBlocked("dataset authority source set mismatch")
    for item in sources:
        if (not isinstance(item, dict)
                or set(item) != {"source_path", "staged_name", "size", "sha256"}
                or not isinstance(item["source_path"], str)
                or not isinstance(item["staged_name"], str)
                or Path(item["staged_name"]).name != item["staged_name"]
                or type(item["size"]) is not int or item["size"] < 1
                or not isinstance(item["sha256"], str)
                or HEX64.fullmatch(item["sha256"]) is None):
            raise DatasetImportBlocked("dataset authority source entry mismatch")
    output = value.get("output")
    if (not isinstance(output, dict)
            or set(output) != {"dataset_sha256", "items_path", "items_size",
                              "items_sha256", "split_path", "split_size",
                              "split_sha256"}
            or any(HEX64.fullmatch(str(output.get(name, ""))) is None
                   for name in ("dataset_sha256", "items_sha256", "split_sha256"))
            or output.get("items_path") != "items.json"
            or output.get("split_path") != "split.json"):
        raise DatasetImportBlocked("dataset authority output contract mismatch")
    access = value.get("access_policy")
    if (not isinstance(access, dict)
            or set(access) != {"owner", "group", "directory_mode", "file_mode",
                               "readers", "must_deny"}
            or access.get("owner") != "root"
            or access.get("group") != "abcr-dataset-read"
            or access.get("directory_mode") != "0550"
            or access.get("file_mode") != "0440"
            or access.get("readers") != ["abcr-itempool", "abcr-auditor"]
            or not isinstance(access.get("must_deny"), list)
            or not access["must_deny"]
            or len(access["must_deny"]) != len(set(access["must_deny"]))
            or set(access["readers"]) & set(access["must_deny"])):
        raise DatasetImportBlocked("dataset authority access policy mismatch")
    return value


def _split_hash(assignments: dict[str, str]) -> str:
    joined = "\n".join(sorted(f"{item_id}\t{split}"
                               for item_id, split in assignments.items()))
    return digest(joined.encode("utf-8"))


def normalize(authority: dict[str, Any], benchmark_raw: bytes,
              split_source_raw: bytes) -> tuple[bytes, bytes, dict[str, Any]]:
    source_sha256 = digest(benchmark_raw + b"\0" + split_source_raw)
    if source_sha256 != authority["source_combined_sha256"]:
        raise DatasetImportBlocked("combined dataset source identity mismatch")
    benchmark = _decode_object(benchmark_raw, label="benchmark source")
    split_source = _decode_object(split_source_raw, label="split source")
    family = authority["dataset_family"]
    invariants = authority["invariants"]
    if (benchmark.get("family") != family or benchmark.get("n_items") != 250
            or split_source.get("family") != family
            or split_source.get("salt") != invariants.get("salt")):
        raise DatasetImportBlocked("dataset family/count/salt invariant mismatch")
    items = benchmark.get("items")
    assignments = split_source.get("assignments")
    distribution = split_source.get("distribution")
    if not isinstance(items, list) or not isinstance(assignments, dict):
        raise DatasetImportBlocked("dataset item/assignment schema mismatch")
    item_ids: list[str] = []
    for item in items:
        item_id = item.get("item_id") if isinstance(item, dict) else None
        if not isinstance(item_id, str) or not item_id or item_id in item_ids:
            raise DatasetImportBlocked("dataset item identity mismatch")
        item_ids.append(item_id)
    if (len(items) != invariants.get("item_count") or set(assignments) != set(item_ids)
            or any(value not in SPLITS for value in assignments.values())):
        raise DatasetImportBlocked("dataset item/assignment coverage mismatch")
    split_counts = {name: sum(value == name for value in assignments.values())
                    for name in SPLITS}
    if (split_counts != invariants.get("split_counts") or distribution != split_counts
            or split_source.get("split_hash") != invariants.get("split_hash")
            or _split_hash(assignments) != invariants.get("split_hash")):
        raise DatasetImportBlocked("dataset split distribution/hash drift")
    split = {name: sorted(item_id for item_id, value in assignments.items()
                          if value == name) for name in SPLITS}
    items_raw = canonical(items) + b"\n"
    split_raw = canonical(split) + b"\n"
    output = authority["output"]
    if (len(items_raw) != output["items_size"]
            or digest(items_raw) != output["items_sha256"]
            or len(split_raw) != output["split_size"]
            or digest(split_raw) != output["split_sha256"]
            or digest(items_raw + b"\0" + split_raw) != output["dataset_sha256"]):
        raise DatasetImportBlocked("canonical dataset output identity mismatch")
    manifest = {
        "schema_version": 1,
        "dataset_sha256": output["dataset_sha256"],
        "dataset_family": family,
        "source_commit": authority["source_commit"],
        "sources": authority["sources"],
        "source_sha256": source_sha256,
        "item_count": len(items),
        "split_counts": split_counts,
        "split_hash": invariants["split_hash"],
        "files": [
            {"path": "items.json", "size": len(items_raw), "sha256": digest(items_raw)},
            {"path": "split.json", "size": len(split_raw), "sha256": digest(split_raw)},
        ],
        "access_policy": authority["access_policy"],
    }
    return items_raw, split_raw, manifest


def _manifest_raw(manifest: dict[str, Any]) -> bytes:
    return canonical(manifest) + b"\n"


def verify_installed(authority: dict[str, Any], *, dataset_root: Path,
                     owner_uid: int, dataset_gid: int,
                     dataset_root_mode: int = 0o550,
                     enforce_acl: bool | None = None,
                     acl_reader: Callable[[Path], str] | None = None,
                     identity_resolver: Callable[[str], tuple[str, int, frozenset[str]]] | None = None,
                     ) -> Path:
    _require_no_symlink_components(dataset_root, label="dataset root")
    _require_directory(dataset_root, owner_uid=owner_uid, exact_mode=dataset_root_mode,
                       required_gid=dataset_gid)
    final = dataset_root / authority["output"]["dataset_sha256"]
    _require_directory(final, owner_uid=owner_uid, exact_mode=0o550,
                       required_gid=dataset_gid)
    try:
        names = {item.name for item in final.iterdir()}
    except OSError as exc:
        raise DatasetImportBlocked("cannot enumerate installed dataset") from exc
    if names != {"items.json", "split.json", "manifest.json"}:
        raise DatasetImportBlocked("installed dataset file set mismatch")
    _check_dataset_acl(
        (dataset_root, final, *(final / name for name in sorted(names))), authority,
        enforce_acl=enforce_acl, acl_reader=acl_reader,
        identity_resolver=identity_resolver,
        posix_reader_groups=(authority["access_policy"]["group"],),
    )
    items_raw = _read_regular(final / "items.json", owner_uid=owner_uid,
                              allowed_modes={0o440},
                              required_gid=dataset_gid,
                              expected_size=authority["output"]["items_size"],
                              expected_sha256=authority["output"]["items_sha256"])
    split_raw = _read_regular(final / "split.json", owner_uid=owner_uid,
                              allowed_modes={0o440},
                              required_gid=dataset_gid,
                              expected_size=authority["output"]["split_size"],
                              expected_sha256=authority["output"]["split_sha256"])
    if digest(items_raw + b"\0" + split_raw) != authority["output"]["dataset_sha256"]:
        raise DatasetImportBlocked("installed dataset directory identity mismatch")
    manifest_raw = _read_regular(final / "manifest.json", owner_uid=owner_uid,
                                 allowed_modes={0o440}, required_gid=dataset_gid)
    manifest = _decode_object(manifest_raw, label="installed dataset manifest")
    required = {
        "schema_version", "dataset_sha256", "dataset_family", "source_commit",
        "sources", "source_sha256", "item_count", "split_counts", "split_hash",
        "files", "access_policy",
    }
    if (set(manifest) != required or manifest.get("schema_version") != 1
            or manifest.get("dataset_sha256") != authority["output"]["dataset_sha256"]
            or manifest.get("dataset_family") != authority["dataset_family"]
            or manifest.get("source_commit") != authority["source_commit"]
            or manifest.get("sources") != authority["sources"]
            or manifest.get("source_sha256") != authority["source_combined_sha256"]
            or manifest.get("item_count") != authority["invariants"]["item_count"]
            or manifest.get("split_counts") != authority["invariants"]["split_counts"]
            or manifest.get("split_hash") != authority["invariants"]["split_hash"]
            or manifest.get("access_policy") != authority["access_policy"]
            or manifest.get("files") != [
                {"path": "items.json", "size": len(items_raw), "sha256": digest(items_raw)},
                {"path": "split.json", "size": len(split_raw), "sha256": digest(split_raw)},
            ]):
        raise DatasetImportBlocked("installed dataset manifest binding mismatch")
    return final


def import_dataset(authority: dict[str, Any], *, source_root: Path,
                   dataset_root: Path, owner_uid: int, source_gid: int,
                   dataset_gid: int, source_root_mode: int = 0o550,
                   dataset_root_mode: int = 0o550,
                   enforce_acl: bool | None = None,
                   acl_reader: Callable[[Path], str] | None = None,
                   identity_resolver: Callable[[str], tuple[str, int, frozenset[str]]] | None = None,
                   ) -> tuple[Path, bool]:
    _require_no_symlink_components(source_root, label="dataset source root")
    _require_no_symlink_components(dataset_root, label="dataset root")
    _require_directory(source_root, owner_uid=owner_uid, exact_mode=source_root_mode,
                       required_gid=source_gid)
    expected_names = {item["staged_name"] for item in authority["sources"]}
    if {item.name for item in source_root.iterdir()} != expected_names:
        raise DatasetImportBlocked("staged dataset source file set mismatch")
    _check_dataset_acl(
        (source_root, *(source_root / name for name in sorted(expected_names))), authority,
        enforce_acl=enforce_acl, acl_reader=acl_reader,
        identity_resolver=identity_resolver,
        posix_reader_groups=(grp.getgrgid(source_gid).gr_name,),
    )
    raw_by_name: dict[str, bytes] = {}
    for item in authority["sources"]:
        raw_by_name[item["staged_name"]] = _read_regular(
            source_root / item["staged_name"], owner_uid=owner_uid,
            allowed_modes={0o440}, expected_size=item["size"],
            expected_sha256=item["sha256"], required_gid=source_gid)
    items_raw, split_raw, manifest = normalize(
        authority, raw_by_name["benchmark.json"], raw_by_name["split-source.json"])

    if dataset_root.exists() or dataset_root.is_symlink():
        _require_directory(dataset_root, owner_uid=owner_uid,
                           exact_mode=dataset_root_mode,
                           required_gid=dataset_gid)
    else:
        parent = dataset_root.parent
        _require_directory(parent, owner_uid=owner_uid)
        dataset_root.mkdir(mode=dataset_root_mode)
        os.chown(dataset_root, owner_uid, dataset_gid)
        os.chmod(dataset_root, dataset_root_mode)
    final = dataset_root / authority["output"]["dataset_sha256"]
    if final.exists() or final.is_symlink():
        return verify_installed(authority, dataset_root=dataset_root,
                                owner_uid=owner_uid, dataset_gid=dataset_gid,
                                dataset_root_mode=dataset_root_mode,
                                enforce_acl=enforce_acl, acl_reader=acl_reader,
                                identity_resolver=identity_resolver), False

    temporary = Path(tempfile.mkdtemp(prefix=".dataset-import-", dir=dataset_root))
    try:
        os.chown(temporary, owner_uid, dataset_gid)
        os.chmod(temporary, 0o750)
        for name, raw in (("items.json", items_raw), ("split.json", split_raw),
                          ("manifest.json", _manifest_raw(manifest))):
            path = temporary / name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o440)
            try:
                with os.fdopen(fd, "wb", closefd=False) as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.fchown(fd, owner_uid, dataset_gid)
                os.fchmod(fd, 0o440)
            finally:
                os.close(fd)
        try:
            os.rename(temporary, final)
            os.chmod(final, 0o550)
        except OSError:
            if not final.exists():
                raise
            verify_installed(authority, dataset_root=dataset_root,
                             owner_uid=owner_uid, dataset_gid=dataset_gid,
                             dataset_root_mode=dataset_root_mode,
                             enforce_acl=enforce_acl, acl_reader=acl_reader,
                             identity_resolver=identity_resolver)
        directory_fd = os.open(dataset_root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return verify_installed(authority, dataset_root=dataset_root,
                            owner_uid=owner_uid, dataset_gid=dataset_gid,
                            dataset_root_mode=dataset_root_mode,
                            enforce_acl=enforce_acl, acl_reader=acl_reader,
                            identity_resolver=identity_resolver), True


def _authority_path() -> Path:
    script = Path(__file__)
    if script.is_symlink():
        raise DatasetImportBlocked("dataset importer cannot execute through a symlink")
    return script.resolve().parents[1] / AUTHORITY_RELATIVE


def _require_reviewed_execution_path() -> Path:
    """Forbid using a mutable checkout as a privileged importer executable."""
    script = Path(__file__)
    try:
        info = script.lstat()
    except OSError as exc:
        raise DatasetImportBlocked("dataset importer executable unavailable") from exc
    resolved = script.resolve()
    release = resolved.parents[1]
    allowed_parents = {
        Path("/Library/Application Support/ABCR-Genesis/reviewed"),
        Path("/Users/superagent/.abcr/releases"),
    }
    if (script.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022
            or release.parent not in allowed_parents
            or RELEASE_ID.fullmatch(release.name) is None
            or resolved != release / "scripts/import_abcr_dataset.py"):
        raise DatasetImportBlocked(
            "dataset importer must execute from a fixed root-owned reviewed/sealed release")
    return release


_LIVE_OPERATIONS = ("list_root", "list_final", "open_items", "open_split")


def _probe_dataset_as_identity(name: str, dataset_root: Path,
                               final: Path) -> dict[str, str]:
    """Fork once, irrevocably drop to the target UID, then exercise the FS.

    The child returns status labels only; it never returns scientific bytes.  A
    downgrade failure is distinct from an access denial and blocks the gate.
    """
    try:
        account = pwd.getpwnam(name)
        # 同 _identity:getgrouplist 要有符号 C int 拼写,否则 nobody 哨兵 gid 会以
        # OverflowError 逃出下面的异常元组,变成非 fail-closed 的崩溃。
        groups = os.getgrouplist(name, _c_int_gid(account.pw_gid))
    except (KeyError, OSError, OverflowError, ValueError) as exc:
        raise DatasetImportBlocked(f"live dataset identity unavailable: {name}") from exc
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:  # pragma: no cover - the parent validates the serialized result
        os.close(read_fd)
        result: dict[str, Any]
        try:
            # setgroups/setgid 只接受无符号 32 位 gid_t 拼写:getgrouplist 返回的
            # nobody 哨兵是 64 位无符号形式,不归一化会在子进程里抛 OverflowError,
            # 使降权在真正落地前就崩掉。
            target_gid = _canonical_gid(account.pw_gid)
            os.setgroups([_canonical_gid(item) for item in groups])
            os.setgid(target_gid)
            os.setuid(account.pw_uid)
            if os.geteuid() != account.pw_uid or _canonical_gid(os.getegid()) != target_gid:
                raise RuntimeError("identity downgrade did not take effect")

            def attempt(operation: Callable[[], None]) -> str:
                try:
                    operation()
                except OSError as exc:
                    return "denied" if exc.errno in {errno.EACCES, errno.EPERM} else "error"
                return "ok"

            def list_path(path: Path) -> None:
                os.listdir(path)

            def read_one(path: Path) -> None:
                fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
                             | getattr(os, "O_NOFOLLOW", 0))
                try:
                    os.read(fd, 1)
                finally:
                    os.close(fd)

            result = {
                "ok": True,
                "operations": {
                    "list_root": attempt(lambda: list_path(dataset_root)),
                    "list_final": attempt(lambda: list_path(final)),
                    "open_items": attempt(lambda: read_one(final / "items.json")),
                    "open_split": attempt(lambda: read_one(final / "split.json")),
                },
            }
        except BaseException as exc:
            result = {"ok": False, "error": type(exc).__name__}
        raw = canonical(result)
        try:
            os.write(write_fd, raw[:16_384])
        finally:
            os.close(write_fd)
            os._exit(0 if result.get("ok") else 70)
    os.close(write_fd)
    chunks: list[bytes] = []
    try:
        while True:
            chunk = os.read(read_fd, 4096)
            if not chunk:
                break
            chunks.append(chunk)
            if sum(map(len, chunks)) > 16_384:
                raise DatasetImportBlocked(f"oversized live dataset probe: {name}")
    finally:
        os.close(read_fd)
    _, status = os.waitpid(pid, 0)
    try:
        result = json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetImportBlocked(f"invalid live dataset probe: {name}") from exc
    if (status != 0 or not isinstance(result, dict) or result.get("ok") is not True
            or not isinstance(result.get("operations"), dict)):
        raise DatasetImportBlocked(f"live dataset identity probe failed: {name}")
    operations = result["operations"]
    if (set(operations) != set(_LIVE_OPERATIONS)
            or any(value not in {"ok", "denied", "error"}
                   for value in operations.values())):
        raise DatasetImportBlocked(f"invalid live dataset operation matrix: {name}")
    return operations


def validate_live_dataset_access(
        authority: dict[str, Any], *, dataset_root: Path, final: Path,
        identity_probe: Callable[[str, Path, Path], dict[str, str]] | None = None,
        group_validator: Callable[[dict[str, Any]], None] | None = None,
        effective_uid: int | None = None, platform_name: str | None = None,
) -> None:
    """Root-only macOS proof of positive readers and every must-deny UID.

    Unit tests may inject a finite probe matrix.  The production CLI never
    injects it, and refuses to claim LIVE on non-macOS or without root.
    """
    euid = os.geteuid() if effective_uid is None else effective_uid
    platform = sys.platform if platform_name is None else platform_name
    if euid != 0 or platform != "darwin":
        raise DatasetImportBlocked(
            "live dataset ACL validation requires root on the production macOS host")
    if group_validator is None:
        validate_exact_dataset_reader_group(authority["access_policy"])
    else:
        try:
            group_validator(authority["access_policy"])
        except DatasetImportBlocked:
            raise
        except Exception as exc:
            raise DatasetImportBlocked("dataset reader group validation failed") from exc
    probe = _probe_dataset_as_identity if identity_probe is None else identity_probe
    access = authority["access_policy"]
    for name in access["readers"]:
        try:
            observed = probe(name, dataset_root, final)
        except DatasetImportBlocked:
            raise
        except Exception as exc:
            raise DatasetImportBlocked(f"live dataset identity probe failed: {name}") from exc
        if set(observed) != set(_LIVE_OPERATIONS) or not all(
                observed.get(operation) == "ok" for operation in _LIVE_OPERATIONS):
            raise DatasetImportBlocked(f"authorized dataset reader probe failed: {name}")
    for name in access["must_deny"]:
        try:
            observed = probe(name, dataset_root, final)
        except DatasetImportBlocked:
            raise
        except Exception as exc:
            raise DatasetImportBlocked(f"live dataset identity probe failed: {name}") from exc
        if set(observed) != set(_LIVE_OPERATIONS) or not all(
                observed.get(operation) == "denied" for operation in _LIVE_OPERATIONS):
            raise DatasetImportBlocked(f"must-deny dataset probe unexpectedly succeeded: {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="import_abcr_dataset.py")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--check-live", action="store_true")
    mode.add_argument("--install-reviewed", metavar="AUTHORITY_SHA")
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0:
            raise DatasetImportBlocked("dataset import/check requires root")
        _require_reviewed_execution_path()
        authority = load_authority(_authority_path(), owner_uid=0)
        dataset_gid = grp.getgrnam("abcr-dataset-read").gr_gid
        source_gid = grp.getgrnam("wheel").gr_gid
        dataset_root = Path(authority["dataset_root"])
        if args.check or args.check_live:
            final = verify_installed(authority, dataset_root=dataset_root,
                                     owner_uid=0, dataset_gid=dataset_gid)
            if args.check_live:
                validate_live_dataset_access(
                    authority, dataset_root=dataset_root, final=final)
            created = False
        else:
            if args.install_reviewed != REVIEWED_AUTHORITY_SHA:
                raise DatasetImportBlocked("reviewed authority SHA is required")
            # Publishing group-readable bytes is unsafe unless this finite
            # authority is the complete direct and effective membership set.
            validate_exact_dataset_reader_group(authority["access_policy"])
            final, created = import_dataset(
                authority, source_root=Path(authority["source_staging_root"]),
                dataset_root=dataset_root, owner_uid=0, source_gid=source_gid,
                dataset_gid=dataset_gid)
        print(json.dumps({"ok": True, "created": created,
                          "live_access_validated": bool(args.check_live),
                          "dataset_sha256": final.name, "path": str(final)},
                         sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__,
                          "message": str(exc)}, sort_keys=True), file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
