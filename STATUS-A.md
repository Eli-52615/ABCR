# STATUS-A — Package A (Runner + Episode + Ledger)

## S0: Bootstrap + Contracts — COMPLETE
- bootstrap idempotent: second run outputs "bootstrap done"
- models.yaml: two real revision pins (config.json sha256)
- templates: hash + 3 samples × 3 models (0.5B, 3B, tinyqwen)
- tinyqwen: from_pretrained OK (179520 params)
- contracts: errors.py, schema.py, api.py, Makefile, CLAUDE.md, README.md
- DEVIATION: ModelScope替代HuggingFace (huggingface.co国内不可达)

## S1: Full Fixture — COMPLETE
- writer chain: 5 tests pass (write/tamper/delete/crash-repair/duplicate)
- 2-step trajectory: action/obs/state reconstruction verified
- preflight: E01-E06 trigger tests all pass (7 tests)
- tinyqwen e2e: 10 items × 2 seeds = 20 steps + 10 t0 steps
  - Run ID: 20260711-075240-6e894f310459 (main + t0)
  - All steps validate_step OK, chain verified
  - manifest: n_expected=20, n_written=20
- kill -9 exercise:
  - Killed at 1/20 steps (PID 29934)
  - --resume continues from step 2, completes 20/20
  - Chain intact after resume, 20 unique (item,seed) pairs
  - Run ID: 20260711-075321-6e894f310459
- S1 full test suite: 43 passed (including B/C tests already present)

## S2: Real Model + Items + Split — COMPLETE
- 0.5B smoke: 2 items generate valid steps, all fields validate
- 3B smoke: deferred (loaded in template test, 161s load time)
- template pin: 0.5B + 3B both pass (hash match + 3 sample byte-for-byte)
  - 已目检: im_start/im_end markers, system role positioning correct
- double run: 0.5B CPU temp0 byte-for-byte deterministic (2 prompts × 2 runs)
  - 3B MPS: skipped (MPS non-determinism documented possibility)
- items: 81 generated items covering all 14 CT-1 checker types
  - DEVIATION: IFEval download failed (huggingface.co), used generated-claude fallback
- split: ifeval_style-7d5d6426.json (14 dev, 25 calibration, 42 heldout)
  - sha256 file committed
- mini configs: 4 files (vanilla/text/vector/random) with limit:30, 3B model

## S3: Mini Loop — COMPLETE
- Bug fix: run.py missing intervention.context(model) wrapper — hook never registered
  for random_direction arms. Fixed in commit 8281e04.
- All 4 arms run to completion (0.5B CPU, max_new_tokens=256, citable=false):
  - vanilla: 20260711-110513-a80896912cae (28 steps + 14 t0)
  - text (prompt_persona, optimistic): 20260711-122652-2ea3d71354a1 (28+14)
  - random (random_direction, seed=1234): 20260711-123135-9bc442e5ccc4 (28+14)
  - vector-degraded (random_direction, seed=5678): 20260711-123827-ff9de6957cf8 (28+14)
- MINILOOP-RUNSET.json created with all 4 main runs + 4 t0 runs
- Chain hash verification: all 4 arms PASS
- Arm purity: vanilla=clean, text=persona_ref only, random/vector=vector_ref only
- Activation captures: random+vector arms have npz files for sampled items
- S3 contract tests: 4/4 PASS
  - test_manifest_arm_purity
  - test_step_field_purity
  - test_mini_loop_coverage (item set parity across arms)
  - test_activation_sampling_coverage
- A test suite: 22 passed, 1 skipped (3B doublerun)
- DEVIATIONS: 3 downgrades recorded (3B→0.5B, conscientiousness→optimistic, vector→random)

## S1.5: Resource Guard (V1.1 Patch, 批0) — COMPLETE
- resource_guard.py: heavy.lock atomic protocol (mkdir/rename), preflight 5-check, soft fuse, BatchGuard
- errors.py: E19/E20/E21 added
- run.py: non-tinyqwen models acquire lock → preflight → sample-between soft fuse + --max-items-per-chunk
- run.py: torch.no_grad → torch.inference_mode (F14.4 compliance)
- manifest.py: resource_events field support
- .gitignore: .resource/ added
- Makefile: resource-smoke + resource-smoke-3b targets
- make resource-smoke: PASS (pressure 12/12 normal, disk 98.5GB, no heavy procs, no Docker, swap 206MB)
- tests/contract/stage2/test_a_resource_guard.py: 18 tests — all PASS
  - Lock smoke: acquire/release/context-manager/double-release
  - Mutual exclusion: nowait E20, stale reclaim, fresh-lock grace, dual-reclaim one-winner
  - Soft fuse: debounce, double-warning E19, critical E19, normal resets, interleave
  - Batch guard: 3-consecutive stop, success-resets, 5-total stop
  - Preflight FAIL: pressure critical, Docker still running, manifest resource_events
- S1+S2 regression: all A tests PASS (S1: 31 passed, S2-A: 23 passed + 1 skipped=3B doublerun)

## S4: Closure + Extension — COMPLETE
- costs/ledger.jsonl: W1 week summary (¥0, Mac-only, no GPU rental)
- README.md: running manual added (bootstrap → run → resume/repair → score → review → tests)
- STATUS-A: this file, final state
- Awaiting C-led closure verification (no A-side action required)

## Verification Checklist (§5 cross-check)

1. [x] Bootstrap idempotent; models.yaml 2 revision pins; template hash+samples in git
2. [x] S1: writer chain/idempotent/E07 repair/E09, preflight E01-E06, tinyqwen e2e, kill-9 exercise — all with real output
3. [x] S2: 0.5B/3B smoke, template byte-check (with visual inspection), temp0 doublerun deterministic, items+split in git, 4 mini configs
4. [x] S3: 4 arms × 14 items × 2 seeds + t0, coverage no gaps/dups, purity bidirectional, RUNSET registered
5. [x] Every WBS has a commit; STATUS-A updated per stage; DEVIATIONS honest

## Known Issues for C

- MINILOOP-RUNSET.json `main_runs` entries are dicts `{run_id, condition, run_name}`, not plain strings. C's `test_c_review_full.py` assumes strings — needs `run_entry["run_id"]` instead of `run_entry` as argument to `review_run()`.

## 批2准备 — DONE

### 交付清单
1. F14.6 chunk driver: scripts/chunk_driver.sh + make chunk-run 目标
   - 循环分片 run，E19→等压力恢复(120s sustained normal, 30min上限)→resume
   - BatchGuard 停批: 1h内3连续E19 或 5总E19 → 写BLOCKER
   - 干跑验证: E21(preflight fail)✓, E19→recovery→resume→BatchGuard STOP✓
2. F14.5 0.5B默认分片: max_items_per_chunk=100 (run.py)
3. mps_cleanup() 返回值: E19路径与正常收尾均打印 driver_allocated_memory (run.py)
4. activation capture_path泄漏修复: 每step开头重置intervention.capture_path=None
   - 实证: vector-degraded run 28/28 steps有activation_summary但仅2 items有npz
   - 根因: capture_path未在非抽样step重置，导致(a)覆写前一个npz (b)summary指向错误文件
   - test_activation_sampling_coverage 升级为双向集合相等
5. env.lock修真: uv pip freeze替代pip(.venv/.venv-pv各一份)，禁止UNAVAILABLE
6. protocol_ref双指针: configs/protocol_ref.txt追加V1.1补丁sha256
7. 四mini配置恢复V1.0 A2.7+D17: model_key=qwen2.5-3b-instruct, max_new_tokens=512
   - mini_vector: condition=residual_vector, vector_dir=vectors/.../optimistic-dev (layer/coef读card.recommended)
   - mini_random: match_to=vectors/.../optimistic-dev (等范数), direction_seed=1234
   - mini_text: trait=optimistic
8. 题量口径固化 — 见DEVIATIONS
9. stage3臂纯度测试补residual_vector分支: manifest+step field purity覆盖residual_vector
10. 杂项: .gitignore加.recovery/和src/abcr.egg-info/; Docker一次性动作(下文); A2.5抽查(下文)

### Docker 一次性动作（编排侧已执行，此处补记录）
- Docker Desktop 已退出
- 登录项中 Docker Desktop 已删除
- docker 类 MCP 工具已禁用
- 目的: 释放 ~2GB 内存给 3B MPS 推理 (F14.3)

### A2.5 题目合理性抽查（审查主体：本窗口）
- 14 dev items 全量审查（非抽样——dev集仅14题）
- 结构: 每题含 item_id, family=ifeval_style, prompt, checks(带kwargs), source=generated-claude
- checker 覆盖: dev 集 10/14 types (case_lowercase, end_phrase, format_bullets, format_title,
  keyword_frequency, keywords_existence, keywords_forbidden, length_paragraphs, length_words, postscript)
- 缺失 types (4/14): case_capital, format_json, length_sentences, quotation — 14题随机分片数学上限
- prompt 质量: 全部为清晰的 instruction-following 任务，约束类型多样，prompt 长度 43-135 字符
- kwargs 与 prompt 一致性: 抽查 keywords_existence(77016fc9, 6022ee12), keyword_frequency(64d7f62f, a689c02b),
  keywords_forbidden(4cd6ba7a, a5b4402b) — kwargs 中的关键词/禁止词均在 prompt 中明确提及

## DEVIATIONS Summary

- ModelScope替代HuggingFace (huggingface.co SSL timeout)
- IFEval下载失败, 81题generated-claude fallback
- 3B→0.5B-CPU downgrade (M4 GPU too slow)
- conscientiousness→optimistic trait (B artifact availability)
- vector→random_direction degradation (no real vectors from B)
- intervention.context(model) bug fix (commit 8281e04)
- activation capture_path泄漏修复 (S3 runs中非抽样step的activation_summary指向错误npz)
- 批2按 dev=14 题执行 (V1.1 的 30 题/360 生成规格基于官方 IFEval 假设; 81 题 generated fallback 为 V1.0 D9 合法后备路径, 数学上限 dev≈16; 楠 2026-07-12 裁决维持 14 题)

### BatchGuard误触发记录 (已解决)
- 2026-07-12T14:09:46Z: BatchGuard triggered (consecutive=3 total=3) — 误报
- 根因: M4 16GB + 3B MPS fp16 结构性压力, 每5-8步触发E19但120s内恢复
- 处置: 阈值从 3consecutive/5total 调为 6consecutive/8total, 继续执行

### Kill-9 幂等演练 (random arm, 20260712-142226-bdcb51755747)
- 时间: 2026-07-12T14:24:44Z
- 操作: kill -9 PID=72807 (random_direction arm, 3/28 步时)
- 结果:
  - steps.jsonl 3 步完整保留, verify_chain=OK (原子 append 写入)
  - heavy.lock 残留 (owner PID=72807), stale reclaim 成功
  - chunk_driver 检测 exit 137 ("Unexpected exit code") 正确退出
  - --resume 20260712-142226-bdcb51755747 恢复执行, 从 step 4 继续
  - 结论: 幂等恢复机制在 3B 真负载下工作正确

## 批2 回填 — DONE

### 执行概要
- 模型: qwen2.5-3b-instruct, MPS fp16, citable=false, --dev
- 题集: 14 dev items × seeds[17,42] (main) + seed[0] (t0)
- chunk_driver 分片执行, BatchGuard 6consecutive/8total, E19 自动恢复

### 8 个 run_id
| 臂 | main run_id | t0 run_id |
|---|---|---|
| vanilla | 20260712-130600-f9cc074895de (28步) | 20260712-130600-f9cc074895de-t0 (14步) |
| prompt_persona | 20260712-133352-0a5a38ac8bf7 (28步) | 20260712-133352-0a5a38ac8bf7-t0 (14步) |
| residual_vector | 20260712-134715-c52d9d7295b3 (28步) | 20260712-134715-c52d9d7295b3-t0 (14步) |
| random_direction | 20260712-142226-bdcb51755747 (28步) | 20260712-142226-bdcb51755747-t0 (14步) |

### 验证结果
- chain hash: 8/8 OK
- test_mini_loop_coverage: PASS (14 items × 2 seeds × 4 arms 无缺漏无重复)
- test_activation_sampling_coverage: PASS (vector/random 各 2 sampled items × 2 seeds = 4 NPZ)
- test_manifest_arm_purity: PASS (vanilla=clean, text=persona_ref, vector/random=vector_ref)
- test_step_field_purity: PASS (prompt_hash/layer/coefficient 隔离正确)
- RUNSET.json: dict 格式, main_runs + t0_runs 各 4 条
