# ABCR｜codex ↔ code 协作契约

> 立约：2026-07-26，经楠拍板。
> 双方：**code**（Claude / Fable5，本机 Claude Code）、**codex**（另一台机器经 ssh 操作本机，**有 sudo**）。
> 本文件是分工的**唯一权威**。发生分歧以本文为准，不以任何一方的记忆或口头约定为准。

---

## 0. 一句话

**code 做全部实现，codex 只做独立验证与签名、不写实现代码。**

---

## 1. 分工契约（硬约束）

| | code（Claude） | codex |
|---|---|---|
| **角色** | 实现者 / 构建者 | **独立 verifier / 签名者** |
| **做** | 写代码、写测试、修缺陷、写 runbook 与人类指引、构建 candidate、出 release | 独立审查、**用 sudo 跑 root 语义验证**、独立重算哈希、签 PASS attestation |
| **绝不做** | 不签自己的 attestation | **不写实现代码**、不改仓内任何被封印文件、不替 code 修缺陷 |
| **发现缺陷时** | 直接修 | **只报告，不动手修**（报给 code，由 code 修，再交回验证） |

**为什么 codex 不写实现代码**——不是不信任，是为了消除你担心的那种浪费：只要双方都写实现，就必然产生「互相验证质量、熟悉对方进度、内容不贯通」的成本。按角色切则完全没有这个问题：codex 的输入只有「一个 exact commit + 一份票据」，不需要了解 code 的工作过程。

---

## 2. 为什么是这个分工（历史依据，非临时决定）

**这套架构本来就要求独立 verifier。** 部署链硬性规定：attestation 必须由「候选 / release / checkout / 本仓之外」的独立持钥方签署，且仓内**故意不提供任何铸造该 key 的命令**。

**是 codex 交付后失联，才让这个设计坍塌成「作者 = 审查者 = 签名者」。** 票据 `REVIEW-TICKET-REL-3e8c1d1a-20260723.md` §0 白纸黑字记录了这个偏差和四条补偿措施，其中「codex 回归后事后复审」一条**空转至今**。

**codex 回归 + 有 sudo，恰好同时修复两个历史缺口：**
1. 恢复架构原本要求的独立性；
2. 补上八轮里最大的测试盲区——**全套件零测试以 root 运行**。

---

## 3. codex 的独有价值：sudo

这是 code **做不到而 codex 能做**的事，也是 codex 在本协作中不可替代的原因。

历史上多个阻断级 P0 的共同点是「只有真正以 root 执行才会暴露」，而当时的 agent 无 sudo：

| 历史 P0 | 为什么测不出来 |
|---|---|
| pyc 自污染（轮1） | `-I` 隐含 `-E` 使 `PYTHONDONTWRITEBYTECODE` 失效、root 无视目录只读位——**非 root 身份下物理上不会发生** |
| `verify_release_read_policy`（轮6） | 需要 root + 真实 gid `abcr-release-read`，测试机上不可执行，全部测试只能 monkeypatch 掉 |
| 哨兵 gid（实机B） | 需要真实 macOS 账户环境 |

**所以 codex 的验证不是「再读一遍代码」，而是要真的用 sudo 跑起来。** 只做静态审查的话，codex 的价值会大打折扣——那部分 code 已经做过了。

---

## 4. 交接接口（窄接口，降低协作成本）

### code → codex（每次交付）

```
1. 一个 exact commit SHA（40 位小写，不接受 branch / tag / HEAD）
2. 一份 review ticket（含全部身份哈希、改动说明、残余风险）
3. 一句话：本次要 codex 重点验证什么
```

**codex 不需要**了解 code 的工作过程、不需要读 session 记录、不需要同步进度。上面三项就是全部输入。

### codex → code（每次回执）

```
裁定：SOUND / BROKEN
若 BROKEN：逐条列出 [级别 P0/P1/P2] + [file:line] + [可复现命令与实际输出]
若 SOUND：签 PASS attestation，给出 attestation 路径与 key fingerprint
root 验证记录：实际用 sudo 跑了什么、输出是什么
```

**codex 发现缺陷时只报告，不修。** 由 code 修完后重新交付一个新的 exact commit，codex 再验。

---

## 5. 红线（双方都不得越过）

1. **codex 不写实现代码。** 包括「顺手改一行」「加个测试」——都不行。发现问题就报告。
2. **不得跳过 exact commit。** 任何以 branch / dirty working tree 交付的东西一律不验。
3. **空结果不算放行。** 验证 agent 崩溃、用量耗尽、超时返回空——一律判 `INVALID`，**不得当作 PASS**。这条有血的教训：历史上 panel 两度撞用量上限返回空结果，当时正确地判了「不算放行」；而 2026-07-26 第八轮首跑，工作流因把「agent 被杀」当成「零发现」而报出假的 clean，已修正。
4. **不得为了让流程通过而降低断言换绿**（仓内 `CLAUDE.md` 执行纪律第 5 条）。
5. **genesis 是全局一次性动作。** 未获明确授权，任何一方都不得执行 genesis 或任何不可逆步骤。

---

## 6. 当前工程状态（2026-07-26）

- **工作分支**：`round8-loop`（git worktree，位于 `abcr/.claude/worktrees/runbook-manifest-assert`），基于 `b65fdc2`。
- **已完成八轮对抗审查**，详见仓内 `ENGINEERING-HISTORY.md` 阶段 4–7 与
  `复盘-七轮审查根因彻查-20260725.md`。
- **`REL-17624261` 已作废**：第八轮 P0 的修复触及封印树内的
  `scripts/install_abcr_runtime.py`，candidate tree hash 必然变化，**须重建 V4**。
- **codex 历史质量问题清单**（7 类 27 条，全部带 file:line）：见**上一级目录**
  `../CODEX-工作质量问题清单-20260726.md`。这不是追责材料，是**验证时的高危区地图**——
  同型缺陷已三次造成阻断级 P0。

### 本轮 code 已完成的实现（待 codex 验证）

| commit | 内容 |
|---|---|
| `f8b4e41` | runbook 引用完整性守门（幻影引用 + 封印遗漏两类事故的自动断言） |
| `8887186` | **第八轮 P0 修复**：安装器策略移植版与 `release_policy` 对齐（tar hardlink + 重名成员），含 17 用例行为等价守门测试 |

回归：**1528 passed / 8 skipped / 0 failed**。

---

## 7. 路径速查

| 项 | 路径 |
|---|---|
| 仓库 | `/Users/superagent/shared-brain/ABCR/abcr` |
| 本轮工作副本 | `abcr/.claude/worktrees/runbook-manifest-assert`（分支 `round8-loop`） |
| 真实封印产物 | `/Users/superagent/.abcr-build/production-b65fdc2-20260725/release-staging/REL-1762426112….staging` |
| verifier 公钥 | `/Users/superagent/.abcr-verifier/production-review-verifier.pub`（fingerprint `6ba3e9e0…`） |
| 文档目录 | `/Users/superagent/shared-brain/ABCR/1-DOCS/0719人格探索落地/` |
| 本协作目录 | 同上 `/codex-code协作完成/` |
| 全量回归 | `cd <repo> && PYTHONPATH=src .venv312/bin/python -m pytest tests --ignore=tests/contract/stage{1,2,3} -q` |
