"""scripts/a_freeze.py —— 冻结区定稿仪式（A2-5，人跑，A 写脚本）。

用法：
  python scripts/a_freeze.py data/golden [--repo-root .] [--profile /private/tmp/abcr-frozen.sb]
  python scripts/a_freeze.py data/golden --supersede   # 旧冻结物换代（artifact_superseded）

步骤（文档 §6·A2-5）：
  ① 断言目标在冻结区三目录内、git 已跟踪、工作区 clean；
  ② 逐文件 sha256 + 目录树哈希（复用 abcr.audit.treehash）；
  ③ 经账本 API 落协议事件至第五链 ledger/protocol.jsonl（AMENDMENT-7）：
     artifact_frozen / artifact_superseded，payload {artifact, tree_hash, git_tag, actor="human"}；
  ④ git tag freeze/<artifact名>-<UTC日期>；
  ⑤ 重新生成 Seatbelt profile（冻结区三目录 deny 恒纳入）；
  ⑥ 打印验证命令让人当场自证。

零外部依赖（argparse + subprocess）。actor 恒 "human"（定稿是人的批准动作）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from abcr.audit.treehash import hash_tree
from abcr.common import external_seal
from abcr.common.ledger_ref import RunLedger
from abcr.review import KIND_ITEMS_SOURCE
from abcr.sandboxing.profiles import FROZEN_RELS, available, frozen_profile

# 冻结区 = golden/splits/traits/items。data/items 是 review 复算判据的权威 items 源
# （V05 生产端封印点），纳入冻结仪式后 `a_freeze data/items` 会对其调 external_seal.seal，
# 使 review 的 citable 路径有锚可验。
FROZEN_ROOTS = tuple(f"data/{n}" for n in ("golden", "splits", "traits", "items"))

# review 读取 items 源时用 basename 作 subject_id（items_file.name），封印端必须同口径。
_ITEMS_SOURCE_FILENAME = "items.jsonl"


def _git(repo_root: Path, *args: str) -> tuple[int, str]:
    r = subprocess.run(["git", "-C", str(repo_root), *args],
                       capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def _in_frozen_zone(artifact_rel: str) -> bool:
    a = artifact_rel.rstrip("/")
    return any(a == root or a.startswith(root + "/") for root in FROZEN_ROOTS)


def artifact_tree_hash(repo_root: Path, artifact_rel: str) -> tuple[str, dict[str, str]]:
    """目标子树的 {相对路径: sha256} + 子树聚合哈希（复用 treehash.hash_tree 过滤前缀）。"""
    full = hash_tree(repo_root)
    prefix = artifact_rel.rstrip("/") + "/"
    sub = {k: v for k, v in full.items() if k == artifact_rel or k.startswith(prefix)}
    tree_hash = hashlib.sha256(json.dumps(sub, sort_keys=True).encode("utf-8")).hexdigest()
    return tree_hash, sub


def _seal_items_sources(repo_root: Path, sub: dict[str, str]) -> list[dict]:
    """对冻结子树内的 items 源（basename==items.jsonl）逐个调 external_seal.seal。

    这是 V05 的【生产端封印点】：review 对 citable 批强制要求 items 源有匹配封印，
    这里在定稿仪式里生成那个锚。摘要口径必须与 review._check_items_source 完全一致
    ——解析同样的 jsonl 条目序列、用同一 external_seal.chain_digest_and_length、
    subject_id 同样取 basename（review 用 items_file.name）。

    返回封印记录列表（用于打印自证）。子树内无 items 源则返回空列表（无副作用）。
    """
    sealed = []
    for rel in sorted(sub):
        if Path(rel).name != _ITEMS_SOURCE_FILENAME:
            continue
        entries = []
        for line in (repo_root / rel).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        digest, length = external_seal.chain_digest_and_length(entries)
        subject_id = Path(rel).name
        rec = external_seal.seal(KIND_ITEMS_SOURCE, subject_id, digest, length,
                                 extra={"source_rel": rel, "actor": "human"})
        sealed.append(rec)
    return sealed


def freeze(repo_root: Path, artifact_rel: str, supersede: bool = False,
           profile_path: str = "/private/tmp/abcr-frozen.sb") -> int:
    repo_root = Path(repo_root).resolve()
    artifact_rel = artifact_rel.rstrip("/")

    # ① 断言：冻结区内 + git 跟踪 + clean
    if not _in_frozen_zone(artifact_rel):
        print(f"FAIL: {artifact_rel} 不在冻结区 {FROZEN_ROOTS}", file=sys.stderr)
        return 2
    if not (repo_root / artifact_rel).exists():
        print(f"FAIL: {artifact_rel} 不存在于 {repo_root}", file=sys.stderr)
        return 2
    code, tracked = _git(repo_root, "ls-files", "--", artifact_rel)
    if code != 0 or not tracked.strip():
        print(f"FAIL: {artifact_rel} 未被 git 跟踪（tracked='{tracked[:80]}'）", file=sys.stderr)
        return 2
    code, dirty = _git(repo_root, "status", "--porcelain", "--", artifact_rel)
    if dirty.strip():
        print(f"FAIL: {artifact_rel} 工作区不 clean:\n{dirty}", file=sys.stderr)
        return 2

    # ② 树哈希
    tree_hash, sub = artifact_tree_hash(repo_root, artifact_rel)

    # ④（先算 tag 名，用于入账 payload）
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    tag = f"freeze/{Path(artifact_rel).name}-{date}"

    # ③ 协议事件入第五链
    event = "artifact_superseded" if supersede else "artifact_frozen"
    protocol = RunLedger(repo_root / "ledger", "protocol")
    rec = protocol.append(event, subject_id=artifact_rel, artifact=artifact_rel,
                          tree_hash=tree_hash, git_tag=tag, actor="human")

    # ③b items 源外部封印（V05）：子树内每个 items.jsonl 落 KIND_ITEMS_SOURCE 锚，
    #     让 review 的 citable 路径有锚可验（缺锚 = citable run fail-closed）。
    sealed_items = _seal_items_sources(repo_root, sub)

    # ④ git tag（已存在则追加 -N 避免碰撞）
    tag_final = tag
    n = 1
    while _git(repo_root, "rev-parse", "-q", "--verify", f"refs/tags/{tag_final}")[0] == 0:
        n += 1
        tag_final = f"{tag}-{n}"
    code, tagout = _git(repo_root, "tag", tag_final,
                        "-m", f"freeze {artifact_rel} tree_hash={tree_hash}")
    tag_ok = code == 0

    # ⑤ 重新生成 Seatbelt profile（冻结区三目录恒纳入）
    profile_written = False
    if available():
        try:
            Path(profile_path).write_text(frozen_profile(repo_root), encoding="utf-8")
            profile_written = True
        except OSError as e:  # noqa: BLE001
            print(f"WARN: profile 写入失败 {e}", file=sys.stderr)

    # ⑥ 自证命令
    print(f"=== 定稿仪式完成 · {artifact_rel} ===")
    print(f"  事件: {event} → ledger/protocol.jsonl (entry_hash={rec['entry_hash'][:12]}…)")
    print(f"  tree_hash: {tree_hash}")
    print(f"  文件数: {len(sub)}")
    if sealed_items:
        for rec in sealed_items:
            print(f"  items 源封印: kind={rec['kind']} subject_id={rec['subject_id']} "
                  f"length={rec['length']} digest={rec['digest'][:12]}… "
                  f"(source={rec['extra'].get('source_rel')})")
    else:
        print("  items 源封印: 子树内无 items.jsonl（SKIP）")
    print(f"  git tag: {tag_final} ({'ok' if tag_ok else 'FAIL '+tagout})")
    print(f"  Seatbelt profile: {profile_path} "
          f"({'已生成' if profile_written else 'SKIP（sandbox-exec 不可用）'})")
    print("  当场自证（人跑）:")
    print(f"    SB={profile_path}")
    print(f'    /usr/bin/sandbox-exec -f $SB /bin/sh -c "echo x >> {artifact_rel}/$(ls {artifact_rel} | head -1)"; echo exit=$?  # 预期 Operation not permitted, exit=1')
    print(f"    git show {tag_final} --stat | head")
    print(f'    python -c "from abcr.common.ledger_ref import RunLedger; from pathlib import Path; '
          f'print([e for e in RunLedger(Path(\'{repo_root}\')/\'ledger\',\'protocol\').events() if e[\'event\']==\'{event}\'][-1])"')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifact", help="冻结区相对路径，如 data/golden")
    ap.add_argument("--repo-root", default=".", help="仓库根")
    ap.add_argument("--supersede", action="store_true",
                    help="旧冻结物换代（artifact_superseded 而非 artifact_frozen）")
    ap.add_argument("--profile", default="/private/tmp/abcr-frozen.sb",
                    help="Seatbelt profile 落地路径")
    args = ap.parse_args()
    return freeze(Path(args.repo_root), args.artifact, supersede=args.supersede,
                  profile_path=args.profile)


if __name__ == "__main__":
    sys.exit(main())
