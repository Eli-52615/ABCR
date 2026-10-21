# PROGRESS — 窗口 C（Governor 审批与同步视图）

> 沟通唯一通道（§7 执行者须知）。最新在顶，追加式。四节缺一不可。

---

## 2026-07-15（D2）— 阶段2 全部 C 卡（C2-1~C2-6）+ §7 阶段3 预置件

> 开工自检：`preflight_kickoff.py` 30/30 PASS；已在 pkg/c worktree 含 R1 冻结基线（无需再 merge）。
> 全程零 LLM/零网络/纯本地；ABCR_NOTIFY_ENABLED=0；未 push；未改 constants/tests/contract；密钥未进 git。

### 完成
- **C2-1 shadow.py**（`src/abcr/governor/shadow.py`）：草案 vs 人工最终决策差异记录（纯函数 `compare`，
  集合维度 set 化比较）。四关键维（budget.gpu_hours_max/budget.cost_cap_cny/set(conditions)/set(splits)/
  item_limit_per_run）任一不同即 key_difference=true；seeds/trait_whitelist 非关键照记不入判定。
  差异记录 v1 落 `plans/shadow/<batch_id>.shadow.json`（哈希单点走 envelope.envelope_sha256）。CLI 就绪。
  补测 `test_shadow.py` **10 用例全绿**（四关键维逐一/仅非关键 false/列表乱序不算差异/写盘/approval 不进哈希）。
- **C2-2/C2-3 repro_pack.py + ACCEPTANCE**（`src/abcr/report/repro_pack.py`）：自包含出包
  `demos/repro-<batch>/`（configs/runs/activations/env/figures/tools + README/ACCEPTANCE/pack_manifest）。
  `rescore_copy.py` = A 的 `audit/rescore.py` 判分函数**逐字节复制**（经 diff 证实，仅 `from abcr.common
  import constants` 一行换等值内联垫片使自包含）；`scorer_copy.py` = B 的 `rig/scorer.py` 逐字节；
  `rescore_standalone.py` = stdlib + 两副本，sha256 完整性核验（污染→exit 2）+ A 主副本重算 vs
  deterministic_v1/rescore_v1 两组一致率。**出包末步空 PYTHONPATH subprocess import 两副本自检，
  失败拒绝出包报 BLOCKER + 删半成品包**（AMENDMENT-20，fail-closed）。ACCEPTANCE.md 四步模板实例化。
  补测 `test_repro_pack.py` **5 用例全绿**（manifest sha256 全符/内容齐+无 .key/仓库外 agreement==1.0/
  污染 exit2/自检 fail-closed）。
- **C2-4 weekly 模板 + 生成器**（`reports/weekly/TEMPLATE-weekly-evidence.md` + `src/abcr/report/weekly.py`）：
  逐字模板（头注释五禁令）；生成器四节实例化（图/可复现/失败/假设），从 views/triage 拉数字；③失败节
  不可空（无失败写「本周无失败记录」+账本查询命令为证）；效应经 blind.render_effect + assert_no_direction。
  **`.gitignore` `/reports/` 改 `/reports/*` 反忽略该单一模板**（git 目录整体排除无法反忽略其中文件）。
  补测 `test_weekly.py` **5 用例全绿**。
- **C2-5 blind.py 复核 + test_blind.py**：blind.py（R1 已落）与 §C2-5 文档嵌码**逐字一致**（无需补全）；
  补齐缺失的 `tests/report/test_blind.py` **9 用例全绿**（探索期含方向/确认期剥方向+剥两臂原值/两相位含
  source_run_ids/词表防回归/assert_no_direction 相位/sync evening 确认期集成）。确认期接线：sync evening
  与 weekly 生成器写盘前对效应区块调 assert_no_direction。
- **C2-6 sync/triage 真实数据适配 + 预算余量段**：sync morning 增「今日预算与熔断」段（从 costs 链读
  est/actual/budget_alert 汇总 + 余额 150−实耗 + 85% 熔断线距离，逐 run 实耗带 subject_id）+「云实例」段
  （折叠未 stopped 实例，idle_alert 标 [A 空转]）；sync evening 逐 run 指标行透传 [non-citable]（读 manifest，
  缺则保守标注）——G7。ledgerio 增 INSTANCE_EVENT_STATE。triage 侧 instance_idle_alert/实耗≥85% 入 A 桶
  （补测锁定）。补测 test_sync **+4**、test_triage **+2**。
- **§7.1 notify.py（全码）+ test_notify.py**：飞书告警按 kind 24h 冷却，`ABCR_NOTIFY_ENABLED!=1` 恒静默
  （阶段1/2 不接线）；发送成功才记冷却/失败重试/原子写状态。逐字 §7.1。补测 **8 用例全绿**（§8.2 C-R2-8）。
- **§7.2 毕业检查器 `scripts/c_shadow_graduation.py` + test**：扫 `plans/shadow/*.shadow.json` 零关键差异
  批次累计 run（runs_index run_registered.batch_id / 未启动以信封 run_configs 对账）+ 审计 overall==PASS
  全绿 → GRADUATED/NOT_GRADUATED。补测 **5 用例全绿**。

### 自证（真实跑过，输出留存）
- `pytest tests/governor tests/report -q` → **105 passed**（R1 基线 57 → +48）。
- `scripts/preflight_kickoff.py` → **30/30 PASS**。
- `tests/contract_pkgabc` → **130 passed**（未触碰，仍绿）。
- **闭合验收全链真跑**（自造 tmp 账本：a_sim_b_fixture 6 假 run + a_rescore 加 rescore_v1 → repro_pack 出包
  33 文件，出包自检通过 → cp /tmp 空 PYTHONPATH 走 ACCEPTANCE 四步）：完整性 PASS；
  `agreement_deterministic_v1=1.0 agreement_rescore_v1=1.0`（360 三元组）；判定 **PASS**。→ C-R2-2/3/4 成立。
  污染注入（篡改 steps.jsonl）→ 独立复算 exit 2、报污染。→ 污染检测成立。

### R2-C 判据（§8.2）自评
- **C-R2-1 shadow 差异记录成立**：✅ test_shadow 10 绿；shadow.json 四关键维判定正确（CLI 真跑证）。
- **C-R2-2 复现包清单齐+全哈希**：✅ 出包后逐文件 sha256 全符（test + 现场证）。
- **C-R2-3 仓库外独立复算全同**：✅ /tmp 空 PYTHONPATH agreement 两组均 1.0。
- **C-R2-4 闭合验收（R2 ④）**：✅ ACCEPTANCE 四步走查 PASS（自扮验收会话，全程未回读仓库）。**待云日**：
  fable 亲自开全新会话对**真 mini 环批**复算（本轮以 fixture 批自证四步链路成立）。
- **C-R2-5 方向锁盲**：✅ `test_blind.py + test_sync.py` 确认期全绿。
- **C-R2-6 周证据包模板合规**：✅ 四节齐 + 头禁令注释在（test + 现场证）。
- **C-R2-7 G7 呈现纪律**：✅ 每段 sync 含 exploratory 标注行（test_every_segment_has_exploratory）；
  evening non_citable 透传在。`grep -L exploratory reports/sync-*.md` 现场为空（sync-*.md 为运行时产物，
  真批次由 R2 现场生成）。
- **C-R2-8 阶段3 预置件就位（不接线）**：✅ test_notify 8 绿；默认静默冒烟 `suppressed-or-failed`。

### 未完成
- **真 mini 环批次现场项（R2 云日）**：C-R2-4 fable 全新会话对真实 mini 环批复算、C-R2-6/7 对真批 sync 四段
  可读性 fable 确认、shadow 对首个真实批次（云日 7B mini 环）落 `plans/shadow/<id>.shadow.json`——均属
  R2 现场/云日项，本轮以 fixture 批把链路全部自证成立，等真批数据到位即可复跑同式。
- **§7.2 auto_dispatch 字段实装**：只交规格 + 毕业检查器（本轮）；实装 = 契约修订须 fable 走 AMENDMENT 广播
  （毕业达成后流程：PROGRESS 出示证据 → 楠点头 → fable 修订 → B dispatch 认字段）。本轮不动。
- **§7.3 飞书接线**：阶段3 楠拍板事项，本轮恒不接线（ABCR_NOTIFY_ENABLED=0）。

### BLOCKER
-（无）

### 契约疑议
- **疑议-6（rescore_copy 逐字节 vs 自包含的张力）**：§C2-2 要求 rescore_copy 从 A 的 `audit/rescore.py`
  「逐字节复制」，但该文件 `from abcr.common import constants`（HEDGING_WORDS 等非 stdlib）——与出包末步
  「空 PYTHONPATH import 自检 stdlib 自包含」（AMENDMENT-20）直接冲突：字面全文照抄会自检必挂。**处置**：
  判分**函数体**逐字节复制（经 diff 证实字节相同），仅把 `from abcr.common import constants` 一行换成等值
  内联 `class constants` 垫片（值从冻结 constants 取，行为 bit 一致）。B 的 `rig/scorer.py` 本就 stdlib 自
  包含，逐字节直抄。所依契约：§C2-2、AMENDMENT-20。请 fable 追认此解读（不改冻结库、不降自检）。
- **疑议-7（毕业检查器 verdict 键形跨包接口）**：§7.2 提示「verdict 键形是跨包接口，检查器上线前须核实
  A 包同版约定」。已核实：A 的 `abcr.audit.report.AuditReport.to_dict()` 整体键 = `overall`（值 PASS/FAIL），
  检查器按此读。R1 后 A/C 同仓，实物一致，无疑；记此以备 A 若改键形时同步。所依契约：§7.2、AMENDMENT-31。

### R1 现场演练备忘（承上不变）
- shadow/weekly/repro_pack 现场演练命令均在各模块 docstring/README/ACCEPTANCE；repro_pack 演练不动
  fixture 原件（出包只读复制）。

---

## 2026-07-14（D1 续）— R1-full 补齐（C1-4~C1-7）+ 全链 C 侧演练

> 纠偏说明：R1-core 交付后我按 AMENDMENT-30 把 C1-4~C1-7 推迟到阶段2，属**偏保守解读**。
> 按「按任务顺序完整执行直到 R1 门」的要求，已补齐阶段1 全部 7 张卡（施工序
> C1-1→C1-2→C1-3→C1-4→C1-5→C1-7→C1-6，C1-7 先于 C1-6）。

### 完成
- **C1-4 planner.py**（`src/abcr/governor/planner.py`）：固定规则计划器 v0，零 LLM。八项预检 P1-P8（split只dev/条件白名单/批预算/W1总预算/trait白名单/规模上限/run_configs实在/预估不超信封）+ 预算预估公式 + 信封草案（**任一 FAIL 不落草案，precheck 报告恒落**）。补测 `test_planner.py` **8 用例全绿**：合法 8/8 PASS+信封validate通过 / 逐项越界(P1/P2/P3/P5/P7/P8)不落草案且 FAIL 指名 / P4 造 costs 实耗触发 / batch_id 格式。
- **C1-5 triage.py + ledgerio.py**（`src/abcr/governor/triage.py`、`src/abcr/report/ledgerio.py`）：ledgerio 只读装载（read_chain_merged 含云链段AMENDMENT-2 + fold_subjects）；triage 七桶（A级/失败未收敛/停摆/TTL/待决/已收敛偏差/正常）+ severity 三级映射（AMENDMENT-31：停摆=A、失败/TTL=B、待决/已收敛=C）+ 尾部「今日 A+B 告警数 N/3」；例外驱动排版（正常合计一行）。补测 `test_triage.py` **4 用例全绿**（6-run 剧本：停摆恰1、已收敛恰1、失败未收敛0、正常4、空账本不炸、待批DRAFT入待决）。
- **C1-7 views.py + cli.py**（`src/abcr/report/{views,cli}.py`）：DuckDB 1.5.4 只读查询面（overview/batch_detail/per_run_metrics/run_item）+ 三层钻取 CLI。**空数据护栏**（K7：glob 判空不下 SQL 返零值结构）；run↔batch 关联走 run_registered.batch_id（AMENDMENT-19）；run_id/item_id 参数化（K8）；L3 output_text 全文不截断只转义控制字符。补测 `test_views.py` **4 用例全绿**（2run×3item 含g03错样：overview计数/臂级均值手算相符/output_text逐字节相等/空数据不炸）。
- **C1-6 blind.py + sync.py**（`src/abcr/report/{blind,sync}.py`）：blind 方向锁盲（§C2-5 全码，render_effect 探索期直通/确认期剥方向 + assert_no_direction）；sync 四段（morning/afternoon/evening/urgent）。**呈现纪律落地**：所有统计数字只经 cite()/render_effect() 两出口，逐数带 run_id/subject_id；臂级聚合以 source_run_ids 随行注明；每段头部注入 exploratory 纪律行。补测 `test_sync.py` **9 用例全绿**（四段渲染+文件名/数字行含run归属/效应行含source runs/告警计数行/urgent单行/确认期无方向token）。
- **阶段1 合计 55 单测全绿**（`python -m pytest tests/governor tests/report -q` → 55 passed）。
- **C-R1-5~8 全链 C 侧演练通过**（隔离目录，draft→approve→模拟dispatch+6假run(含1crash续跑)+评分+审计落账→triage→sync四段→cli三连）：
  - C-R1-5 planner 合法出草案（8/8 PASS）、越界拒草案（单测证）✅
  - C-R1-6 triage crash-resume run 现身「已收敛偏差」✅
  - C-R1-7 sync 四段逐数带 run_id、效应行含 6 个 source run 列表、四段均有纪律行 ✅
  - C-R1-8 三层钻取 overview+batch+run/item 总耗时 **0.375s**（≤60s），g03 原文=WRONG 逐字节呈现 ✅

### 未完成
- **C2-*（阶段2）+ notify（阶段3 预置件）**：不在阶段1 范围，R2 前完成。

### BLOCKER
-（承上：BLOCKER-1 kickoff 缺口仍在——ledger_ref/fixtures 为 bootstrap 占位，见下方 R1-core 段与契约疑议。R1-full 四卡不新增 BLOCKER。）

### 契约疑议
- **疑议-4（views 自愿切换窗口）**：C1-7 views/C1-5 ledgerio 现为 C 自建只读副本；R1 合并后可自愿切 A 的 `abcr.ledger.views`/`statemachine`（两拒绝事件呈现标记映射保留 C 侧）。所依契约：§3.3、§C1-5/§C1-7。
- **疑议-5（per_run_metrics 属查询面扩展）**：sync evening 逐 run 呈现需按 run_id 聚合，我在 views 增 `per_run_metrics()`（overview/batch_detail/run_item 三冻结签名未动）。若 A 的 views 上线后有同义函数，切换时对齐。所依契约：§C1-6 点③「聚合从 views 取」、§C1-7 冻结签名。

### R1 现场演练备忘（提醒 fable，承上不变）
- 演练命令必带 `--key fixtures/test_approval.key`；演练后 `git checkout -- fixtures/`。
- R1 全链跨包演练（B dispatch / A 审计）需 A/B 包就位——当前 C 侧 R1-core+R1-full 全齐、C 侧链路已自演证。

---

## 2026-07-14（D1）— R1-core 交付（C1-1 / C1-2 / C1-3）

### 完成
- **C1-1 approval_token.py**（`src/abcr/common/approval_token.py`）：落地 §C1-1 嵌入全码，逐字忠实（载荷字段、双序列化口径、校验顺序结构→scope→恒时比较签名→envelope哈希→过期→已消费、六原因码、`EXPECTED_SCOPE="batch_approve"`）。补测 `tests/governor/test_approval_token.py` **14 用例全绿**：正样 / 六失败路径逐一原因码 / bad_expires_at / naive-ISO 不崩按 UTC / consume 幂等 / consumed.json 损坏放行 / load_or_create_key 首建 0600+幂等 / **fixture 真值锚（正样 ok、坏样 bad_signature）**。
- **C1-2 envelope.py**（`src/abcr/governor/envelope.py`）：落地 §C1-2 嵌入全码（`canonical_json` 紧凑口径、`envelope_sha256` 去 approval、`validate_envelope` 八类结构校验）。补测 `tests/governor/test_envelope.py` **8 用例全绿**：fixture validate 通过 / sha 幂等 / approval 不进哈希 / scope 改动改哈希 / **≥8 变异样本拒绝且 problems 指名** / save-load 往返 sha 不变 / 非对象护栏。
- **C1-3 abcrctl**（`scripts/abcrctl`，chmod +x）：落地 §C1-3 嵌入全码（draft/approve/reject/status；approve 写回后自校验；AMENDMENT-10 三事件以"人"身份落 batches.jsonl）。补测 `tests/governor/test_abcrctl.py` **8 用例全绿**（subprocess、cwd=tmp 伪 worktree）：approve 退出0+七字段+key 0600 / fixture 原件字节不变 / 原件令牌重验 ok / 结构坏→退出2 无approval 无账本事件 / reject 生成 .reject.json / status 三态 / **落账 actor=="human" 且 event/subject_id 正确** / consumed 损坏 status 标注不崩。
- **合计 30 单测全绿**（`python -m pytest tests/governor tests/report -q` → 30 passed）。手工冒烟：approve→APPROVED、reject→REJECTED、K5 缺失标注正确。
- **C-R1-4 的 C 侧链路已自证**：`approve --key fixtures/test_approval.key` 签发的令牌，被 dispatch 式 `verify_token`（test key + 去approval哈希）验签返回 `(True, "ok")`。

### 未完成
- **C1-4 planner / C1-5 triage / C1-6 sync / C1-7 report / C2-* / notify**：均属 **R1-full / 阶段2**（AMENDMENT-30），本轮不做。abcrctl 的 `draft` 子命令依赖 planner（C1-4）——planner 未就位时 `draft` 会 ImportError，approve/reject/status 不受影响（planner 仅在 draft 内 import）。
- **C-R1-1 契约测试全绿**：本工作流 `tests/contract/` 尚未 kickoff 交付（见 BLOCKER-1），当前无契约测试可跑；C 侧代码不违反任何已嵌契约条文。

### BLOCKER
- **BLOCKER-1（需 fable / kickoff）：本自动化工作流尚未 kickoff。** 文档 §执行者须知/§3.8/§4.4 假定的 kickoff 骨架（worktree `abcr-wt/c` + `pkg/c` 分支、`src/abcr/common/{ledger_ref,constants}.py`、`fixtures/*`、`tests/contract/`、`data/golden/golden10.json`）在实仓 `/Users/superagent/abcr`（现装的是**旧 W1 实验实现** run.py/eval/interventions，结构与本控制面不兼容）中**均不存在**。
  - **已尝试**：核实 `git worktree list`（仅 main）、`git branch`（无 pkg/c）、`src/abcr/` 实际内容（旧结构）。
  - **本轮如何在缺 kickoff 下推进 R1-core（bootstrap，已隔离标注，待覆盖）**：
    1. 在文档指定路径 `/Users/superagent/abcr-wt/c` 建**独立 git 仓（branch pkg/c）**，不污染旧实验仓。
    2. `src/abcr/common/ledger_ref.py` = 按 §3.2 冻结哈希链协议（GENESIS_HASH、entry_hash 默认separators+prev_hash拼接、fcntl.flock 全局互斥）写的**最小忠实实现**，仅供 abcrctl 落账自测闭环。**归属是 A**——真 kickoff 到位后应由 A 实物整体替换（见契约疑议-1）。
    3. `fixtures/{test_approval.key, envelope_fixture.json, envelope_fixture_badtoken.json}` = 由 `scripts/c_bootstrap_fixtures.py` 用 C 的 approval_token+envelope 模块**自洽生成**（§3.8 规范：6 假run=2cond×3seed、golden10、engine=fake；scope=`batch_approve`）。**归属是 fable/kickoff（"共"冻结物）**——真 kickoff 到位后应由 fable 的预签 fixture 替换（见契约疑议-2）。

### 契约疑议
- **疑议-1（ledger_ref 归属 A）**：本轮 bootstrap 的 `ledger_ref.RunLedger(path).append(event, subject_id=..., **payload)` 签名取自 §4.4 假名。真 kickoff 后须以 A 实物签名为准核对（§4.4 核对项4）；若不符，abcrctl 的 `_ledger_append` 相应调整。所依契约：§3.2、§2.3（AMENDMENT-10）。
- **疑议-2（fixture token TTL）**：bootstrap fixture 令牌用 **10 年 TTL** 保静态 fixture 不随时间过期（真 kickoff 由 fable 按需 TTL 预签）。所依契约：§3.5、§3.8、§4.4 核对项2（scope 冻结 `batch_approve`——本轮 fixture 已符）。
- **疑议-3（venv Python 版本）**：文档 §4.1 写 Python 3.12，实测 `/Users/superagent/abcr/.venv` 为 **3.11.15**（pytest 9.1.1）。R1-core 仅 stdlib+pytest，不受影响；记录待 fable 对齐环境事实。

### R1 现场演练备忘（提醒 fable）
- 演练命令**必带 `--key` 旗标**：`scripts/abcrctl approve fixtures/envelope_fixture.json --key fixtures/test_approval.key`。不带则默认用 `state/approval.key`（首用新生成密钥并就地重签），B 的 dispatch 用 test key 验签必得 `bad_signature`，现场直接失败（§C1-3 / K）。
- 对 fixture 原件就地 approve 无害（approve 换 approval 字段不改 envelope_sha256）；演练后 `git checkout -- fixtures/envelope_fixture.json` 还原。
- **⚠️ 前置**：R1 全链演练（approve→B dispatch→6假run→评分→A复评→审计→C同步视图）需 A/B 包就位——当前仅 C 侧 R1-core 齐备，跨包演练待 kickoff 与 A/B 交付。


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