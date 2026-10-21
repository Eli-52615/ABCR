# ABCR W1（含云日）系统性对抗终验方案 V2.0

> 版本：V2.0-r7 再审批候选版（封闭 scope、original-series、技术失效证据类型/哈希构造、负样本计算器与最新远端增量复核）
> 日期：2026-07-15（America/Los_Angeles）
> 状态：**Gate A 增量静审后的再审批候选版；本次正文变化使旧 APPROVE_PLAN 失效，尚未进入正式分支测试**
> 作用域：ABCR W1 Mac 工程阶段、云日 #1/#2、跨阶段证据链，以及它们对《ABCR 实验方案 V1.3》的满足程度
> 版本关系：本文取代《ABCR-W1测试方案-V1.0》作为后续终验执行依据；不修改、也不重新解释已冻结的 W1 V1.0/V1.1 协议正文
> 原则：测试失败只能修实现、修数据或降结论；禁止删测试、放宽断言、补写解释后宣称 PASS

---

## 0. 审批结论摘要

### 0.1 本方案当前判断

在正式分支测试尚未执行前，本轮已完成对权威文档、Mac mini 真实仓、完整受控源码树、既有 run/score/review/pack、未跟踪云回传包的**只读静态审查**。以下是 Gate A 预审判断，不冒充 Gate B 动态回归：

1. **真实工程仓持续可读，但既有 Mac PASS 已被静态反例击穿。** 早期逐行审查锚定 `e02d4c3ccb777d850bb9e6aa687e89ff75648ad8`；2026-07-15 再次 SSH 只读复核时，canonical 仓 `/Users/superagent/abcr` 已前进到 `main@edbd351fcbb0cce4918225d21da7cb2d871dd299`、tree `198c23aadc736780654bf8e638c5026e57a38631`。相对 `9d579e5960f48cab4816e825be8a72461dda43b4` 仅新增 `阶段2-R2就绪报告-20260715.md` 一文件41行，生产/测试代码未变；该报告内声称的 `726` 通过、`4 skip` 没有本终验的获批 plan/seed、exact collection、原始日志与 seal，不能冒充 Gate B PASS。报告所含 key/401 片段只作为 secret-scan 对象，普通证据与本文均不得复述其值；云/API预算仍未获 `APPROVE_COST`。此前静审确认的空batch、令牌重放/并发双消费、队列提前done、resume身份不闭合、云segment遗漏、成本与报告空集假绿等 P0/P1 不因新增报告而关闭。
2. **真实工作树不是“纯 Git 工件”，且当前 tracked dirty。** 最新只读状态仍含4个受跟踪修改：`artifacts/traits/REVIEW-REQUEST.md` 及 conscientiousness/neuroticism/openness 的 `provenance.json`；四文件观察 SHA 与 §19 的上一轮相同。它们不属于当前 HEAD tree，所有权未知，Gate B 必须保留并单独封存，不能清理、夹带或让它们暗改 baseline/candidate。canonical 仓另有未跟踪/ignored 的云回传、`.venv*`、`third_party/persona_vectors`、`tests/fixtures/tinyqwen` 与 bridge checkpoint；其他 worktree 还可能含不在任何 commit tree 的可执行脚本。干净 clone 不含这些依赖，故“从源码可复现”尚未成立。
3. **云归档传输哈希匹配，但内容证据链不闭合。** 本轮取得的 `cloud-results.tar.gz` SHA256 观察值为 `82681b6bda04c81cb6cbbdcd9b0337a333e9b88ed5277c531bd853602cda536a`，与报告一致；归档内实际为27文件：13 CSV、9个仅 Day1 日志、5个 `.pt`。安全解析 zip/pickle metadata 后确认：5文件由3个 optimistic 抽取变体和 conscientiousness/neuroticism 两个 response 文件构成，均为 layer key 14–24、`BFloat16Storage`；其中4文件每层 `(3584,)`，`optimistic_prompt_last_diff.pt` 每层 `(1,3584)`。它们不是 W1 标准全层 float32 三件套。归档没有逐文件 manifest、实际执行源码/commit/patch、模型与 tokenizer 身份、judge 原始响应、card/extraction_meta；Day2 无执行日志，openness 无向量。传输字节匹配不等于实验身份或科学有效；Gate A 的观察值仍须在 Gate B 按 §4.3 证据 schema 重放后才能成为正式 `PASS`。
4. **W1“含云日”目前不能判完成。** 云日交接协议规定 Day1 六项校准任一 FAIL 必须停；云日报告明确记录 monotonic FAIL，却继续 Day2。当前材料未见早于继续动作、可唯一归属该失败的 waiver，也未见独立的 `REVIEW approved`。V2 对未来审批强化 SHA 绑定，但不把新格式追溯强加给历史消息。
5. **Parity 与 projection 均未形成可核验证据。** 实际云运行从 vLLM 改为 transformers-only，却跳过原定跨引擎 parity；归档也没有官方 `eval.cal_projection` 结果。因此不得声称替代路径等价或 Day1 五阶段闭合。
6. **Day2 与表达检未完成且已有结论错标。** 云包只有 conscientiousness/neuroticism 两个 response 向量；openness 没有向量，三个 trait 均缺完整表达池/key/raw、系数扫描和激活抽样。Mac 侧现存 conscientiousness 表达报告实际为 `steered_pos=68.92 < baseline=71.12 > steered_neg=59.17`，不满足冻结顺序 `pos > baseline > neg`；`STATUS-C.md` 仍以 `pos > neg` 写“方向正确”，另有无 baseline 的旧 fallback 报告标 `direction_clear=true`，属于相互冲突的领域结论。
7. **云端关键实现不可复现。** `/tmp/genvec_v5.py`、云端 transformers-only 抽取/steering 脚本、命令历史、环境 lock、逐样本 judge raw 与最终执行 commit 未在归档中；Mac 侧被忽略的 pinned upstream 虽在 `b8e0f044...`，但实际 dirty patch 仅存在嵌套工作树。云代码逐行终验保持 BLOCKED。
8. **当前云产物维持 `evidence_stage=exploratory`、`citable=false`。** 证据阶段、对象命名与 artifact/claim 引用资格是三条独立轴：对象最多只能按证据称 `direction-k`，只有 V1.3 五检全部通过才可命名人格向量。现有产物不得冒充五检完成，也不得据此启动 W2 正式剂量标定。

### 0.2 “零 bug”的可执行定义

软件与实验系统无法用有限测试证明数学意义上的“绝对零缺陷”。本任务采用更严格、可审计的工程定义：

- 零已知 P0/P1/P2 缺陷；
- 零静默降级、零静默缺数、零未经授权的门禁跨越；
- 所有关键失败路径 fail-closed，并产生稳定错误码与完整证据；
- 关键模块所有预设 mutation 均被测试杀死；
- 同一输入从原始数据到报告结论可逐项重算；
- 所有 PASS 均绑定唯一源码树、输入哈希、环境、命令、原始输出和测试日志；
- 无法验证的项目只能是 `BLOCKED/UNVERIFIED`，不能折算为 PASS。

本方案的 repo identity、candidate tree、外部 seal、policy calculator 与一次灾难恢复并非“探索实验的认证装饰”。真实代码已出现空集全绿、历史证据被运行时覆写、付费调用与凭据外泄通道；这些控制直接防止错误合并、重复计费和不可逆证据污染。比例边界也同时冻结：元审计全部使用无计费小 fixture，身份/封存工具各只保留一个权威实现和一次恢复演练；任何 API/GPU 重放仍由独立 Cost Gate 控制，历史科学证据缺失不得迫使为“让合并变绿”而重新烧钱。

---

## 1. 权威层级与冲突裁定

### 1.1 文档角色

| 层级 | 文档 | 本方案中的角色 |
|---|---|---|
| R1 研究语义 | `ABCR-实验方案-V1.3.md` | 当前研究轨唯一有效操作文档；决定什么可以称为证据、direction-k 或命名人格向量 |
| R2 W1 设计 | `ABCR-W1方案-最小纵向闭环-V0.9.md` | 定义 W1 机器的目标、冻结清单、四件交付和 G1–G7 |
| R3 W1 执行契约 | `ABCR-W1执行方案-V1.0.md` | F1–F13、schema、错误码、阶段回归和三包知识边界 |
| R4 增量覆盖 | `ABCR-W1执行方案-V1.1补丁-资源治理门与节奏修订.md` | 与 V1.0 冲突处优先；增加 F14、S1.5、E19–E21、双协议指针 |
| R5 后续人工冻结裁决 | `ABCR-W1指令分派指引-冻结版-20260712.md` | 覆盖剩余工作图中的未决项；批2固定 dev=14、不重试 IFEval、不得降模型档或臂类型 |
| R6 执行证据 | W1 终验报告、云日交接状态、云日执行报告 | 只证明“声称做过什么”；不能反向修改 R1–R5 的门和断言 |
| R7 旧测试提纲 | `ABCR-W1测试方案-V1.0.md` | 风险线索来源；其范围、优先级和判定标准由本文取代 |
| R8 外部实现基线 | [persona_vectors @ b8e0f044](https://github.com/safety-research/persona_vectors/tree/b8e0f044fe2410a6fad579f38324f03f13b4e917) | 只作 differential/实现谱系基线；不覆盖 R1–R5 的 ABCR 研究与执行语义 |

### 1.2 明确裁定

1. W1 V1.0 保持字节级冻结；本文是新的测试协议，不改旧 run 的 `protocol_ref`。
2. 批2验收采用 14 个 dev item 的已批准事实口径，不再按工作图的“重试官方 IFEval”或补丁早期 30 题口径倒推失败；但必须保持 3B、四臂、2 seed、t0 和 citable=false。
3. V1.1 F14 不直接约束云端 CUDA 实例；云端仍必须满足独立的预算、checkpoint、回传、关机和证据门。
4. “表达检记录完成”不等于“命名人格向量通过”。按 V1.3，五检为谱系、表达、词表、孪生、副作用；未全部通过最多只能称 `direction-k`。`exploratory/confirmatory` 是证据阶段而非对象名；citable 又须按具体 artifact/claim 的交付完整性、provenance 与所需人工批准独立判定。
5. 测试发现历史执行跨门，只能记为协议 FAIL；历史 waiver 至少须早于动作、含审批人/时间，并能由原始消息、commit、路径与会话上下文唯一归属具体失败项。V2 起的新 waiver 进一步必须绑定审批对象 SHA、scope 与输入 manifest。事后解释对历史和未来均无效，但不得用 V2 新格式追溯否定一条本可唯一归属的历史原始批准。
6. 历史仓的“无远端、永不 push”继续有效。本轮可在恢复出的本地副本上建 `codex/` 测试分支，但不得给历史仓擅自加远端或 push。

### 1.3 original W1 作用域冲突的显式裁决

以下裁决只把既有权威文本变成可机械执行的 original-scope 合同，不增补科学规则，也不得用后来结果反推：

1. V0.9 的“单 trait 约 2000 条生成”来自 `约5对 prompt × 20题 × 10响应 × 2极`，是容量、时长与费用的**粗量级估算**，不是 expected-set 或逐文件精确行数；不能以实际行数不等于2000单独判协议 FAIL，也不能用2000替代逐阶段 manifest。
2. 逐阶段计数冻结为 `extract(pos)=10/题`、`extract(neg)=10/题`、`Day1 compared-condition eval=10/题/条件`、`Day2 expression/scan=2/题/条件或极性`。V0.9 的“表达至少2”被后续冻结 Day2 runbook 的逐命令 `n=2`具体化为**恰好2**；禁止把抽取的10外推到 Day2，或因看到结果再改2。
3. W1 专用 V0.9 明确把开发运行冻结为 `2–3 seed`，并把 V1.3 的 `≥5 seed`留到 W2 起的正式规格；因此 original W1 不因只有2–3 seed而失败。已由冻结分派确定的 mini 环进一步精确为 `[17,42]`，temp0 sanity 为独立 seed0诊断，不把该诊断计作第三个正式 seed。
4. 抽取过滤在等号边界采用 V1.0 的可执行精确式：`pos_trait >= 50`、`neg_trait < 50`、双侧 `coherence >= 50`。V0.9 表格中的 `>50/<50` 是早期简写；在 `trait_score==50` 时以较晚且给出完整实现式的 V1.0 为准。任何实现把正侧写回 `>50`、把负侧写成 `<=50` 或把 coherence 写成 `>50` 均为 exact-scope FAIL。
5. Day2 的 trait、层、系数或候选 artifact 选择若存在多个合法候选，必须在读取任何 selector-input outcome 前封存候选全集、selector、方向/约束、稳定 tie-breaker 与全并列处理，并在首个 Day2 outcome-bearing 输出前机械封存 realized selection；selector/tie-breaker 属 `PREOUTPUT_FREEZE_WITHIN_ORIGINAL_ALLOWED_DOMAIN`。原协议没有唯一规定且历史也无事前封存时只能 `BLOCKED/UNDERSPECIFIED_AND_NOT_SILENTLY_FILLABLE`，不得看结果后补一个“合理”选择器，也不得仅因缺选择器把已知 original run 静默改称 amended。
6. `INVALIDATED_TECHNICAL` 只允许消费事前注册、对全部 run 对称、与科学值无关的身份/完整性/执行谓词。具体失效判定与 receipt 必须发生在任何人或程序读取 outcome-bearing raw、judge响应、score、聚合、排名、输出长度等 domain proxy **之前**；若必须查看 raw/domain proxy 才能给出理由，该 run 不得技术失效，其有效科学 FAIL/PARTIAL 继续进入 fail-dominant reducer。raw缺失可由事前 expected-set 与文件存在性判断；raw内容“不好看”、阈值失败、拒答率或方向不显著从来不是技术理由。

---

## 2. 威胁模型与审查范围

### 2.1 要防的不是只有崩溃

本方案重点捕获六类“看似正常但结论已坏”的失败：

1. **身份漂移**：源码、模型、tokenizer、模板、trait、split、patch 或环境不是报告所称版本。
2. **条件污染**：人格文本泄入向量臂、hook 未摘除、capture path 复用，或主随机对照并非独立、等范数、可复现。主对照不附加“必须正交”的事后要求；正交化/打乱方向只可作为另行标注的探索诊断。
3. **账本假完整**：重复、漏行、错 join、半行、错误 repair、同实现自证同错同绿。
4. **评分假信号**：judge 空返回被吞、数字 token 不兼容、条件泄盲、原始返回缺失、API 非确定性覆盖正式工件。
5. **门禁失效**：测试或校准 FAIL 后仍继续；DEVIATIONS 被当成 waiver；报告只看均值掩盖全百、全零、拒答或局部崩坏。
6. **操作不可复现**：依赖旧绝对路径、临时脚本、热缓存、人工 shell 状态或未保存命令；换实验者后无法恢复。

### 2.2 覆盖面

纳入：

- git 历史、协议指针、环境和秘密治理；
- Runner、schema、writer、manifest、repair/resume、resource guard；
- prompt/vector/random/ablation intervention、层号、response-only、capture；
- checker、score、review、judge、盲评；
- repro pack、独立 rescore、闭合验收；
- 云日实际改动、数据、模型身份、judge 兼容、向量生成、parity、成本和关机证据；
- W1 对 V1.3 后续 W2/W10 所需日志语义是否真实就绪；
- 实验者从空环境按文档操作时的可达性、可诊断性和中断恢复。

不纳入正式科学假设 H1/H2/S1 的成立性检验；W1 只验“产生证据的机器”。但若 W1/云日报告越权声称 H1/H2/S1 或 citable，本文会把该声明作为缺陷拦截。

---

## 3. 审批、分支、提交与合并流程

### Gate A：测试方案审批（当前）

- 审批包只含本文、变更摘要和同目录 `ABCR-W1测试策略种子-V2.0.json`；不创建源工程测试分支、不运行正式回归、不提交、不合并。
- 审批回执必须明确为 `APPROVE_PLAN`，并同时绑定本文最终 SHA256、policy seed SHA256、测试范围与 `cost_cap_cny=0`；原始人类消息连同本任务的审批人身份、RFC3339 时间和认证会话标识一并封存。未绑定、只表示“已读”或只绑定旧的 pre-append SHA 均不算批准。
- 审批通过后才进入 Gate B。方案正文、policy seed，或本文§19冻结的 baseline HEAD/tree 任一变化，Gate A 自动失效并须基于新baseline重做只读增量审查后重新审批；candidate、测试结果或报告变化只使对应 Gate B 结果/报告/合并审批失效，不使未变化的 Gate A 方案审批失效。四个用户dirty文件字节漂移不自动授权纳入baseline，只会使保护性观察失效并阻断，直至重新封存其所有权/处置。

### Gate B：分支测试与修复

1. Mac Air 只作方案与耐久审计证据协调端，**绝不导入工程源码**。Gate B 默认耐久根冻结为 `ABCR_AUDIT_ROOT=/Users/wangyinan/ABCR-audit-results`（可由新的 Gate A 审批显式替换，禁止静默落到当前 cwd）。启动时先在内存中解析原始 `APPROVE_PLAN` 字节并核对 plan SHA、policy seed SHA、范围与零成本上限；只有四者逐字匹配，才核验 `/Users/wangyinan` 的 realpath/owner/mode/device/inode，以不跟随 symlink 的方式创建或验收 0700 的 `ABCR_AUDIT_ROOT`，再原子创建唯一 0700 `<audit_id>/`。任何写动作前先在内存生成`abcr.bootstrap-intent.v1`，冻结原始receipt字节SHA、获批root/audit_id、预期owner/mode/device约束、拟执行动作和禁止项；目录创建后第一批写入只能是该intent、获批plan、policy seed、原始receipt及其manifest。完成fsync、复读、权限/探针观察后另生成不可改写的`abcr.bootstrap-observation.v1`，分别把SHA写入`bootstrap_intent_manifest_sha256/bootstrap_observation_manifest_sha256`，再生成bootstrap seal，才把PRE-10正式记PASS并由PRE-11复核。PRE-09/10/11 使用固定 bootstrap resolver、`PRE_BOOTSTRAP` phase identity、执行前 evidence-requirement/slot manifest 与执行后 completion manifest；此时 repo/candidate/subject registry/matrix/policy 均为 null，禁止事后回填。Gate B 后不重跑也不生成替代PRE result；只生成exact三条record的`bootstrap_reference_manifest_sha256`，每条机械绑定`assertion_id + PRE result_id + PRE result_record_sha256 + matrix subject/context + frozen policy fields`，顶层再绑定机器审批receipt、intent/observation、registry/matrix。该manifest只能逐字复核已封存PRE结果，不能替换、重演或改写bootstrap observation。任一步失败都删除尚未封存的空 staging（不删除既有目录）并全停。当前已观察到旧路径 `/Users/wangyinan/Documents/ABCR` 不可达，故不得继续把它写成可执行前提。
2. 通过 SSH 在 Mac mini 上只读核验 canonical 仓 `/Users/superagent/abcr`，先生成不可混淆的 `target_repo_id`：主机指纹、realpath、filesystem volume UUID、目录 device/inode、`git rev-parse --git-dir/--git-common-dir/--show-toplevel`、object format、alternates、全部 worktree 与 refs。随后从该本地路径建立无 hardlink/无 alternates 的全新隔离 clone `/private/tmp/abcr-audit-worktrees/<audit_id>/source`，立即删除 clone 的持久 remote；不 push。来源、保管人、传输方式、完整40位 commit、全部 refs 与已知 artifact hash 必须对上；若用 bundle则 `git bundle verify`，canonical 与 clone 都 `git fsck --full`。不得把普通文件快照、同名路径或另一 worktree 冒充目标仓。
3. 从 canonical 仓明确冻结 `refs/heads/main → target_sha`；`baseline_commit` 必须等于该`target_sha`，并与§19获批观察的HEAD/tree逐字相等。HEAD/tree不等即停止、更新Gate A增量静审与方案审批，禁止把另一baseline套入既有CR red→green；四个tracked dirty路径则必须仍在原位置、逐字匹配观察SHA且单独封存，不纳入commit tree。确认target、worktree、index、sparse/submodule状态在案后，只在隔离clone创建唯一`codex/w1-adversarial-audit-<audit_id>`，ref已存在即fail-closed。
4. **认证或源码不可得的分支路径**：判 `MAC_ENGINEERING=BLOCKED`，不创建 branch/candidate，`MERGE_ELIGIBLE=false`；当前已取得材料可继续做 CLOUD 离线审计，但只写独立封存的 `abcr.offline-partial-audit.v1`，不得伪造正式 Gate B result 的 Git/tree/harness 字段，也不得进入正式 exact-set、closure receipt 或 Gate C。该报告只能 `ACK_REPORT`。
5. 先只引入批准方案所要求的独立测试、fixture 和审计工具，且不得改生产路径；用临时 index 冻结 `test_harness_tree`、`test_only_patch_sha256`、`test_suite_manifest_sha256` 与 `expected_assertion_inventory_sha256`。先在clean baseline上做discovery red，再只修生产实现；此时的discovery输出只用于定位，不进最终closure。候选修复稳定后才冻结 `candidate_tree`。policy seed 已为 CR-01–45 逐项冻结 `closure_mode`：只有 `CODE_RED_GREEN` 在同一 harness 的 clean materialization 上要求正式baseline为FAIL、candidate为PASS；`DETECTION_PASS_DOMAIN_NONPASS` 要求 baseline 与 candidate 两版审计器都正确检出同一历史subject的精确FAIL/PARTIAL/INVALID/BLOCKED，meta verdict为PASS但领域状态不改；`EVIDENCE_BLOCKED` 的旧subject在真实原始输入恢复前保持OPEN_BLOCKED，后来代码不能替代。若测试字节变化，相关baseline/detection证据立即失效并重跑；禁止修改测试后只跑green。
6. Gate A 已用 policy seed 冻结全部 root/assertion/check、blocking/cost/track/closure/merge/final-adjudication 推导。Gate B 在 `test_harness_tree` 后重算172项assertion/check inventory并与seed SHA逐字相等；在 `candidate_tree` 冻结后、任何正式证据执行前，封存current global/candidate、每个run/artifact/claim，并派生九个逻辑 expected-slot 定义。每个slot先按冻结谓词解析：唯一实际对象则只登记actual；零匹配才登记一个 `EXPECTED_SUBJECT_SLOT` placeholder；多匹配或actual+placeholder并存为ERROR，因此placeholder实数为0–9而不是固定九条。随后纯函数生成expected assertion×subject×atomic-context matrix及SHA，不得在Gate B决定分句、ID、role、required context或漏subject。再按seed、binary full-index diff与subject registry解析applicability、blocks_w1/merge与context参与性，先生成纯 `evidence_requirement_inventory`，把其SHA作为输入生成`test-policy.json`。每条requirement与slot必须带typed consumer `consumer_type=RESULT|LIVE_REVALIDATION`、稳定`consumer_id`、闭合`evidence_role`和从0连续的`evidence_ordinal`；subject producer则只允许§14.1三种版本化binding contract，不能用路径、文件名或报告文字猜生产者。每一执行阶段都在输出前封存 phase identity、execution envelope 与 expected-evidence-slot manifest；运行中只追加已存在字节、与consumer/role/ordinal/producer精确相等的 evidence-ledger record；结果封存前生成 exact completion manifest。随后在同一最终matrix/policy下重放clean baseline red、candidate green和两版detector；discovery red不得事后换绑matrix。缺/多/重复结果、ordinal不连续、空profile、空`required_evidence`、证据slot/bytes/cardinality/consumer/producer/subject错配或非法attempt均ERROR。每个root是全部适用assertion/check/subject/context的合取。`W1_INCLUSIVE/MERGE_ELIGIBLE`均由版本化计算器导出并封存；candidate、harness、subject registry任一变化分别使对应policy/results/report失效，人工不得覆写。
7. dirty worktree 只用于快速迭代，其结果不进入正式报告。所有正式测试都在 Mac mini 上、由 `candidate_tree` 物化的无 ignored/cache/local-config 依赖的 clean 隔离仓中运行，确保 MPS/资源门测试发生在真实工程机；临时 fixture commit 只服务 commit 语义测试，不指向 canonical 目标分支且结束后销毁。排除项依赖扫描必须为零，candidate tree 在正式套件期间不得漂移。
8. 若发现 P0/P1/P2，先修复、重建 candidate tree，并重跑受影响测试及完整无计费确定性回归；任何 tree 变化都会使旧结果与旧报告失效。改变科学输入、评分语义或需要计费动作时，旧产物按影响标 INVALID/BLOCKED，费用不能自行扩大。
9. Mac mini 的临时证据目录只作 staging；每个 checkpoint 都将**脱敏后**新增证据及 manifest 传回 `$ABCR_AUDIT_ROOT/<audit_id>/`，核对文件集/SHA 后再生成 append-only seal。证据按 `PRE_BOOTSTRAP/GATE_B/POST_COMMIT/POST_MERGE` 四代分别封存 requirement inventory→slot manifest→ledger tip→completion manifest，早期记录永不含后期身份；同一canonical source/input/oracle可被多个兼容slot引用，但同kind+bytes+subject+source的别名重复为ERROR。Gate B 先生成不可再改的 `test-completion-seal`，最终报告绑定 plan/policy seed、`target_repo_id`、`target_ref/target_sha`、`baseline_commit`、`test_harness_tree`、`candidate_tree`、candidate 恢复材料、resolved policy/eligibility calculator、red→green 证据、全部结果及排除清单。人类回执分两种：`ACK_REPORT` 只表示收到；只有符合seed机器schema的原始消息 `APPROVE_COMMIT_MERGE` 同时绑定report/test-completion seal、registry/matrix/harness/policy、candidate/target、one-commit metadata与`MERGE_ELIGIBLE=true`，才授权 Gate C。回执同样封存身份、时间与认证会话。

### Gate C：提交与 fast-forward 合并

- 进入条件：原始 `APPROVE_COMMIT_MERGE` 绑定 report seal、approved `candidate_tree`、`target_ref/target_sha`，且 `MERGE_ELIGIBLE=true`。`ACK_REPORT`、候选工程 FAIL/BLOCKED 或 eligibility=false 均不授权进入。
- 提交计划冻结为**一个**正式 commit：唯一 parent=`baseline_commit=approved target_sha`，tree=`approved candidate_tree`；不夹带额外 commit。author/committer/message 等允许变化的 metadata 在 receipt 中列明，tree 与 parent 不得变化。
- 批准后、创建commit对象前，先生成 `abcr.gate-c-post-work-definition.v1`，为POST_COMMIT/POST_MERGE逐项冻结work item、phase、`consumer_type=RESULT|LIVE_REVALIDATION`、稳定consumer ID、subject、execution mode、required evidence role/ordinal、envelope约束以及“LIVE只复核零重调”的动作定义；其SHA写入`gate_c_post_work_definition_manifest_sha256`。随后才从work-definition纯函数生成`abcr.gate-c-expected-set.v1`：对每条参与merge且`blocks_merge=true`的Gate B终态，`LOCAL_FIXTURE/SEALED_DOMAIN_REPLAY`预生成POST_COMMIT与POST_MERGE各一个result ID；`LIVE_EXTERNAL`预生成两个phase各一个live-revalidation ID。有效N/A不执行post但继续进入applicability-integrity门；本版空authority registry下任何N/A均ERROR。work-definition/expected-set都不得包含尚不存在的runtime bytes；expected-set使用不含自身SHA的稳定result/revalidation identity，完整manifest SHA只进入后续payload，禁止自引用。每条live-revalidation必须补齐`phase_identity_manifest_sha256/evidence_requirement_inventory_sha256/required_evidence`并通过同一consumer exact-set，不得只引用旧result后写“仍有效”。
- 正式 commit 先只建在 Mac mini 的隔离测试分支；验证 parent、commit count、`HEAD^{tree}` 后，在临时 worktree 对该精确 commit 运行完整无计费确定性套件。对既有外部/API/GPU结果只做 `abcr.live-evidence-revalidation.v1`：逐字复核原result、input、APPROVE_COST、cost/global-ledger、evidence-completion与seal，且provider recall/network event必须为零；自然到期不追溯抹除原本合法调用，但原attempt时未授权、已撤销或现被证伪一律FAIL/BLOCKED。POST_COMMIT的local/sealed result集合与LIVE revalidation集合必须分别精确相等且全PASS后才可合并；提交后生成 `commit-seal`，不得覆写 Gate B `test-completion-seal`。
- 上述预合并验证全绿后，先核验 `/Users/superagent` 的 realpath/owner/device/inode；宿主机外置父目录 `/Users/superagent/.abcr-audit-locks` 不存在时只允许以当前 owner、0700、no-symlink 原子创建，存在时必须为同 owner 的真实目录且 group/world 不可写。随后在 `<target_repo_id>.lock` 用原子 `mkdir` 取得独占 audit lock，并以同目录临时文件+fsync+rename 写 owner：audit_id、host、pid+process start、随机 fencing token、target ref/old SHA 和取得时间。此短锁不自动超时/强夺；owner 缺失、损坏或不可证实时直接 BLOCKED，须人工清障并留 receipt。持锁范围覆盖 canonical 工作树/索引/当前 target/old SHA 复核、一次性 fetch、`git merge --ff-only`、精确 commit/tree 与 closure smoke；在 fetch、ref 更新、closure smoke、释放前都须复读 owner 并恒时比较 fencing token。token/目录 inode 任一漂移即停止且不得删除他人锁；只有原 owner token 可在全部 trap 路径释放。canonical 仓用隔离 clone 路径做一次性 fetch（不保存 remote），随后只允许 fast-forward 到已测试的精确 commit；目标漂移、非 fast-forward、脏树、冲突或审批对象变化均停止并回 Gate B，不现场修冲突。
- 更新后核对 canonical `target_repo_id`、target commit/tree、工作树纯净性、seal 与无计费完整性 smoke；fast-forward 后 target tree 必须等于 approved candidate tree，不生成未审批 merge tree。再执行POST_MERGE phase的local/sealed精确result集合与LIVE零重调revalidation集合，缺/多/重复/跨类型替换或任一非PASS均使Gate C失败。不 push。全部成功后另生成覆盖test/commit/merge、四代evidence completion及Gate C exact-set receipts的`closure-seal`；测试完成seal不能冒充合并完成。任何意外失败立即如实报告，禁止现场改代码、降低断言或用破坏性 reset 掩盖。

### Cost Gate：任何计费动作的独立授权

- Gate A/Gate B 默认 `cost_cap_cny=0`。真实 DeepSeek 请求、GPU/云实例、付费存储或其他计费动作均不得因“测试方案已批”自动获得授权。
- 如确需计费，必须先取得符合seed `abcr.approve-cost-receipt.v1` 的独立 `APPROVE_COST` 原始回执，绑定raw message SHA、approver/时间/认证会话、有效期/撤销账、plan+seed SHA、audit_id、适用的candidate tree、execution commit/patch manifest、输入/action-set manifest、provider/engine、精确命令、最大调用次数、数据范围、样本量、最长时限、动作预算、W1≤¥150与项目≤¥4000两条独立上限、E16与关机/清key动作；receipt还必须绑定唯一`project_cost_ledger_id/project_cost_ledger_genesis_sha256/w1_budget_scope_id`。只有与候选代码无关的只读provider能力探针或纯基础设施provision，才允许`candidate_tree=null`，并须显式写`code_independent_reason`；任何会产生实验数据的动作不得null。任一64hex字符串本身不构成授权。
- 预算采用唯一append-only项目账本和原子双账。每个transaction先取得单调fencing token，每次RESERVED事件在CAS当前ledger tip的同一临界区重算“既有settled+既有liability+新reservation”，并分别校验动作cap、W1累计≤¥150、项目累计≤¥4000；不能把三门折成一个min值。每个reservation必须记录`approved_action_ids/reserved_amount/actual_amount/released_amount/outstanding_liability_after`，local attempt必须记录`completed_at/outcome`，provider attempt必须记录唯一`approved_action_id/provider_outcome/provider_receipt_sha256`；ledger事件均有typed `payload_schema_version`，并显式追加`LOCAL_ATTEMPT_COMPLETED`。正式LIVE PASS的coverage manifest必须证明`required_action_ids == visible_action_ids` exact equality，且每个approved action在reservation↔local↔provider↔settlement/release间双向唯一覆盖；失败尝试、存储与实例空转同样入账，多个provider attempt不得被一个总价行吞并。正式LIVE结果只在每笔reservation已SETTLED/RELEASED且coverage闭合后封存，故本结果未结责任为0；其他并发未结责任仍保留在全局post-ledger状态。结果行必须链接审批、项目ledger genesis与tip before/after、transaction/fence、Cost receipt、执行代码、input manifest与stop/关机凭证，不能事后只按总小时估算。
- local attempt把`outcome`与`provider_visibility`分开：VISIBLE恰一provider receipt，UNOBSERVABLE与NOT_REACHED均无provider id；混合attempt保留所有可见谱系，任一UNOBSERVABLE使结果`BLOCKED/PROVIDER_UNOBSERVABLE`，不能用可见兄弟洗绿。时间必须满足approval→reservation→local→可见provider→local end→settlement的RFC3339 UTC顺序；账单不可得保持BLOCKED，绝不估算成PASS。
- 5% smoke PASS 只证明 smoke 完成，不授权全量；全量动作必须在 Cost Gate 明文范围内。

---

## 4. 严重级别、状态与证据格式

### 4.1 严重级别

| 级别 | 定义 | 处置 |
|---|---|---|
| P0 | 可静默污染数据、错误放行 citable/阶段门、破坏隔离/溯源/秘密，或使核心链不可复现 | 立即 FAIL；相关产物隔离并从下游拒用 |
| P1 | 破坏明确契约、关键恢复/并发/边界行为，或使结果解释不可靠 | 必修；全回归后才可 PASS |
| P2 | 非核心正确性、可操作性、诊断性或文档一致性缺陷 | 本轮清零；不能以“记录即可”放行 |
| P3 | 不影响正确性的优化建议 | 可列后续，不阻塞终验 |

旧方案将 DeepSeek token 兼容、pos/neg 对齐、judge 可复现性列为 P1/P2；本文全部提升为 P0，因为它们直接决定云结果是否真实。

每个原子 finding 只允许一个严重级。若历史复合 finding 暂时无法拆开，机器策略取其中最高级；本版 CR-01–45 已按这一规则规范化。严重级只决定处置强度，不替代 `blocks_w1/blocks_merge` 两个正交字段。

### 4.2 唯一允许的测试状态

- `PASS`：全部断言实际执行通过，证据齐全。
- `FAIL`：断言被实际反例击穿。
- `BLOCKED`：输入、权限、设备或外部事实不可得；不是 PASS，也不计入通过率。
- `NOT_APPLICABLE`：必须有权威范围依据；不得用来隐藏未实现路径。
- `UNVERIFIED`：历史报告有声称但本轮未复现；最终总判定时等同未通过。

`BLOCKED` 仍是唯一“无法执行”状态，但必须另填 `blocker_class=MISSING_INPUT|MISSING_AUTHORITY|COST_NOT_AUTHORIZED|PROVIDER_UNOBSERVABLE|ENVIRONMENT_UNAVAILABLE` 与唯一 `recovery_condition`；禁止另造 `STRUCTURALLY_BLOCKED` 冒充新状态。复合 AND 门采用三值保守逻辑：已有任一可信子门 FAIL 时总门可 FAIL，但其余未知子门必须继续保留 BLOCKED/UNVERIFIED，不能被批量改写为 FAIL。Gate A 只读复核只允许 `finding_status=CORROBORATED_STATIC|CORROBORATED_EVIDENCE|PROPOSED|REJECTED`，封存状态另用 `seal_status=SEALED|UNSEALED`；不得把两者拼成新枚举，也不得把未按下述 schema 封存的观察冒充正式测试 PASS。

### 4.3 每个用例的证据记录

每项必须保存：

```json
{
  "result_schema_version": "abcr.test-result.v2",
  "result_id": "<sha256 of canonical identity tuple below>",
  "result_record_sha256": "<sha256 of canonical full record with this field omitted>",
  "audit_id": "<unique id>",
  "test_id": "L-03",
  "assertion_id": "L-03.A01",
  "source_row_sha256": "<approved exact Markdown row sha256>",
  "assertion_text_sha256": "<approved full-row or marker-delimited role text sha256>",
  "assertion_role": "FULL_ROW|ZERO_CONTROL|EXTERNAL_OR_SEALED_DOMAIN",
  "expected_check_inventory_sha256": "<approved seed value>",
  "runner": "<stable runner id>",
  "nodeid": "<stable nodeid or null>",
  "oracle_ref_sha256": "<sha or null>",
  "required_evidence": ["EV-<lowercase sha256>"],
  "attempt": 1,
  "phase": "PRE|GATE_B|POST_COMMIT|POST_MERGE",
  "run_role": "BASELINE_RED|CANDIDATE_GREEN|EVIDENCE_AUDIT|POST_COMMIT|POST_MERGE|META",
  "context_profile_id": "<approved atomic context profile>",
  "attempt_policy_id": "<approved append-only attempt policy>",
  "subject_role": "BASELINE|CANDIDATE|COMMIT|TARGET|CONTROL",
  "subject_identity_sha256": "<typed execution-tree/commit/target/control identity sha>",
  "matrix_subject_role": "CURRENT_GLOBAL|CURRENT_CANDIDATE|CLOUD_RUN|ARTIFACT|CLAIM|CONTROL|EXPECTED_SUBJECT_SLOT",
  "matrix_subject_identity_sha256": "<typed subject-registry identity sha>",
  "matrix_subject_run_id": "<cloud run id or null>",
  "matrix_subject_bytes_sha256": "<artifact/claim bytes sha or null>",
  "matrix_producer_subject_identity_sha256": "<producer run subject sha or null>",
  "matrix_producer_binding_type": "RUN_PRODUCED|AGGREGATE_REPORT|AUDIT_MISSINGNESS|null",
  "matrix_producer_binding_identity_sha256": "<typed producer/report/missingness identity sha or null>",
  "matrix_producer_binding_manifest_sha256": "<producer lineage manifest sha or null>",
  "matrix_reported_protocol_class": "ORIGINAL_W1|AMENDED_PROTOCOL|UNCLASSIFIED|null",
  "matrix_derived_protocol_class": "ORIGINAL_W1|AMENDED_PROTOCOL|UNCLASSIFIED|NOT_RUN_SCOPED",
  "matrix_exact_scope_status": "PASS|FAIL|BLOCKED|UNVERIFIED|NOT_RUN_SCOPED",
  "matrix_w1_aggregation_role": "CURRENT_GLOBAL|CURRENT_CANDIDATE|ACTIVE_ORIGINAL_LEGACY|AUTHORITATIVE_ORIGINAL|SUPERSEDED_ORIGINAL|AMENDED|ARCHIVAL_ONLY",
  "matrix_original_series_id": "<stable original-series sha or null>",
  "matrix_original_series_receipt_sha256": "<pre-output series receipt sha or null>",
  "matrix_original_series_slot_id": "<predeclared logical slot id or null>",
  "matrix_original_series_status": "VALID_SERIES_RUN|INVALIDATED_TECHNICAL|BLOCKED_SERIES_IDENTITY|NOT_ORIGINAL_SERIES|null",
  "matrix_technical_invalidation_receipt_sha256": "<pre-domain-proxy invalidation receipt sha or null>",
  "matrix_supersedes_reason_code": "PREDECLARED_TECHNICAL_INVALIDATION|PREDECLARED_REPLICATION|null",
  "matrix_predecessor_invalidation_receipt_sha256": "<receipt that invalidated the predecessor or null>",
  "subject_registry_sha256": "<sha or null only for PRE bootstrap>",
  "expected_assertion_subject_matrix_sha256": "<sha or null only for PRE bootstrap>",
  "track": "GLOBAL|MAC|CLOUD",
  "expected_observation": "PASS|FAIL|BLOCKED|NOT_APPLICABLE|UNVERIFIED",
  "observed_status": "PASS|FAIL|BLOCKED|NOT_APPLICABLE|UNVERIFIED",
  "meta_verdict": "PASS|FAIL",
  "applicability_rule_id": "<seed rule id or null>",
  "authority_ref_sha256": "<sha or null>",
  "not_applicable_reason": "<nonempty text or null>",
  "plan_sha256": "<approved plan sha256>",
  "policy_seed_sha256": "<approved Gate A seed sha256>",
  "expected_assertion_inventory_sha256": "<approved seed value>",
  "bootstrap_intent_manifest_sha256": "<pre-action bootstrap intent sha only for PRE; otherwise null>",
  "bootstrap_observation_manifest_sha256": "<post-action bootstrap observation sha only for PRE; otherwise null>",
  "bootstrap_reference_manifest_sha256": "<phase-level exact-three bootstrap reference manifest sha or null>",
  "phase_identity_manifest_sha256": "<phase-specific identity sha>",
  "evidence_requirement_inventory_sha256": "<pre-execution requirement inventory sha>",
  "expected_evidence_slot_manifest_sha256": "<pre-execution slot manifest sha>",
  "evidence_completion_manifest_sha256": "<post-execution exact resolution sha>",
  "execution_envelope_manifest_sha256": "<pre-execution cwd/argv/env/network/resource/output/cost envelope sha or null only when execution_state=NOT_STARTED>",
  "gate_c_post_work_definition_manifest_sha256": "<pre-POST work-definition sha or null outside POST phases>",
  "gate_c_expected_set_manifest_sha256": "<POST payload sha or null>",
  "approve_commit_merge_receipt_sha256": "<POST approval receipt sha or null>",
  "target_repo_id": "<sealed repo identity sha256 or null>",
  "target_ref": "<ref or null>",
  "target_sha": "<40-char sha or null>",
  "baseline_commit": "<40-char sha or null>",
  "candidate_tree": "<40-char git tree sha or null>",
  "candidate_patch_sha256": "<binary full-index diff sha or null>",
  "test_harness_tree": "<40-char git tree sha or null>",
  "test_suite_manifest_sha256": "<sha or null>",
  "resolved_test_policy_sha256": "<sha or null>",
  "finding_links": [{"requirement_id": "CR-01#L-06.A01", "finding_id": "CR-01", "finding_subject_role": "BASELINE_CODE|HISTORICAL_RUN|HISTORICAL_ARTIFACT|HISTORICAL_REPORT", "finding_subject_identity_sha256": "<sha>", "finding_instance_id": "<canonical sha>", "closure_mode": "CODE_RED_GREEN|DETECTION_PASS_DOMAIN_NONPASS|EVIDENCE_BLOCKED", "finding_disposition": "RED_CONFIRMED|FIX_VERIFIED|DETECTION_VERIFIED_DOMAIN_OPEN|OPEN_BLOCKED"}],
  "finding_disposition_summary": "NOT_LINKED|SINGLE|MIXED",
  "blocks_subject_claim": true,
  "blocks_w1_base": true,
  "blocks_w1_resolved": true,
  "blocks_merge": true,
  "is_final_consumed_context": true,
  "is_gate_c_required": false,
  "participates_in_w1_reducer": true,
  "participates_in_merge_reducer": true,
  "cost_class": "ZERO|SEALED_EVIDENCE|COST_GATED_API|COST_GATED_GPU|COST_GATED_MIXED",
  "execution_mode": "LOCAL_FIXTURE|SEALED_DOMAIN_REPLAY|LIVE_EXTERNAL|PRECONDITION_BLOCKED|AUTHORITY_NOT_APPLICABLE",
  "execution_state": "NOT_STARTED|COMPLETED",
  "sealed_input_manifest_sha256": "<sha or null>",
  "approve_cost_receipt_sha256": "<sha or null>",
  "blocker_class": "<enum or null>",
  "recovery_condition": "<single exact condition or null>",
  "execution_commit": "<40-char fixture/formal sha or null>",
  "execution_patch_manifest_sha256": "<sha or null>",
  "protocol_ref_sha256": "<sha or null>",
  "scope_manifest_sha256": "<sha or null>",
  "input_manifest_sha256": "<sha or null>",
  "matrix_artifact_id": "<stable id or null>",
  "matrix_claim_id": "<stable id or null>",
  "command": ["argv", "without-secret"],
  "started_at": "RFC3339 or null when never started",
  "ended_at": "RFC3339 or null when never started",
  "exit_code": "<actual integer or null if never started>",
  "checks": [{"check_id": "L-03.A01.C01", "check_text_sha256": "<same as assertion_text_sha256>", "expected": "entire frozen assertion text holds", "actual": "...", "status": "PASS|FAIL|BLOCKED|NOT_APPLICABLE|UNVERIFIED"}],
  "stdout_sha256": "<sha or null>",
  "stderr_sha256": "<sha or null>",
  "stdout_path": "<sealed sanitized transport log outside source worktree or null>",
  "stderr_path": "<sealed sanitized transport log outside source worktree or null>",
  "artifacts": [{"path": "...", "sha256": "..."}],
  "domain_outputs": [{"artifact_or_claim_id": "...", "status": "PASS|FAIL|PARTIAL|INVALID|BLOCKED|UNVERIFIED", "domain_code": "<stable code or null>", "field": "<stable field or null>", "value": "<typed scalar or null>", "basis_sha256": "<sha>"}],
  "cost_receipt_manifest_sha256": "<sha or null>",
  "project_cost_ledger_id": "<stable project ledger id or null>",
  "project_cost_ledger_genesis_sha256": "<project ledger genesis sha or null>",
  "w1_budget_scope_id": "<stable W1 budget scope id or null>",
  "reservation_provider_coverage_manifest_sha256": "<required-vs-visible approved action coverage sha or null>",
  "local_attempt_ids": [],
  "reservation_ids": [],
  "provider_attempt_ids": [],
  "settlement_ids": [],
  "notes": "no hidden waiver"
}
```

一行只表达一个 policy assertion。seed 对普通 root 冻结一个 `FULL_ROW` A01；对25个 mixed root，规范行内恰有一次有序标记 `【A01 ZERO_CONTROL】...【A02 EXTERNAL_OR_SEALED_DOMAIN】...`。解析器先对整行 SHA，再按表结构分派两条唯一 regex：PRE 固定为 `ID|轨道|级别|断言`四列，其他规范表固定为 `ID|级别|断言`三列，断言 cell 必须是各自 regex 的最后贪婪捕获组；匹配零条/多条都 ERROR，禁止按 `|` 分列（C-12 正文自带管道符）。A01 text 是首标记结束到次标记开始的精确 UTF-8 字节，A02 text 是次标记结束到断言 cell 末尾的精确字节，不 trim、不 Unicode normalize、不含 marker/末尾 ` |`。两段必须非空，Gate B 不能移句。每个 assertion 恰有一个 `<assertion_id>.C01` policy check，其 text SHA 与整个 assertion text 相同；runner 可输出诊断细目，但不得改变 policy check 集或以部分细目 PASS 代替整段合取。`subject_*` 唯一指本条结果的执行树/提交/控制件，`matrix_subject_*` 唯一指 assertion×subject 矩阵中被评价的 run/artifact/claim/current 对象，两者不得复用同一个模糊“subject”字段。`result_id=SHA256(canonical_json([result_schema_version,audit_id,phase,run_role,context_profile_id,attempt_policy_id,subject_role,subject_identity_sha256,matrix_subject_role,matrix_subject_identity_sha256,matrix_original_series_id,matrix_original_series_receipt_sha256,matrix_original_series_slot_id,matrix_original_series_status,matrix_technical_invalidation_receipt_sha256,matrix_supersedes_reason_code,matrix_predecessor_invalidation_receipt_sha256,bootstrap_intent_manifest_sha256,bootstrap_observation_manifest_sha256,bootstrap_reference_manifest_sha256,subject_registry_sha256,expected_assertion_subject_matrix_sha256,test_harness_tree,test_suite_manifest_sha256,policy_seed_sha256,resolved_test_policy_sha256,phase_identity_manifest_sha256,evidence_requirement_inventory_sha256,execution_envelope_manifest_sha256,gate_c_post_work_definition_manifest_sha256,approve_commit_merge_receipt_sha256,execution_commit,test_id,assertion_id,attempt]))`，`result_record_sha256`另对除自身字段外的完整canonical record取SHA。Gate C expected-set SHA故意不进result_id及COMMIT/TARGET subject constructor，只进入完整payload，避免manifest列result ID时形成自循环；revalidation ID同样由不含manifest SHA的冻结tuple生成。因此相同identity的PASS/FAIL payload不会被当作同一证据，且bootstrap、series、registry/matrix/harness/执行树/context/envelope或payload变化均能被正确分代识别。

`finding_links[]` 可为空，也可把同一 assertion 映射到多个 CR；disposition 必须在每条 link 内独立记录，顶层只允许 `NOT_LINKED|SINGLE|MIXED` 摘要，不得用一个标量覆盖多 finding 的不同状态。finding subject 与 result subject 必须分离：代码 finding 固定绑定 target repo+baseline commit，baseline/candidate 两条结果引用同一 instance；历史 finding 固定绑定原 run/archive/report/artifact，baseline/candidate 两版 detector 也引用同一 instance。`finding_instance_id=SHA256(canonical_json([finding_id,finding_subject_role,finding_subject_identity_sha256]))`。本轮358条closure receipt中disposition按context固定为`RED_CONFIRMED/FIX_VERIFIED/DETECTION_VERIFIED_DOMAIN_OPEN/OPEN_BLOCKED`；后续恢复只能另发append-only recovery event，不能改本轮receipt。`blocks_w1_base/blocks_w1_resolved/blocks_merge/matrix_w1_aggregation_role/matrix_original_series_*/participates_*`全部由resolver注入。active subject为current global/current candidate，加所有`matrix_original_series_status=VALID_SERIES_RUN|BLOCKED_SERIES_IDENTITY`的original成员；`SUPERSEDED_ORIGINAL`只表示图角色，若其series状态仍有效就继续参与 fail-dominant reducer。只有事前注册且在读取任何raw/domain proxy前封存有效receipt的`INVALIDATED_TECHNICAL`才排除；科学FAIL/PARTIAL、结果难看或事后理由不得技术失效。`participates_in_w1_reducer=is_final_consumed_context AND active_subject`，`blocks_w1_resolved=blocks_w1_base AND participates_in_w1_reducer`，`participates_in_merge_reducer=is_final_consumed_context AND blocks_merge AND active_subject`。历史/domain reducer独立消费原状态，任何participation布尔不得洗掉它。

`expected_observation` 描述 red/green/detection 预期，`observed_status` 如实记录受测工程/审计器表现，`meta_verdict=PASS` 当且仅当二者逐字相等，否则为FAIL；所有 context 共用此纯函数。baseline 如期失败是 `observed_status=FAIL, meta_verdict=PASS`，绝不能被汇报成候选 PASS。两版审计器正确检出旧产物非通过时自身可 `observed_status=PASS, meta_verdict=PASS`，但必须在 `domain_outputs[]` 保留该 artifact/claim 的精确 FAIL/PARTIAL/INVALID/BLOCKED；最终 W1 同时消费工程断言与 §14 所需领域门。唯一 C01 的 `status` 必须与 `observed_status` 逐字一致；候选终态只能由 `(PASS,PASS)` 或权威完整的 `(NOT_APPLICABLE,NOT_APPLICABLE)` 满足，baseline FAIL 只是red证据，BLOCKED/UNVERIFIED 绝不参与通过率。

`NOT_APPLICABLE` 三字段必须同时非空且命中seed权威规则，并使用 `AUTHORITY_NOT_APPLICABLE/execution_state=NOT_STARTED`；matrix 同时保留每个 context 的 `context_sources`，它只能替换来源集合精确为`[BASE]`的默认 `CANDIDATE_ASSERTION`。任何含`CLOSURE`来源的context（包括CODE candidate green）以及subject-profile、baseline/detector/blocker/PRE context均不可替换。`PRECONDITION_BLOCKED` 仅表示尚未执行就因缺输入/授权/环境阻断，不允许`PROVIDER_UNOBSERVABLE`，且必须 `observed_status=BLOCKED,started_at=null,ended_at=null,exit_code=null`；已有seal/批准凭证按阻断原因保留，不能强制抹空。三种实际执行模式都必须 `execution_state=COMPLETED`、开始/结束时间非空、`exit_code`为整数且有不可变local attempt id；过程事件另存 append-only 日志。`ZERO_CONTROL ⇒ LOCAL_FIXTURE+ZERO`；`EXTERNAL_OR_SEALED_DOMAIN ⇒ SEALED_DOMAIN_REPLAY+COST_GATED_MIXED` 或 `LIVE_EXTERNAL+COST_GATED_MIXED`；FULL_ROW 按resolved policy执行。`LOCAL_FIXTURE`禁止网络/大模型/计费，`SEALED_DOMAIN_REPLAY`绑定sealed input且零provider attempt，`LIVE_EXTERNAL`绑定覆盖该动作的`APPROVE_COST`与完整成本manifest，并与local/reservation/provider/settlement ID集合双向相等；供应商request不可见也须保留本地attempt谱系。非法组合ERROR。

本版seed的authority applicability registry是哈希绑定的空数组，因此当前正式矩阵中实际上不允许任何N/A；保留该schema只为防止未来直接改代码扩权。以后新增一条N/A规则就是policy seed字节变化，必须重走Gate A，而不能由runner提交一个非空字符串自行生效。

正式 Gate B 每条结果都绑定非空 `target_repo_id/target_ref/target_sha=baseline_commit/candidate_tree/candidate_patch/test_harness_tree/test_suite_manifest/resolved policy`。baseline执行对象是`baseline_commit`；candidate/detector-candidate执行对象是冻结tree，`execution_commit=null`，不得为满足schema提前制造正式commit。POST_COMMIT与POST_MERGE是独立`is_gate_c_required=true`的PASS预期context，必须绑定approved commit、candidate tree、同一harness/suite/policy；POST_MERGE另要求目标ref/sha已等于approved commit且其tree等于candidate tree。源码身份不可构造时只产出独立partial-audit，不得用null身份填正式结果。

`attempt_policy_id` 对每个 matrix×atomic-context 冻结为 `FORMAL_ATTEMPT_1_ONLY`；正式结果 `attempt=1`，重试只能追加诊断事件而不得挑最绿。10轮 flake 用独立 `replicate_manifest` 全量消费，不借 `attempt`字段选样。`required_evidence`不得为空，且必须恰等其phase completion中对应typed slots解析出的EV ID排序去重集合；每个requirement/slot都绑定`consumer_type=RESULT|LIVE_REVALIDATION`、稳定`consumer_id`、闭合`evidence_role`与从0连续无重的`evidence_ordinal`，禁止只靠kind猜消费者。canonical evidence自身不复制consumer字段：`evidence_id='EV-'+lowercase_hex(SHA256(canonical_json([audit_id,kind,bytes_sha256,subject_identity_sha256,source_manifest_sha256,producer_binding_identity_sha256])))`，其中前缀严格大写`EV-`、digest严格`[0-9a-f]{64}`、kind为schema大写枚举；同一EV可满足多个类型兼容slot。执行前inventory只冻结kind/cardinality/typed consumer/producer约束，不可能预填执行后bytes SHA；执行中ledger在字节存在后append；执行后completion再做exact-set。一个canonical source/input/oracle可满足多个兼容slot，但同tuple别名重复、非formal记录进入结果、completed结果缺EXECUTION_MANIFEST/COMMAND_LOG/两条stdout+stderr RAW_OUTPUT均ERROR。三种COMPLETED模式即使输出为空也必须保存标准空字节SHA与路径；`observed_status=PASS`还必须`exit_code=0`。每次实际执行还必须在启动前封存`execution_envelope_manifest_sha256`，精确绑定cwd/realpath、argv、allowlisted env及被明确unset的secret/proxy、网络策略、资源锁、timeout、输入/输出根和cost授权；运行后不得改envelope。PRE先封存intent再封存observation，后续matrix只能通过exact-three `bootstrap_reference_manifest_sha256`引用不可变PRE结果，不能伪造一次新bootstrap。Gate B才由matrix+resolved policy注入其他字段，runner均不得自填策略。

捕获流先经过 allowlist 脱敏器再写入交付日志，随后只读化并计算 SHA。若脱敏前检测到疑似凭据，原始字节只进入权限0700的隔离区、停止该轨并记安全事件，不进入普通证据包；交付日志只保留不可逆定位摘要。每阶段以“上一 checkpoint seal + 本阶段新增文件 manifest”形成 append-only seal chain，整批结束再生成 final seal。秘密、密码、key、完整认证 header 永不进入可交付记录。

顶层 `attempt` 是测试执行尝试，不得与供应商 logical request/网络重试混用；所有计费子尝试通过一个不可变cost receipt manifest和全局project ledger展开。reservation/local/provider/settlement各自使用不同前缀主键并双向join；provider outcome与visibility分列，VISIBLE恰一provider record，UNOBSERVABLE/NOT_REACHED为null，混合可见谱系不得丢。账本按transaction/fence/CAS追加并同时重算动作、W1、项目三道cap，正式result只在全部settlement/release终结后生成。

### 4.4 统一数值容差政策

离散身份、key 集、token、文本、shape、层号与哈希一律精确比较，不允许 tolerance。浮点断言统一读取事前封存的 `numeric_tolerance.json`：逐 dtype/算子记录 `atol/rtol`、维度/归约长度、norm scaling、零与近零范数处理、硬件/内核和推导依据。oracle 分两层：①小型解析 fixture 用不导入候选 torch 路径的 stdlib/NumPy float64 实现，BF16 由原始 bit pattern 独立解码、`math.fsum` 归约并保存预计算 golden；②真实模型只做 pinned-upstream differential/身份 smoke，不冒充数学 oracle。oracle/tolerance 生成器、golden、来源 SHA 与版本先于 candidate green 封存，并接受轴交换、pair mask、符号、dtype、NaN/Inf、归约分母和容差放宽 mutation。禁止读取跨实现结果后调宽容差；同实现重复误差只能作为事前误差预算输入，不能替代独立 oracle。

### 4.5 Gate A 冻结的测试策略种子

同目录 `ABCR-W1测试策略种子-V2.0.json` 是本文的机器可展开伴随件。其 inventory 必须与正文精确相等：`PRE-00..14`（15）、`S-01..17`（17）、`L-01..24`（24）、`I-01..16`（16）、`E-01..20`（20）、`P-01..11`（11）、`C-00..34`（35）、`R-01..09`（9），合计 **147 个唯一 root test_id**。seed 还冻结 assertion expansion 版本、规范表行的字节提取规则、25条mixed行的角色标记语法、172个期望 assertion/check ID、逐行/逐角色 text SHA 与 canonical inventory SHA；未知、重复、断号、正文引用不存在、标记缺失/重复/换序、输出 SHA 不符或 policy 漏项均 fail-closed。Gate B 只能重算，不能重新切句或移动子句。

- 所有适用 root test 默认 `blocks_w1=true`；root PASS 是该规范行全部原子断言 PASS 的合取，不允许“跑了其中几个”。
- `merge_rule=ALWAYS` 是默认。`PRE-CLOUD` 历史取证、真实付费 provider 描述性探针和历史科学 outcome 由 seed 明列 `NEVER`，其 FAIL/BLOCKED 仍阻断 W1-inclusive，但不阻止把已完整验证的防错修复合并；云实现类仅在 candidate 触及 seed 冻结的 cloud path class 时解析为 `blocks_merge=true`。
- `IF_CANDIDATE_TOUCHES` 只能由 binary full-index diff 与 seed 中的 path matcher 纯函数解析；未知新增生产路径、submodule/patch/mode/symlink 变化默认 impacted，不允许人工判“无关”。
- 同一 root 内若同时含零成本 fixture/离线控制与真实外部或已封存领域证据，规范行本身已固定为 `【A01 ZERO_CONTROL】...【A02 EXTERNAL_OR_SEALED_DOMAIN】...` 两段；merge 只消费 A01，A02 仍按 subject/run 作用域阻断 W1。任何需要新成本的 A02 没有 `APPROVE_COST` 时为 BLOCKED，但能由身份完整的 sealed evidence 满足时不强迫重烧；两种路径都不得使零成本轨停摆。
- 每个 assertion 同时绑定所属规范表整行 SHA 与自身精确 text SHA；普通行 A01 text 是整行，mixed行 A01/A02 text 是两个标记间/标记后的精确字节。每项只允许一个 `<assertion_id>.C01` policy check并绑定同一text SHA，语义为“整段全部成立”；runner诊断细目不参与替换或缩减policy check。seed 已给出稳定 ID、role、cost、merge、expected assertion/check inventory SHA；Gate B 只补 runner/nodeid/oracle/required evidence，不能改变任何冻结字段。

---

## 5. PRE：受测对象与证据真实性门

PRE 分轨执行，不能让云证据缺失阻断可独立完成的 Mac 工程审查：

- `PRE-GLOBAL`：PRE-09/10/11；Gate A receipt、audit_id、证据目录隔离、当前可得材料的秘密扫描；失败时全停。
- `PRE-MAC`：PRE-00/01/02/07/08/12/13 适用部分；失败只阻断 S/L/I/E/P/Mac 回归。
- `PRE-CLOUD`：PRE-03/04/05/06/14 及 PRE-09 的云材料部分；失败只阻断对应云动态复验，离线可得材料仍继续审查。

每条轨道独立给 PASS/FAIL/BLOCKED。最终可以是 `MAC 已测 + CLOUD BLOCKED`，但 BLOCKED 不能折算为 W1-inclusive PASS。

| ID | 轨道 | 级别 | 动作与精确断言 |
|---|---|---:|---|
| PRE-00 | MAC | P0 | 从已确认地址 `superagent@192.168.3.70:/Users/superagent/abcr` 定位真实工程仓；必须有非空 HEAD 和完整 object database。认证不可得判 MAC BLOCKED；Mac Air 当前协调仓不得当受测对象。本轮静审已见 `e02d4c3...`，Gate B 仍须重新读取时变状态。 |
| PRE-01 | MAC | P0 | 固定 `target_repo_id`、`baseline_commit` 完整40位 SHA、tree SHA、全部 refs、worktree/common-dir/alternates、`git fsck --full`、工作树状态；核对报告中的缩写 commit 对应唯一完整对象、四条 `[REG]` 和任何云日后 `[cloud]` 提交。 |
| PRE-02 | MAC | P0 | 记录来源/保管人和传输 SHA；`git bundle verify` 或等价 SSH git 协议验真，已知 refs/artifact hash 对照；仅在无 hardlink 的隔离副本建分支。源仓只读、无 remote变更、canonical artifacts 不变。 |
| PRE-03 | CLOUD | P0 | 取得 `cloud-results.tar.gz` 并校验报告期望 SHA `82681b6bda04c81cb6cbbdcd9b0337a333e9b88ed5277c531bd853602cda536a`。文件缺失判 BLOCKED；文件存在但 SHA 不符判 FAIL，不能改报告迁就文件。 |
| PRE-04 | CLOUD | P0 | 取得云端最小输入包或其 manifest；核对交接报告 SHA `d46150e0ec42fb53b1bd98719582a4b15c16ddb12bc2e33edda705f2416e53f2`、111 文件与实际源码来源。缺失为该证据链 BLOCKED。 |
| PRE-05 | CLOUD | P0 | 恢复云端**实际执行版本**的 `eval_persona.py`、`judge.py`、`model_utils.py`、`generate_vec.py`/`genvec_v5.py`、patch、全部命令和日志；关键临时脚本无法恢复则云结果不可复现，云代码复验 BLOCKED。 |
| PRE-06 | CLOUD | P0 | 生成权威输入 manifest：模型/tokenizer/config/template 全文件 SHA，trait extract/eval SHA，split/item SHA，PV/ABCR完整 commit，patch SHA，Python/torch/transformers/CUDA/vLLM 版本。 |
| PRE-07 | MAC | P0 | 历史 run 自批2起只要求 V1.0+V1.1 双 `protocol_ref`；w1-full 按历史规格核对 V1.0+V1.1+ABC 文档。冻结分派指引作为本轮 audit authority 单独钉 SHA，不追溯要求历史 run/pack 引用。 |
| PRE-08 | MAC | P0 | 核对包/manifest 中两套真实 env lock，禁止 `UNAVAILABLE`；从 lock 在全新隔离环境重建并记录实际 import provenance。原 `.venv/.venv-pv` 若仍在只作加强证据，不要求历史目录永久存活。 |
| PRE-09 | GLOBAL/各轨 | P0 | 对当前已取得的源码、git历史、日志、run、score、review、pack、cloud tar、shell证据做秘密扫描；测试 key 仅用假值。发现真实 key 立即停止并隔离相关输出；未取得材料明确记 UNVERIFIED，不假称已扫。 |
| PRE-10 | GLOBAL | P0 | 先按 Gate B.1 在内存验证原始 `APPROVE_PLAN` receipt：本文 SHA256、policy seed SHA256、完整范围与 `cost_cap_cny=0` 必须逐字匹配；安全建立审计目录后，立即保存获批 plan/seed 与原始 receipt 字节、approver 身份、RFC3339 时间及认证会话，复读哈希并生成 bootstrap seal，才正式记 PASS。任何缺字段、转述、旧 SHA、审批后改文或 bootstrap seal 失败均 FAIL，禁止后续 Gate B。 |
| PRE-11 | GLOBAL | P0 | 复核已按 Gate B.1 建立的 `$ABCR_AUDIT_ROOT/<audit_id>/`（本版默认 `/Users/wangyinan/ABCR-audit-results/<audit_id>/`）：root 与 audit_id 均为真实目录、当前 owner、0700、非 symlink、非 group/world 可写；realpath 位于获批 root，audit_id 创建时不得预存在。保存时钟/时区、磁盘、操作者、宿主机、目录 device/inode 与写入探针；bootstrap 四件套及 seal 只能读，后续证据只追加。源码在另一隔离 worktree，证据增长不得改变 candidate tree。 |
| PRE-12 | MAC | P0 | 对canonical及`git worktree list --porcelain`发现的**每一个**worktree分别封存路径身份、ref/HEAD/tree、tracked、untracked、ignored三类清单；非获批baseline/candidate的worktree及其文件一律列入排除集。当前已知未跟踪云包/目录不得被测试或`git add -A`意外纳入候选；被忽略`.venv*`、`third_party`、tinyqwen、checkpoint不得成为未声明输入。特别核对独立`r2-integration`：其ref/tree时变，两个launcher曾从`8e7b59a2.../cca160e...`的untracked文件进入`896f3ebf.../3a40b1e...`树，后续仍可推进；它不是main baseline，Gate B必须活体重读并逐字证明未进入clone/candidate/harness/依赖/命令/执行，不能因“worktree clean”自动当candidate或执行。每个适用依赖必须转为hash-bound fixture/cache manifest，或明确使该测试BLOCKED。 |
| PRE-13 | MAC | P0 | nested `third_party/persona_vectors` 独立做 repo 身份审计：commit、tree、dirty binary diff、未跟踪/ignored、submodule/remote。当前静审见 detached `b8e0f044...` 且 `config.py/generate_vec.py` dirty；实际 dirty diff SHA、仓内两份 patch SHA 与运行产物必须一一对应，不能只核对 upstream HEAD。 |
| PRE-14 | CLOUD | P0 | 云归档执行安全解包预检并封存 archive-level 与逐 member hash；拒绝 traversal/symlink/重复/大小写冲突。对当前 27 文件建立 expected-vs-actual 表；“archive SHA 匹配”只授予 `TRANSFER_INTEGRITY=PASS`，不得自动授予 `RUN_IDENTITY/ARTIFACT_VALIDITY/PROTOCOL=PASS`。同时验证 sidecar 只含允许的 basename/相对标识；当前 `cloud-results.sha256` 已观察到泄露云端绝对路径 `/root/autodl-tmp/cloud-results.tar.gz`，正式测试应将其作为可移植性/最小披露 FAIL，而非修改 sidecar 后假装历史包原本合格。 |

路径适配必须通过单一 `ABCR_ROOT`/CLI 参数完成。任何生产代码硬编码 `/Users/superagent`、`/root/autodl-tmp` 或当前用户名，均应由 P1 测试击穿；协议文档中的历史路径不作文本替换。

---

## 6. S：静态契约、测试纯度与需求追踪

### 6.1 Gate A 实码静审缺陷账本

下表不是“待 Gate B 才知道的猜测”，而是对 `e02d4c3...` 源码/既有工件及当前云归档逐行只读审查得到的反例。表内 `STATIC/EVIDENCE/ENV` 只表示 evidence basis：控制流/数据流已足以构造必现反例、现存工件自证不满足声明、或环境材料缺失；机器 finding 仍只用 §4.2 的 `CORROBORATED_STATIC/CORROBORATED_EVIDENCE`，并另记 `seal_status`。Gate B 按下表后的 closure map 固化检测：代码缺陷做 red→green，历史负证据只要求探测器正确检出并永久保留领域 FAIL，缺失历史输入只能 BLOCKED；不得因候选代码变绿而删除或洗绿历史记录。

| ID | 级别/证据基底 | 已确认缺陷与代码锚点 | 影响 | Gate B 杀手测试 |
|---|---|---|---|---|
| CR-01 | P0 / STATIC | `run.py:294-341` 在校验旧 run 身份前重写 manifest；`manifest.py:83-127` 重置 started_at、repair/resource events 与 env lock。 | config B 可续跑 run A，旧 `config.yaml` 与新 manifest 分裂，两次实验拼成一条链。 | L-06、L-19 |
| CR-02 | P0 / STATIC | `writer.py:25-39` resume 不验旧链/schema/重复；`:95-129` repair 会给任意 JSON 合法前缀重算哈希。 | 中段篡改可被“洗白”；CLI repair 也不记 manifest event。 | L-03–06、L-20 |
| CR-03 | P0 / STATIC | `score.py:31-70`、`review.py:114-123` 在 items/unknown item/checks 缺失时以空 checks 计算 `1.0/true`。 | 题库丢失反而全绿；score/review/rescore 同错同绿。 | E-15、P-10 |
| CR-04 | P0 / STATIC+EVIDENCE | `review.py:40-195` 将 `n_expected=len(steps)`，缺 manifest/score、不可验证 split/template 不入错误；`review.py:302-312` 还可用任意同 hash 的 `items.jsonl` 代替 manifest 声明路径。8 个现存报告均 `split_hash_unverifiable=true`、`chat_template_hash_verified=false` 但 `pass=true`。 | 删 step+对应 score 或整份 scores仍可 PASS；文件内容碰巧同 hash 也会丢失路径/角色身份，历史 review PASS 失去证明力。 | L-09/10/22、E-16 |
| CR-05 | P0 / STATIC+EVIDENCE | `review.py:399-419` 从 step 读不存在的 `vector_dir`，空值直接 continue 后 `ok=true`。 | residual run 的三件套、shape、dtype、SHA 实际从未复核。 | I-13、L-10 |
| CR-06 | P0 / STATIC | `run.py:145-187`、`splits.py:59-66` 只验 split 自身 sidecar，不把 `items_source_sha256`、item_id/prompt/check、全集/唯一性与 dev 绑定。 | 改题保留 ID、重复 ID、空 dev、用 heldout 都可能通过。 | L-22、E-06 |
| CR-07 | P0 / STATIC | `run.py:75-87,433-439` 只查禁键，不验证 `condition↔method`；clean Mac run 又可由 `run.py:90-163` 标 `citable=true`。 | 真实 residual hook 可被记成 vanilla；违反 Mac 恒 non-citable。 | I-08/12、L-01 |
| CR-08 | P0 / STATIC | `models.py:20-52` 对本地 snapshot 忽略 revision；`run.py:120-125` 仅 hash `config.json` 前12位。 | 替换权重/tokenizer 不触发 E02，模型身份漂移。 | PRE-06/08、L-22 |
| CR-09 | P0 / STATIC | `residual_vector.py:92-109`、`random_direction.py:87-102`、`projection_ablation.py:73-89` 用 module 级 `_past_seen*` 与 `shape[1]>1` 的有状态 prefill heuristic 猜 response 阶段。 | cache-on 首生成 token漏干预；cache-off会污染整段；单 token prompt或同一 context 第二次 generate误判；与 pinned upstream“逐 forward 只改最后有效位置”不一致。 | I-06/07/14 |
| CR-10 | P0 / STATIC+EVIDENCE | residual/projection loader 只校整 tensor shape，random reference path 连完整 shape 也未校；三者均未完整强制 card/meta SHA、model/tokenizer/trait/revision、dtype/finite/nonzero/layer map。现有 optimistic card 的 pos/neg effective 数不可能来自 upstream 共同 mask，且记 fp16。 | 错模型/错方向/NaN/零向量可进臂；“官方复现”无法成立。 | I-11/13、C-15 |
| CR-11 | P0 / STATIC | `resource_guard.py:38-50,81-108,355-367` 把 sysctl/ps/Docker/MPS-cap 异常吞成 NORMAL/空/未运行。 | 探针坏掉时 3B 仍加载，资源门 fail-open。 | L-13、L-21 |
| CR-12 | P0 / STATIC | `run.py:256-650` 取锁后无总 finally；t0 E19 最终可退出0；`chunk_driver.sh` 用最新目录猜 run_id、E21 不按协议重试，shell 6/8 与 Python/测试3/5分裂。 | 残锁、错 run resume、未完成却宣告成功、历史 override 被全局化。 | L-12/15/17、L-19 |
| CR-13 | P0 / STATIC | Make 只跑 contract stage、不跑 unit；stage3/4 可 skip，stage2 缺向量直接 return；stage2 在 import 读真实 key、调用付费 API并改 tracked output/card/DEVIATIONS，重模型入口不经 guard。 | pytest “绿”可代表未执行、复用陈旧缓存、产生费用或污染候选树。 | S-04、S-10、R-07 |
| CR-14 | P0 / STATIC+ENV | 干净 clone 缺 ignored tinyqwen/third_party；`bootstrap.sh:3-67` 硬编码路径、下载浮动 revision、失败建议手工放宽版本，并 `git add -A && git commit`；`pyproject.toml` 无任何运行依赖。 | 新实验者无法从受控树重建；bootstrap 可夹带用户文件并改变历史。 | S-09、S-11/12 |
| CR-15 | P0 / STATIC | Day1 runbook 使用未定义 `START_TS/RATE`；Day2 先追加无 `remaining_cny` 行，再从最后一行取该键；E16 无生产 state machine。 | 预算检查要么报错、要么在花费后才发生，无法事前熔断。 | L-18、S-14 |
| CR-16 | P0 / EVIDENCE | cloud tar 不含 `genvec_v5.py`、transformers-only 实际脚本、执行 commit/patch/env/命令历史；Mac nested upstream 是 dirty、ignored 状态。 | 云代码逐行审计 BLOCKED，不能由报告文字补齐。 | PRE-04–06/13/14、C-34 |
| CR-17 | P0 / EVIDENCE | cloud tar 虽 SHA 匹配，但仅27文件；无 manifest/raw/card/meta，Day2 无日志、openness 无向量。5个 `.pt` 均为 layers14–24、bfloat16：4文件每层 `(3584,)`，`optimistic_prompt_last_diff.pt` 每层 `(1,3584)`。 | 已确认不满足 W1全29层float32标准；subset算法/模型/有效性仍不可证。 | PRE-14、C-17/24/31 |
| CR-18 | P0 / STATIC | `judge/client.py` 对所有异常重试且只计成功调用；`probe.py:135-140` 在两模式都坏时仍推荐 text_parse；所谓 bridge judge_raw 只存聚合分与截断答案。 | 401也重试、失败成本漏账、raw不可重算、模式漂移可被放行。 | E-07–13、E-19 |
| CR-19 | P1 / STATIC+EVIDENCE | `exprcheck_gen.py:114-135` 先按 condition 顺序编号再 shuffle，当前 `id%6` 可100%解出臂；只 seed shuffle 而 `do_sample=True` 生成未封存 torch RNG；pool/key 同目录；deblind 对重复/缺 key 用覆盖/UNKNOWN继续；dual judge 缺稳定 ID 时退化为位置式 `s000...`，并把完整父进程环境/key传给子进程、把 prompt 放 argv。 | 盲法可预测、生成不可复现、重排破坏 join，缺失可改变条件均值；凭据与敏感 prompt 可经进程环境/列表泄露。 | E-11/14/18/20、S-15、R-06 |
| CR-20 | P0 / STATIC | `rescore_bundle.py` 允许缺 hash/scores/run，空集合也 PASS，链字段又是 opt-in；pack verifier 信任可同改的内 manifest、未绑定 approved candidate/input trust anchor、忽略 extras/path 风险，judge_raw_check 不进入总 PASS。 | “168/168 独立复算”不能证明完备或独立；结论文件可事后改。 | P-02–11 |
| CR-21 | P0 / STATIC | checker 与 rescore 是复制实现；JSON 只要求可解析、case checker 对无字母文本 PASS；`build_items.py` 任意异常降级10题且仍写文件，fallback 的“exactly 5 sentences”却编码为 at-least。 | prompt 约束未完整编码、同源 oracle 无法发现语义错，构建失败可静默换实验。 | E-01/02/17、S-12 |
| CR-22 | P0 / STATIC | runner/review 的 run_id 可接受绝对/`..`/symlink；manifest/score/blind/dual/pack 多为直接覆写、无 fsync/atomic rename；输出冲突无 attempt ledger。 | 越根写、撕裂文件、并发覆盖和半成品假完整。 | L-04/07/20/23、E-19 |
| CR-23 | P1 / STATIC | 两份 parity runbook 语义分裂：`cloudday1-official-trait.md` 将 TF/vLLM 答案各截200字符后才 exact compare；`parity-smoke.md` 虽用完整答案做 exact，却只比较前50 token并以较短序列为分母、batch=10 只逐条复跑前3条且只比较第0条。前者 5% smoke 注释称“双极/4生成+4judge”，实际命令只跑 pos，且未实现“2题”参数。 | 长短不同前缀可得100% token match，部分样本/单极可冒充完整 smoke，打印而不 assert，无法证明 batch/引擎等价。 | C-07–12、S-14 |
| CR-24 | P1 / EVIDENCE | 表达报告 `pos=68.92<baseline=71.12`，STATUS 却以 `pos>neg` 宣称方向正确；终包同时收入无 baseline 的旧 `direction_clear=true` 报告。 | 领域判定与冻结标准不一致，canonical claim 冲突；历史 order 只能保持 NONPOSITIVE/FAIL。 | E-20、S-07 |
| CR-25 | P0 / STATIC | `manifest.py:96-119` 从不写 review 所读的 `n_items/seeds/conditions/steps_per_item`；即便人工补字段，`review.py:64-88` 用 int item_idx 对 str item_id，并以 `len(actual)>=len(expected)` 代替集合相等。 | 真实 run 的 expected-key 门恒为空或错型，多余 step 可掩盖缺 step。 | L-09/10、E-16 |
| CR-26 | P0 / STATIC+EVIDENCE | 云 `.pt` 是 `dict{14..24→bf16 tensor}`、无 card/meta、文件名不合标准；当前 `residual_vector.build` 要 `response_avg_diff.pt+card+meta` 且直接访问 tensor `.shape==(29,3584)`。 | 现有云件不能直接进入标准 residual arm；任何转换都是新 artifact，须另建 lineage，不能事后假称原件已集成。 | I-11/13、C-17/31 |
| CR-27 | P0 / STATIC | `review.py:383` 只有同一 report 中存在 vanilla hashes 才执行跨臂 prompt-hash 比较；真实每 run 单 condition。manifest forbidden-key 子检查仍会跑，但不能替代跨 run 同题比较。 | residual/random prompt 被污染时，真实 run 的 E06 跨臂纯度门不执行。 | I-08/12、L-10 |
| CR-28 | P0 / STATIC | `resource_guard.py:213-231` 在 owner 不可读且 lock dir age≥10s 时不证明持有者 PID 已死就 rename+rmtree；延迟 owner 写、owner损坏/删除或读失败可让活任务被回收。 | 两个重模型进程可并发；旧持有者还可能迟写 owner 覆盖新 lease，缺 fencing。 | L-11/12/21 |
| CR-29 | P1 / STATIC | residual/random capture 固定读取 `h_new[0,-1]`，projection ablation 始终返回 `activation_summary=None`。 | batch>1 只记录成员0，projection 路径无法满足逐 token/逐成员激活证据。 | I-09/10/15 |
| CR-30 | P2 / STATIC | `run.py:214-219` 将既非 EOS 也非 max-token 的未知停止原因回填为 `"eos"`。 | 诊断与数据语义被伪造，可能掩盖 generation backend 异常。 | L-01、S-08 |
| CR-31 | P2 / STATIC | `manifest._protocol_ref()` 在 tracked `configs/protocol_ref.txt` 缺失时，运行期读取仓外硬编码绝对路径并写回 tracked config；正常当前树因文件已存在不触发。 | clean/materialized 变体出现未声明写副作用，失败还可把 `UNAVAILABLE` 持久化。 | S-04/11、P-01 |
| CR-32 | P1 / STATIC | `run()` 在 `_validate_config` 前先索引 `cfg["model_key"]` 并可能取得 heavy lock；缺/错顶层键会走 KeyError/异常而非 E05，总 finally 又缺失。 | malformed config 可留下锁、错误码漂移且无受控 manifest。 | S-05/08、L-20/21 |
| CR-33 | P0 / STATIC | `approval_token.py` 对损坏 consumed store 回落空集，verify不绑定task/batch，verify→consume非原子；并发可双消费，key创建亦有竞态/权限缺口。 | 旧批准可跨batch重放、并发重复启动或在损坏账本后复活。 | S-03/05/06、L-07/20 |
| CR-34 | P0 / STATIC | queue/runstate 的run_id/path未做containment；rename可覆盖，runstate读改写分锁，resume不核items/meta/config，orphan scan可暂停其他活进程。 | 路径逃逸、状态丢写、跨输入拼接与误杀活run。 | L-06/07/19/20/23 |
| CR-35 | P0 / STATIC | dispatch对空config用`all([])`结算，仅执行首seed，scoring前即queue done；skip-done可无score结算，batch success只看queue，append-once与token消费非原子。 | 少跑/未评分/重复消费仍报告settled成功。 | L-06/08/09、E-15/16、R-01 |
| CR-36 | P0 / STATIC | code-tree manifest漏`.toml/.sh/fixture/Makefile`等且接受dirty；manifest原位重写，start/end身份不分，step去重只看item+seed。 | 运行中换代码/输入或不同condition可拼成同一“完成”run。 | S-04、L-10/19/22、R-05 |
| CR-37 | P0 / STATIC | 空batch可让audit item1/item2/health通过；`overall`把SKIP/空/未知折成PASS，调用者可选未知/子集再apply，cancelled排序还高于completed。 | 零证据、未验链或部分审计可推进状态。 | S-10、E-15/16、P-10、R-07 |
| CR-38 | P0 / STATIC | rescore/auditor join key遗漏trajectory/condition/step且seen未随append更新；未真正调用rescore，零comparison可PASS，也不拒绝missing/extra expected set。 | 错行、重复、跨轨迹串线或完全没复评分仍绿。 | L-08/09、E-15/16、P-10 |
| CR-39 | P0 / STATIC | ledger权威view/auditor只读主链忽略cloud segments；presentation按文件名拼接无全局序，fold忽略非法transition/未知event，解析损坏常被跳过。 | 云动作、坏链与非法状态可从权威结论中消失。 | L-03/04/21、R-05 |
| CR-40 | P0 / STATIC | watchdog对损坏state/ledger/timestamp跳过且不验链/不读cloud；任意历史terminal压制后续活动，instance idle把任一fresh run当全实例活且返回错iid；同秒同类alert覆盖。 | 失联、预算空转与异常活动不告警或告错对象。 | L-14/20/21/24、R-03 |
| CR-41 | P0 / STATIC | cost planner把缺账本当0，接受负数/NaN/cap，未知engine可落零/假价；估算漏seed/condition，无reservation liability，next_batch_id并发碰撞。 | 超预算或并发重复动作可被授权为“低成本”。 | L-18/24、C-30.A01 |
| CR-42 | P0 / STATIC | report聚合所有重复/未验证score与全部run state；`count(*)`含null而avg不含，effect按字典序前两行且可能是同condition不同scorer，并用所有done run id冒充provenance。 | 缺数、重复和错比较可产出显著效应/完整报告。 | S-07、E-16、P-10、R-08 |
| CR-43 | P1 / STATIC | blind phase拼错/未知时默认exploration并泄露direction，direction token集不全，NaN可入，source IDs可缺且confirmation标签不一致。 | 盲法失败、非有限分数和来源缺失可进入正式结论。 | S-07、E-11/18/20 |
| CR-44 | P0 / STATIC | queue/runstate/report/audit/output-date等多处用户标识直拼路径；任意run config路径可读，report/alert/precheck/envelope写入无统一atomic+fsync，同秒alert覆盖。 | 路径逃逸、任意读取、半文件及证据覆盖。 | S-05/06、L-20/23、P-07 |
| CR-45 | P0 / STATIC | dispatch未调用envelope validator；validator只做浅层deadline/protocol/type检查，NaN/Inf预算、重复/额外seed、空config seed与trait whitelist语义均未闭合。 | 无批准、过期、超预算或畸形batch仍可进入执行。 | L-01/20/22/24 |

closure mode 是 Gate A policy 的封闭枚举，45 项双向完备映射如下：

| closure_mode | CR 集合 | 成功语义 |
|---|---|---|
| `CODE_RED_GREEN` | CR-01–15、CR-18–23、CR-25、CR-27–45 | 同一获批 harness 对 baseline 观察 FAIL、对仅含生产修复的 candidate 观察 PASS；历史 artifact/domain 状态不随之改写。 |
| `DETECTION_PASS_DOMAIN_NONPASS` | CR-17、CR-24、CR-26 | 两版检测器正确识别seed冻结的既存archive/report/artifact精确非通过状态即meta PASS；原件继续INVALID/FAIL/PARTIAL/BLOCKED，禁止“修报告”或转换新artifact后回写历史。 |
| `EVIDENCE_BLOCKED` | CR-16 | 实际执行源码/patch/env/命令未恢复前旧finding instance保持OPEN_BLOCKED；后来重写等价脚本不能替代。若真实输入恢复则追加RECOVERED_AUDIT；若新authoritative取代则旧instance转ARCHIVAL_OPEN而非关闭。 |

集合必须恰好覆盖 CR-01..45、无重复；S-16 对其做机器双向校验。

### 6.2 静态契约与测试系统用例

| ID | 级别 | 断言 |
|---|---:|---|
| S-01 | P0 | 建立 `V1.3 中明确约束 W1 的条款 → W1 V0.9 → F1–F14/E01–E21 → 代码 → 测试 → 证据` 追踪矩阵。V1.3 范围至少含 §10 的 W1 行、§11 日志/schema、§4 科学命名、§5 对 W2 前置日志语义及其他显式回指 W1 的条款；W2–W12 其余阶段要求逐项标 `NOT_APPLICABLE` 并写权威依据，不得误当 W1 缺陷。适用硬需求无代码或无测试即 FAIL。 |
| S-02 | P1 | A/B/C 所有权与知识边界静态扫描：A 不读取向量生成内部；C 不参与生成且对 `runs/` 零写；B 对外只交标准向量工件。 |
| S-03 | P0 | `canonical_json`、chain、config/envelope/approval-token hash、manifest 校验不得存在互相漂移的重复实现；审批token须由独立oracle验证canonical payload、task/batch/scope/deadline/key identity及一次消费绑定，同时准备独立预计算黄金向量，防共享实现同错同绿。 |
| S-04 | P0 | 运行每个 regression 前后比较冻结的 `candidate_tree`、工作树状态与 canonical artifact 哈希；结果必须与执行前一致。测试不得更新 `direction_check_3b.json` 或任何正式证据。真实 API 探针必须落新的 audit run_id。 |
| S-05 | P1 | F10/F14及automation控制面CLI失败必须非零退出并在 stderr 含唯一稳定错误；空/未知audit item、空batch、畸形/过期/错batch token、路径逃逸和apply前置不满足均不得留下 PASS、状态迁移、半成品 manifest 或被 `\|\| true` 吞掉。argparse、compile/import 与 bootstrap 等非 E01–E21 路径另有稳定的非零 contract。 |
| S-06 | P1 | 关键模块 `compileall`、import smoke、未使用/不可达 fallback、绝对路径、宽泛 `except Exception`、损坏状态回落、NaN/Inf/负数、token/store/key-file竞态、危险 `torch.load`、symlink/path traversal 与用户标识直拼路径静态审查。 |
| S-07 | P0 | 报告/图注 claim lint：Mac/旧 mini/cloud 未闭门产物强制 `citable=false`；禁止“证实 H1/H2/S1”“通用”“命名人格向量”等越界措辞。 |
| S-08 | P0 | E01–E21 每码至少一条触发例和一条相邻不触发例；核对进程退出码、stderr码、manifest状态、无秘密、无半成品。未实现、复用错码或文档/代码漂移均失败。 |
| S-09 | P1 | F13 bootstrap 覆盖双进程同时启动、fake-clock 29:59/30:00 超时边界、下载/checkout 中断、partial/伪造 `.bootstrap.done`、锁清理和幂等重入；`.bootstrap.done` 只有在真实 bootstrap commit、完整树与 env lock 同时匹配时有效。 |
| S-10 | P0 | 测试系统及automation控制面自审：先冻结 expected test/audit inventory，再 collect；全部required test/item必须真实collected/executed，空选择、未知item、`SKIP/skip/xfail/xpass/deselected/collection error/提前return`均不能计PASS或触发apply。Make/CI包含unit+contract+shell integration，最终全量不得`-x`；收集阶段禁止读真实key、联网、加载大模型、写canonical文件、扫描后自动执行其他worktree脚本、生成真实approval.key或自签token。任何入口默认选择真7B/provider/API、把audit/dispatch失败用`\|\| true`旁路，或在没有外部`APPROVE_COST`时构造执行批准，都必须在执行前被harness拒绝；测试只用隔离假key/fake provider。 |
| S-11 | P0 | 在无 ignored 文件的 clean materialization 中按受控 dependency lock 重建：Python wheels/版本/hash、tiny fixture 生成输入、上游 repo commit+binary patch、模型/tokenizer/template manifest 全冻结。缓存只可按 SHA命中；缺缓存为 BLOCKED，不得回落 `master/latest`。 |
| S-12 | P0 | bootstrap/build-items 在临时 fixture repo 演练：不得硬编码用户、改 git identity、自动 `git add -A/commit`、夹带预存文件、任意异常换题库、手工放宽依赖或以 `.done` 掩盖 partial。输出先 staging+核验+原子发布；任何科学输入 fallback 需事前批准的新 scope。 |
| S-13 | P1 | 建立生产模块、CLI、shell/runbook、Make target、artifact builder 到正向/负向/并发/中断测试的覆盖表；无调用测试的生产分支、错误码或入口按缺口 FAIL。覆盖率数字只作辅助，不能替代 CR-01–45 的语义 mutation。 |
| S-14 | P0 | 将 cloud Markdown 中每个可执行 code block 提取为带 mock provider/fake clock/fake ledger 的 dry-run；`set -u` 下不得有未定义变量、`<填>`、错误 JSON、真实 key/网络/计费。注释计划次数、展开命令、实际 mock 调用数、双极/题数/范围必须精确一致。 |
| S-15 | P0 | allowlist 脱敏器自审：注入真实格式与变体的 API key、认证 header、SSH口令、home/云绝对路径、prompt/argv/env 泄漏，必须在写普通证据前阻断或不可逆脱敏；正常 hash/错误码/统计不得误删。测试原始 secret 仅用假 canary，隔离区权限/清理/事件 receipt 与日志二次扫描均验证。 |
| S-16 | P0 | policy/inventory/seal 工具自审：正文147个root与policy双向相等，marker expansion重算恰为172个assertion及C01，ID/text/inventory SHA一致；标记/分列/trim/normalize/role/blocking/context_sources/subject-matrix/candidate mutation均fail-closed。CR requirement→assertion→finding instance→result receipt双向完备且01–45各subject不漏，closure历史subject路由唯一。七个`matrix_original_series_*`/invalidation/supersedes字段与seed schema逐键相等；对`VALID_SERIES_RUN/INVALIDATED_TECHNICAL/BLOCKED_SERIES_IDENTITY/NOT_ORIGINAL_SERIES/null`、receipt/slot/supersedes组合跑闭合truth-table，缺receipt、slot复用、事后失效、科学FAIL伪技术失效、有效SUPERSEDED退出reducer均ERROR。bootstrap intent/observation/reference、typed consumer+role+ordinal、execution envelope、POST work-definition、三类producer binding与project-cost coverage也接受删加换序同改mutation；checkpoint/final/test/report/commit/closure seal及final-adjudication/eligibility全部fail-closed。 |
| S-17 | P0 | numeric tolerance/oracle 工具自审：预计算手算 golden 与独立 float64/BF16 bit-decoder oracle一致；候选实现、oracle与 tolerance builder 不共享生产归约函数。轴/符号/pair mask/分母/dtype/NaN/Inf/零范数、把容差调宽及读取 candidate 结果后重写 policy 的 mutation 全被杀死。 |

---

## 7. L：Ledger、schema、manifest、resume 与资源治理

### 7.1 schema 与哈希链

| ID | 级别 | 断言 |
|---|---:|---|
| L-01 | P0 | F4 全字段逐项正反例：缺字段、错类型、非法 null、未知枚举、NaN/Inf、负 token/latency、Unicode、超长文本均明确处理。Mac step 恒 `citable=false`。 |
| L-02 | P1 | `condition` 与 `method` 必须能无歧义表示 `projection_ablation`；若 w1.1 枚举缺该 condition，新增 schema 版本和迁移测试，不原改历史 schema。 |
| L-03 | P0 | 用独立实现逐一验证主ledger及每个cloud segment的canonical JSON、entry hash、segment identity/起止链；改单字节、换key序、删插重排、改prev_hash、重算局部链、漏segment、跨segment错序全部被发现，权威reader集合与sealed segment manifest双向相等。 |
| L-04 | P0 | 系统调用级确认每行 flush+fsync；在“组装前、write 中、newline 前、flush 后、fsync 后、manifest 前”注入终止。恢复结果只能是完整前缀或 E07，不得出现合法但错链数据。 |
| L-05 | P0 | repair 只修尾半行；原文件永久保存 `crashed-*`，有效前缀哈希一致、manifest 有 repair event；中段损坏禁止修饰性跳过。 |
| L-06 | P0 | 两层验证 runner/queue/dispatch resume：冻结时钟/ID/latency的fixture连续10次及kill-point后与不中断基线逐字节或规范投影一致；恢复前精确核items/meta/config/envelope/seed/condition/trajectory与queue/runstate。最终expected key、输出、score、queue terminal完全一致，空config/只首seed/skip-done/提前done均不得settle。 |
| L-07 | P0 | 两runner同时resume同一run只能一个写；token verify+consume、queue rename、runstate read-modify-write、append-once和batch-id分配均须跨进程原子且持同一fencing lock，竞态注入不得双消费、覆盖或丢更新。run_id同config同刻不得碰撞。 |
| L-08 | P1 | 完成键与所有dispatch/rescore/auditor join加入并验证`run_id/item/seed/condition/trajectory_id/step_id/scorer`的所需全集；任两个维度复用不得互相跳过，2-step、跨轨迹/condition replay均正确。 |
| L-09 | P0 | score/review/audit/rescore join 的missing、duplicate、wrong run/condition/trajectory/step、乱序、额外行分别触发E10/E11或稳定audit错误；expected集合独立生成且零comparison失败，生产rescore必须真实调用并证明输出集合双向相等。generation永不回写parsed/is_correct。 |
| L-10 | P0 | manifest 独立核验start/end code tree、dirty状态、全部受控扩展名/Make/shell/fixture、commit、config、protocol、env、model/template/split/arm/expected keys/vector；source/input/control-plane身份纳入每个step完成键。原位重写、运行中漂移或任一字节变化均fail-closed。 |

### 7.2 resource guard 与 chunk driver

| ID | 级别 | 断言 |
|---|---:|---|
| L-11 | P0 | 原子 `mkdir` 锁：并发、`--nowait`、阻塞排队、第6次 Claude 调用边界；全机同刻最多一个重任务。 |
| L-12 | P0 | owner 缺失/半写、mtime 9.9/10.1 秒、PID 复用、启动时间错、活进程 owner 被删/损坏、活进程假卡8h、SIGTERM/SIGKILL残锁；没有可验证 owner+PID start 时不得仅凭年龄强夺。构造“旧持有者延迟写 owner→新持有者回收→旧者迟写”交错，fencing token/inode 必须阻止覆盖；双等待者回收只有一方成功。 |
| L-13 | P0 | preflight 必须取锁后执行；normal 12×5s；V1.1 写的是 SI `GB`，故磁盘门冻结为 `free_bytes >= 50_000_000_000`，测试阈值前1字节/等于阈值；另测 RSS =2GB/>2GB、Docker 自愈成功/失败，swap 只记录。E21 必释放锁，3 次后 BLOCKER。 |
| L-14 | P0 | pressure 状态机：N-W-N-W 不触发；W-W、C、W-C 正确 E19；当前样本完整 fsync、resource event 在案、只 E19 可自动续跑。 |
| L-15 | P0 | normal 连续 120s 后才恢复；30min 超时、V1.1 默认1h连续3次/累计5次双闸边界 ±1。历史批2经明确追认的6/8只作为绑定该 run/scope 的 override，不得变成未来默认；状态机实现、部署 shell、日志文案与测试读取同一 policy。未知退出码/E20禁重试；E21按冻结节奏5min×最多3次，仍失败写 BLOCKER。 |
| L-16 | P1 | 3B 分片 10–40 默认20、0.5B≤100；父进程消失后子进程在下一样本边界退出；片间 MPS allocated memory 入日志，合并 hash 完整。 |
| L-17 | P1 | 3B 显式 fp16、MPS cap=`min(8GiB,recommended)` 且禁0、eval+inference_mode；非采集 run 不开 hidden states。异常/OOM 后模型释放、锁释放。 |
| L-18 | P0 | E16预算边界：计算、judge API、存储/实例、全部seed/condition分账；缺/负/NaN/Inf价格、成本或cap、未知engine、零价fallback与未结liability均fail-closed。reserve前低预算即停新动作并保存证据、清key、关闭/标记实例。 |

### 7.3 已确认代码反例的专项门

| ID | 级别 | 断言 |
|---|---:|---|
| L-19 | P0 | CLI/queue resume在任何写入前读取并验证原manifest/config/env/items/meta/steps/envelope及source/input/control-plane身份；model全文件、split、protocol、git、template、seed/condition/trajectory/schema任一变化稳定E09/E12且run树不变。started_at/provenance不可改，events只追加；runner返回唯一run_id，driver禁用mtime猜测。 |
| L-20 | P0 | config/envelope/token必须在取lock、创建run dir或读科学输入前完成schema/类型/有限数/范围/集合验证，malformed或空集合稳定非零且零副作用。manifest/config/env/queue/runstate/steps/scores/raw/report/alert/precheck/pack全部temp→flush→fsync(file+dir)→no-clobber atomic rename；并发/kill/ENOSPC只允许旧完成版或INCOMPLETE，expected key精确完成后才terminal。 |
| L-21 | P0 | sysctl/ps/pgrep/Docker/MPS及watchdog state/ledger/timestamp/chain/segment任一timeout、损坏、权限、缺失或解析异常都产生UNKNOWN→E21/alert，不得跳过或映射NORMAL；terminal后活动、同秒多alert、多实例一活一闲、cloud segment与错iid均覆盖。所有模型入口统一lock/preflight/cap并异常释放。 |
| L-22 | P0 | 输入与模型双向绑定：items 文件 SHA=split 内 source SHA，assignment keys=item IDs全集，counts重算，item_id按冻结算法由 prompt重算且唯一，W1 target=dev；model/tokenizer/config/template/weights每文件 SHA 与 resolved immutable revision一致。改单字节、缺 sidecar、重复/空/heldout、`master/latest` 均 fail-closed。 |
| L-23 | P0 | 所有run/score/review/repair/pack及automation queue/runstate/audit/report/alert/output-date/config-path CLI对用户输入做realpath root containment：拒绝绝对路径、`..`、symlink/hardlink escape、控制字符、Unicode/大小写碰撞、任意读取与既有非本audit输出。`--repair <run_id>`可独立运行。 |
| L-24 | P0 | E16为单一项目级原子状态机：reserve→start→local/provider attempt→settle/release→stop receipt；并发reservation/batch-id、失败重试、实例空转、API/存储及worst-case未结liability全入账。缺账本、未知engine、负/NaN/Inf/时钟回拨/半行mutation均拒绝，估算精确乘全部seed/condition，支出前熔断。 |

---

## 8. I：Intervention、层语义、arm purity 与激活采集

| ID | 级别 | 断言 |
|---|---:|---|
| I-01 | P0 | 层号黄金测试：对每个候选 L，证明向量 `hidden_states[L]` 与 hook `model.layers[L-1]` 的输出是同一残差位置；L-1/L/L+1 均有可区分哨兵。 |
| I-02 | P0 | coef=0 与完全无 hook 在 logits、token IDs、输出文本上逐字节等价；测试单条、混合长度 batch、cache on/off。 |
| I-03 | P0 | 用可手算 float64 oracle 验证已知 v、c 的位移为 `c·v`，浮点项按 §4.4 已封存 policy 裁决；正负、0、极小、极大、零/近零范数、NaN/Inf、错误 shape/layer/dtype/revision 均有断言或拒绝。 |
| I-04 | P0 | projection ablation 后该方向投影与正交分量分别按 §4.4 的事前容差裁决；同时验证零/近零方向、幅度保持与独立 float64 oracle，避免把全部激活清零仍假绿。 |
| I-05 | P0 | W1 主 random control 必须由独立随机过程生成、与目标方向等范数、seed 可复现；记录其与目标方向的 cosine、碰撞检查和 `match_to` SHA，不把偶然相关静默当作目标方向。不同 seed 不得意外相同。正交化或分量打乱方向若运行，只能标为探索性诊断，不能替代或污染主随机对照。 |
| I-06 | P0 | 将 response-only 定义为“每次 forward 只改用于预测下一个生成 token 的最后一个有效位置”：首次 prefill 必须只改各样本最后非 pad prompt 位置以影响首个生成 token，绝不改其余 prompt；后续 cache-on/cache-off 也只改当前最后有效位置。与 pinned upstream ActivationSteerer 逐 forward/逐元素对照；覆盖 DynamicCache、cache-off、连续多 token、1-token prompt、left padding、混合长度、EOS/pad及同一 context 连续两次独立 generate。禁止用 module flag/`seq_len==1` 猜阶段；若 API 不支持一 context 多 generate，必须在第二次调用前显式拒绝。 |
| I-07 | P0 | context 内正常退出、异常、取消、OOM 后 hook 与全部 `_past_seen*`/capture 状态都被摘除；同模型连续跑四臂或连续两个 prompt，后臂/后 prompt 不继承前状态。 |
| I-08 | P0 | arm purity：prompt 臂无 vector ref/layer/coef；vector/random 臂 prompt_hash 与 vanilla 同题相同且无 persona 文本；所有禁键含 null、嵌套、别名均 E06。 |
| I-09 | P0 | capture 命中集合与 `sha256(item_id)` 10% 规则双向相等；sampled→unsampled→sampled、同 item 不同 seed 均不复用路径，unsampled 恒 null。 |
| I-10 | P0 | NPZ 与摘要的 layer、proj_mean/P50/P90、token 数和文件 SHA 独立重算一致；NaN/Inf、旧路径、跨 run 路径、缺文件全部 E15/E12。 |
| I-11 | P1 | 标准向量三件套：`.pt` float32、shape `(layers+1, hidden)`、all finite、card/meta SHA 一致；从官方 response_avg 规范化时内容字节不变。 |
| I-12 | P0 | 穷举 condition×method：只允许 `vanilla↔none`、`prompt_persona↔prompt_persona`、`residual_vector↔residual_vector`、`random_direction↔random_direction`；projection ablation 要么有独立 schema-versioned condition，要么 runner 显式拒绝。`describe()`、manifest、每条 step 与 review 再交叉一致，错标 mutation 必须 E06。 |
| I-13 | P0 | 运行前从 manifest config 解析 vector 三件套，而非从 step 猜路径；强制 card/meta/pt 三 SHA、model/tokenizer revision、trait/pole、source commit/patch、dtype/shape/layer map、finite/nonzero norm、coef finite。删除/换模型/bit-flip/NaN/Inf/zero/错层/缺 hash全部 E15，且相关身份写入 manifest/step。 |
| I-14 | P0 | 以 pinned upstream、手算 tensor oracle 与候选 hook 做 response-only differential；首次 prefill、首生成 token logits、后续 token、tuple/list/tensor 输出全覆盖。候选实现若有意偏离 upstream，必须有事前批准的独立协议与新标签，不能沿用“官方复现”。 |
| I-15 | P0 | capture 对每个 sampled logical sample 的每个实际生成 token完整记录，batch成员不得只取 index0；逐成员保存或以带 batch 维的明示 schema 保存，projection ablation 也不得恒返回 null。明确 pre/post/delta投影语义，保存 item/trajectory/seed/token index/model/vector/layer/coef SHA。max_new_tokens=1也有一条；文件 atomic，kill 后不留可被误读的 NPZ。摘要从 NPZ 独立重算。 |
| I-16 | P1 | prompt persona artifact 必须校验 trait/pole/instruction index/文件 SHA；负 index、越界、空/重复 instruction、spec 与 artifact trait/pole 不符均拒绝。random control 保存 match_to 三件套 SHA、reference trait、seed、norm/cosine/collision，不以正交化替代主随机对照。 |

---

## 9. E：确定性评分、judge、盲评与数据隔离

### 9.1 checker 与 score/review

| ID | 级别 | 断言 |
|---|---:|---|
| E-01 | P0 | CT-1 14 类 checker 各有人工独立 oracle，覆盖 Unicode casefold、词边界、标点、空白、CRLF、JSON 顶层、markdown、尾随引号、多约束；不能只让生产实现复评自己。 |
| E-02 | P0 | 至少对官方 IFEval 支持子集做 differential test；差异必须逐例裁定。generated fallback 的 10 题人工审查证据与 81 题 provenance 在案。 |
| E-03 | P0 | score/review 前后递归哈希 `runs/` 完全不变；score 只写 audit 临时目录，review 从原始 steps 独立重算。 |
| E-04 | P0 | 168-step 权威 mini run：4 main×14×2=112，4 t0×14=56；8 run、四臂、3B MPS fp16、optimistic、seeds 17/42、t0 seed0、全部 citable=false，无缺重。 |
| E-05 | P0 | t0 每 run 有 scores，或 manifest 显式 `scored:false` + 理由；空目录、隐式不评分、只 review 均失败。 |
| E-06 | P0 | split 20/40/40 工具确定性；W1 只读 dev。抽取/评测隔离同时检查规范化字符串、prompt hash、question/instruction/sample 唯一键和近重复报告。 |

### 9.2 judge P0 门

| ID | 级别 | 断言 |
|---|---:|---|
| E-07 | P0 | `{}`、空 choices、空/None logprobs、数字概率总质量<0.25、非法 token 的结果必须为 typed failure/None，不得变成 0、50、100 或被丢行。每个计划样本必须恰有一条结果记录，缺失/额外结果行均为0；显式落盘的 typed failure/None 不算缺失行，其批级失败率统一按 E-12 裁决。 |
| E-08 | P0 | 429/5xx/timeout/connection 可有限重试；400/401/403 立即失败。确认 backoff 真实收到异常，不能被函数内部 `except Exception` 先吞成 `{}`。记录脱敏 request id、attempt、错误类。 |
| E-09 | P0 | 在取得 Cost Gate 后，DeepSeek 真实探针覆盖 0–100、前导空格、单/多 token、top20 概率质量、`seed=0` 支持/忽略及同请求≥10次重复；逐次保存 raw、概率截断质量和人工锚答案的排序。重复探针只作描述性稳定性诊断；未事先注册容差、功效和独立判据时，不得据此宣称“稳定”或“等价”。top20 总质量 0.25 是冻结上游聚合器的有效输入门，E-07 只验证该实现的 typed `None` 传播，不把它解释为 judge 真值保证。 |
| E-10 | P0 | 每个 judge 样本保存脱敏 raw 返回、解析版本和 join key；断网后可从 raw 重聚合。改 raw 一字节或删一条必须被 pack/review 发现。 |
| E-11 | P0 | 盲评请求的**语义样本字段**只含不透明随机 `sample_id/question/answer` 与必要 rubric；传输控制字段按 model、temperature、logprobs、timeout 等最小 allowlist。两者均不得含 condition、trait pole、arm、路径或文件名；sample_id、长度、序号、文件名也须通过条件预测/互信息泄漏审计。置换 seed 和解盲 key 可重算，key 与 pool 分权保存，在 raw评分完成并 seal 前不可见。 |
| E-12 | P0 | parse/refusal 恰10%允许按协议继续，>10%整批触发 E14（错误码）；分母固定为计划样本数，不能先丢无效行再算率。 |
| E-13 | P0 | 【A01 ZERO_CONTROL】用 fake provider/fake ledger 验证 concurrency=1 与30 的计划样本集合、join、raw数量一致；429 风暴下逻辑幂等键/attempt ledger 无重复成功行、覆盖或漏项；两个进程写同 output 时第二个在任何 mock/API 调用前被拒；不可观测账单不得被报告成零重复计费。【A02 EXTERNAL_OR_SEALED_DOMAIN】对实际 provider run 或身份完整的 sealed raw/attempt ledger 重做样本集合、join、raw与逐次请求核对，保存供应商 request id；只有供应商提供可核账字段时才裁决重复计费，否则明确 `PROVIDER_UNOBSERVABLE`。 |
| E-14 | P1 | 【A01 ZERO_CONTROL】在冻结本地 fixture 上验证 n=50 双 judge **描述性漂移审计**：不足50拒绝静默 `min(n,len)`；sample_id唯一、抽样清单事前封存、失败率分母固定计划 N；pairwise-complete 按 question 聚类 bootstrap，严格 JSON 表示常数/空/NaN，Claude parser 不从散文捞首个整数；输出完整散点/差值、Spearman、MAE、signed bias及区间，证据完整才记 test PASS 与 `DRIFT_CHARACTERIZED`，结论仍 judge-specific；“可互换”须另立前瞻 ROPE/功效/独立效度协议，本文无魔法阈值。【A02 EXTERNAL_OR_SEALED_DOMAIN】两方实际完整 raw、样本身份、抽样清单与 attempt lineage 必须由 sealed evidence 提供；若需新调任一 judge，先过 Cost Gate，再在同一冻结清单上执行 A01 算法。 |

官方 `_aggregate_0_100_score({})` 的预期是 `None`，不是 100。旧方案“空 dict 可能直接变100”的猜测改为验证：检查 None 在 CSV、过滤、聚合和报告中是否被正确保留并触发失败。

### 9.3 已确认 score/review/judge/表达反例专项门

| ID | 级别 | 断言 |
|---|---:|---|
| E-15 | P0 | scorer/auditor遇缺items、unknown/duplicate、空/重复/未知check或audit item、非法kwargs、step无checks时在写分数/应用状态前失败；禁止`all([])`、零comparison、全SKIP/未知选择生成PASS。scores带完整run/condition/trajectory/step/input/checker/raw SHA；空run/batch不得成功summary。 |
| E-16 | P0 | review/audit/report不以observed行定义expected：从frozen config+items+split+seeds+conditions+trajectory+scorer+batch/run registry独立生成精确集合，steps↔scores↔audit comparisons双射。删step+score、少seed/condition、重复/null、wrong join、extra done run或身份不可验均FAIL/BLOCKED；聚合count与avg使用同一非null集合。 |
| E-17 | P0 | 对14类 checker 做 pinned upstream differential、独立 oracle、property/mutation；逐条实际 dev prompt 审核“自然语言约束→checks”是否完整。JSON 必须满足题目所要求顶层/keys，case checker 不能让无字母文本通过；构建器 zip 长度不等、任意异常 fallback、10题缩水、exactly→at-least 等均拒绝或产生另批新 scope。 |
| E-18 | P0 | 盲池列集合规范化后必须精确为三列；sample ID用密码学随机不透明值且与 condition/顺序/长度无可预测映射，输入无稳定 ID 时拒绝，禁止位置式 `s000...` fallback。pool、key、raw、score、deblind做集合双射；重复/缺失/extra/UNKNOWN全部 FAIL。生成按 question×replicate×condition 事前派生并记录 Python/NumPy/Torch/device RNG seed/状态，使同一 question 的 baseline/正/负配对且重放一致；shuffle seed不得冒充 generation seed。解盲按 question×replicate配对，计划 N 是 refusal 分母，不能各条件先丢 None。 |
| E-19 | P0 | judge probe 两模式均不可靠时输出 `JUDGE_UNAVAILABLE`，禁止默认推荐；正式 mode/model resolved version/prompt/parser 必须与获批 probe 或 waiver一致。每个 logical request 有 append-only attempt ledger，400/401/403不重试，429/5xx按界重试；成功与失败尝试、request id、token、reserved/actual成本全记录。raw保存完整可重算响应而非聚合分/截断答案；输出 atomic且两进程第二个在调用前拒绝。 |
| E-20 | P0 | 表达检只允许一个 canonical claim：生成 pool/key、盲评 raw+score，先 seal raw，再解盲并生成 report；历史工件须证明此时间顺序，V2 新工件还须四者 SHA互绑。判定按每题等权 `pos-baseline` 与 `baseline-neg`；当前 conscientiousness 的前者为负，必须输出 `order=NONPOSITIVE`，旧无 baseline fallback 与 `STATUS-C` 的“方向正确”不得作为 PASS。清晰度若无同期冻结门则另标 `CRITERION_UNDERSPECIFIED/UNVERIFIED`，不能覆盖 order。 |

---

## 10. P：ReproPack、独立闭合与篡改测试

| ID | 级别 | 断言 |
|---|---:|---|
| P-01 | P0 | w1-full 清单含8 run全链、manifest、真实 env lock、activations、scores/review、split+.sha256、双协议、t0 evidence、唯一 canonical 表达检、主图、stdlib-only independent rescore；凡包声称闭合的 judge 结果，还须含完整 pool/key custody、prompt、client/parser源码和 raw。无 pycache、secret。manifest、配置、可执行脚本与 README 中不得存在不可移植的操作绝对路径；只读谱系/冻结协议中的历史路径仅作忠实留档，且不得被脚本当配置。 |
| P-02 | P0 | 采用可闭合的两层封存：内层 `pack_manifest.json` 覆盖全部 payload但明确排除自身；包外 `PACK.sha256` 覆盖一次生成后不再修改的**精确归档 bytes**（含 manifest），其值再写入 git/audit report 作为外部信任锚。除非另有冻结的 tar/gzip canonical profile，不宣称重建归档会得到相同 SHA；payload 等价由内层 manifest 验证。禁止要求内容在内部加密哈希自身。 |
| P-03 | P0 | `CLOSURE-RESULT.md` 保存在封存 payload 外，并记录被验归档的外部 SHA；若业务必须把 RESULT 收回包内，则生成新归档和新外部 seal 并重新做完整性检查。不能既声称包不可变又静默加入后写文件。 |
| P-04 | P0 | 在空临时目录、清空 PYTHONPATH、断网、不用项目 venv，只凭包运行 verify+rescore；168/168 分数一致、8/8 chain OK、所有 payload SHA一致。 |
| P-05 | P0 | rescore 前后包全树哈希不变；测试产生的 pycache/临时文件必须定向到包外或被禁用。 |
| P-06 | P0 | 在包的临时复制件分别改/删/加 steps、scores、review、rescore、README、protocol、split、activation、judge raw、t0 report；全部被发现。 |
| P-07 | P0 | 拒绝 symlink、hardlink逃逸、`../`、archive member 绝对路径、可执行配置中的外部绝对引用、重复文件名、大小写冲突、tar path traversal、超大解压比；pack 不得读取声明根目录外文件。冻结协议正文内的历史路径仅按 P-01 豁免。 |
| P-08 | P1 | 用独立 golden checker 评分全部14个实际 dev item，而非仅手工3/168；14类 checker 的语法/边界由 E-01 覆盖。关键 mutation（跳hash、忽略缺行、恒PASS、换score）100%被杀死。 |
| P-09 | P0 | G5 验收者身份、开始/结束时间、自生成结果 SHA、可读范围在案；不能由产包者事后改写 RESULT 后仍保留同一 PASS。 |
| P-10 | P0 | rescore必须拒绝空/缺run、缺steps/scores/链、duplicate完整join key、missing/extra score、unknown item/checker/旧version；链字段不得opt-in。expected run/step/condition/trajectory/scorer集合由封存输入独立导出，真实调用独立rescore并比较每项；零comparison、调用者选子集、同condition不同scorer误作effect均失败。 |
| P-11 | P0 | pack builder 每次在不存在的新目录构建，拒绝 unknown/empty preset、stale extras、源根外 glob/symlink；README 计数、manifest `n_files`、实际 allowlist一致。`pack_manifest` schema/路径唯一性/size/SHA全验，外部 seal 绑定 manifest+archive+candidate/target；从 baseline bundle+candidate恢复材料及包本体各做一次灾难恢复。 |

---

## 11. C：云日代码与产物对抗终验

Gate A 已静态 corroborate 的云归档事实：archive SHA 观察值匹配交接值；安全解包后为27个文件，其中 Day1 9日志+7 CSV+3 pt，Day2 6 CSV+2 pt。13个 CSV 均没有 `trait/instruction_id/sample_index/seed` 完整 join key；多个文件有 null judge分，openness 正负均全100、neuroticism几乎全0。5个 pt = 3个 optimistic 抽取变体 + 2个 anchor response 文件，非执行式 metadata 均是 layers14–24、bfloat16；4文件每层 `(3584,)`，prompt-last 文件每层 `(1,3584)`。直接按 bfloat16 storage 解码均 finite且层范数非零，但这只是必要条件。没有 provider raw、内部 manifest、card/meta、Day2日志或 openness 向量。这些事实直接进入 C-13/14/17/24/31 的输入，不允许 Gate B 用报告摘要替换原件；正式状态仍须 Gate B 重放。

| Gate A CSV 静态聚合（不是 judge 独立复算） | rows / trait-null | trait mean | 已确认含义 |
|---|---:|---:|---|
| optimistic extract pos / neg | `1000/16` / `1000/26` | `99.924 / 28.739` | 有方向分离但 pos近饱和；缺 raw/pair key |
| optimistic baseline | `200/5` | `82.923` | coherence 全100，需审查 judge分辨率 |
| optimistic steer +2 / +3.5 | `200/4` / `200/5` | `100 / 100` | 原 monotonic 硬门明确 FAIL |
| optimistic steer -2 / -3.5 | `200/10` / `200/2` | `21.053 / 4.495` | 负向有序但 -3.5 coherence均值仅63.2 |
| conscientiousness extract pos / neg | `1000/0` / `1000/4` | `93.659 / 78.768` | 分离较弱，且现有表达 pos低于baseline |
| openness extract pos / neg | `1000/0` / `1000/0` | `100 / 100` | 完全饱和，无方向信息；无向量交付 |
| neuroticism extract pos / neg | `1000/0` / `1000/0` | `0.8 / 0.1` | 几乎全0，极性/评估器/语料根因未决 |

Day1 原 pos/neg 日志均出现 `AttributeError: 'NoneType' object has no attribute 'content'`，随后另有 pos retry；归档没有 attempt ledger 或逐样本 raw，故不能确认失败样本、重试幂等性与费用。Gate B 必须从原始代码/日志恢复，而不是把最终 CSV 存在视为成功证明。

### 11.1 环境、源码和恢复

| ID | 级别 | 断言 |
|---|---:|---|
| C-00 | P0 | 【A01 ZERO_CONTROL】用 fixture 验证实例身份 receipt 的字段/schema/交叉约束，以及“5% smoke 仅为必要条件、不得授权全量”的 Cost Gate 状态机。【A02 EXTERNAL_OR_SEALED_DOMAIN】实际云实例的主机身份、GPU UUID/型号、24GB VRAM、CUDA、driver、torch bf16支持、磁盘、时区和计费主体必须由身份完整的 sealed evidence 证明；任何新 5%/全量运行另需对应 Cost Gate。 |
| C-01 | P0 | 【A01 ZERO_CONTROL】模型身份 verifier 必须逐文件验 SHA、精确 revision 与跨仓 revision 映射，只有模型名时 fail-closed。【A02 EXTERNAL_OR_SEALED_DOMAIN】Qwen2.5-7B 实际 model/tokenizer/template 文件须由 sealed manifest 绑定 ModelScope revision `a09a35458c70`，并给出可核验的目标 HF revision 身份映射；需重新访问付费存储/实例时先过 Cost Gate。 |
| C-02 | P0 | 【A01 ZERO_CONTROL】lineage verifier 强制完整 upstream commit、版本化 binary patch/branch、diff SHA，并拒绝未入版本控制的 `/tmp` 执行脚本。【A02 EXTERNAL_OR_SEALED_DOMAIN】实际执行 PV checkout 的 HEAD 必须为 `b8e0f044fe2410a6fad579f38324f03f13b4e917`，全部实际改动与 `git diff --binary`/SHA、`genvec_v5.py` 的 sealed source lineage 一一对应。 |
| C-03 | P0 | 【A01 ZERO_CONTROL】fixture loader/manifest 测试强制真实模型入口显式 bf16，未记录 dtype patch/自定义脚本时禁止“官方原版”claim。【A02 EXTERNAL_OR_SEALED_DOMAIN】目标模型实际运行须以 sealed trace 证明参数 dtype、激活 dtype、峰值 VRAM及所有 dtype patch/脚本身份；若需新加载7B模型先过 Cost Gate。 |
| C-04 | P0 | 【A01 ZERO_CONTROL】用 tiny model/fake provider 在生成10%/50%/90%、mock API返回后落盘前、向量写盘中、回传中注入终止，验证 resume 后逻辑样本完整唯一、输入 SHA不变、无半文件且模拟成本账闭合。【A02 EXTERNAL_OR_SEALED_DOMAIN】实际 provider/目标模型 run 必须提供上述 kill-point 的 sealed interruption/resume/attempt/cost evidence；需新执行任何外部动作先过 Cost Gate。 |
| C-05 | P0 | 【A01 ZERO_CONTROL】fake provider 上同阶段重入须零新增 mock 调用且输出 SHA不变或调用前拒绝；输入 SHA变化禁止复用旧 CSV/checkpoint；写盘必须 temp+fsync+atomic rename。【A02 EXTERNAL_OR_SEALED_DOMAIN】实际 provider run 的 sealed attempt ledger 与输出 hash 必须证明重入零新增计费调用/原子拒绝；若需新探针先过 Cost Gate。 |
| C-06 | P0 | key 文件 `umask 077`/0600、只在 `/dev/shm`、不进 argv/history/log/tar/git；任务结束 trap unlink。保存脱敏扫描报告和实例关闭/不可连证据。 |

### 11.2 transformers 替代路径（旧方案 S1–S4）

| ID | 级别 | 断言 |
|---|---:|---|
| C-07 | P0 | 【A01 ZERO_CONTROL】pinned tiny fixture 中 `do_sample=False` 的 temp0 golden token 与单样本 greedy 精确一致；`temperature=None` 只作实现细节，不凭猜测判错。【A02 EXTERNAL_OR_SEALED_DOMAIN】目标模型/实际 generation stack 的同配置 token trace 须由 sealed evidence 验证；需新加载模型先过 Cost Gate。 |
| C-08 | P0 | 【A01 ZERO_CONTROL】tiny fixture 比较 left-padding 混合长度 batch 与逐条 `bs=1` 的 attention-mask 去pad语义tokens、输出数/序、空文本、EOS/pad；配置/样本串扰为FAIL，token分叉按C-12分类查因，padded input width截取本身不预设bug。【A02 EXTERNAL_OR_SEALED_DOMAIN】目标模型实际 batch/逐条 token、完整输出与配置 manifest 须由 sealed evidence 提供；需新运行先过 Cost Gate。 |
| C-09 | P1 | 【A01 ZERO_CONTROL】fixture 实测 `min_new_tokens=1`/原`min_tokens=1`在EOS、空输出、max_new_tokens边界，并用确定性 fault injection 验证 OOM诊断与降批状态机。【A02 EXTERNAL_OR_SEALED_DOMAIN】目标模型超长上下文与`bs=20`的实际OOM/降批 trace须由sealed evidence证明；需新运行先过Cost Gate。 |
| C-10 | P0 | 【A01 ZERO_CONTROL】fixture/manifest 强制 baseline 与 steering 的 model、dtype、tokenizer、template、generation path 全同，唯一差异为受控 hook，并捕获 device_map/offload差异。【A02 EXTERNAL_OR_SEALED_DOMAIN】目标模型两臂的实际 resolved config、load/generation trace 与hook证据须由sealed evidence逐项相等；需新运行先过Cost Gate。 |
| C-11 | P1 | 【A01 ZERO_CONTROL】fixture 中 `lora_path` 非空不得静默忽略；W1不支持LoRA时必须调用前显式拒绝。【A02 EXTERNAL_OR_SEALED_DOMAIN】实际run若`lora_path`非空，须有sealed load/拒绝证据；权威scope证明其恒为空时A02才可NOT_APPLICABLE，不能因未记录而N/A。 |
| C-12 | P0 | 【A01 ZERO_CONTROL】固定 tiny fixture/双engine harness 实现两层parity及判定逻辑：层A每engine 10题temp0比较batch/逐条去pad tokens、可得logits摘要与完整生成，分叉标`BATCH_PATH_DIVERGENCE`并定位；只有违反冻结batch契约、因果对比混用batch语义或实现错误才FAIL，纯数值sensitivity只冻结正式batch/版本且禁称invariant。层B 20题；配置不一致先FAIL，否则输出首分叉、logits/top-k、checker/trait差及`OBSERVED_DIVERGENCE\|NO_DIVERGENCE_OBSERVED_ON_FIXED_SMOKE`。【A02 EXTERNAL_OR_SEALED_DOMAIN】兼容vLLM的固定实际镜像、目标模型两engine的10题层A与20题层B完整输入/输出/配置/logits证据须sealed；需新GPU运行先过Cost Gate。 |

20题 smoke 不能证明全局引擎等价。无论是否观察到分叉，W2 同一因果对比的 intervention/baseline 必须固定同一引擎、版本和 batch 语义；若要跨引擎合并，须另立前瞻等价性协议并预注册 ROPE、功效和独立判据。

### 11.3 judge 与向量生成（旧方案 J1–J3、V1–V3）

| ID | 级别 | 断言 |
|---|---:|---|
| C-13 | P0 | 【A01 ZERO_CONTROL】对pinned云judge代码用E-07–E-14 fixture验证parser/retry/join/统计，并对本地sealed raw离线统计每文件null、0、100、全百/全零条件、概率质量和拒答，不只打印均值。【A02 EXTERNAL_OR_SEALED_DOMAIN】云端实际judge执行代码身份与完整真实raw/attempt lineage须sealed并重做同一统计；缺raw而需新调用provider时先过Cost Gate。 |
| C-14 | P0 | pos/neg 先按 `(trait, question_id, instruction_id, sample_index, seed)` 一对一 join；键集合完全相同、无重复。随机打乱 neg 行必须使测试失败，不能按裸行位置继续。 |
| C-15 | P0 | 【A01 ZERO_CONTROL】用可手算fixture比较自定义实现、冻结patched upstream与独立float64 oracle；同一input/model/template/dtype/device/seed下比较全部重叠层、有效pair、中间充分统计量和向量；容差事前按dtype/归约/重复误差封存，超差FAIL。【A02 EXTERNAL_OR_SEALED_DOMAIN】真实7B的layers14/20/24只作身份smoke，其完整resolved身份与输出须sealed；不能替代A01全层differential，需新GPU运行先过Cost Gate。 |
| C-16 | P0 | 【A01 ZERO_CONTROL】artifact/fixture verifier强制layer key为int、L20存在，并把subset14–24仅标`subset direction`、禁止声称官方全29层。【A02 EXTERNAL_OR_SEALED_DOMAIN】目标模型实际hidden_states[20]与steering L20对齐须由I-01 sealed trace证明；需新模型运行先过Cost Gate。 |
| C-17 | P0 | 【A01 ZERO_CONTROL】artifact validator强制W1标准向量为全层`(29,3584)` float32三件套；subset必须标非标准/层范围、不能满足C-24/G4或冒充全层，引用另走C-28真值表，all-finite仅必要非充分。【A02 EXTERNAL_OR_SEALED_DOMAIN】被评价的实际云artifact字节、card/meta/provenance与shape/dtype证据须身份完整并sealed；转换件必须新artifact lineage，不能回写原件。 |
| C-18 | P0 | 【A01 ZERO_CONTROL】fixture verifier强制extraction/Day1-eval/Day2-expression-scan题目集合隔离、行数公式、唯一prompt/question/sample ID，分别断言extraction正/负各恰10、Day1 eval每题每被比较条件恰10、Day2 expression/scan每题每条件或极性恰2；V0.9“约2000”只作容量/费用粗估，不可作为exact count。过滤边界精确为`pos>=50,neg<50,coherence>=50`；W1开发seed为2–3而V1.3≥5从W2起，已冻结mini正式seed恰为17/42且temp0 seed0不计入正式seed。并验证每个formal stage的rendered generation config为temperature=0.7、parity专用temp0未泄入。【A02 EXTERNAL_OR_SEALED_DOMAIN】实际run的冻结题库、split/input/seed manifest、0.7 conformance patch/adapter与全部行须sealed并通过同一分阶段集合/计数/阈值/解码断言；上游或runbook默认1.0、Day2多/少于2、看结果补seed均不得冒充original，需新生成时先过Cost Gate。 |
| C-19 | P1 | 【A01 ZERO_CONTROL】fixture实现对全部事前候选层按question/instruction split-half与bootstrap重抽，报告cosine/范数/有效对数；L20预选须SHA，同数据选择须`post-hoc selected`、完整层扫描并在每次嵌套重抽中重选，禁止固定获胜L20冒充选择后稳定性。Day2存在多个合法trait/layer/coefficient/artifact候选时，须在首个outcome-bearing输出前封存候选全集、selector、约束、稳定tie-breaker与并列处理；缺失为UNDERSPECIFIED/BLOCKED，禁止事后挑最好者。【A02 EXTERNAL_OR_SEALED_DOMAIN】实际domain vectors、pair/split manifest、预选SHA、selector/tie-breaker receipt与全层统计输入须sealed，并用A01算法重算；需新模型/向量生成先过Cost Gate。 |

### 11.4 Day 1/Day 2 完整性与科学标签

| ID | 级别 | 断言 |
|---|---:|---|
| C-20 | P0 | Day1 五阶段必须齐：pos/neg抽取、标准向量、baseline、±系数 steering、官方 `eval.cal_projection`。报告未列 projection 产物时状态为未验证。 |
| C-21 | P0 | **历史重放**必须从实际执行 commit 恢复原 Day1 checker，逐字执行当时冻结的六项校准及其阈值、分母、缺失处理和运算符；原 checker 源码不可恢复则 BLOCKED。同时用不共享聚合实现的独立 oracle 从逐样本 raw 重算，分别输出 `HISTORICAL_REPRODUCTION` 与 `CHECKER_CORRECTNESS`；二者不一致即历史 checker/report 失效。另算 null/极值、熵、聚类 bootstrap、coherence 逐行等只作诊断，不改写历史协议状态。 |
| C-22 | P0 | 将历史判定与未来校准分离：现有 `+2.0=+3.5=100` 永久记录 `HISTORICAL_CALIBRATION_FAIL`，新 run/new audit_id 不得覆盖。若未来采用“饱和后允许持平”的 V1.3 monotonic segment，必须在看新结果前冻结系数网格、有效区间、饱和定义、采样、趋势统计和判定规则；其结果只能评价新运行。 |
| C-23 | P0 | Day1 任一校准 FAIL 后必须隔离其后动作。历史合规审查接受早于动作、含审批人/时间，且能由原始 commit、路径与会话上下文唯一归属失败项的明确继续授权；历史 REVIEW 按交接原文核验指定 REVIEW-REQUEST 后的原始 `REVIEW approved`，同样要求上下文唯一、早于 Day2。两者彼此独立，不能互代。V2 之后的新 waiver/REVIEW 则强化为绑定检查名、输入/代码/artifact/manifest SHA。现有材料未见批准但消息语料未穷尽，故两个子门保持 UNVERIFIED、sequence compliance 保持 UNVERIFIED；reported original run 仍因已知 Day1 FAIL 与 Day2 PARTIAL 判 FAIL，不能把“未见”伪装成“已证不存在”，也不能仅因后来找到的历史批准没有 SHA 就追溯加罪。 |
| C-24 | P0 | Day2 三 trait 各自必须齐：抽取、标准向量、盲化表达池/key、正式盲评、系数扫、激活抽样、原始 judge、manifest。任一缺失则该 trait PARTIAL。 |
| C-25 | P0 | 按 W1 V0.9 与后续冻结Day2 runbook执行表达检：至少20个 eval questions；每题每个正/负 steering及baseline条件**恰2条**回答，不能把“至少2”解释为看到结果后追加；样本盲化、随机化，E-12 无效率按计划 N 且 `>10%` 才FAIL（恰10%为PASS）。raw/score 必须在解盲前 seal；解盲后先按 question 算各条件均值，再对 question 等权计算 `pos-baseline`、`baseline-neg`；pooled-response 只描述。两差均正仅标 `ORDER_OBSERVED`，任一非正即 `ORDER_NONPOSITIVE`；当前 conscientiousness 的 `pos-baseline=-2.2` 必须进入后者。完整保存每题差、效应量、分布与 judge lineage，coherence/PPL只记录。因 V0.9 未操作化“明显/方向清晰”，证据完整只授予 `W1_EXPRESSION_RECORDED`；只有能恢复同期、盲化且按冻结规则作出的清晰度裁决，才可记录历史 `W1_EXPRESSION_PASS`，否则标 `CRITERION_UNDERSPECIFIED/UNVERIFIED`。未来数值门须在看新结果前另批协议。 |
| C-26 | P0 | openness 100/100 与 neuroticism 0.8/0.1 先标 `POLARITY_OR_EFFECTIVENESS_GATE_FAIL`，相应现有向量不得升级有效，根因保持 `UNRESOLVED`。分别审计 judge raw/解析、人工锚、eval_prompt、极性定义、pos-neg join 与生成响应后，才能归因 evaluator、语料、prompt、实现或 trait；禁止仅凭极端均值指定根因。 |
| C-27 | P0 | optimistic 当前报告最多声称 `reported direction candidate`，在 C-13–C-18 验真前为 UNVERIFIED；即便验真，正向饱和、coherence下降及历史 monotonic FAIL 也禁止把 `[-3.5,3.5]` 当 W2 正式剂量。V1.3 文本剂量点、KL预算和等范数对照尚未完成。 |
| C-28 | P0 | 拆成三轴：`evidence_stage=exploratory/confirmatory`；`object_label=none/direction-k/named-persona-vector`；`citability_status=ELIGIBLE/INELIGIBLE/BLOCKED/UNVERIFIED` 按 artifact_id/claim_id 而非笼统 trait 判定。历史 manifest 的 bool `citable` 只有 ELIGIBLE 映射 true，其余 fail-closed 为 false；审计四态仍保留。每次转换绑定门清单、审批人/时间和 manifest SHA，禁止互相推导。 |
| C-29 | P0 | 只有 V1.3 五检全部通过才允许 `object_label=named-persona-vector`；未全过最多 `direction-k`。`exploratory` 可与 `direction-k` 同时成立，不得把证据阶段误作对象名。 |
| C-30 | P0 | 【A01 ZERO_CONTROL】fake billing/clock/GPU controller 验证唯一项目账本genesis/tip与W1 scope，逐reservation记录approved action、reserved/actual/released/liability，逐local/provider/settlement双向join，并要求LIVE PASS的`required_action_ids == visible_action_ids`；覆盖实例、存储、judge API与失败重试，分别核对E16≤¥150/项目≤¥4000，并在完成、失败、时限/金额触顶时先停模拟GPU；本地SHA只门控卷/快照删除。【A02 EXTERNAL_OR_SEALED_DOMAIN】实际run的项目ledger、reservation/local/provider/settlement/release与action coverage、provider receipt及停GPU/停止计费receipt须sealed，证明无action漏账且关机未被本地回传复验延迟；任何新实例/API动作先过Cost Gate。 |
| C-31 | P0 | 【A01 ZERO_CONTROL】identity verifier 强制每个cloud run具备`run_id/protocol_ref_sha256/scope_manifest_sha256/execution_commit/execution_patch_manifest_sha256/input_manifest_sha256/artifact_manifest_sha256/identity_status`及七个matrix series字段；original成员还须有series id/事前receipt/slot/status，supersedes必须给冻结reason与前驱invalidation receipt。缺项或非法truth-table即BLOCKED/ERROR，并拒绝用归档SHA/日志路径/日期代替代码、scope或series身份。【A02 EXTERNAL_OR_SEALED_DOMAIN】每个实际cloud run的上述字段、对象和交叉hash须由sealed manifests提供；缺失保持该subject`BLOCKED_SERIES_IDENTITY`/BLOCKED，不能由后来run补写旧身份。 |
| C-32 | P0 | 【A01 ZERO_CONTROL】用穷举fixture按§14/seed版本化纯函数导出`day1_calibration/continuation_authorization/review_gate/day2_delivery`各自`reported/audited/effective/basis`及`reported_outcome/reproduced_outcome/sequence_compliance/effective_protocol_status`；再对series status/slot/supersedes/invalidation receipt跑truth-table并以`FAIL_DOMINANT_ALL_VALID_LOGICAL_RUNS`归约。test execution PASS不得覆盖domain非PASS，未知授权保持未知，有效SUPERSEDED FAIL必须继续消费。【A02 EXTERNAL_OR_SEALED_DOMAIN】每个实际run的原报告、raw、waiver/REVIEW消息、动作时间线、series receipt/graph与manifest须sealed并输入同一函数；Day1 FAIL后的继续与REVIEW分别需要有效事前授权，Day2 PARTIAL永不折算PASS。 |
| C-33 | P0 | 【A01 ZERO_CONTROL】scope classifier/selector对冻结original scope manifest逐字段精确比较，拒绝按结果挑run；首个original输出前须封存series id、primary/replacement/replication逻辑slot、每slot身份/seed/input/tree、非outcome技术失效谓词，以及Day2候选selector/tie-breaker。只有身份PASS、exact-scope PASS、series receipt有效且series reducer全门PASS的唯一active tip可成为authoritative；amended与original状态并存且不得洗历史。【A02 EXTERNAL_OR_SEALED_DOMAIN】候选新run的实际scope/input/trait/判据/交付/engine/dose/seed、execution、series slot/receipt/supersedes及事前designation evidence须sealed；任一scope改变归类`AMENDED_PROTOCOL`，事后加slot/按结果替换为ERROR，只有完全同scope且全部有效series成员归约PASS才可关闭当前`W1_ORIGINAL_PROTOCOL`。 |
| C-34 | P0 | 【A01 ZERO_CONTROL】从fixture source/env/model/input manifest在mock/小fixture重放runbook全部命令，核对resume/checkpoint、输出schema、逐文件manifest与关机trap，并杀死用后来等价脚本冒充原件的mutation。【A02 EXTERNAL_OR_SEALED_DOMAIN】历史actual source、env、model/input manifest、`/tmp`脚本、实际patch、execution commit与原命令/会话记录须身份绑定并sealed后才能重放；缺失时该历史subject永久保持BLOCKED/OPEN_BLOCKED，后来等价脚本或后来run都不能修补、替换或关闭这个subject。另一个run只有作为事前预声明series slot的独立subject参与fail-dominant聚合，且不得按历史outcome选择；它不改变本条历史重放状态。 |

引用资格真值表（每个对象有唯一 artifact_id/claim_id；未列门不允许靠措辞放行）：

| 对象类 | ELIGIBLE 的最低机器门 | 额外规则 |
|---|---|---|
| `raw-calibration/<run>/<trait>` | PRE-03–06、C-13/14、C-20–22、P-02–07、独立 oracle 与 final seal | 如实记录的负校准可以引用；**不依赖 C-23** 的 Day2继续 waiver/REVIEW。原始负结果与“协议合规”claim必须分开。 |
| `vector/<run>/<trait>/<layers>` | PRE-03–06、C-01/03、E-07–13与C-13（若 judge过滤样本）、C-14–19、P-02–07、artifact人工对表批准 | subset 必须写层范围；对象标签与 citability 分开。source pair 集与 judge raw 必须可重算。 |
| `expression/<run>/<trait>` | PRE-03–06、E-18–20、C-13/14、C-18、C-24/25、P-02–07、source vector=`VALID`、盲化/key custody、raw-before-unblind seal 与人工对表 | 只能引用实际 outcome；`RECORDED` 不得改写成显著或“明显”，source vector无效则表达 claim不得独立升级。 |
| `protocol-completion/<run>` | C-20–25、`effective_protocol_status=PASS`、同期 waiver/REVIEW（若适用）、完整 manifest | 任一越门、PARTIAL或已知领域 FAIL 即 INELIGIBLE；不能由 raw 结果可引用反推协议完成。 |
| `sequence-compliance/<run>` | C-23、两个授权门的 audited/effective 证据、动作时间线与完整 manifest | 只评价 waiver/REVIEW/先后顺序；消息未穷尽时可 UNVERIFIED，但不得据此把 protocol completion 改成 UNVERIFIED 或 PASS。 |
| `dose-recommendation/<run>/<trait>` | C-12、C-20–27 加 V1.3 W2 剂量/KL/对照前瞻门全部闭合 | 当前 W1/云日一律 INELIGIBLE；方向候选不授权剂量。 |

---

## 12. R：回归、mutation、flakiness 与实操验收

### 12.1 执行顺序

1. PRE-GLOBAL 必须全绿；PRE-MAC/PRE-CLOUD 按轨独立裁定，某轨 BLOCKED 不掩盖另一轨可执行审查，也不能让总判定假绿。
2. 先执行 S-10/R-07 harness 元验收和 clean materialization 依赖门；任何 required test 可能 skip/return、收集即读 key/联网/写文件时，禁止相信后续 pytest 汇总。
3. 按 Gate B.5 先冻结 test harness 并重算 Gate A assertion inventory；在clean baseline做不进入closure的discovery red，随后只改生产实现，冻结candidate tree、subject registry、matrix与resolved policy。最后在这一份最终matrix/policy下，以完全相同harness正式重放`CODE_RED_GREEN`的baseline red和candidate green；`DETECTION_PASS_DOMAIN_NONPASS`以baseline/candidate两版审计器报告同一历史subject的冻结非通过状态；`EVIDENCE_BLOCKED`核对blocker、合取恢复条件与subject作用域。静态/fixture覆盖S、L-01–24、I fixture、E checker/judge mock、P临时包；测试字节或candidate变化使相关正式证据失效并按顺序重建。
4. 运行 unit + stage1 全量（最终轮不用 `-x`），连续10次零 flake、零 skip/xfail、零 candidate-tree/canonical-artifact drift。10×范围只含无计费 fixture/unit/stage1；3B、stage2–4、真实API/GPU与历史证据重放各按其单次门执行，不进该分母。
5. S1.5：`make resource-smoke`；真实原机可达且满足条件时再跑 3B smoke。所有模型 load 入口均先过同一 guard。
6. stage2–4 在 guard 和隔离输出目录中运行；不得覆盖历史 evidence；缺 fixture/报告是显式 FAIL/BLOCKED，不得 skip成绿。
7. 168-step mini 环只做权威产物重审；除非修复触及生成语义，不默认重烧 3B。若需重跑，使用新 run_id 并与历史逐项对比。
8. 云包离线审计；真实 API/GPU动作只有独立 `APPROVE_COST` 明确覆盖后执行。未获成本授权时记 BLOCKED并给精确样本量、预算和时限，不用“低成本”自行越门。
9. 全回归、mutation、flakiness、实操 dry-run、eligibility真值表与灾难恢复演练。

### 12.2 R 系列出口用例

| ID | 级别 | 断言 |
|---|---:|---|
| R-01 | P0 | 在唯一 `candidate_tree` 上依序执行全部147个 root ID的所有适用 assertion及 stage1–4 回归；每个 assertion有独立结果行，任何适用P0/P1/P2未执行、BLOCKED或失败均不得汇总为全绿。test execution 与 domain outcome 分栏，正确识别历史 FAIL 可使审计测试 PASS，但绝不能把 domain FAIL 改成 PASS。 |
| R-02 | P0 | 对 §12.3 的 mutation 集逐个注入并逐个被指定测试杀死；记录 mutant SHA、预期杀手测试与实际失败断言，mutation score 必须为适用项 100%，不能靠编译崩溃冒充语义杀死。 |
| R-03 | P1 | 无计费 fixture 与确定性回归连续10轮；保存每轮顺序、seed、耗时和 raw log。必须观察到 0/10 flake；任何偶现失败先按 FAIL 处理，禁止只重跑到绿。报告只写“0/10 observed”，不得外推统计稳定性。真实外部服务变异另列描述性结果，不计入 fixture flake 分母。 |
| R-04 | P1 | 未参与实现的实验者按 §12.4 从空 shell 完成全流程 dry-run；每一步只凭版本化 README/CLI 可达、失败可诊断、无需旧 alias、人工记忆、热缓存或未封存 `/tmp` 脚本。 |
| R-05 | P0 | 每个阶段前后重新计算 `candidate_tree`、canonical artifact 与排除清单；任何未声明漂移立即使此前结果失效。证据目录允许只追加，通过 checkpoint seal chain 证明旧文件未变与新增文件已纳入；最终报告绑定的 tree 必须与最后一轮全回归完全相同。 |
| R-06 | P0 | 对候选树、历史/云材料、日志和待交付包执行秘密及危险路径扫描；只输出脱敏定位。真实凭据或可执行外逃路径立即隔离并 FAIL，未取得材料保持 UNVERIFIED。 |
| R-07 | P0 | 测试 harness 元验收：root test→assertion_id→runner/nodeid→JUnit/JSON结果双向一一对应，required项 `passed == collected == executed`，skip/xfail/deselected/return均为阻断状态；unit、contract、shell、runbook、mutation均在册。每个测试前后比较 test suite/candidate/canonical及所有worktree排除清单hash，并用canary证明收集阶段零secret read、零网络、零API、零大模型、零canonical write、零自签审批。注入“脚本自动创建approval.key并给自身签token”“默认真7B并dispatch”“audit失败经`\|\| true`继续”三个mutation，必须在provider/model/状态写入前被拒绝。 |
| R-08 | P0 | 对W1/领域/series/merge/report reducer做真值表与mutation：删blocking result、把FAIL改N/A、翻participates、洗历史domain、重复/null score、错condition/scorer、伪provenance run、未知test或任一SHA/seal/candidate/closure错配均失败。series矩阵必须穷举七字段的合法/非法组合、VALID/BLOCKED/TECHNICAL/NOT_SERIES状态、primary/replacement/replication slot、supersedes边、receipt时序及多run归约；删有效SUPERSEDED FAIL、raw/domain proxy后才技术失效、事后加slot/edge或按结果挑authoritative均被mutation杀死。独立oracle按冻结active-subject与`FAIL_DOMINANT_ALL_VALID_LOGICAL_RUNS`公式交叉计算，报告只消费精确机器集合。 |
| R-09 | P0 | 灾难恢复与目标仓演练：销毁测试 clone后，仅凭 durable baseline bundle、candidate object pack/binary diff、policy、seals重建 exact candidate tree并复跑无计费 smoke；再在假 canonical repo演练 target漂移、脏树、另一worktree占用、同名另一仓、非FF、post-merge失败，均不得错合并或破坏性回滚。 |

### 12.3 关键 mutation 必须 100% 被杀死

- hash 比较恒 True、跳过 fsync、repair 忽略中段损坏；
- resume 完成键删除 trajectory/condition 任一维；
- E19/E21 混码、锁释放删除、stale lock 无 PID start time；
- hook layer `L-1/L/L+1` 互换、hook 不摘除、coef符号翻转；
- activation_summary 复用上一条 path；
- arm purity 少查一个禁键；
- score 缺行不报错、review 恒PASS；
- judge `{}`→0/50/100、parse fail先drop、盲评附condition；
- pack verifier漏验一个文件、允许symlink、rescore恒复制旧score；
- cloud calibration 把 tie 当 PASS、Day1 FAIL 后继续。
- scorer 缺 items/checks→满分、review 用 observed steps 当 expected、删 step+score后仍PASS；
- resume 改 config/model/split后覆盖 manifest、StepWriter 不预验旧链、repair重算合法篡改；
- resource probe异常→NORMAL、MPS cap异常被吞、异常路径不释放锁、driver猜错run_id；
- condition 与 method 错配、Mac clean run citable=true、权重替换但 config不变；
- response-only 跳首 token/cache-off改整段、vector缺hash/NaN/zero仍加载、capture少首token；
- test缺fixture skip/return为PASS、收集时读真实key、stage2改tracked文件、unit不运行；
- blind ID泄条件、deblind缺key→UNKNOWN、probe全失败仍推荐text_parse、401被重试；
- empty pack/run/scores无hash仍PASS、manifest+payload同改自洽、extra文件未检；
- eligibility删blocking结果仍true、candidate tree变后旧report/approval仍有效；
- amended protocol结果覆盖original历史FAIL、raw calibration错误依赖Day2 waiver。
- review expected字段缺失/键类型错仍完成、单条件 run 跳过跨臂 prompt-hash；
- cloud dict/subset向量被标准 loader 接受、活 owner metadata 损坏后锁被强夺；
- capture只记录 batch0、projection capture恒null、unknown stop回填eos；
- expression只seed shuffle不seed生成、缺稳定sample ID退化为位置ID；
- protocol_ref缺失时运行期写tracked config、malformed config在校验前取得锁；
- redactor漏过 canary、seal payload+manifest同改、policy漏一个 assertion、oracle与生产实现共享归约。
- consumed-token store损坏→空集、错task/batch token仍验过、verify与consume间双进程同时成功；
- queue空config/仅首seed/score前done/skip-done结算，runstate分锁丢写、orphan scanner暂停活run；
- audit空/未知/全SKIP/子集→overall PASS并apply，cancelled状态冒充completed、重复apply再次迁移；
- rescore漏condition/trajectory/step/scorer、实际rescore函数不调用、零comparison或missing/extra集合仍PASS；
- 权威reader漏cloud segment、segment字典序代替事件全序、坏链/未知transition跳过；
- watchdog坏state/timestamp/ledger静默跳过、旧terminal掩盖后续、多实例错iid、同秒alert覆盖；
- cost缺账本→0、负/NaN/Inf/未知engine、漏乘seed/condition、忽略未结liability、并发batch id碰撞；
- report重复/null score、同condition不同scorer误作effect、全部done run充provenance；blind未知phase泄方向、NaN/缺source仍入账；
- 原original有效FAIL后建green successor仍被洗成PASS、把科学FAIL伪标technical invalidation、看结果后新增series slot/edge、漏一个预声明logical run；
- PRE result事后回填matrix SHA、执行前slot伪填runtime bytes、同一evidence造别名、共享source被迫复制、formal结果引用offline/diagnostic、completed PASS缺raw stream或exit非0；
- Gate C expected-set/result/subject/revalidation ID引入自引用、POST_COMMIT漏target ref/old SHA、LIVE重新调用provider、local result冒充revalidation、四typed集合缺/多/重复；
- 项目cost ledger tip并发双写、stale fencing reservation、单result cap代替W1/项目累计cap、事后reservation、VISIBLE/UNOBSERVABLE混合丢可见receipt、未settle即封正式result；
- artifact/claim强塞伪cloud producer、aggregate冒充selected-run产物、MISSING_PROVENANCE满足expected slot、CR-24因producer缺失从registry消失；
- run_id/date/batch/config路径escape、report/envelope/alert半写；dispatch绕过过期/错protocol/NaN预算/重复seed envelope。
- 非selected worktree脚本被自动纳入candidate/collection、脚本自建approval.key并自签、零预算却默认真7B/provider执行、audit item失败被`\|\| true`洗掉、空包`total=0`却报`agreement=1`。

### 12.4 实验者实操脚本

由未参与实现的执行者只读本文和仓内 README，从空 shell 完成：

1. 定位根目录和 Python，不依赖旧用户名；
2. 执行 fixture 回归并理解每个 E 码；
3. 制造半行、repair、resume；
4. score/review 一个复制 run，确认原 run 不变；
5. 构建临时 pack，在断网空目录 rescore；
6. 对复制 pack 做一次篡改并看到明确 FAIL；
7. 查看一项云结果的模型→输入→命令→raw→CSV→向量→报告完整链；
8. 在不查看任何 key 内容的情况下完成秘密扫描。

任何命令依赖未记录的 shell alias、人工记忆、`/tmp` 文件、热缓存或外部仓内容，均为 P1 实操缺陷。

---

## 13. 需求—出口门矩阵

| 出口 | 通过所需测试 | 当前文档预审状态 |
|---|---|---|
| G1 可重复 | PRE、S-15–17、L-03–08/19–23、C-04/05/31/34、R-01/03/05/07/09 | **静审FAIL：resume/repair/hidden依赖/非原子反例已确认** |
| G2 schema就绪 | L-01/02/08/09/19–23、I-12/13、E-15/16 | **静审FAIL：expected自指、臂标签可错、缺题默认满分** |
| G3 配方校准 | I-01–16、C-15–23/31–34、projection、parity | **未通过：hook语义偏离、monotonic FAIL、projection/parity无证据** |
| G4 首批向量 | E-07–20、C-24–29/31–33、五检标签 | **未通过：Day2 partial、表达顺序不成立、盲法/身份缺陷** |
| G5 闭环闭合 | S-15/16、P-01–11、R-08/09 | **静审FAIL：rescore/pack可空集或缺件PASS，缺外部seal** |
| G6 预算 | L-18/24、C-30 | **静审FAIL：runbook预算状态机不可执行，实际凭证仍缺** |
| G7 呈现纪律 | S-07、E-20、C-28/29/33 | **FAIL：表达报告与STATUS错标，云报告存在越线风险** |
| 云日完整 | C-00–34 全部适用项 | **FAIL/PARTIAL/BLOCKED** |
| W2 可启动 | G1–G7、云日必需门、无P0/P1/P2 | **当前不允许** |

---

## 14. 最终判定规则

### 14.1 必须输出判定向量，禁止用一个总词掩盖不同事实

最终报告至少输出：

```yaml
ASSESSMENT_PHASE: GATE_B_FINAL
TARGET_REPO_ID: <sha-or-null>
MAC_ENGINEERING: PASS|FAIL|BLOCKED|UNVERIFIED
CLOUD_RUNS:
  <run_id>:
    reported_protocol_class: ORIGINAL_W1|AMENDED_PROTOCOL|UNCLASSIFIED
    derived_protocol_class: ORIGINAL_W1|AMENDED_PROTOCOL|UNCLASSIFIED
    exact_scope_status: PASS|FAIL|BLOCKED|UNVERIFIED
    w1_aggregation_role: ACTIVE_ORIGINAL_LEGACY|AUTHORITATIVE_ORIGINAL|SUPERSEDED_ORIGINAL|AMENDED|ARCHIVAL_ONLY
    matrix_original_series_id: <stable-series-sha-or-null>
    matrix_original_series_receipt_sha256: <pre-output-series-receipt-sha-or-null>
    matrix_original_series_slot_id: <predeclared-logical-slot-id-or-null>
    matrix_original_series_status: VALID_SERIES_RUN|INVALIDATED_TECHNICAL|BLOCKED_SERIES_IDENTITY|NOT_ORIGINAL_SERIES|null
    matrix_technical_invalidation_receipt_sha256: <pre-domain-proxy-receipt-sha-or-null>
    matrix_supersedes_reason_code: PREDECLARED_TECHNICAL_INVALIDATION|PREDECLARED_REPLICATION|null
    matrix_predecessor_invalidation_receipt_sha256: <sha-or-null>
    identity_status: PASS|FAIL|BLOCKED|UNVERIFIED
    protocol_ref_sha256: <sha-or-null>
    scope_manifest_sha256: <sha-or-null>
    execution_commit: <sha-or-null>
    execution_patch_manifest_sha256: <sha-or-null>
    input_manifest_sha256: <sha-or-null>
    reported_outcome_status: PASS|FAIL|PARTIAL|UNVERIFIED
    reproduced_outcome_status: PASS|FAIL|PARTIAL|BLOCKED|UNVERIFIED
    sequence_compliance: PASS|FAIL|BLOCKED|UNVERIFIED
    effective_protocol_status: PASS|FAIL|BLOCKED|UNVERIFIED
    gate_outcomes:
      day1_calibration:
        reported: PASS|FAIL|BLOCKED|UNVERIFIED
        audited: PASS|FAIL|BLOCKED|UNVERIFIED
        effective: PASS|FAIL|BLOCKED|UNVERIFIED
        effective_basis: [<typed source/evidence id>]
        reported_negative_eligible: true|false
        reported_negative_provisional: true|false
      continuation_authorization:
        reported: PASS|FAIL|NOT_REQUIRED|BLOCKED|UNVERIFIED
        audited: PASS|FAIL|NOT_REQUIRED|BLOCKED|UNVERIFIED
        effective: PASS|FAIL|NOT_REQUIRED|BLOCKED|UNVERIFIED
        effective_basis: [<typed source/evidence id>]
        reported_negative_eligible: true|false
        reported_negative_provisional: true|false
      review_gate:
        reported: PASS|FAIL|NOT_REQUIRED|BLOCKED|UNVERIFIED
        audited: PASS|FAIL|NOT_REQUIRED|BLOCKED|UNVERIFIED
        effective: PASS|FAIL|NOT_REQUIRED|BLOCKED|UNVERIFIED
        effective_basis: [<typed source/evidence id>]
        reported_negative_eligible: true|false
        reported_negative_provisional: true|false
      day2_delivery:
        reported: PASS|FAIL|PARTIAL|BLOCKED|UNVERIFIED
        audited: PASS|FAIL|PARTIAL|BLOCKED|UNVERIFIED
        effective: PASS|FAIL|PARTIAL|BLOCKED|UNVERIFIED
        effective_basis: [<typed source/evidence id>]
        reported_negative_eligible: true|false
        reported_negative_provisional: true|false
    manifest_sha256: <sha-or-null>
    pre_output_designation_receipt_sha256: <sha-or-null>
    supersedes: <run_id-or-null>
ORIGINAL_SCOPE_MANIFEST_SHA256: <approved seed subobject sha>
ORIGINAL_SERIES:
  original_series_id: <stable-series-sha>
  original_series_manifest_sha256: <sha>
  original_series_receipt_sha256: <pre-output-receipt-sha-or-null>
  reducer_id: FAIL_DOMINANT_ALL_VALID_LOGICAL_RUNS
  series_status: PASS|FAIL|BLOCKED|UNVERIFIED
  declared_slot_ids: [<stable-slot-id>]
  realized_slot_ids: [<stable-slot-id>]
  valid_series_run_ids: [<run-id>]
  invalidated_technical_run_ids: [<run-id>]
  blocked_series_identity_run_ids: [<run-id>]
  active_tip_run_id: <run-id-or-null>
  series_graph_manifest_sha256: <sha-or-null>
SUBJECT_REGISTRY_SHA256: <sha>
EXPECTED_ASSERTION_SUBJECT_MATRIX_SHA256: <sha>
ACTIVE_ORIGINAL_LEGACY_RUN_ID: <run-id-or-null>
AUTHORITATIVE_ORIGINAL_RUN_ID: <exact-scope-run-id-or-null>
AMENDED_PROTOCOL_RUN_IDS: [<run-id>]
W1_ORIGINAL_PROTOCOL: PASS|FAIL|BLOCKED|UNVERIFIED
ORIGINAL_SCOPE_DISPOSITION:
  status: ACTIVE|RETIRED_BY_PROTOCOL_CHANGE
  authority_ref_sha256: <sha-or-null>
  authority_registry_sha256: <sha-or-null>
  successor_protocol_ref_sha256: <sha-or-null>
  approver_id: <stable-id-or-null>
  approved_at: <RFC3339-or-null>
  reason: <nonempty-string-or-null>
W1_AMENDED_PROTOCOL: PASS|FAIL|BLOCKED|UNVERIFIED|NOT_RUN
PROGRAM_PROGRESSION_AUTHORIZATION:
  status: NOT_AUTHORIZED|AUTHORIZED|REVOKED
  authorization_id: <stable-id-or-null>
  authorization_event_log_sha256: <sha-or-null>
  authority_registry_sha256: <sha-or-null>
  authority_ref_sha256: <sha-or-null>
  successor_protocol_ref_sha256: <sha-or-null>
  approval_time_w1_status: <PASS|FAIL|BLOCKED|UNVERIFIED|null>
  approval_time_w1_snapshot_sha256: <sha-or-null>
  explicit_w1_fail_risk_acceptance: true|false
  target_phase: <phase-or-null>
  approver_id: <stable-id-or-null>
  approved_at: <RFC3339-or-null>
  revoked_at: <RFC3339-or-null>
  evaluated_at: <RFC3339-or-null>
PROGRAM_MAY_PROGRESS: true|false
ARTIFACT_VALIDITY:
  <artifact_id>: VALID|PARTIAL|INVALID|BLOCKED|UNVERIFIED
CITABILITY_STATUS:
  <artifact_id-or-claim_id>: ELIGIBLE|INELIGIBLE|BLOCKED|UNVERIFIED
EVIDENCE_STAGE:
  <artifact_id-or-claim_id>: exploratory|confirmatory
OBJECT_LABEL:
  <artifact_id>: none|direction-k|named-persona-vector
EXPRESSION_CHECK:
  <expression-artifact-id>:
    evidence: NOT_RUN|PARTIAL|RECORDED
    blind_integrity: PASS|FAIL|BLOCKED|UNVERIFIED
    order: POSITIVE|NONPOSITIVE|UNVERIFIED
    decision: PASS|FAIL|BLOCKED|UNVERIFIED|CRITERION_UNDERSPECIFIED
W1_INCLUSIVE: PASS|FAIL|BLOCKED|UNVERIFIED
MERGE_ELIGIBLE: true|false
MERGE_BLOCK_REASONS: [<test_id-or-policy-reason>]
TEST_COMPLETION_SEAL: <sha-or-null>
TEST_HARNESS_TREE: <git-tree-or-null>
TEST_SUITE_MANIFEST: <sha-or-null>
TEST_POLICY: <sha-or-null>
REPORT_SEAL: <sha-or-null>
COMMIT_SEAL: <sha-or-null>
CLOSURE_SEAL: <sha-or-null>
```

所有 cloud run 都 append-only：历史 `HISTORICAL_CALIBRATION_FAIL` 永不改写。seed 的 `original_scope_contract` 以 `ORIGINAL_SCOPE_MANIFEST_SHA256` 冻结 original W1 的 protocol/runbook refs、模型与生成身份、trait/input/item/seed集合、Day1五阶段和六判据、Day2逐trait交付、表达门与预算；字段分为 `CONTRACT_FIXED`、`PREOUTPUT_FREEZE_WITHIN_ORIGINAL_ALLOWED_DOMAIN`、`UNDERSPECIFIED_AND_NOT_SILENTLY_FILLABLE`。冲突按阶段逐条裁决：正/负response抽取用vLLM；标准向量构造用pinned persona_vectors transformers；被比较的baseline、signed steering与expression臂统一transformers+bf16+validated hook；projection只认官方`eval.cal_projection`。计数与边界明确冻结：`约2000`仅是容量/费用粗估；extract正/负各n=10，Day1 compared-condition eval每题每条件n=10，Day2 baseline/±expression/scan每题每条件或极性**恰n=2**；抽取过滤为`pos>=50,neg<50,coherence>=50`。W1使用2–3 seed，V1.3的≥5从W2正式规格起；已冻结mini正式seed为17/42，temp0 seed0只是诊断。Day2多候选的候选集、selector、方向/约束、tie-breaker与并列处理必须在读取任何selector-input outcome前seal，realized selection再于首个Day2 outcome-bearing输出前机械seal；缺失不得事后静默补齐。V1.3/V0.9的formal temperature=0.7高于pinned `eval_persona.py`在n>1时硬编码的1.0及runbook省略参数/“temp=1”实现默认；original run必须在首输出前封存把0.7传入各stage并记录rendered config的binary patch/adapter，该修补是在落实原规则，不构成amended；实际1.0则AMENDED/FAIL。只有20题parity诊断为temperature=0/do_sample=false。每个适配/边界均source-sealed并过parity/differential门。`derived_protocol_class/exact_scope_status`逐字段纯函数计算。

对完整discovery corpus中每个输出前声称original且未知amended的CLOUD_RUN，`original-compatible`是三态：字段齐全且相等=`COMPATIBLE`，无已知不等但缺字段=`BLOCKED_COMPATIBLE`，已知不等=`AMENDED`；前两者都进入图和legacy候选，故缺身份不能让历史run消失，且BLOCKED永不能PASS/authoritative。图选择与实验聚合分离：固定`original_series_id=hash(original scope,normative input)`，首个original logical run首输出前一次性封存primary+全部replacement/replication slots、每slot物理attempt/seed/input/tree与非outcome技术失效谓词；跨logical run固定`FAIL_DOMINANT_ALL_VALID_LOGICAL_RUNS`，执行者无权另选。每条supersedes边只允许预声明技术替换或replication；科学PASS/FAIL/PARTIAL一经有效即永久进入series reducer，`SUPERSEDED_ORIGINAL`也继续参与，后继green不能删除前驱FAIL。只有按对所有run对称的预注册身份/完整性谓词，并在任何人或程序读取outcome-bearing raw、judge响应、score、聚合、排名、输出长度等domain proxy前封存有效receipt，才能标`INVALIDATED_TECHNICAL`并排除；晚判、读raw/score后的理由、伪receipt、科学FAIL或事后加slot均ERROR且前驱继续参与。技术失效policy只允许受限AST中的正向身份/完整性failure atom与`ALL/ANY`，禁止`NOT`、动态代码、路径或自报证据类型。所有identity/record hash均以域分隔tag构造；policy采用无环双哈希：`policy_sha256`对同时省略identity/full-record两哈希的canonical对象取值，`policy_record_sha256`只省略自身并包含前者。policy本体不得含批准自身的receipt或未来runtime evidence hash；独立pre-registry validator先从完整corpus封存`abcr.technical-resource-descriptor-registry.v1`，policy只写`TEVS-*`事前slot，随后另发不被policy反向引用的derivation receipt，series receipt才绑定三者。runtime pre-domain evidence只可在后出的`abcr.technical-evidence-resolution.v1`中解析到FORMAL_ELIGIBLE ledger；type→`INPUT_MANIFEST|CHAIN_AUDIT`→typed payload是一一映射，`RAW_OUTPUT|DOMAIN_RAW|ORACLE`及score/judge/output proxy都不可表示。各atom的slot数、顺序、same-resource/subject join和求值函数由`invalidation_predicate_evidence_signatures`固定，因此把score贴成“OBSERVED_BYTE_HASH”或把actual hash事后塞回policy均ERROR。policy/decision authority另须解析到外部人批的确定性checker registry，不能由被测run自签。新run仍须首输出前绑定全部身份、scope/input/seed、tree+patch、series slot与supersedes receipt。所有claimed-original非amended节点组成连接append-only无环图且恰一active tip；断链、分叉、多tip、缺前驱均ERROR，不能自动归`ARCHIVAL_ONLY`。标准JSON Schema不能表达的slot/run主键唯一、前驱序、跨record equality与DAG约束，由seed冻结的`abcr.original-series-graph-closure.v1`确定性validator按30个固定`GS*`错误码重放；其输入先满足`abcr.original-series-graph-closure-input.v1`，显式绑定series、policy双哈希/derivation、resource descriptors、authority、resolution、边/receipt/timeline/corpus及pre-registry sealed validator binding。该binding只依赖批准/引导/发现/harness，禁止引用后出的matrix/phase/resolved-policy，避免closure环。图closure PASS与30项对抗mutation exact-set全绿是series PASS前置；mutation records改为30个必填object key并绑定Gate B phase/harness/suite/policy/runner blob、seed contract及definition bytes，重复一个ID三十次不可能通过。生产者自报PASS无效。缺series receipt的历史节点保留为`BLOCKED_SERIES_IDENTITY`并阻止PASS，不能事后补签。

Gate B先封存完整discovery-corpus manifest，再登记current global/candidate、每个cloud run/artifact/claim，并派生九个逻辑slot定义；只有未解析slot才产生placeholder，故实际`EXPECTED_SUBJECT_SLOT` registry记录为0–9。每个slot按冻结role+schema/media class+trait+typed producer+run-manifest谓词恰一匹配；文件名/报告标签不参与。producer只允许三种版本化contract：`abcr.producer-binding.run-produced.v1`含`binding_identity_sha256,subject_kind,subject_stable_id,subject_bytes_sha256,producer_run_subject_identity_sha256,producer_run_manifest_sha256,producer_output_inventory_sha256,discovery_corpus_manifest_sha256,manifest_record_sha256`；`abcr.producer-binding.aggregate-report.v1`含`binding_identity_sha256,subject_kind,subject_stable_id,subject_bytes_sha256,source_subject_identity_sha256s,source_evidence_ids,report_manifest_sha256,discovery_corpus_manifest_sha256,manifest_record_sha256`；`abcr.producer-binding.audit-missingness.v1`含`binding_identity_sha256,subject_kind,subject_stable_id,subject_bytes_sha256,missing_required_fields,source_evidence_ids,discovery_corpus_manifest_sha256,blocks_subject_claim=true,manifest_record_sha256`。`RUN_PRODUCED`恰一registry run并继承其role，`AGGREGATE_REPORT`绑定多源report lineage但不可冒充单run，`AUDIT_MISSINGNESS`显式保留缺provenance对象并阻断；CR-24等历史对象不得因没有可证cloud producer而消失，也不得伪造producer。seed给172个assertion各生成base record；PRE-09/10/11只由exact-three bootstrap-reference manifest引用已封存PRE result，其余再展开subject profile、slot、closure与applicability context。slot多匹配/消失、selector歧义、额外/重复/dangling subject均ERROR。CR-16/17/24/26由历史selector直接路由唯一subject。contexts保存逐项`context_sources`，N/A只替换来源恰为`[BASE]`的默认candidate，含`CLOSURE`者不可替换；本版空authority registry实际禁止N/A。baseline/detection-baseline不是W1终态输入。旧finding instance不会被“关闭”；新run产生新subject instance。

final adjudication 使用seed的 `abcr.cloud-gate.v1` 全函数，runner/report自填的audited标量被忽略。audited状态只能从sealed原始证据派生：Day1逐一重算六门；输入矛盾→FAIL，必需输入不可得→BLOCKED，尚未正式审计→UNVERIFIED，完整且任一门FAIL→FAIL，六门全PASS→PASS。Day2逐trait重算：强制科学/完整性门FAIL→FAIL；缺输入但sealed完整omission inventory证明严格非空子集→PARTIAL，证明Day2启动后零交付→FAIL，证明全部交付存在但checker/source/identity等其他审计输入缺失→BLOCKED，无完整omission inventory→BLOCKED；输入存在未审计→UNVERIFIED；完整三trait且至少一anchor有效原协议表达PASS→PASS。每种状态都要非空typed basis，非法组合使计算器ERROR并停止输出W1/merge判定。

`reported_negative_eligible` 按numeric failure、explicit omission、sequence failure三类证据分别校验；仅在允许的FAIL/PARTIAL source已content-addressed并SEALED、绑定registry中`ACTIVE_ORIGINAL_LEGACY|AUTHORITATIVE_ORIGINAL|SUPERSEDED_ORIGINAL`且`matrix_original_series_status=VALID_SERIES_RUN`、身份/时间/所需字段完整且无冲突时为true。seed的`abcr.reported-negative-eligibility.v1`机器record以互斥`ELIGIBLE|BLOCKED_MISSING|INELIGIBLE_SERIES|REJECTED_CONFLICT`分支封闭role×series-status×scope×profile×conflict，并把source registry/bytes/seal/scope-input与typed EV逐项hash绑定；有效`SUPERSEDED_ORIGINAL`可贡献负面，有效技术失效或archival/amended不可。其`reported_negative_id`、`recomputed_fields_sha256`与`record_sha256`均用域分隔无环constructor；`abcr.reported-negative-calculation-input.v1`进一步绑定audit/seed/完整corpus/registry/source、profile EV、stronger-evidence exact-set及Gate B calculator binding/source/harness/suite。独立计算器忽略producer的identity/profile/status/reason声明，从认证输入重算字段；状态按`REJECTED_CONFLICT > INELIGIBLE_SERIES > BLOCKED_MISSING > ELIGIBLE`的明文互斥优先级导出，reason codes只输出**最终dominant branch**内为真的码并按固定枚举序形成exact set，不能混入低优先级分支。任一错码、漏码、自报false、任意validator SHA不在精确harness/suite或hash不一致均ERROR；把原本合格source的stored identity改false/blocked不会被采信。legacy要求完整corpus中同期original声明及所有已观察scope字段相等；任何缺字段使资格BLOCKED、已知不等转amended。eligible negative只能产生FAIL/PARTIAL，永不能产生PASS。Gate A未封存观察只能标provisional且不进reducer。effective优先级为audited FAIL、eligible reported FAIL、Day2 audited/eligible PARTIAL、audited PASS/合法NOT_REQUIRED、audited BLOCKED、audited UNVERIFIED；reported PASS绝不授权PASS。

continuation仅在Day1 PASS，或完整时间线证明校准后无任何动作时可NOT_REQUIRED；Day1 FAIL且有后续动作时，只有动作前、唯一绑定失败项/scope的waiver才PASS，已穷尽语料证明缺失/迟到/错绑才FAIL，语料未穷尽为UNVERIFIED，材料不可得为BLOCKED。review仅在完整时间线证明未开始Day2时可NOT_REQUIRED；一旦Day2开始，只有开始前绑定指定REVIEW-REQUEST/scope的approval才PASS，迟到/错绑/穷尽后缺失才FAIL。waiver不改变Day1 FAIL。`reported_outcome_status`只消费eligible reported negative/两门sealed reported PASS；`reproduced_outcome_status`只消费Day1/Day2 audited状态，按FAIL>PARTIAL>BLOCKED>UNVERIFIED>PASS，绝不把reported negative冒充复现。`sequence_compliance`按FAIL>BLOCKED>UNVERIFIED>PASS/NR。每个series成员的`effective_protocol_status`对identity与四门强AND，mandatory PARTIAL归FAIL；`W1_ORIGINAL_PROTOCOL`对全部非技术失效成员按FAIL/PARTIAL>BLOCKED>UNVERIFIED>PASS归约，且PASS还要求预声明slot全集完成、唯一active tip为AUTHORITATIVE_ORIGINAL并PASS。`W1_INCLUSIVE`再合取current global/current candidate；后继green永不覆盖前驱有效FAIL。

retirement/progression 使用seed的闭合字段矩阵和sealed authority registry。`ACTIVE`当且仅当退休字段全null；`RETIRED_BY_PROTOCOL_CHANGE`要求现行协议所有者明确替代V1.3对应入口，绑定authority registry、successor、人、时、理由；只允许append-only ACTIVE→RETIRED，退休不改任何run/W1状态。例外推进采用按 `authorization_id+target_phase` 的append-only `APPROVED/REVOKED`事件账本：批准时冻结W1状态与快照，REVOKED引用既有批准且历史不删除；查询结果按明确`evaluated_at`输出NOT_AUTHORIZED/AUTHORIZED/REVOKED。`PROGRAM_MAY_PROGRESS(target_phase,evaluated_at)=(W1_INCLUSIVE==PASS) OR 该时点该阶段存在有效未撤销且明确接受W1非PASS风险的授权`；retirement、amended PASS、普通receipt不能扩权到其他阶段、时间或merge。

`ARTIFACT_VALIDITY` 评价具体产物的输入、实现、评分和证据链；`CITABILITY_STATUS` 按 §11 真值表评价具体 artifact/claim；`EVIDENCE_STAGE` 与 `OBJECT_LABEL` 又是两条独立科学轴。一个 provenance 完整的负校准可以 `CITABILITY_STATUS=ELIGIBLE`、`EVIDENCE_STAGE=exploratory`、`OBJECT_LABEL=direction-k`；科学效应为零或反向，只要协议与测量有效，也不是软件 FAIL。历史 manifest 的 `citable` bool 仅由 ELIGIBLE 映射为 true。

### 14.2 `W1_INCLUSIVE=PASS` 的充要门

只有同时满足以下条件才判“ABCR W1（含云日）工程终验 PASS”：

1. `MAC_ENGINEERING=PASS`，存在身份完整、slot全集闭合且唯一active tip为`AUTHORITATIVE_ORIGINAL_RUN_ID`的original series；`W1_ORIGINAL_PROTOCOL=PASS`必须由`FAIL_DOMINANT_ALL_VALID_LOGICAL_RUNS`对全部有效成员的四项gate真值表机器导出，不能只看authoritative tip；仅`W1_AMENDED_PROTOCOL=PASS`不足；
2. PRE 至 R 对 current global、当前 candidate、authoritative original run及全部`matrix_original_series_status=VALID_SERIES_RUN|BLOCKED_SERIES_IDENTITY`的original成员之完整 assertion×subject 矩阵均已实际执行并按series规则归约，无 BLOCKED/UNVERIFIED 被折算为 PASS；有效`SUPERSEDED_ORIGINAL`继续进入`FAIL_DOMINANT_ALL_VALID_LOGICAL_RUNS`，只有`ARCHIVAL_ONLY`和在raw/domain proxy前机械证明的`INVALIDATED_TECHNICAL`排除；
3. G1–G7 分别有机器证据，云日计划内每个 trait 按冻结交付范围逐项闭合，且至少一个 anchor trait 有有效 `W1_EXPRESSION_PASS`；仅 `W1_EXPRESSION_RECORDED/ORDER_OBSERVED` 不足以关闭该实验出口。历史 PASS 必须有同期盲化裁决，未来 PASS 必须有看结果前冻结的判据；
4. 全部适用 mutation 被语义测试杀死，确定性 fixture 连续10轮零 flake；
5. 测试前后 candidate tree 与 canonical 历史证据不变，所有修复、测试、报告绑定同一 `candidate_tree`；
6. current global、当前 candidate 与全部参与original series reducer的subject无未解决P0/P1/P2；其他历史subject未解决项继续阻断其自身claim/citability并完整报告，不以“归档”改写；
7. artifact/claim 引用资格、证据阶段与对象标签按各自门独立、真实输出，最终核心数字由 manifest 生成。

这个 PASS **不**表示五检全过、跨引擎全局等价、人格假设成立或所有 trait 都能命名；这些结论各有独立证据门。

若原冻结 monotonic 因 ceiling 或 engine/scope矛盾被认为不再科学合适，允许由符合 §14.1 结构的正式 successor authority 另批 amended protocol，并将 original scope 行政标记为 retired；但单次 `+2=+3.5=100` 不能证明“定义上永不可达”，测试方案也无权追溯改写原门。此时诚实终态可以是 `W1_ORIGINAL_PROTOCOL=FAIL + ORIGINAL_SCOPE_DISPOSITION.status=RETIRED_BY_PROTOCOL_CHANGE + W1_AMENDED_PROTOCOL=PASS + W1_INCLUSIVE=FAIL`。继续项目只能由同一 successor authority 明文给出 `PROGRAM_PROGRESSION_AUTHORIZATION.status=AUTHORIZED` 且接受 W1 未通过风险；普通审批回执不能借新枚举冒充 W1 original PASS或覆盖 V1.3。

### 14.3 FAIL、BLOCKED、PARTIAL 与合并资格

- Mac 工程全绿但 original cloud protocol 不全：`MAC_ENGINEERING=PASS / W1_ORIGINAL_PROTOCOL=FAIL或BLOCKED / W1_INCLUSIVE=FAIL或BLOCKED`，不得用“W1 已完成”概括；即使 amended run PASS 也须并列写明。
- 单个方向有部分有效证据但表达/五检不全：artifact 标 `PARTIAL`，并分别输出 `EVIDENCE_STAGE=exploratory` 与 `OBJECT_LABEL=none或direction-k`；引用资格按 artifact/claim 独立判断，不能由方向有效或未命名自动推导。
- 旧结果被实现 bug 或协议越门影响且无法无偏修复：对应 artifact 标 `INVALID`；原件保留供审计，不从记录删除，也不用新 run 覆盖历史判定。
- 因 SSH、原源码、云包、权限或成本授权不可得而不能验证：对应轨为 BLOCKED/UNVERIFIED，列出精确恢复输入、预算和预计时长。
- `MERGE_ELIGIBLE` 与 `W1_INCLUSIVE` 分开，并由封存的 test-policy 自动计算：只有 `blocks_merge=true` 的适用项全 PASS、候选树无未解决代码 P0/P1/P2、证据 seal 完整且提交内容安全时才可为 true；每个 false 必须列 `MERGE_BLOCK_REASONS`。历史云 run 仍 FAIL 不必阻止合并已完整验证的防越门测试/修复，但绝不能把该合并解释为实验 PASS。

### 14.4 当前文档预审向量（不是正式测试结果）

```yaml
ASSESSMENT_PHASE: GATE_A_STATIC_PREAUDIT
TARGET_REPO_ID: null
TARGET_REPO_ID_STATUS: UNSEALED
GATE_B_ENTERED: false
GATE_B_ENTRY_BLOCKERS: ["APPROVE_PLAN_MISSING"]
COSTED_TRACKS_AUTHORIZED: false
COSTED_TRACKS_BLOCKER: "APPROVE_COST_MISSING；不阻断零成本 Gate B 轨"
MAC_ENGINEERING: FAIL
CLOUD_RUNS:
  reported-cloud-run-20260714:
    reported_protocol_class: ORIGINAL_W1
    derived_protocol_class: UNCLASSIFIED
    exact_scope_status: BLOCKED
    w1_aggregation_role: null
    provisional_w1_aggregation_role: ACTIVE_ORIGINAL_LEGACY
    provisional_role_basis: "complete discovery corpus and registry are not sealed; this hint is not a formal role and is not consumed"
    matrix_original_series_id: null
    matrix_original_series_receipt_sha256: null
    matrix_original_series_slot_id: null
    matrix_original_series_status: BLOCKED_SERIES_IDENTITY
    matrix_technical_invalidation_receipt_sha256: null
    matrix_supersedes_reason_code: null
    matrix_predecessor_invalidation_receipt_sha256: null
    identity_status: BLOCKED
    reported_outcome_status: UNVERIFIED
    reproduced_outcome_status: BLOCKED
    sequence_compliance: UNVERIFIED
    effective_protocol_status: BLOCKED
    gate_outcomes:
      day1_calibration:
        reported: FAIL
        audited: BLOCKED
        effective: BLOCKED
        effective_basis: ["Gate A report observation is corroborated but not yet sealed as a formal baseline; audited raw inputs remain unavailable"]
        reported_negative_eligible: false
        reported_negative_provisional: true
      continuation_authorization:
        reported: UNVERIFIED
        audited: UNVERIFIED
        effective: UNVERIFIED
        effective_basis: ["approval-message-corpus-not-exhaustive"]
        reported_negative_eligible: false
        reported_negative_provisional: false
      review_gate:
        reported: UNVERIFIED
        audited: UNVERIFIED
        effective: UNVERIFIED
        effective_basis: ["review-message-corpus-not-exhaustive"]
        reported_negative_eligible: false
        reported_negative_provisional: false
      day2_delivery:
        reported: PARTIAL
        audited: BLOCKED
        effective: BLOCKED
        effective_basis: ["Gate A report/archive observation is provisional and the formal omission inventory/input identity is unsealed"]
        reported_negative_eligible: false
        reported_negative_provisional: true
    manifest_sha256: null
    pre_output_designation_receipt_sha256: null
    supersedes: null
ORIGINAL_SCOPE_MANIFEST_SHA256: "ee636875efad961a9e63c7f1b8c43a9df38b81b2594415774c1175036210b16c"
ORIGINAL_SERIES:
  original_series_id: null
  original_series_manifest_sha256: null
  original_series_receipt_sha256: null
  reducer_id: FAIL_DOMINANT_ALL_VALID_LOGICAL_RUNS
  series_status: BLOCKED
  declared_slot_ids: []
  realized_slot_ids: []
  valid_series_run_ids: []
  invalidated_technical_run_ids: []
  blocked_series_identity_run_ids: [reported-cloud-run-20260714]
  active_tip_run_id: null
  series_graph_manifest_sha256: null
SUBJECT_REGISTRY_SHA256: null
EXPECTED_ASSERTION_SUBJECT_MATRIX_SHA256: null
ACTIVE_ORIGINAL_LEGACY_RUN_ID: null
PROVISIONAL_LEGACY_CANDIDATE_RUN_ID: reported-cloud-run-20260714
AUTHORITATIVE_ORIGINAL_RUN_ID: null
AMENDED_PROTOCOL_RUN_IDS: []
W1_ORIGINAL_PROTOCOL: UNVERIFIED
ORIGINAL_SCOPE_DISPOSITION:
  status: ACTIVE
  authority_ref_sha256: null
  authority_registry_sha256: null
  successor_protocol_ref_sha256: null
  approver_id: null
  approved_at: null
  reason: null
W1_AMENDED_PROTOCOL: NOT_RUN
PROGRAM_PROGRESSION_AUTHORIZATION:
  status: NOT_AUTHORIZED
  authorization_id: null
  authorization_event_log_sha256: null
  authority_registry_sha256: null
  authority_ref_sha256: null
  successor_protocol_ref_sha256: null
  approval_time_w1_status: null
  approval_time_w1_snapshot_sha256: null
  explicit_w1_fail_risk_acceptance: false
  target_phase: W2
  approver_id: null
  approved_at: null
  revoked_at: null
  evaluated_at: "2026-07-14T20:33:21-07:00"
PROGRAM_MAY_PROGRESS: false
TRANSFER_INTEGRITY:
  observation: OBSERVED_MATCH
  seal_status: UNSEALED
ARTIFACT_VALIDITY:
  "vector-standard claims": INVALID
  "raw calibration": BLOCKED
  "optimistic subset vectors": UNVERIFIED
  "conscientiousness response vector": PARTIAL
  "neuroticism response vector": PARTIAL
  "openness response vector": BLOCKED
CITABILITY_STATUS:
  "vector-standard claims": INELIGIBLE
  "raw calibration": BLOCKED
  "protocol-completion claim": INELIGIBLE
  "sequence-compliance claim": UNVERIFIED
EVIDENCE_STAGE: "按artifact/claim均为exploratory"
OBJECT_LABEL: "现有对象最多为reported direction candidate；验真前按artifact记none"
EXPRESSION_CHECK:
  expression/mac/conscientiousness/current:
    evidence: PARTIAL
    blind_integrity: FAIL
    order: NONPOSITIVE
    decision: FAIL
W1_INCLUSIVE: FAIL
MERGE_ELIGIBLE: false
MERGE_BLOCK_REASONS: ["APPROVE_PLAN missing", "no approved candidate_tree", "CR-01..CR-45 unresolved", "formal Gate B suite not run"]
```

这里的 `MAC_ENGINEERING=FAIL` 来自已corroborate的源码控制流反例，不是pytest结果，因此当前 `W1_INCLUSIVE=FAIL`。旧报告只自称original，因完整corpus/registry未封存而没有正式selected run；`ACTIVE_ORIGINAL_LEGACY`仅作不参与计算的provisional hint，故按`UNVERIFIED_NO_SELECTED_ORIGINAL`输出`W1_ORIGINAL_PROTOCOL=UNVERIFIED`。其Day1 monotonic FAIL与Day2 PARTIAL也只是provisional negative，不能折算original FAIL。Gate B若完成身份、scope/input、图与证据seal，可正式选出active legacy并把合格negative升级为eligible，届时纯函数可能输出FAIL或BLOCKED。waiver/REVIEW语料仍未穷尽；`TRANSFER_INTEGRITY.seal_status=UNSEALED`表明这只是Gate A预审，不能冒充正式回归。

---

## 15. Gate B 预期交付物

审批通过并完成测试后，必须交付：

1. `ABCR-W1对抗终验报告-<date>.md`；
2. 源码树外耐久目录 `$ABCR_AUDIT_ROOT/<audit_id>/test-results.jsonl`、bootstrap intent/observation与exact-three reference manifest、每phase identity/execution-envelope/evidence requirement/slot/completion、checkpoint chain、`test-completion-seal`及最终封存归档；
3. `target_repo_id`、需求追踪矩阵、CR-01–45 closure-mode账本（代码red→green、历史detection/domain双状态、evidence blocker）、original-series id/receipt/slot/graph/status及`FAIL_DOMINANT_ALL_VALID_LOGICAL_RUNS`逐成员归约明细；
4. 缺陷清单（根因、影响范围、历史 run/artifact/claim 失效矩阵、修复 commit 计划）；
5. `test_harness_tree/test_suite_manifest/assertion_inventory`、baseline red、`candidate_tree`、相对 baseline 的 binary full-index diff、candidate object pack、baseline bundle、SHA256、明确排除清单及灾难恢复结果；
6. 全回归、147-root/172-assertion/172-policy-check inventory、subject registry与assertion×subject矩阵、resolved policy、typed consumer/role/ordinal exact-set、三类producer-binding manifest、series schema/reducer、mutation、flake、secret scan、pack tamper、eligibility/最终判定真值表及云证据审计结果；
7. 唯一项目成本账本的genesis/tip、每reservation的approved action/金额/liability、每local/provider/settlement/release记录、`required_action_ids == visible_action_ids`coverage、完整cost receipt与停止计费凭证；无计费则给零动作证明并仍封存项目账本身份；
8. 明确的提交/合并清单、`gate_c_post_work_definition_manifest`、post-commit/post-merge expected-set、LIVE revalidation required-evidence exact-set与seal分层；
9. 若仍 BLOCKED，按每个缺失输入的唯一标识列出精确清单，不提出开放式讨论题。

人工审批 Gate B 报告后，才进入提交与合并。

---

## 16. 本版相对 V1.0 测试方案的关键变化

1. 范围从“云端三个修改点”扩为 W1 Mac + 云日 + V1.3 证据语义全链。
2. 新增受测仓/云包恢复、commit 与 SHA 的 PRE 硬门，解决旧路径不可执行问题。
3. 所有用例补齐输入、断言、失败处置和证据格式；删除“打印后人工看”的假测试。
4. DeepSeek token/seed、pos-neg 对齐、judge可重算全部升为 P0。
5. 修正旧方案两处技术预设：left-padding统一按 padded width 截取不先判 bug；temp0 由 `do_sample=False` golden test裁定。
6. 新增回归纯度门，禁止测试重写 canonical judge/artifact。
7. 新增多trajectory、run_id并发、manifest自封存、symlink/path traversal、mutation和10次flake测试。
8. 云日门按实际执行重判：monotonic FAIL 不得口头放行；parity、projection、Day2表达检/扫描/激活缺失均是硬缺口。
9. citable 按 artifact/claim、证据阶段与对象命名拆成三条机器状态轴，杜绝报告措辞先于证据。
10. 固化两次人工审批：先批方案，再批测试报告；最后才提交、post-commit验证和合并。
11. 新增对真实 `e02d4c3...` 历史锚及 `9d579e5...` 当前增量的全源码、测试、shell、控制面、既有工件与 ignored/nested依赖 Gate A 静审，固化 CR-01–45；历史“全绿”已被多个必现反例击穿。
12. 实取 cloud tar 并核对 SHA/27文件结构，把 transfer integrity 与 run identity/artifact validity/protocol status拆开。
13. 新增测试 harness 元门：required skip/return/collection副作用不得变绿，unit/shell/runbook进入完整 inventory。
14. 修正 response-only 首 token语义；新增 pinned upstream differential、condition↔method穷举、vector三件套与 capture逐token身份门。
15. original W1 与 amended protocol 分轨；amended PASS不得洗绿原 W1。每个 cloud run输出四项 gate outcomes及完整代码/scope/input身份。
16. candidate 在审批期间用 bundle/object pack/binary diff耐久恢复；eligibility计算器、target repo identity、test/commit/closure seal均成为P0受测对象。
17. 新增 Gate A policy seed、147-root/逐 assertion inventory、test-harness tree 与同测试字节 baseline-red→candidate-green 纪律，消除临场决定 blocking 和“改测试只跑绿”的出口。
18. 新增 S-15–17，对脱敏器、policy/seal、numeric oracle/tolerance工具本身做黄金输入与 mutation；成本证据改为多 reservation/provider-attempt/settlement manifest。
19. 独立裁定 Claude NEW-01..18：接受/归并真实反例，明确驳回 dtype 混加、step级抽样、同模型家族等误判；修正云5pt的3+2构成与1D/2D分叉。
20. 拆分 reported/reproduced/sequence-compliance，未知 waiver/REVIEW 保持UNVERIFIED；行政退役不得洗绿original FAIL。修复Mac Air耐久路径和Gate C锁竞态。
21. original run改为预注册series：七个matrix字段、slot/receipt/supersedes图与fail-dominant reducer机械绑定；有效SUPERSEDED FAIL继续参与，只有raw/domain proxy前证明的技术失效可排除。
22. 显式裁决original scope冲突：约2000仅粗估；extract/Day1/Day2计数分别10/10/恰2；W1 2–3 seed而≥5从W2起；抽取边界`>=50/<50/coherence>=50`；Day2 selector/tie-breaker必须事前封存。
23. 证据协议拆分bootstrap intent/observation/reference、typed consumer+role+ordinal、execution envelope、POST work-definition与三类producer binding；成本协议补项目账本身份及逐reservation/provider action exact coverage。
24. 活体main基线更新到`edbd351.../198c23...`并隔离时变`r2-integration`候选；新增报告与任何未封存pytest数字都不继承Gate B PASS，非selected worktree脚本不得自动进入candidate或执行。
25. 关闭独立复核发现的三个P0机器空洞：技术失效改为事前resource descriptor+slot、事后typed resolution且无policy/approval循环；reported-negative补域分隔constructor、独立input/binding与dominant-branch reason函数；closure/mutation补无环validator binding和30-key exact object，拒绝自报PASS、任意validator SHA与重复mutation ID。

---

## 17. 本版审查输入基线

以下 SHA256 是本版制定时实际逐行审查的输入版本；后续文档若变化，须先做语义 diff，不能默认沿用本方案的判断。

| 文档 | SHA256 |
|---|---|
| ABCR-实验方案-V1.3.md | `bb0fafb8650b4c295b5966e2a90258e9a8f6991e14bf942143604d76399d13ab` |
| ABCR-W1方案-最小纵向闭环-V0.9.md | `43c3a82e74e08e1a75c3dbca706d6bb499988e6dba44ecbb0a4d5b412aca649d` |
| ABCR-W1执行方案-V1.0.md | `b4d39632560b54dac663b9ce63b0180258fbd4764f1f0d76de7bc5a50c1df332` |
| ABCR-W1执行方案-V1.1补丁-资源治理门与节奏修订.md | `5addf84a96365687b91b88b5324fe72993864f5d2027292a6e2202162f7b4608` |
| ABCR-W1剩余工作图-批2批3-20260712.md | `243de9b194406d0fac8459f8cf29b1c61dd00cd9ab62cb4f7a5a7cf2240bd967` |
| ABCR-W1指令分派指引-冻结版-20260712.md | `9fdca08a7f1171bedbb44fa0b1830648a68dad8e89de695ddd4623f1ff42d848` |
| ABCR-W1测试方案-V1.0.md | `11b81abef52020d8584b4a9d32e41619bc1b7862e323ae275e50216cfed1193c` |
| ABCR-W1终验报告-20260713.md | `dc6fb5039c2e099c94a3c849c3c8eafff95a2edf58f08843a60e90000939eb02` |
| ABCR-云日执行交接状态-20260713.md | `b8d2397ef442487d658054ae389a15e78b698c07c63e1614d805c9d369bfa490` |
| ABCR-云日执行报告-20260714.md | `932e658fab476f6ec9f2d91100c30f7c0cb4a36ecb47d5f5390c402d98840020` |
| ABCR-W1工程包A-Runner-Episode-Ledger-V1.0.md | `954d0cf779e38446372c4ee598004872b5b83ea6805ea476bfa9ff35a9f450d6` |
| ABCR-W1工程包B-Hook-Intervention-PV复现-V1.0.md | `6d455a0eb39f06ffa8716c244c4e2a71becc2fac019934935d60d10ccb815ad9` |
| ABCR-W1工程包C-Scorer-Audit-ReproPack-V1.0.md | `2d2bf33b71000b1c1b832d06b1251bda578c81a06c46e6073d88eaec80ac3a2b` |

最初真实工程/产物静审锚（用于复现 CR-01–32 与规范输入，不代表当前HEAD）：

| 对象 | 只读核验值 |
|---|---|
| canonical repo | `superagent@192.168.3.70:/Users/superagent/abcr`；branch `main` |
| outer commit/tree | `e02d4c3ccb777d850bb9e6aa687e89ff75648ad8` / `74ebf32fc8446dc28165572808b1c357adda2076` |
| outer tracked status | 无 staged/modified/deleted；另有未跟踪 cloud结果与 `.DS_Store`，以及 ignored env/upstream/model/checkpoint |
| Gate A read-only clone | `/private/tmp/abcr_gate_a_review_20260713`；只用于本轮逐行静审，不是 Gate B 测试工作树 |
| nested persona_vectors | detached `b8e0f044fe2410a6fad579f38324f03f13b4e917`；tree `cdf80e84887de88f5756f6eae7e1971b99a1a763`；`config.py/generate_vec.py` dirty |
| nested dirty binary diff | SHA256 `80a59c9c08d9b7c2d02a18dc789fec67668dd06adc4286cdee1cafd4aa674671`；实际 `config.py`=`15d33067cb791bcdaff54dd647cb7526b328d32137b508ea90d420c0e0790cf9`，`generate_vec.py`=`d4e25882a5997990358e57706f15cd53c95fc2b20c8ec9c562699f3489cb31c5` |
| cloud archive | 5,337,506 bytes；SHA256 `82681b6bda04c81cb6cbbdcd9b0337a333e9b88ed5277c531bd853602cda536a`；安全解包27文件 |
| cloud archive结构 | Day1 9 logs + 7 CSV + 3 pt；Day2 6 CSV + 2 pt；5 pt均layers14–24/bfloat16，4文件逐层`(3584,)`、prompt-last逐层`(1,3584)`；无内部 manifest/raw/card/meta/Day2 logs/openness vector |

上述代码锚点行号仅对该 commit 有效。它完整保存 CR-01–32 与13个 normative input 文件的来源身份；当前 remote 已由后续提交推进，见§19。Gate B 必须对获批时目标重做语义diff并重建行级CR映射，不得把行号漂移当作缺陷消失。本轮没有创建工程分支、没有运行 pytest/模型/API/正式回归、没有修改 Mac mini 仓，也没有提交或合并。

---

## 18. Claude 补充的独立裁定与纳入记录（2026-07-14）

> 谱系：Claude 追加前的 parent plan SHA256 为 `6cf0db7aaecdd4efba50af85d3472944170185a2db5820312f60444e3a0424b8`；原始追加版全文件 SHA256 为 `bc98d6f0a4e49a0f3cb5f9374005349e3f16ab058617d52fb8f961156f28c9ad`。两者都只是历史 checkpoint，**均不具本版审批效力**。本节与 §0–§17 同属单一审批对象，最终批准只能绑定整合完成后的全文件 SHA 和 policy seed SHA。
>
> 方法：对补充中的每条源码/工件主张重新读取 pinned tree、两份 parity runbook、冻结协议和云 archive metadata；有效项并入规范正文，重复项归并，事实错误明确驳回。以下状态均为 Gate A finding status，不是 §4.2 的正式测试 PASS。

### 18.1 已复核的观察证据

| evidence_ref | 观察 | finding_status | seal_status | 正文落点 |
|---|---|---|---|---|
| OBS-01 | archive SHA观察值=`82681b…36a`，安全清单=27文件（Day1 9log+7csv+3pt；Day2 6csv+2pt） | `CORROBORATED_EVIDENCE` | `UNSEALED` | §0.1、PRE-03/14、§11/17 |
| OBS-02 | 13 CSV 的行数/null/trait mean逐格重算吻合；完整 join key 缺失 | `CORROBORATED_EVIDENCE` | `UNSEALED` | §11、C-13/14 |
| OBS-03 | 5 pt均为dict、key14–24、bf16；4文件逐层`(3584,)`，prompt-last逐层`(1,3584)` | `CORROBORATED_EVIDENCE` | `UNSEALED` | CR-17/26、C-17 |
| OBS-04 | 当前表达报告为 baseline=71.12、pos=68.92、neg=59.17；STATUS只凭pos>neg称“方向正确”，另有无baseline旧报告 | `CORROBORATED_EVIDENCE` | `UNSEALED` | CR-24、E-20、C-25 |
| OBS-05 | `cloud-results.sha256` 含云端绝对路径 `/root/autodl-tmp/cloud-results.tar.gz` | `CORROBORATED_EVIDENCE` | `UNSEALED` | PRE-14、P-01 |
| OBS-06 | Claude补充裁定checkpoint时SSH只读值为 `main@e02d4c3...`/tree `74ebf32...`；这是历史观察，已被§19的新HEAD观察取代 | `CORROBORATED_STATIC` | `UNSEALED` | §17/19；Gate B仍须重封 |

`OBS-01/02/03/06` 未生成正式 audit_id、result row、stdout/stderr seal，故不能标 PRE/C/R 的 PASS；Gate B 必须重放。`OBS-04/05` 是现存原件自身的反例，允许作为 Gate A confirmed evidence finding，但仍不冒充动态修复验证。

### 18.2 旧 CR 的措辞复核裁定

| 项 | 最终裁定 |
|---|---|
| CR-09 | 接受“有状态 prefill heuristic”校准，已直接改正文；补同一context第二次generate测试。 |
| CR-10 | 不接受“正文曾声称完全不校shape”的指控。最终改为loader-specific：residual/projection只校整shape，random reference更弱，三者均缺完整身份/dtype/finite/nonzero校验。 |
| CR-23 | **保持成立，不降级。** `cloudday1-official-trait.md` 确实在各截200字符后exact compare，且5% smoke注释称双极但命令只跑pos；`parity-smoke.md` 的`[:300]`仅展示，但其token分母/前50 token/只抽3条single/只比第0条仍有独立缺陷。两份脚本分开记证据。 |
| CR-17 | 修正5 pt构成和1D/2D shape；不再写成“全部逐层3584一维”。 |
| 严重级 | 原复合等级已按最高影响规范为单一级；CR-12/14/18/21/22=P0，CR-24=P1。 |

### 18.3 Claude `NEW-01..18` 的逐项裁定

| 原编号 | 裁定 | 规范化结果 |
|---|---|---|
| NEW-01 | 接受 | 独立根因记 CR-25；E-16/L-09/10 杀手门。 |
| NEW-02 | 接受并收窄措辞 | 记 CR-26：“现有云 dict/subset 文件不能被标准 arm 直接加载”；转换是新 artifact，不反证原件有效。 |
| NEW-03 | 接受并纠正 | 记 CR-27；仅跨臂 prompt-hash 子门对单condition run不执行，manifest forbidden-key 子门仍执行。 |
| NEW-04 | 接受并纠正 | 记 CR-28；不是“10秒内瞬时强夺”，而是owner不可读且age≥10s时未证明PID死亡即可回收，存在迟写覆盖和缺fencing风险。 |
| NEW-05 | 原指控驳回、真实缺口归并 | copy后对payload算内manifest hash是正常职责；未绑定approved candidate/input外部trust anchor并入CR-20/P-02/P-11。 |
| NEW-06 | 接受、归并 | rescore链字段opt-in并入CR-20/P-10 mutation。 |
| NEW-07 | 接受、归并 | 任意同hash文件替代声明split身份并入CR-04/L-10/22/E-16。 |
| NEW-08 | 接受、归并 | 生成未seed torch而只seed shuffle并入CR-19/E-18。 |
| NEW-09 | 驳回为“新缺陷” | 0.25已由E-09明确冻结为上游聚合输入门且不代表judge真值；只要求版本化常量、边界与policy SHA。 |
| NEW-10 | 驳回事实表述 | DeepSeek与Claude不是同模型家族；代码报告已有“仅漂移、不作独立效度” caveat。STATUS若越权由S-07 claim lint处理。 |
| NEW-11 | 条件成立、归并 | 当前runner每step新context，未证明历史正式run已跨序列污染；API复用同一context时风险成立，并入CR-09/I-06/07。 |
| NEW-12 | 接受 | 记CR-29；batch index0反例成立，projection恒null也纳入I-15。 |
| NEW-13 | 驳回事实错误 | `residual_vector.py:84-85` 已把vector显式cast到model dtype/device，不存在所称float32直接混加；cast误差由I-03/S-17测，但不是该缺陷。 |
| NEW-14 | 接受 | 记CR-30；unknown stop不得伪造为eos。 |
| NEW-15 | 驳回 | 冻结协议明确按`sha256(item_id)`抽10%题目，同item各seed均命中是当前contract，不是step-level bug。 |
| NEW-16 | 条件接受并纠正 | 仅tracked `configs/protocol_ref.txt`缺失时触发运行期仓外读取/写config，记CR-31。 |
| NEW-17 | 接受、归并 | Docker quit后的二次探针fail-open是CR-11/L-21的mutation，不另造finding。 |
| NEW-18 | 接受、归并 | 位置式sample ID fallback并入CR-19/E-18。 |

Claude补充裁定checkpoint另发现 `run()` 在config schema验证前索引字段并可能取heavy lock，记为 CR-32；因此该历史checkpoint的静态账本为 CR-01..32。“NEW-01..18整包确认”及“至少4条P0全都新增测试门”的原说法被撤销；当前账本另见§19的CR-33..45。

### 18.4 方案级 P-A..P-J 的最终处置

| 项 | 裁定与已落实修改 |
|---|---|
| P-A | 成立。§4.5与伴随policy seed冻结147个root ID、blocking/cost/track/merge推导；Gate B只可纯函数解析candidate影响。 |
| P-B | 成立。§4.1规定原子finding单一级；本版复合CR已规范化。 |
| P-C/P-D | 成立但“1000样本研究级oracle”属夸大。§4.4定义小型独立oracle，新增S-15脱敏器、S-16 policy/seal、S-17 tolerance/oracle；eligibility仍由R-08。 |
| P-E | “新增W1_ORIGINAL_RETIRED成功态”驳回。§14只允许正交的`ORIGINAL_SCOPE_DISPOSITION`，不能洗掉original FAIL或令W1-inclusive变绿。 |
| P-F | 属资源意见，不是正确性反例。§0.2补充比例理由和最小化边界，不降低身份、seal、recovery门。 |
| P-G | 驳回新状态。保持§4.2唯一词表，用`blocker_class=PROVIDER_UNOBSERVABLE`；E-13供应商账单字段仅条件核验。 |
| P-H | 原正文已限定无计费fixture；R-03/§12.1再次明确10×不含3B/stage2–4/API/GPU。 |
| P-I | 成立。所有5pt描述已统一为3+2构成及4个1D/1个2D。 |
| P-J | 仅“账本非穷尽”成立。经逐项复核后纳入CR-25..32，而非照单纳入18条。 |

此外，本轮独立发现并已修正四个补充未覆盖的流程缺口：① test+fix共树无法证明red/green使用同一测试字节，现新增`test_harness_tree/test_suite_manifest`；②candidate变化不应使Gate A plan审批失效；③旧Mac Air耐久路径当前不可达，改为审批绑定的`ABCR_AUDIT_ROOT`；④Gate C独占锁与cost receipt多attempt身份原先欠规约，现已明确。

### 18.5 Claude 补充裁定 checkpoint 的 Gate A 状态（历史、已被§19取代）

```yaml
ASSESSMENT_PHASE: GATE_A_STATIC_PREAUDIT
PLAN_PARENT_SHA256: 6cf0db7aaecdd4efba50af85d3472944170185a2db5820312f60444e3a0424b8
CLAUDE_SUPPLEMENT_CHECKPOINT_SHA256: bc98d6f0a4e49a0f3cb5f9374005349e3f16ab058617d52fb8f961156f28c9ad
TARGET_SHA_OBSERVED: e02d4c3ccb777d850bb9e6aa687e89ff75648ad8
TARGET_TREE_OBSERVED: 74ebf32fc8446dc28165572808b1c357adda2076
TARGET_REPO_ID: null
TARGET_REPO_ID_STATUS: UNSEALED
KNOWN_FINDINGS: CR-01..32
TRANSFER_INTEGRITY:
  observation: OBSERVED_MATCH
  finding_status: CORROBORATED_EVIDENCE
  seal_status: UNSEALED
SECTION_11_NUMERICS:
  finding_status: CORROBORATED_EVIDENCE
  seal_status: UNSEALED
MAC_ENGINEERING: FAIL
CLOUD_ARTIFACT_INTEGRATION: FAIL
GATE_B_ENTERED: false
GATE_B_ENTRY_BLOCKERS: [APPROVE_PLAN_MISSING]
COSTED_TRACKS_AUTHORIZED: false
```

### 18.6 Gate A 交付纪律

- 本节不保留主观“质量等级”，也不把未封存静态复核写成正式 PASS。
- 当前审批对象是整份 V2.0-r6 与伴随 policy seed；`6cf0...`、`bc98...` 只用于谱系。
- 本轮未创建/切换工程分支，未运行 pytest/模型/API/正式回归，未修改 Mac mini canonical，未提交、未合并、未 push。
- 获得同时绑定最终 plan SHA、policy seed SHA、范围与 `cost_cap_cny=0` 的 `APPROVE_PLAN` 后，才按 §3 进入 Gate B；Cost Gate只控制计费子轨，不阻断零成本测试。

---

## 19. 当前远端增量静审与 CR-33～45（更新至2026-07-15）

### 19.1 活体只读观察

2026-07-15 通过既有SSH认证会话只读重核 `/Users/superagent/abcr`，最新观察到：

```yaml
REMOTE_PATH: /Users/superagent/abcr
BRANCH: main
HEAD_OBSERVED: edbd351fcbb0cce4918225d21da7cb2d871dd299
TREE_OBSERVED: 198c23aadc736780654bf8e638c5026e57a38631
PREVIOUS_HEAD_OBSERVED: 9d579e5960f48cab4816e825be8a72461dda43b4
DELTA_FROM_PREVIOUS: "only 阶段2-R2就绪报告-20260715.md, 41 added lines; no production/test code change"
TRACKED_DIRTY:
  - artifacts/traits/REVIEW-REQUEST.md
  - artifacts/traits/conscientiousness/provenance.json
  - artifacts/traits/neuroticism/provenance.json
  - artifacts/traits/openness/provenance.json
GATE_B_ENTERED: false
FORMAL_GATE_B_TESTS_RUN_BY_THIS_AUDIT: false
UNSEALED_REPORT_CLAIM: "726 passed / 4 skipped; not accepted as Gate B evidence"
SECRET_SCAN_OBJECT: "key/401 fragment in the new report; value must never be reproduced"
CLOUD_OR_API_BUDGET_AUTHORIZED: false
REMOTE_WRITES: false
```

四个dirty文件的本轮观察SHA依次仍为 `01da49d8b5a49681a4cfe301ad5542f2633113d98aeca61b982fe28e04fdb2ad`、`6b7f817234908e2a6dc488d4f3cf3a4eb0c7d22a18607c37cdf8e72765a0fd92`、`895b97beaa21fadd649c8e8cc8be080d48697811c09a11d38a896231f079404e`、`7b3704f72e13860be7e27c0f8567fbbb4316dd15664d2c50383bd93fcdcf6835`，与上一轮观察不变；仅用于证明观察时字节，不授权接纳、删除或提交。新报告的`726/4 skip`没有本方案要求的获批plan/seed、exact collection、raw log、execution envelope、typed evidence与seal，其中skip本身也违反正式必跑项纪律；其key/401片段只进入隔离secret scan且不得复述。报告没有授权任何云/API费用。Gate B开始时必须重读HEAD/tree/status、全部worktree及四个字节哈希；任何漂移都先形成新的source observation和语义diff，不能沿用本节假装目标未变。

### 19.2 增量代码审查结论

相对最初 `e02d4c3...` 锚，`9d579e5...` 的生产/测试增量为99文件/9007行，主要位于 `src/abcr/common`、`ledger`、`audit`、`ops`、`governor`、`report`、`rig`；`9d579e5...→edbd351...` 只再加一份41行报告，故下列生产代码控制流反例与CR路由均未变化。逐模块审查得到13组独立反例，已在§6.1登记CR-33～45：

| 风险组 | 静态可构造反例 | 闭合出口 |
|---|---|---|
| approval token | 损坏消费账本fail-open、错batch复用、verify/consume竞态 | CR-33；S-03/05/06、L-07/20 |
| queue/runstate | path escape、rename覆盖、分锁丢更新、跨输入resume、误判orphan | CR-34；L-06/07/19/20/23 |
| dispatch settle | 空config、首seed少跑、scoring前done、skip-done无score、非原子settle | CR-35；L-06/08/09、E-15/16、R-01 |
| provenance | code tree漏受控文件/dirty，manifest原位重写，start/end及step身份不足 | CR-36；S-04、L-10/19/22、R-05 |
| audit apply | 空/未知/子集/SKIP可overall PASS并apply，非法状态排序 | CR-37；S-10、E-15/16、P-10、R-07 |
| rescore join | 键漏condition/trajectory/step、未真实rescore、零comparison PASS | CR-38；L-08/09、E-15/16、P-10 |
| ledger/cloud | 权威reader漏segments、拼接无全序、损坏/非法transition被跳过 | CR-39；L-03/04/21、R-05 |
| watchdog | 坏输入fail-open、历史terminal压制后续、多实例错判、alert覆盖 | CR-40；L-14/20/21/24、R-03 |
| cost | 缺账本为0、负/NaN、未知engine、漏seed/condition与未结责任、ID竞态 | CR-41；L-18/24、C-30.A01 |
| report | 重复/null/错condition聚合、所有done run冒充provenance、非法fold | CR-42；S-07、E-16、P-10、R-08 |
| blinding | 未知phase泄盲、NaN、token/source/label不闭合 | CR-43；S-07、E-11/18/20 |
| path/atomicity | 多入口直拼路径、任意config读取、报告/alert/envelope半写与覆盖 | CR-44；S-05/06、L-20/23、P-07 |
| envelope | dispatch不验证，deadline/protocol/budget/seed/config/trait只浅校 | CR-45；L-01/20/22/24 |

上述是 Gate A `CORROBORATED_STATIC/UNSEALED` finding，不是动态red或测试PASS。正式 closure 必须在审批后以同一冻结harness对获批baseline复现FAIL、对只改生产实现的candidate观察PASS；若当前HEAD、dirty bytes或相关实现再变化，13组finding不自动消失，只能由语义重映射和正式receipt关闭。

### 19.3 非baseline `r2-integration` 时变观察与 OBS-R2-02/03

`r2-integration` 是独立时变候选，不是本次 `main@edbd351...` baseline，也不是已批准candidate。只读观察先见其为 `8e7b59a2...` / tree `cca160e...`，tracked clean但有两个untracked脚本：`scripts/make_r2_envelope.py`（SHA前缀`c922710a…`）和`scripts/run_r2_batch.sh`（SHA前缀`719f4d2e…`）；随后该ref前进到 `896f3ebf...` / tree `3a40b1e...` 并把两脚本提交入tree，worktree转为clean。clean只说明文件已提交，不说明安全或已验收；不能把对一个时点的观察套到后来tree，也不能继承main报告或任何`726/4 skip`数字。若未来选择该ref为candidate，必须重新冻结当时精确commit/tree、binary diff、依赖与全worktree排除清单，再做完整静审和同harness baseline-red→candidate-green。

`OBS-R2-03` 记录下一次只读漂移：`896f3ebf01bc1369c47630e76a9664bfc402e0dd/3a40b1efb9e8ab95c82a6d21d1ea4a70d9574107` 前进1个commit到 `eecd1f2646f4aa3c3c42747ba92a70351f1be41b/0c80eab8dbd60205ce3baf384dfffdf10789a409`，末态worktree clean；diff恰2份runbook、`+7/-0`，无production/test/config/launcher字节变化。两个launcher SHA仍分别为`c922710aac47c27c37353401303128d659141f4a8d0d36473fef153ea3d2fa84`与`719f4d2e44d01530f6506997f77f971ebc75f74965efa855ea38053b13346fd7`；两份新runbook SHA分别为`97d5f95b038e72469600426d2cf4548d5b4ff724a84e2620e641e8b052a2d64c`、`bcb1850d97f957206cce516c1592897273c147f44c4c831b1bac96a26ba9d23d`。新增控制流是在浮动pip安装后全局`pip uninstall -y hf_xet 2>/dev/null || true`并导出`HF_HUB_DISABLE_XET=1`：它吞卸载失败、破坏共享环境且未把HF变量/package/model snapshot写入lock或manifest；预下载又使用默认未钉revision，而launcher写入不同的占位`PIN-AT-PROVISION`，所以下载成功不证明正式dispatch身份或可运行性。该变化不关闭OBS-R2-02，归既有CR-08/14/36/41/45及AD-R2-01/07/09/14/15。

为避免被明确排除的时变ref形成审批DoS，后续仅因`r2-integration`继续推进，**不使获批main方案自动失效**；Gate B PRE-12必须在执行时活体封存其ref/HEAD/tree/status，并以字节级证明其未进入clone、candidate、harness、fixture/cache/dependency manifest、命令或执行。无法证明排除即STOP；任何r2字节一旦进入这些输入，立即回Gate A重新冻结、语义审查与审批。该规则不放宽main的HEAD/tree/受保护dirty mismatch门。

`OBS-R2-02` 为该非baseline subject的P0静态风险集合，因此不新增CR-46，但若r2进入candidate则下列每项都必须闭合：

- `make_r2_envelope.py` 自动生成 `approval.key` 并给自身签token，`run_r2_batch.sh` 默认真实transformers 7B后直接dispatch，形成self-approval与默认外部/计费动作；
- 复制fixture仍可写`gpu_hours=0/cap=0`，dispatch未验证预算/engine，真实engine的估价basis仍为fake/0；零预算不能授权真实7B、provider或GPU；
- audit item6可经`|| true`继续且脚本不解析真实audit verdict便进入pack；每次重跑又建新batch，无幂等reservation，也无关机trap；打印的cloud stop CLI不存在或instance未register，不能作为停止计费凭证；
- dispatch写`cloud-day-r2` segment而auditor只读主ledger，可把空batch当已审；repro在`total=0`时给`agreement=1`，missing score直接continue，复制scorer没有独立重算，manifest verifier也不拒extra，故空/残包可假绿。

对`896f3ebf.../3a40b1e...`的代码级观察以及`eecd1f26.../0c80eab...`未改变的production/test/launcher字节，路由摘要如下；这是非main baseline subject的静审，不是candidate验收：

| r2风险面 | 静态反例 | 若纳入candidate的既有red→green出口 |
|---|---|---|
| live与成本 | `gpu_hours/cap=0`仍可走真实7B/provider，价格basis为fake/0 | CR-41/45；L-18/24、C-30、R-08 |
| 审计与停机 | audit失败经`\|\| true`继续；打印的cloud stop命令无实现或instance未register，无trap保证停计费 | CR-13/37/41；S-05/10、L-18、C-30、R-07 |
| ledger分段 | dispatch写cloud segment而auditor只读主ledger，空视图可被折成PASS | CR-37/39；L-03/21、E-15/16、R-05/08 |
| dispatch completeness | 只跑首seed、empty `all([])`结算、golden数量硬编码10而非从expected-set派生 | CR-35/37/45；L-06/08/09/24、E-15/16、R-01 |
| budget schema | NaN/负数/额外actual可绕过，实际额与未结liability漏入合计 | CR-41/45；L-01/18/24、C-30、R-08 |
| provenance/citability | live输出仍被硬标non-citable；tree hash漏`.sh/.toml`与依赖，执行后手补manifest | CR-36/42；S-04/07、L-10/19/22、R-05 |
| repro/pack | extra/symlink未拒绝、`total=0→agreement=1`、可`rmtree`覆盖、所谓独立复评复用current scorer | CR-20/38；P-02–11、R-02/08 |
| 科学runner | hook响应期、seed封存、vector身份/shape/dtype/finite与层映射仍沿用既知缺口 | CR-07–10/19/27/29；I-01–16、E-18、C-15–19 |
| scorer/auditor | 空集合可绿，join/dedupe键缺condition/trajectory/step/scorer或seen不更新 | CR-03/25/37/38/42；L-08/09、E-15/16、P-10、R-08 |
| 冻结与独立门 | split/blind/judge/parity/bootstrap/freeze缺完整身份、独立oracle与首输出前receipt | CR-06/14/18/19/21/23/36/43；S-03/09/11/14、E-07–14/18、C-07–14/31–33 |

路由采用既有CR-13/33/37/38/41/45与S-03/05/07/10、L-01/06/08/18/20/24、P-08/10、R-01/05/07/08；mutation必须显式覆盖“自签+零预算真engine+audit `|| true`+空包agreement=1”。在r2未被正式选为candidate前，这些只作为`CORROBORATED_STATIC/UNSEALED`排除证据，不改变main baseline的closure instance。

下列 `AD-R2-*` 只是现有root assertion的具名反例索引，不新增root/result命名空间；只有当r2字节进入获批candidate或执行输入时才进入正式exact-set，且必须映射到右列既有root并全部red→green：

| 反例索引 | 必杀场景 | 既有root映射 |
|---|---|---|
| AD-R2-01 | 启动前活体复核r2精确commit/tree/status/脚本及可执行runbook SHA；漂移不继承旧观察，且必须逐字证明未进入获批输入 | PRE-01/02/12、R-05 |
| AD-R2-02 | 删除key/token后只跑launcher；必须在人工批准前hard-fail，且不得创建key/token/envelope | S-03/05/10、L-20/24 |
| AD-R2-03 | 零、负、NaN、Inf预算配live engine；必须在dispatch前FAIL且0网络/GPU/run-ledger动作 | L-01/18/24、C-30、R-08 |
| AD-R2-04 | 强制audit非零；wrapper必须非零退出且不得pack、不得打印合格 | S-10、E-15/16、R-01/07 |
| AD-R2-05 | cloud segment写入后audit必须读同一segment；空或all-SKIP必须FAIL | L-03/21、E-15/16、R-05/08 |
| AD-R2-06 | stop必须调用真实CLI/provider并有可核receipt；错参数、失败或仅`verified_by`自报必须阻断 | L-18/24、C-30、R-06 |
| AD-R2-07 | empty configs、unknown engine、多seed、非golden family、placeholder/错revision、缺step或score crash均不得settled/done | PRE-06/08、L-06/08/09/22/24、E-15/16、R-01 |
| AD-R2-08 | extra actual、重复ID、estimate=0而actual>0、负/NaN、乱序/重复stop、跨batch同instance、缺provider receipt全部fail-closed | L-18/24、C-30、R-08 |
| AD-R2-09 | 改`.sh/.toml/Makefile/lockfile`、可执行runbook、HF env、package/model revision均必须改变完整执行身份；non-citable live run不得进入可引用pack | S-04/07、L-10/22、R-05 |
| AD-R2-10 | pack含extra、symlink escape、`../` ID、缺run、空比较、自改manifest、错执行代码或secret-bearing依赖URL时拒绝，且不得删除pack root外文件 | P-01–11、R-02/06/08 |
| AD-R2-11 | 同seed双跑一致、异seed可区分；hook使用fp32 norm且拒绝非finite/zero/unknown mode；activation的shape/layer/token position完整 | I-01–15、S-17 |
| AD-R2-12 | missing steps、重复顶缺、零comparison、未知item、subset apply、all-SKIP全部FAIL | E-15/16、P-10、R-07/08 |
| AD-R2-13 | split assignment/hash严格一致；blind必须恰三条件×计划N并拒绝NaN/重复/缺失 | L-22、E-06/11/18/20 |
| AD-R2-14 | 无Cost Gate时judge/parity `--run`必须0网络；live双引擎须同revision/template且超阈值非零 | E-09/13/14、C-06/23/30 |
| AD-R2-15 | human actor来自外部认证；tag/profile/event原子一致；key 0600且不进上传/pack/log；只在隔离venv用`python -m pip`执行pin+hash安装，不得吞卸载失败，并封存HF变量/model snapshot；浮动依赖与unsafe tar阻断 | S-03/09/14/15、P-01/07、R-06 |
