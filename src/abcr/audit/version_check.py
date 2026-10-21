"""abcr.audit.version_check —— 审计项5 · 版本一致（A2-2）。

架构位置：包A·验船师侧。输入 batch_id + run_ids，输出 AuditItem(id=5)。四查：

0. **git_commit 真核验**（check_git_commit）：真跑 `git cat-file -e <sha>^{commit}`，
   伪造/不存在的 commit = FAIL；不可核验（非 git 仓/git 缺位）对 citable 或 strict 亦 FAIL。
   strict 另加 worktree 干净 + HEAD == manifest.git_commit。
1. **git clean 自洽**：manifest.git_clean=false 时必须 non_citable=true（脏树产物不可引用）；
   git_clean=false 且 non_citable=false = FAIL（脏树却宣称可引用）。
2. **code_tree_hash 重算**（treehash，§3.7 单一定义）：对当前 worktree 重算，与
   manifest.code_tree_hash 比对。不一致本身不必然 FAIL（审计时代码可能已推进）——报告呈现
   两值并标 `code_drift: true`；**strict=True（复现包出包前）时漂移升级为 FAIL**。
3. **env lock**：manifest.env_lock_ref 指向的 lockfile 存在、非空、含 python 版本行；且与
   steps 的 env_lock_ref 字段一致。lockfile 缺位/残缺：citable run = FAIL；non_citable
   run（Mac/fixture 产物）降为呈现注记（呈现纪律：Mac 产物 non_citable）。

契约出处：工程包A §6·A2-2 + §8.2 R2-A7；code_tree_hash 定义 §3.7。
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from abcr.audit.report import AuditItem
from abcr.audit.treehash import code_tree_hash

_PY_VERSION_RE = re.compile(r"python", re.IGNORECASE)
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


def _git(repo_root: Path, *args: str) -> tuple[int, str]:
    """跑一条只读 git 命令，返回 (returncode, stdout.strip())。git 缺位/超时 → (-1, 原因)。"""
    try:
        p = subprocess.run(["git", "-C", str(repo_root), *args],
                           capture_output=True, text=True, timeout=10)
        return p.returncode, (p.stdout or "").strip()
    except (OSError, subprocess.SubprocessError) as e:      # git 不存在 / 超时
        return -1, f"{type(e).__name__}: {e}"


def _is_git_repo(repo_root: Path) -> bool:
    rc, out = _git(repo_root, "rev-parse", "--is-inside-work-tree")
    return rc == 0 and out == "true"


def check_git_commit(repo_root: Path, manifest: dict, rid: str,
                     strict: bool) -> tuple[bool, str]:
    """**真跑 git** 核验 manifest.git_commit 确实存在（根因①：无外部信任根）。

    原实现只有 item1 的"22 键存在性"检查，从不问这个 SHA 是否真的是一个 commit——
    实测击穿：把 git_commit 改成 deadbeef…（任何 git 仓都没有的 SHA），strict 下
    仍判 PASS，而 repro_pack 会把这个伪造 SHA 原样印进复现说明，误导复现者。
    这里把"溯源锚点必须可解析"接成可执行判据：

    - 字段缺失/非法：不在此判（item1 的 MANIFEST_KEYS 已守存在性）；strict 下补判 FAIL
      （复现包出包前必须有可解析的 commit）。
    - 字段存在：`git cat-file -e <sha>^{commit}` 真跑。解析不到 = 伪造/丢失 → FAIL。
    - git 不可用 / repo_root 非 git 仓（tmp fixture）：**无法核验**。citable run 或
      strict 一律 FAIL（不可核验的溯源不得当作已核验）；non_citable 非 strict 降注记。
    - strict（复现包出包前）另加：worktree 必须干净、HEAD 必须等于 manifest.git_commit
      ——出包时刻的代码状态必须与 manifest 自述完全对上。
    """
    commit = manifest.get("git_commit")
    non_citable = manifest.get("non_citable") is True
    lenient = non_citable and not strict          # 只有 non_citable 且非 strict 才降注记

    if not isinstance(commit, str) or not _SHA_RE.match(commit.strip()):
        if strict:
            return False, f"[strict] {rid}: git_commit 缺失/非法 SHA（{commit!r}）→ 复现包不得出包"
        # 字段**存在但不是 SHA**（如 "fixture0000"）：对 citable run 就是伪造的溯源锚点，
        # 非 strict 也判 FAIL。字段**缺失**留给 item1 的 MANIFEST_KEYS 存在性检查，
        # 此处只注记，避免与 item1 重复判同一件事。
        if "git_commit" in manifest and not lenient:
            return False, (f"{rid}: git_commit={commit!r} 不是可解析的 SHA"
                           f"（citable run 的溯源锚点必须可解析 → FAIL）")
        return True, f"{rid}: git_commit 未提供可解析 SHA（{commit!r}，注记）"
    commit = commit.strip()

    if not _is_git_repo(repo_root):
        if lenient:
            return True, f"{rid}: {repo_root} 非 git 仓，git_commit {commit[:12]} 无法核验（non_citable，注记）"
        return False, (f"{rid}: {repo_root} 非 git 仓或 git 不可用，git_commit {commit[:12]} "
                       f"**无法核验**（不可核验≠已核验 → FAIL）")

    rc, _ = _git(repo_root, "cat-file", "-e", f"{commit}^{{commit}}")
    if rc != 0:
        return False, (f"{rid}: git_commit {commit[:12]}… 在本仓不存在任何对应 commit"
                       f"（伪造/丢失的溯源锚点 → FAIL）")
    lines = [f"{rid}: git_commit {commit[:12]}… 经 git cat-file 核验存在"]

    if strict:
        rc_s, dirty = _git(repo_root, "status", "--porcelain")
        if rc_s != 0:
            return False, f"[strict] {rid}: git status 执行失败，无法核验 worktree 干净度 → FAIL"
        if dirty:
            n = len(dirty.splitlines())
            return False, (f"[strict] {rid}: worktree 不干净（{n} 条未提交改动）"
                           f"→ 复现包出包前须干净 → FAIL")
        rc_h, head = _git(repo_root, "rev-parse", "HEAD")
        if rc_h != 0 or not head.startswith(commit) and not commit.startswith(head[:len(commit)]):
            return False, (f"[strict] {rid}: HEAD={head[:12]}… ≠ manifest.git_commit "
                           f"{commit[:12]}… → 出包代码状态与自述不符 → FAIL")
        lines.append(f"[strict] {rid}: worktree 干净且 HEAD 与 manifest.git_commit 一致")
    return True, "；".join(lines)


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
    return out


def _load_manifest(repo_root: Path, rid: str) -> dict | None:
    p = repo_root / "data" / "runs" / rid / "manifest.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None


def check_git_clean(manifest: dict, rid: str) -> tuple[bool, str]:
    """git_clean=false 时必须 non_citable=true。返回 (ok, 证据行)。

    缺字段即 FAIL（根因②：缺失不作干净）：原实现 ``manifest.get("git_clean")`` 缺键
    得 None，``None is False`` 为假 → 直接判自洽通过——即"manifest 干脆不写 git_clean
    就绕过脏树检查"。故 git_clean 字段缺失/非布尔一律 FAIL，不再默许。
    """
    git_clean = manifest.get("git_clean")
    non_citable = manifest.get("non_citable")
    if not isinstance(git_clean, bool):
        return False, f"{rid}: manifest 缺 git_clean 布尔字段（缺失/非法不作干净 → FAIL）"
    if git_clean is False and non_citable is not True:
        return False, f"{rid}: git_clean=false 却 non_citable={non_citable!r}（脏树宣称可引用）"
    return True, f"{rid}: git_clean={git_clean} non_citable={non_citable}（自洽）"


def check_code_tree_hash(repo_root: Path, manifest: dict, rid: str,
                         current_hash: str, strict: bool) -> tuple[bool, str]:
    """当前 worktree code_tree_hash vs manifest。漂移标 code_drift；strict 时升 FAIL。"""
    recorded = manifest.get("code_tree_hash")
    if recorded == current_hash:
        return True, f"{rid}: code_tree_hash 一致（{str(current_hash)[:12]}…）"
    line = (f"{rid}: code_drift=true 生成时={str(recorded)[:12]}… 当前={str(current_hash)[:12]}…")
    if strict:
        return False, "[strict] " + line + "（复现包出包前须一致 → FAIL）"
    return True, line + "（审计时代码已推进，呈现不判 FAIL）"


def check_env_lock(repo_root: Path, manifest: dict, rid: str,
                   step_refs: set[str]) -> tuple[bool, str]:
    """env_lock_ref 存在/非空/含 python 版本行 + 与 steps 一致。non_citable 缺位降注记。"""
    ref = manifest.get("env_lock_ref")
    non_citable = manifest.get("non_citable") is True
    if not isinstance(ref, str) or not ref:
        return non_citable, \
            f"{rid}: env_lock_ref 缺失" + ("（non_citable，注记）" if non_citable else "（citable → FAIL）")
    # steps 一致性（真实完整性问题，与 citable 无关）
    if step_refs and step_refs != {ref}:
        return False, f"{rid}: env_lock_ref manifest={ref!r} 与 steps {sorted(step_refs)} 不一致"
    lock_p = repo_root / ref
    if not lock_p.exists() or lock_p.stat().st_size == 0:
        if non_citable:
            return True, f"{rid}: env_lock {ref} 缺位/空（non_citable Mac 产物，注记）"
        return False, f"{rid}: env_lock {ref} 缺位或空（citable → FAIL）"
    text = lock_p.read_text(encoding="utf-8", errors="replace")
    if not _PY_VERSION_RE.search(text):
        if non_citable:
            return True, f"{rid}: env_lock {ref} 无 python 版本行（non_citable，注记）"
        return False, f"{rid}: env_lock {ref} 缺 python 版本行（citable → FAIL）"
    return True, f"{rid}: env_lock {ref} 存在/非空/含 python 版本行、与 steps 一致"


def version_consistency_item(repo_root: Path, batch_id: str, run_ids: list[str],
                             strict: bool = False) -> AuditItem:
    """审计项5 编排：三查逐 run；任一硬失败 → item FAIL。"""
    repo_root = Path(repo_root)
    evidence: list[str] = []
    fails: list[str] = []
    current_hash = code_tree_hash(repo_root)
    evidence.append(f"当前 worktree code_tree_hash = {current_hash[:16]}…")

    if not run_ids:
        return AuditItem.make(5, "SKIP", ["项5（版本一致）: 批内无 run，SKIP"])

    for rid in run_ids:
        manifest = _load_manifest(repo_root, rid)
        if manifest is None:
            fails.append(f"{rid}: manifest.json 缺失或非法 JSON")
            continue
        step_refs = {st.get("env_lock_ref") for st in
                     _load_jsonl(repo_root / "data" / "runs" / rid / "steps.jsonl")
                     if st.get("env_lock_ref") is not None}
        for ok, line in (
            check_git_clean(manifest, rid),
            check_git_commit(repo_root, manifest, rid, strict),
            check_code_tree_hash(repo_root, manifest, rid, current_hash, strict),
            check_env_lock(repo_root, manifest, rid, step_refs),
        ):
            (evidence if ok else fails).append(line)

    verdict = "FAIL" if fails else "PASS"
    return AuditItem.make(5, verdict, (fails + evidence) if fails else evidence)
