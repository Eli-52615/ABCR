# FABLE 广播 · 2026-07-16 · 仓库迁址(楠指示归并)

**自 2026-07-16 起,仓库根变更**(楠指示:ABCR 归入 shared-brain,与 AILH 并列):

| 旧路径 | 新路径 |
|---|---|
| `/Users/superagent/abcr` | `/Users/superagent/shared-brain/ABCR/abcr` |
| `/Users/superagent/abcr-wt/{a,b,c,r2}` | `/Users/superagent/shared-brain/ABCR/abcr-wt/{a,b,c,r2}` |
| `/Users/superagent/abcr-backups-20260715` | `/Users/superagent/shared-brain/ABCR/abcr-backups-20260715` |

- **协议文档(configs/protocol/*.md、FABLE-BROADCAST-20260715.md)已冻结不改**:其中出现的旧绝对路径,一律按上表映射到新根解释(含 DEVIATIONS/STATUS/heavy.lock/repro_packs 等)。
- 已同步修复:worktree 双向指针(git worktree repair)、wtb/wtc remote、三 venv shebang/activate、preflight_kickoff.py(main+四 worktree)、bootstrap.sh(改根+归档注记)。
- Syncthing:shared-brain/.stignore 已加 `/ABCR` 整体排除——本仓不外传 wangyinan;如需同步见 .stignore 注释。
- 历史 runs/PROGRESS/manifest 里的旧路径是证据记录,保持原样,勿改。
