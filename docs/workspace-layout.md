# ABCR — 自动化实验工程(2026-07-16 迁入 shared-brain,与 AILH 并列)

> 设计文档:`shared-brain/L2-project/docs/1Personality-Experiment-Final/自动化工作流/`
> 迁址广播(路径映射表):`abcr-wt/r2/FABLE-BROADCAST-20260716-迁址.md`

## 结构 — 三个目录是什么、为什么不"合并成一个"

```
ABCR/
├── abcr/                    ← 主仓(main 分支,R1 过门态;唯一 .git 对象库在这里)
├── abcr-wt/                 ← 同一仓库的 4 个 worktree(不是拷贝!)
│   ├── a  → pkg/a 分支     (包A:账本/审计 Auditor)
│   ├── b  → pkg/b 分支     (包B:Operator/rig 科学载荷)
│   ├── c  → pkg/c 分支     (包C:Governor 审批/同步视图)
│   └── r2 → r2-integration (三包集成 + R2 门工作;最新代码在这)
└── abcr-backups-20260715/   ← 2026-07-15 git 拓扑修复前的安全备份(bundle+tar)
```

**为什么保持这个结构**:`abcr-wt/*` 是 git worktree——四个分支的并行工作副本,共享 `abcr/.git`
对象库(所以 abcr-wt 才 71MB 而非 4×2GB)。三包并行开发(文件所有权互斥)+ 集成门纪律
(main 只在回归门推进)靠它实现。"合并成一个文件夹" = 归入本父目录,worktree 关系保留。

## 常用入口

- **开工第一动作**:`cd abcr-wt/r2 && PYTHONPATH=src ../../abcr/.venv312/bin/python scripts/preflight_kickoff.py`
- **R2 真批一条命令**:`abcr-wt/r2/scripts/run_r2_batch.sh`(云上真 7B / 本地 `fake` 自证)
- **云上操作说明(非技术人员)**:`abcr-wt/r2/scripts/cloud/R2-操作说明-非技术人员照抄版.md`
- **最小上传包**:`~/abcr-r2-min-upload.tar.gz`(305KB,实测可跑)

## 备份处置(侦查结论 2026-07-16)

- `abcr-main-worktree-files.tar.gz`(133M):**保留**——是 cloud-results(W1 真实云数据,不可再生)
  的唯一第二副本,校验通过前不删。
- 3 个 bundle + orphan-repo-b/c(~5.5M):git 内容已被现仓完全超越,确认无虞后可删。

## Syncthing

本目录在 Syncthing folder 根(`~/shared-brain/AILH`)**之外**(ABCR 是 AILH 的兄弟,不在其下),
故**根本不在同步范围内**,不外传 wangyinan——无需任何 ignore 规则。
(2026-07-16 路径B 迁移前 ABCR 曾短暂位于 shared-brain 内、靠 `/ABCR` 忽略规则排除;迁移后已无此需要。)
