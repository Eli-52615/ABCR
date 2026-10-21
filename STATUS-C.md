# STATUS-C: Scorer + Audit + Repro Pack

## S0: Bootstrap — DONE
- [x] C0.1 bootstrap 完成（手动，HF 不可达，记 DEVIATIONS）
- [x] C0.2 等待期工作全部完成

## S1: 确定性评分链 + 审计器 — PASS
- [x] C1.1 14 checker + registry (44 unit tests pass)
- [x] C1.2 golden_answers 20 例（覆盖 14 种 checker、5 fail、2 multi-constraint）；黄金检 21 tests pass
- [x] C1.3 score.py（评分独立 pass，对 steps 零写入）
- [x] C1.4 review.py（链校验 + 完备性 + 复评 diff + manifest 审计；canonical_json 已与 A 的 schema.py 对齐）
- [x] C1.5 故障注入：4 类全被抓（篡改字段→E08, 删末行→E10, 伪造分数→E11, 缺 split_hash→E12）

验收输出：73 tests passed in 0.07s

## S2: Judge 后端 + 实链评分 + 首包 — PASS
- [x] C2.1 D0 探针完成：DeepSeek logprobs 10/10 成功，recommended_mode=logprob_weighted
- [x] C2.2 judge client（双模式 logprob_weighted + text_parse，backoff 重试，成本追踪）
- [x] C2.3 blind scoring（违禁列拒绝 + 洗牌可复现 + 端到端打分 6 样本通过）
- [x] C2.4 实链评分 PASS：12 runs（228 steps）全部 chain_ok + score_mismatches=0 + error_codes=[]
  - 修复 review.py items_path 解析 bug（与 score.py 一致化）
  - 覆盖条件：vanilla / prompt_persona / random_direction
- [x] C2.5 repro_pack.py + 首包测试（合成数据：clean pass + 篡改检测 + 缺失文件检测）

验收输出：S2 全绿（contract tests pass, 12 real-chain reviews PASS）
D0 探针报告：review/judge_probe_report.json

## S3: Mini Loop 评分复评 + 表达检 + 主图 — PASS
- [x] C3.1 mini 环全量评分复评：4 main_runs + 4 t0_runs 全 PASS；跨 run 一致性（同 item set、同 seed set）验证通过
  - MINILOOP-RUNSET.json 由 C 从已有 runs 自动构建（A 未显式产出；记 note 字段）
- [x] C3.2 dev 表达检（后备路径）：方向清晰（pos=82.5 > neg=75.3），Cohen's d=0.385，coherence 无副作用（>95）
  - 后备原因：exprcheck_pool.csv 未由 B 生成，直接消费 B 的 judge_raw（记 DEVIATIONS）
  - 报告：review/exprcheck_conscientiousness_report.json
  - 配图：figures/exprcheck_conscientiousness.png（角标齐全）
- [x] C3.3 主图生成：figures/mini_loop.png（双面板：逐 seed 得分 + 输出长度分布，角标齐全）

验收输出：test_c_review_full 2 passed; 主图+表达检图已产出
契约测试：tests/contract/stage3/test_c_review_full.py PASS

## S4: 闭合验收 + 双 judge + 终包 — 批1 DONE（终包待批2）
- [x] C4.2 CLOSURE-PROTOCOL.md 已写
- [x] C4.3 n=50 双 judge 一致性完成：pearson=0.809, spearman=0.833, MAE=21.9
  - 报告：review/judge_consistency_n50.json
  - 散点图：figures/judge_consistency.png（角标 `dev · non-citable · exploratory`，重叠修复）
  - 42/50 有效对（8 个 DeepSeek logprob numeric_mass 不足导致 refusal；Claude 0 refusal）
- [x] rescore_bundle 已验证（stdlib-only，端到端 PASS）
- [x] C4.4 图表终检 PASS（批1）
  - mini_loop.png：补 `exploratory` 角标
  - judge_consistency.png：修复角标与 X 轴重叠（ax.text→fig.text）
  - exprcheck_conscientiousness.png：原已齐全，PASS
- [x] C4.1 w1-mini 终包重建（批1，含 §6 修正）
  - P1 env.lock：两 venv 真实 `uv pip freeze`（141 行，0 UNAVAILABLE）
  - P2 t0 scores：4 t0_runs scores 入包（scores.jsonl + summary.json 各 4）
  - P3 protocol docs：V1.0 + V1.1 补丁 + 三包文档共 5 份入包，pack_manifest.protocol_refs 记 sha256
  - rescore 端到端：8 runs（4 main + 4 t0，168 steps）全 PASS，SHA256 PASS
  - 文件数 70→84
- [x] C guard 接入自证（V1.1 §3.1 C 项）：`python -m abcr.resource_guard run -- echo` PASS
  - preflight: 12/12 normal, disk 92.4GB, no heavy procs, no Docker
  - 规则：凡 claude CLI 批量（>5 次或上界不可预估）经 guard 包装执行
- [ ] C4.1 w1-full 终包：待批2 回填 run 齐后打包（批3 指令）

## 批2准备（批0 接入 + 批2 前置工作）

### 已完成
- [x] test_c_review_full.py str/dict 双兼容修复
- [x] RUNSET 越界补记（DEVIATIONS + STATUS-C 自证更正）
- [x] guard 接入自证（resource_guard wrapper PASS）
- [x] judge 可重算性修复（raw 落盘 + E14 语义 + pool_csv 路径 + refusal 归因）
- [x] review 审计强度补齐（6 项）：
  - arm purity prompt_hash 规则核对
  - _check_manifest 四缺项补齐（chat_template_hash、arm_purity、split_hash 搜索、expected_keys、manifest_fields_complete）
  - protocol_ref 存在性校验
  - 删除 _verify_chain_fallback，只用 A 的 StepWriter.verify_chain + canonical_json
  - E15 向量工件审计
  - review --pack 增 judge_raw→聚合分重算比对
  - REVIEW_VERSION c1.0→c2.0
- [x] coherence eval prompt 行号追踪（blind.py prompt_source 参数）
  - coherence: third_party/persona_vectors/eval/prompts.py:3-21
  - trait eval template: third_party/persona_vectors/data_generation/prompts.py:32-52

### 已解除
- [x] C3.2 表达检正路径回补（DONE）：
  - 120 样本 × 2 prompt（trait + coherence）= 240 次 DeepSeek API 调用，0 refusal
  - 经 guard 包装执行（HeavyLock nowait acquire + release）
  - deblind 验证方向性：steered_neg -11.95 vs baseline，pos_vs_neg +9.75（方向正确）
  - coherence 维持：所有条件 ≥84.62（向量干预无语言破坏）
  - 产出：exprcheck_scores.jsonl / exprcheck_deblinded.jsonl / exprcheck_report.json / judge_raw/
  - prompt_source 追踪：trait=eval.json:eval_prompt, coherence=prompts.py:3-21
  - 标注：exploratory / rig-validation / citable=false

## 批2③: 8 回填 run 全量评分复评 — ALL PASS
- [x] 4 main runs: vanilla/prompt_persona/residual_vector/random_direction (各 28 steps)
- [x] 4 t0 runs: 对应 4 臂 (各 14 steps)
- [x] 全部 chain_ok=True, error_codes=[], score_mismatches=0
- [x] arm_purity: manifest 侧 + prompt_hash 侧双重验证 PASS
- [x] protocol_ref: V1.0+V1.1 双指针 PASS, manifest_fields_complete=True
- [x] P4 activation: vector/random 臂 NPZ↔summary 集合相等 PASS
- [x] guard wrapped (HeavyLock nowait)
- 无 A 侧 bug 发现

## 批3: w1-full 终包 — DONE（待 G5 闭合）
- [x] C4.1 w1-full 终包构建: 183 文件
  - 4 main + 4 t0 runs 全链入包 (steps/manifest/config.yaml/env.lock/activations)
  - 8 scores + 8 review reports 入包
  - 表达检产出入包 (exprcheck_pool/key/scores/deblinded/report/judge_raw)
  - 3 figures 入包 (mini_loop.png 已用批2数据重生成)
  - split + .sha256 入包
  - 5 protocol docs (V1.0 主文 + V1.1 补丁 + ABC 三包) + sha256
  - patches (3) + vectors (4) 入包
  - MINILOOP-RUNSET.json 更新为批2 runs (批1 降级记 superseded)
  - §6 P1: env.lock 真实 uv pip freeze (两 venv)
  - §6 P2: t0 scores 全部入包 (4 t0 runs × scores.jsonl + summary.json)
  - §6 P3: 协议文档 5 份 + pack_manifest.protocol_refs 含 sha256
  - rescore 自含捆绑: generate_rescore 集成至 build_pack, 4 文件 (checkers/registry/rescore/__init__)
  - README + pack_manifest.json 全部纳入 manifest sha 覆盖
  - __pycache__ 已清除
- [x] 三重自验:
  - rescore 端到端: 8 runs SHA256 PASS + chain PASS + 0 mismatches
  - review_pack: 183 files, 0 missing, 0 sha_mismatch, pass=True
  - stage2 吸收: 66/66 stage2 文件完全被 w1-full 覆盖

## Stage2 首包裁定: 豁免（被 w1-full 完全吸收）
- stage2 preset 定义的 66 文件全部包含在 w1-full 的 183 文件中
- 差集 = 0，无需单独出包
- C2.5 验收标准（合成数据 clean pass + 篡改检测 + 缺失文件检测）已在 w1-full 的 review_pack 中覆盖

## 全程验收条件
- [x] runs/ 零写入：**更正**——112d65f 覆写了 runs/MINILOOP-RUNSET.json（记 DEVIATIONS），此后不再写入；批3 更新 RUNSET 为批2 runs
- [x] key 零泄露：rg -i "sk-" 无真值命中
- [x] 每 WBS 一 commit：含本次
- [x] DEVIATIONS 如实：5 条偏差记录

## 阻塞项
- ~~A 的 runs/ 目录为空~~ → 已解决
- ~~B 的 exprcheck 素材未到位~~ → DONE
- ~~C4.1 终包可立即执行~~ → w1-full 出包 DONE
- ~~C3.2 表达检正路径需 OPENAI_API_KEY~~ → DONE

## G5 闭合验收 — PASS
- CLOSURE-RESULT.md 已写入 repro_packs/w1-full/（独立窗口执行，信息隔离）
- 三项标准全 PASS：rescore 168 步零偏差 + 183 文件 SHA256 + 零缺口
- 含手动 trace checker 逻辑深度抽样（3 样本，排除脚本篡改）
- commit 98fa342

## REG 阶段回归收口 — ALL PASS
- [x] stage1: 43 passed in 2.05s（逻辑层）
- [x] stage2: 33 passed in 3187.39s（真模型 3B MPS + 260 DeepSeek API，guard wrapped）
  - test_a_resource_guard (F14.7) PASS
- [x] stage3: 7 passed in 2.81s（run 级完整性）
- [x] stage4: 3 passed in 0.00s（judge 一致性）
- 总计: 86 passed, 0 failed

## 批3 DONE + REG 收口 DONE
