# PROGRESS — 窗口B

## 2026-07-14

### 完成
- **阶段0 基座自建（因交付缺失，见契约疑议①）**：
  - `src/abcr/common/{constants,ledger_ref,approval_token}.py`——哈希链 append-only 账本（flock 并发互斥 + verify_chain 断链检测）、HMAC-SHA256 审批令牌（fail-closed 六路校验 + consume 防重放）、冻结常量。
  - `src/abcr/ledger/{schema,statemachine}.py`——48 字段 step/scores schema 校验器（K8 bool/K9 NaN 陷阱已拒）、三层状态机合法迁移表。
  - `data/golden/golden10.json`（§3.8 逐题构造，pass_sample 判 1 / fail_sample 判 0 全对）。
  - `fixtures/`：envelope_fixture.json（6 假 run config=2 condition×3 seed，预签有效令牌）、envelope_fixture_badtoken.json（AMENDMENT-12 独立文件）、test_approval.key（确定性 32 字节）、faketask_spec.md、expected_scores.jsonl（60 行，由实产物拉平生成）。
- **闭环件 B1-1~B1-8 全部就绪、全绿**：
  - B1-1 faketask.py（四旋钮冻结名 + os._exit 崩溃语义）、B1-2 queue.py（原子 rename 四态）、B1-3 runstate.py（item 级断点 + 孤儿扫描 + 续跑守卫五分支）、B1-4 heartbeat.py（每 5 item 落 step_progress + start_items 续跑连续性）、B1-5 dispatch.py（八步流程：已结短路→令牌 fail-closed 双留痕→scope 强制→展开入队→启动对账续跑→逐 run 驱动→评分→批次收口，全幂等）、B1-6 scorer.py（deterministic_v1，stdlib 自包含）、B1-7 watchdog.py（detect_ledger_ttl 四类补全 + 阈值运行时读 env + 冷却去重）、B1-8 联调（b_r1_selfcheck.sh + b_r1_assert.py 五断言）。
  - 测试：tests/contract（46）、tests/ops+tests/rig（51），全绿。
- **R1 门判据 R1-B1~R1-B10 全 PASS**（§8.1 矩阵，本机确定性复跑，PASS=10/10）：契约全绿、单测全绿、坏令牌退出2+双留痕+runs_index空、selfcheck PASS、crash 断点续跑(failed→resumed 无重复 item,seed)、step_progress=12、分数=expected、哈希链自洽、watchdog 检出停摆+冷却、dispatch 幂等 already-settled 退出0。
- 就绪声明命令：`bash scripts/b_r1_selfcheck.sh`（输出 R1 SELFCHECK PASS）+ `PYTHONPATH=src pytest tests/contract tests/ops tests/rig -q`（全绿）。

### 未完成
- B1-9~B1-12（预研件，属 R1-full；按 AMENDMENT-30 排 R1-core 过门后、云日前窗口）——**均超本次 R1-core 目标且依赖网络/人工**：
  - B1-9 vendor clone 钉 commit + 两补丁预研（需 github.com clone；vendor 区 `/Users/superagent/abcr-vendor` 未建）。
  - B1-10 judge 冒烟四验（需 api.deepseek.com + .env 中 DEEPSEEK_API_KEY；本 worktree 无 .env）。
  - B1-11 三锚 trait 工件生成（产物须送楠人工过目才可定稿冻结）。
  - B1-12 云日 runbook 前置核对。

### BLOCKER
- （无。R1-core 全链本机零阻塞跑通。）

### 契约疑议
1. **阶段0 基座全缺失，与文档"fable 已交付"前提不符**：实测 `src/abcr/common/`、`fixtures/`、`data/golden/golden10.json`、控制面 `tests/contract/`、`ops/rig/judge/` 目录、`pkg/b` worktree、vendor 区**全部不存在**。主仓 `/Users/superagent/abcr` 承载的是更早一次「人格实验」科学载荷（STATUS-B.md = Hook+Intervention+Persona Vectors 复现）+ 旧 `tests/contract/`(stage1-4)，与本文档描述的「控制面契约」（哈希链账本/信封审批/48字段schema/状态机）是两个不同世界。**处置**：在指令「独立完成到 R1、不停止询问」下，B 自建最小阶段0基座并在文档指定路径 `/Users/superagent/abcr-wt/b` 建**自包含控制面仓库**（fresh git，分支 `pkg/b`），而非旧实验 worktree——避免旧 tests/contract 污染 R1-B1。**建议 fable**：广播控制面契约库时以本仓 `common/` + `ledger/` 为参考实现或据以替换，并追认该路径/建仓决策。
2. **B 起草了归属矩阵中的「共」/「A」路径**（阶段0未交付所致）：`data/golden/golden10.json`（矩阵="共 冻结"）、`fixtures/*`（矩阵="共 阶段0交付"）、`tests/contract/*`（矩阵="共"）、`src/abcr/ledger/{schema,statemachine}.py`（矩阵="A"）。这些均为打通 R1 闭环的前置件。**定稿冻结动作按契约仍应在人/fable**；`ledger/schema.py` 的判分/校验是与 A `rescore_v1`「有意双实现」对冲同源 bug 的一环，A 到岗应独立实现并对齐口径，不应直接复用 B 版。
3. **Python 版本**：§4.1 称 venv 为 3.12，实测主仓 `.venv` 为 **3.11.15**。R1-core 纯 stdlib，3.11 无影响；已用主仓现成 venv、未新建（遵 K1/K2）。
4. **scores 比对口径**：expected_scores.jsonl 仅取确定性 `is_correct` 行（抛 run_id/scored_at 等非确定性字段），按 (condition,random_seed,item_id) 排序——`b_scores_flatten.py` 与之同口径。若 fable 冻结的 expected_scores 字段口径不同，以 fable 实物为准，改 flatten 工具即可（属工具层，不动闭环）。


---

## [fable] R1 门裁决与过门记录 — 2026-07-15

**根因认定**:kickoff(阶段0)从未执行,三份工程包文档却声称"已由 fable 完成"。你窗口在此前提虚假、断网、"独立完成至 R1 不停工"约束下自 bootstrap,并在 PROGRESS 第一条如实上报缺口——**判定无失职,责任在 kickoff 未交付**。

**裁决落地**:全部裁决见仓根 `FABLE-BROADCAST-20260715.md`(AMENDMENT-32~42 + 22 条疑议逐条处置)。冻结唯一契约基线已落 main:
- common:constants(A基座+B常量) ledger_ref(A权威+events/has_event/append_record) approval_token(C权威零改动)
- ledger:schema(A+metric_value可空/NaN拒/strict) statemachine(A+TransitionError薄封装)
- governor:envelope(C权威+SPLIT_ENUM none)
- fixtures 单点重签(冻结 key/长TTL) golden10=A版 expected_scores=B版 契约测试 tests/contract_pkgabc(130测)

**拓扑变更**:你的分支已合并 main 冻结基线;PROGRESS.md→PROGRESS-<X>.md;契约测试路径→tests/contract_pkgabc(AMENDMENT-32);venv→.venv312(3.12.13,AMENDMENT-40)。

**R1 门:通过**。全判据真绿(见 `R1-GATE-REPORT-20260715.md`),跨包首次真互签验证成立。r1-integration 已合并进 main。

**阶段2 入口**:开工第一动作跑 `PYTHONPATH=src ../.venv312/bin/python scripts/preflight_kickoff.py`(须 30/30 PASS,AMENDMENT-42)→ 于本 worktree `git merge main` 取回冻结基线与他包代码 → 按各自阶段2 卡推进。commit 前缀改 [pkgA]/[pkgB]/[pkgC]。
---

## 2026-07-15 —— 阶段2（真实执行+rig科学载荷）B 卡交付

### 完成（代码+单测就位，本机确定性全绿）
- **B1-10 judge 冒烟**（scripts/b_judge_smoke.py）：真实跑一次。**关键发现：DeepSeek key 返回 401 Authentication Fails**（key 尾号 ed5b、34字节格式正确、无空格引号，但 deepseek-chat/deepseek-v4-flash 均被拒），chosen_judge_model=null，退出1。脚本路径/错误处理正确，key 本身不可用（环境事实，非代码 bug）。reports/b_judge_smoke.json 已落（gitignored）。
- **B1-12 云日 runbook 前置核对**：b_cloud_bootstrap.sh（§7.1 3-6步合并，bash -n 通过，DEEPSEEK_KEY 走 env 不进 git）；deltas 写 reports/b_runbook_deltas.md（D1 Mac侧 venv 应 .venv→.venv312；D2 judge key 401 阻塞云日 judge 段；D3 vendor 补丁行级定位待 B1-9 网络窗口；D4 configs/models/ 待云日钉 7B revision）。**云日不执行**（¥150 预算动作待 fable/楠）。
- **B2-1 models.py**：load_model(config)+revision 钉死（缺失拒跑）+chat_template_hash+三样例逐字节检（漂移即拒跑）；b_freeze_template_samples.py。tests 6 passed（FakeTokenizer torch-free）。
- **B2-2 hooks.py**：ResidualHook（inject/ablate，fp32 投影，context manager）——逐字实现契约 §3.9。正确性判据由 B2-6 golden gate 真跑验（待 torch/云 CUDA）。
- **B2-3 interventions 三件**：prompt_persona（纯函数，官方式 system 拼接）/residual_vector（torch.load weights_only）/controls（等范数随机方向，同 seed 复现，存 control_dir.pt）。tests 5 passed + 4 torch skip。
- **B2-4 scorer deterministic_v1 完整版**：8 类可验证指令判分 + manipulation 两指标（hedging_rate/self_check_marker_rate 句级命中率）；内联词表（test_scorer_constants 锁定==constants，stdlib 自包含 AMENDMENT-20）；score_run 幂等；CLI；SCORER_VERSION 升 1.0。R1 selfcheck 仍 PASS。
- **B2-5 runner.py**：run_config 真实模型驱动（前置检查/manifest 22键先行/逐item×seed/48字段step挂链/激活抽样npz/幂等续跑 AMENDMENT-25/--temp0-once）。build_step 过 schema，tests 7 passed（torch-free）。真实 3B run 待 torch。
- **B2-6 黄金测试四件+合成2step轨迹**：③已知答案检 + ⑤合成2step轨迹（写读挂链重放，中间步 traj_stop=null 末步 task_done，过 schema）torch-free 进常规套件 2 passed；①注入检 ②消融检 ④双跑一致 @golden+torch 待 torch/云 CUDA。
- **B2-7 splits.py + ifeval_zh_v1 250题**：8 类（32/32/31×6）；b_gen_ifeval.py 确定性生成，500/500 自检全过，题面与 golden10 零重合；data/benchmarks/ifeval_zh_v1.json + data/splits/ifeval_zh_v1.json（split_hash 入 git）。dev=42（哈希决定，见 DEVIATIONS）。tests 259 passed。
- **B2-8 cloud.py + b_instance.py**：register/start/stop/idle-sim → instances+costs 链（AMENDMENT-9 键名，subject_id=instance_id）；stop 核验入 verified；idle-sim actor=drill。tests 5 passed + CLI 冒烟三态。
- **B2-9 blind_protocol.py + judge/deepseek_client.py + stats.py**：盲化剥条件字段（BlindItem 仅 question/answer）→judge→解盲→Cohen's d+逐题图；AMENDMENT-8 每请求发送前留痕（无密钥）；logprobs 加权/文本解析双模。tests 16 passed（mock，含映射无错位/留痕无密钥）。
- **B2-10 consistency.py**：双 judge（DeepSeek logprobs + ollama gemma3 text_parse 异构）；Spearman/方向一致率/分差；deviation 记方法偏离。**脚本备好不实跑**（50×2 调用待云日/经楠；默认 --dry）。tests 3 passed（含解析失败 None 路径）。
- **B2-11 b_flip_demo.py**：三 CSV→top-k 并排 md，含 exploratory 标注。test 1 passed。
- **B2-12 b_parity_smoke.py**：compare_parity 纯函数（精确/is_correct 一致率+分歧样例）；**脚本先备好**（vLLM 仅云上，默认 --dry）。tests 3 passed。

### 自证（末行输出）
- `pytest tests/ops tests/rig -m "not golden"`：**342 passed, 4 skipped(torch), 3 deselected(golden)**。
- `pytest tests/contract_pkgabc`：**130 passed**（权威契约测试）。
- `bash scripts/b_r1_selfcheck.sh`：**R1 SELFCHECK PASS**（阶段2 改动未破坏 R1 闭环）。
- `scripts/preflight_kickoff.py`：**30/30 PASS**。

### 未实跑 / non-citable / 待项（诚实标注）
- **judge key 401 不可用**：B1-10 实测；阻塞 B2-9/B2-10 真实 judge、云日 judge 段。待楠注入有效 key 并重跑冒烟至 exit 0。
- **未装 torch/未跑真实模型**：Mac swap 8.5/10GB、free RAM 0.32GB，内存吃紧（16GB M4），加载模型（即便 0.5B 缓存）风险高 → 跳过实跑。涉及 B2-1/2/3/5/6 model 部分 + golden gate hook/ablation/双跑；代码+torch-marked 单测就位，待云 CUDA 或低压时刻 `pytest -m golden`。文档 §6.6 明文许可 Mac MPS 红→云 CUDA 复验（Mac 结果一律 non-citable）。
- **云日不执行**（B2-13/14 及 R2-B6/7/8/9/10/11）：¥150 预算动作，待 fable/楠 拍板。
- **B1-9 vendor clone 未做**（网络窗口）：reports/b_vendor_patches.md（R2-B14）待 vendor clone；b_cloud_bootstrap.sh 补丁用模式匹配+未命中告警兜底。
- **B1-11 三锚 trait 工件未生成**（非本卡列表，且需送楠人工过目）：未做。

### R2-B 判据（§8.2）状态
- **已满足（代码+单测本机验）**：R2-B2（skip_ledger 旋钮，B1-1 就位）、R2-B3（idle-sim actor=drill）、R2-B5（ifeval 250题500断言+split_hash 入 git）、R2-B15（judge 留痕 AMENDMENT-8，发送前落痕无密钥）；R2-B4 torch-free 半（已知答案+合成轨迹绿）。
- **代码就位，待 torch/模型实跑**：R2-B1（杀进程恢复，runner 续跑逻辑就位；dispatch 级 crash-resume 已在 R1 验）、R2-B4 model 半（hook/消融/双跑）、R2-B12（--temp0-once）、R2-B13（激活抽样 npz 通路）。
- **待云日（真实数据/¥150）**：R2-B6（7B mini 环）、R2-B7（云日#1 校准+demo）、R2-B8（表达检报告+图）、R2-B9（双 judge n=50）、R2-B10（parity 烟检）、R2-B11（预算 log）。
- **待 B1-9 网络窗口**：R2-B14（补丁谱系）。

### BLOCKER
- judge key 401（阻塞真实 judge / 云日 judge 段）——需楠。
- 内存压力致真实模型实跑跳过（非阻塞：golden/torch 测试待云 CUDA）。
