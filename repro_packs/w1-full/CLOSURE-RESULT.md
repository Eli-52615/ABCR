# CLOSURE-RESULT — W1 终包 (w1-full) G5 闭合验收

验收时间: 2026-07-13T07:46+08:00
验收员: 独立 Claude Code 会话（信息隔离，仅读 CLOSURE-PROTOCOL.md + w1-full/）
包版本: git commit 5fc90d6cd8da9666038a62e883b64d67740b59e6
打包时间: 2026-07-12T23:37:45.565729+00:00

---

## 验收标准逐条结论

### 1. 分数逐条一致（rescore 复算比对）

**PASS**

执行命令: `python3 rescore/rescore.py .`

| Run ID | Steps | Mismatches | Chain OK | Result |
|--------|-------|------------|----------|--------|
| 20260712-130600-f9cc074895de | 28 | 0 | ✅ | PASS |
| 20260712-130600-f9cc074895de-t0 | 14 | 0 | ✅ | PASS |
| 20260712-133352-0a5a38ac8bf7 | 28 | 0 | ✅ | PASS |
| 20260712-133352-0a5a38ac8bf7-t0 | 14 | 0 | ✅ | PASS |
| 20260712-134715-c52d9d7295b3 | 28 | 0 | ✅ | PASS |
| 20260712-134715-c52d9d7295b3-t0 | 14 | 0 | ✅ | PASS |
| 20260712-142226-bdcb51755747 | 28 | 0 | ✅ | PASS |
| 20260712-142226-bdcb51755747-t0 | 14 | 0 | ✅ | PASS |

总计: 168 条分数，全部独立复算一致，零 mismatch。

### 2. 链与哈希零异常

**PASS**

- **SHA256 文件校验**: 183/183 文件全部 PASS（与 pack_manifest.json 中记录的哈希逐字节匹配）
- **Hash Chain（entry_hash / prev_hash）**: 8/8 个 run 全部链完整，零 break
- **文件完整性**: 磁盘上 186 文件 vs manifest 183 文件；3 个差异均为预期：
  - `pack_manifest.json`（自身无法列入自身）
  - `rescore/__pycache__/checkers.cpython-314.pyc`（执行 rescore 时 Python 自动生成）
  - `rescore/__pycache__/registry.cpython-314.pyc`（同上）

### 3. 缺口清单

**空（无缺口）**

- rescore/ 仅使用 Python 3 stdlib（json, hashlib, pathlib, sys, os, re, typing），无第三方依赖
- 包内自含 data/items/ifeval_style/items.jsonl（题库）、全部 steps.jsonl（原始输出）、scores/（打分）、rescore/（复算代码）
- 新会话无需任何包外信息即可完成全部复算

---

## 附加验证

### summary.json 一致性

所有 8 个 summary.json 的 n_steps 字段与对应 scores.jsonl 行数精确匹配。

### RUNSET 结构

4 臂设计确认（MINILOOP-RUNSET.json）:
- vanilla: 20260712-130600-f9cc074895de (+ t0)
- prompt_persona: 20260712-133352-0a5a38ac8bf7 (+ t0)
- residual_vector: 20260712-134715-c52d9d7295b3 (+ t0)
- random_direction: 20260712-142226-bdcb51755747 (+ t0)

每臂: main run = 14 items × 2 seeds = 28 steps; t0 run = 14 items × 1 seed = 14 steps。

### 篡改检测抽样

- 对全部 8 个 run 的 steps.jsonl 独立重算 entry_hash chain: 全部完整
- 对全部 8 个 scores 目录逐条重算 is_correct + score: 零偏差
- rescore 代码审读确认: 纯确定性规则打分（IFEval-style checkers），无随机性、无模型调用

### 篡改检测深度抽样：手动 trace checker 逻辑

为验证 rescore 脚本本身未被篡改（非"永远输出 PASS"的假脚本），从 3 个不同 run 各抽取 1 条 step，人工逐字段 trace checker 逻辑：

| 样本 | Run | Check | Output 关键内容 | 人工判定 | 保存分数 | 匹配 |
|------|-----|-------|----------------|---------|---------|------|
| #1 | 130600-f9cc07 step[5] | keywords_forbidden: cold/snow/ice | "...against the cold. Nature enters..." | FAIL(cold出现) → 0.0 | 0.0 | ✅ |
| #2 | 133352-0a5a38 step[10] | keywords_existence: collaboration/success/communication | 三词均多次出现 | PASS → 1.0 | 1.0 | ✅ |
| #3 | 142226-bdcb51-t0 step[3] | length_words≥50 + keywords + end_phrase | 28词(FAIL) + 词在(PASS) + "Happy reading."大写+句号(FAIL) | 1/3=0.3333 | 0.3333 | ✅ |

结论：rescore 代码逻辑与人工 trace 完全一致，排除脚本篡改可能。

---

## 最终结论

**PASS**

三项验收标准全部满足。W1 终包 (w1-full) 闭合验收通过。
