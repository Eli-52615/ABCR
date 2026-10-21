# 第八轮 findings 处置清单（2026-07-26）

> 第八轮由 5 个视角并行搜查，共报 15 条（去重后）；每条经 2 名独立裁定者复核。
> 楠指令停在第八轮，不跑 9–12 轮。本清单记录**每条的处置状态**，未闭合的不许遗忘。

---

## 已闭合

### ✅ P0 — tar hardlink 成员规则四方不一致

**两个独立视角各自撞上同一条**，是本轮唯一的阻断级发现。

- 机理：`install_abcr_runtime.py:317` 拒绝 hardlink，而 `release_policy.py:174` 放行；
  真实封印 release 内 `dateutil-zoneinfo.tar.gz` 实测含 **245 个 hardlink 成员**；
  调用链 `verify_receipt():515 → enforce_release_scientific_content_policy():544`
  → 必然 `InstallBlocked` → genesis 装不进去。
- 归属：**codex 基线 `936fdd7`** ——「一次性引入两份实现，安装器移植版从未与
  `release_policy` 的 hardlink 放行对齐，也从未被任何测试或真实产物比对过」。
- 处置：commit **`8887186`**。移植版逐条对齐原版；顺带补上原版有而移植版没有的
  **重名成员检测**（此条无任何 panel 报告过，是等价性测试自己抓出来的）。
- 守门：`tests/control/test_policy_port_equivalence.py`（17 用例）。不检查常量相等，
  而是**把同一批字节喂给两侧断言判定一致**，覆盖 hardlink / symlink / 悬空链接 /
  重名 / 嵌套归档 / 路径归一化六个维度，真实产物存在时直接实测。修复前实跑为红。

### ✅ P2 — 幻影引用（`qualify_abcr_autonomous.py` 等）

- 处置：commit **`f8b4e41`** 的 `scripts/check_runbook_refs.py` 已把这类事故变成
  CI 自动断言。3 条已知有意缺席（均属 AUTONOMOUS_QUAL 门，票据 §5 明示保持 BLOCKED）
  登记在 `KNOWN_ABSENT` 内并附门与交付时机。
- 历史回归实证：把该检查器放到 `1a7daf1` 的树上跑，精确报出轮2 那个 P0
  （`qualify_abcr_genesis_probation.py` 不存在于任何提交），rc=1。

---

## 待处置（按影响阶段排序）

### 🔸 影响**阶段 1**（V4 指引必须修正）

**P2 — 人类操作指引步骤 0.5 的 git diff 范围错误**
- `人类操作指引-阶段1-最终版…md:22,35`：diff 范围与变更统计**与任何真实区间都不符**，
  人照它逐行复核**会完全漏掉第五/六/七轮**——也就是漏掉两个 P0 的修复。
- 归属：Fable5（从旧版指引复制，未随轮次更新）。
- **处置：随 V4 指引一并修正，并改为由脚本生成真实区间，不再手写。**

### 🔸 影响**阶段 2B**（genesis 之后的激活，当前用不到但不得遗忘）

**P1 ×3 全部落在仓外 1014 行扩展版 runbook**——它冻结于 07-23，而仓内副本已五轮修订：

| 级别 | 问题 | 位置 |
|---|---|---|
| P1 | §8.1–8.2 首次激活流程与仓内 §7 **相反**，按仓外执行必然停在 PENDING、永不 ACTIVE | 451–487 |
| P1 | §5 仍宣称 genesis 失败后 "retains the exact LKG/receipt for reviewed retry"，与代码相反（第七轮只改了仓内副本） | 293–294 |
| P1 | §7/§8 描述的仍是 round-3 之前的首次激活模型 | 428–447 / 449– |
| P2 | §7 的「三组件整代 transaction 原子晋级 + 共同回退」在代码中不存在 | 430–443 |
| P2 | §8.3 要求核验两个本 release 任何代码都不会创建的文件 | 492–507 |
| P2 | §8.3 宣称 `--abort-probation` 会 bootout probation worker，代码相反 | 517 |
| P2 | §9.2 调用不存在的 `qualify_abcr_autonomous.py` | 775–786 |

> **根本处置建议：把扩展版 runbook 收编进仓。**
> 它是「部署权威」，却位于 git 与封印树之外——整套 hash / fail-closed 完整性机器对它
> **结构性失明**，且与仓内副本靠人工同步，已实证会漂移（本轮 3 条 P1 全部由此产生）。
> 票据 `REL-3e8c1d1a` §5 的未决项「评估把共享扩展版 runbook 收编进仓」**至今未闭合**。
> 收编后即可被 `check_runbook_refs.py` 与 git 同时覆盖。

### 🔸 代码侧遗留

| 级别 | 问题 | 位置 | 归属 |
|---|---|---|---|
| P2 | b65fdc2 新增的「>8 MiB manifest 回归」测试**不覆盖任何一个被修的调用点**：把四处修复全部回退，全树仍 1502 passed / 0 failed | `tests/control/test_deployment_contract.py:260-283` | b65fdc2（Fable5） |
| P2 | `_check_promotions` 新不变量接受 seal-broker「回滚到 genesis LKG」的状态，旧硬编码会拒绝，晋级闸在此处失效 | `qualify_abcr_genesis_probation.py:354-359` | b65fdc2 |
| P2 | runbook §6 声称「重跑安装器多装一代会被 genesis qualification gate 拒绝」，而**同一个 commit** 恰恰把那个闸改成接受它 | `ops/install/REVIEWED-RUNTIME-INSTALL.md:307-311` | b65fdc2（文档与同 commit 代码自相矛盾） |
| P2 | B2/B4 drain 阶段 handler 内部抛错时结果写成终局失败信封且 work_id 永不可再入队，而 runbook §7 错误码分诊表只覆盖 `genesis_*` 闭集，会误导 | `qualify_abcr_genesis_probation.py:489-497` | codex 队列语义 + Fable5 分诊表 |

> 第一条值得单独说：它意味着**第七轮那 4 个 P0 的修复至今没有有效的回归守门**——
> 测试存在但空转。这与票据残余风险第 1 条（该批修复未经独立复核）叠加，
> 是 codex 本批验证的重点之一。

---

## 归属统计（本轮）

| 归属 | 条数 |
|---|---|
| codex 基线 `936fdd7` | **2 条 P0**（同一缺陷的两个视角） |
| Fable5 文档侧（仓外 runbook 未同步） | 3 条 P1 + 4 条 P2 |
| Fable5 代码侧（b65fdc2 等） | 4 条 P2 |
| 混合 | 1 条 P2 |

**本轮唯一的阻断级缺陷仍出自 codex 基线**，与前七轮的分布一致（八轮下来，全部
阻断级 P0 无一由修复引入）。同时也如实记录：**本轮 P1 全部是 Fable5 的文档侧欠账**。
