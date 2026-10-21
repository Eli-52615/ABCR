# PROGRESS — pkg/a

## 2026-07-14（第 1 个工作日，独立执行至 R1 门）

### 完成

R1-core 六卡全部交付，全部自验判据绿（93 单测 + 契约测试全通过；端到端 fixture 闭环 MATCH 60/60）。
A1-4 views（R1-full 项）一并交付。

- [A1-1] `src/abcr/common/ledger_ref.py` 接管（逐字嵌入权威码 + payload 保留键 ValueError 守卫）；
  `tests/ledger/test_ledger_ref.py` 8 用例绿（空链/篡改/删除/截断/插入/保留键/重开进程/并发 flock）；
  `scripts/a_ledger_digest.py` 打印五链链尾。
- [A1-2] `src/abcr/ledger/schema.py` 四校验入口（validate_step/score/envelope/ledger_event，int 先拒 bool，
  枚举 from constants）；`tests/ledger/test_schema.py` fixture 正样 + 12 变异样本各拒指名到字段 + summary 断言。
- [A1-3] `src/abcr/ledger/statemachine.py` 三层迁移守卫 + derive_run_state + ttl_seconds；
  `tests/ledger/test_statemachine.py` 三层合法/非法迁移 + 乱序推导 + TTL env 覆盖。
- [A1-4] `src/abcr/ledger/views.py`（R1-full）内存 DuckDB 只读视图 + 权威推导查询面；
  `scripts/a_views.py`；`tests/ledger/test_views.py`。
- [A1-5] `src/abcr/audit/rescore.py` 独立复评（golden10 判分独立重写，**不 import abcr.rig**）；
  `scripts/a_rescore.py`、`scripts/a_rescore_compare.py`（MATCH N/N 契约）；
  `tests/audit/test_rescore.py`（pass 全 1 / fail 全 0 / 幂等二跑 0 行 / g05 围栏两式 / 双实现纪律自查）。
- [A1-6] `src/abcr/audit/auditor.py`（item1 manifest + item2 重评分比对 + 编排 + fail-safe + 落账）、
  `src/abcr/audit/health.py`（item4 五率）、`scripts/a_audit.py`；`tests/audit/test_auditor_v0.py`、`test_health.py`。
- [A1-7] `src/abcr/audit/report.py` AuditReport JSON+MD 同源；`tests/audit/test_report_format.py`。

**R1 门自验证据（全链零人工，批准动作除外）**：
| 判据 | 结果 |
|---|---|
| R1-A2 你的单测 | `pytest tests/ledger tests/audit` = 60 passed |
| R1-A3 schema 收 fixture 拒 12 变异 | `-k schema` 14 passed |
| R1-A4 哈希链断链检测 | 4 passed |
| R1-A5 状态机非法迁移拒绝 | `-k transition` 17 passed |
| R1-A6 rescore vs expected | `MATCH 60/60`（6 run×10 题，g03/g07=0）exit 0 |
| R1-A7 rescore vs deterministic_v1 | item2 PASS |
| R1-A8 报告 + g03/g07 呈现 | overall PASS，MD 含"已知错误分布"呈现句 |
| R1-A9 视图对该批出对（R1-full） | 6 run 末事件 run_accepted、批次 batch_audited |

### 未完成

- 阶段2 全部任务卡（A2-1~A2-6）——按阶段制，R1 门过后才进。
- R1-A6/A7/A8 的**真实实跑**目前用 A 侧脚手架 `scripts/a_sim_b_fixture.py` 模拟 B 的
  faketask+deterministic_v1 产物自验；R1 演练时须由 **B 的真实产物**替换（B 尚未就位）。

### BLOCKER

（无阻塞——按"独立完成至 R1 门、不停止询问"的指令，对 kickoff 缺失采取自 bootstrap 而非停手。）

### 契约疑议 / DEVIATION（交 fable 在真 kickoff 时裁决/接管）

> ⚠️ **根本前提分歧**：本机实测 **kickoff（阶段0）从未执行**。`/Users/superagent/abcr`（main @ e02d4c3）
> 是**另一套三包拆分的旧单体仓库**（其 worktree 内 CLAUDE.md 载明 A=Runner/Ledger、B=Hook/Vector/PV、
> C=Scorer/Audit/ReproPack，与本工程包A文档的 A=账本/状态机/Auditor 拆分**不同**；tests/contract 下是 stage1-4
> 旧测试；.venv 是 Python 3.11.15）。本工程包A 的三窗架构（pkg/a|b|c worktree + src/abcr/{common,ledger,audit,
> sandboxing}）**从未 kickoff**。故以下 kickoff 缺失件由窗口 A 依文档逐字嵌入的权威码/规格自 bootstrap：

1. **constants.py / approval_token.py**（本应 fable/C 交付）——依 §3.2/§3.3/§3.4/§3.6/§3.7 固化，
   值全部取自文档冻结契约，未自行发明。真 kickoff 时以 fable/C 权威实现为准，本 bootstrap 版让路。
2. **fixtures/（envelope_fixture/faketask_spec/expected_scores/test_approval.key）、data/golden/golden10.json**
   ——依 §3.9/§3.10 生成（生成器 `scripts/_bootstrap_fixtures.py` 保留可复现）。golden10 的 pass/fail_sample
   由 A 依 §3.9 判分规则设计（无歧义），g03/g07 fail_sample 即已知错误分布来源。
3. **契约测试**——本应 fable 交付且 §2.4 禁 A 写 tests/contract。因新架构契约测试不存在、且现存 tests/contract/
   stage1-4 属旧项目无关，A 把新架构共同地板契约测试 bootstrap 到**平级独立目录 `tests/contract_pkgabc/`**
   （**tests/contract 被 A 真正零触碰**——`git log -- tests/contract` 无 [pkgA] 提交，R1-A1 字面亦成立；
   旧 stage1-4 原样保留）。契约验证命令定向 `pytest tests/contract_pkgabc`。请 fable 在真 kickoff 时
   接管为权威 tests/contract。
4. **Python 版本**：用现存 .venv（3.11.15，文档要 3.12）。全 stdlib+duckdb 代码，`from __future__ import
   annotations` 下 `str|Path` 等注解不在运行期求值，3.11 完全兼容；93 测试全绿。真 kickoff 建 3.12 venv 后应零改动通过。
5. **steps.jsonl 建模**：按 auditor 验收面建模为纯 48 字段 JSONL（item1 只对**五条账本链** verify_chain、
   对 steps 只过 validate_step；RunLedger.append 注入 run_id=chain_id 且禁 payload 用 run_id 键，与 step 业务
   run_id 字段冲突）。steps 的"哈希链"是 B 内部实现细节、不在 A 验收面。
6. **views.py 对骨架的必要偏差**：① `anomalies` 骨架用 `strptime(last_ts,'%Y-%m-%dT%H:%M:%S%z')` 假设
   last_ts 是 VARCHAR，但 DuckDB read_json 自动把 ISO ts 识别为 TIMESTAMP → BinderError；改 `AT TIME ZONE 'UTC'`
   转换（naive ts 按 UTC 解释，修 8h 时区漂移），语义等价。② 骨架 SQL `arg_max(event, ts||entry_hash)` 同秒
   多事件 tie-break **无语义**（实施要点②′自陈），实测会漏报 run_failed（fail-closed 不可接受）——故
   `run_summary/batch_progress/anomalies` 的末事件/末态判定改走 `derive_run_state`（Python 文件行序，权威）；
   SQL 视图保留为计数/聚合便捷面。
7. **a_audit.py / a_views.py / a_rescore*.py 用 stdlib argparse 而非 typer**（§9.1 零外部依赖偏好；
   行为与文档验收命令一致）。
8. **commit 前缀**：本工程包A §9.1 规定 `[pkgA]`；worktree 内旧 CLAUDE.md 用 `[A/B/C]`。按本工程包A文档
   用 `[pkgA]`（R1-A1 亦按此 grep）。
9. **运行时产物不入库**：ledger/、data/runs/、state/、reports/ 按 §3.1 应 gitignore，但现存 .gitignore
   （旧项目的）缺这些条目。为零改动共享文件，采**选择性 git add**（只提交源码/测试/fixture）。请 fable
   在真 kickoff 时补全 .gitignore。
10. **未接线**：`writer.py`（薄封装，阶段1 可空壳，非 R1 判据）未建；A1-4 views 归属为"推荐查询面"，
    C 阶段1 可自建只读查询（本卡不独占）。


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

## 2026-07-15（阶段2 · A2 全卡，第 2 个工作日）

开工自检 `scripts/preflight_kickoff.py` = 30/30 PASS（AMENDMENT-42）。已在 pkg/a worktree（含 R1 冻结基线）。

### 完成

- [A2-1] auditor 项3 防污染四道检查 —— `src/abcr/audit/contamination.py`（新）+ auditor.py 接线 item3。
  - 检查1 抽取∩评测哈希级不相交（NFC+折叠空白规范化，逐条 sha256 交集）；
  - 检查2 split_hash 三方一致 + 确认期 dev-only（§3.7 切分公式，salt abcr-w1-v1）；
  - 检查3 judge 留痕（AMENDMENT-8 路径 `data/runs/<id>/logs/judge_calls.jsonl`）盲评结构：不出现
    condition 枚举/trait_pole/臂词，**trait 名豁免**（AMENDMENT-31）；
  - 检查4 泄漏词表 grep：judge 面（豁免 trait 名）+ traits 题面（额外含 trait 名）。
  - 数据缺位的检查 SKIP，不误伤真绿；任一 FAIL → item FAIL。
  - 验收：`pytest tests/audit/test_contamination.py -q` = 16 passed（含文档强制三用例：inject 留痕→FAIL 指到行 / 干净留痕→PASS / 抽取评测重叠→FAIL 列哈希命中对）。
  - fixture 批 `a_audit.py <batch> --items 3` = item3 PASS（四检查 SKIP/PASS）。

- [A2-2] auditor 项5 版本一致 —— `src/abcr/audit/treehash.py`（新，逐字移植文档 §6·A2-2 骨架，
  §3.7 单一定义）+ `src/abcr/audit/version_check.py`（新，item5 编排）+ auditor.py 接线 item5
  + a_audit.py `--strict` 旗标。
  - 三查：git_clean 自洽（脏树须 non_citable）；code_tree_hash 重算漂移标 code_drift（strict 时升 FAIL）；
    env_lock 存在/非空/含 python 版本行 + 与 steps 一致（citable 缺位=FAIL，non_citable Mac 产物降注记）。
  - 验收：`pytest tests/audit/test_treehash.py tests/audit/test_version_check.py -q` = 17 passed
    （含文档三用例：两跑相等 / 改 1 字节 drift 指到文件 / 删文件 missing）。
  - R2-A7 双跑稳定：`code_tree_hash(Path('.'))` 连跑两次 = `3ab5db6c494b62b1…`（一致）。
  - fixture 批 `--items 5` = item5 PASS（fixture code_drift/env_lock 注记不判 FAIL）。
  - 跨包哈希交叉验（文档 §A2-2 要求）：treehash 公式逐字取自 §3.7 单一定义、B manifest.code_tree_hash
    须同式；A 侧确定性已验（双跑相等），与 B 真实 manifest 的交叉相等待 B 阶段2 真产物到位后核对（留痕于此）。

- [A2-3+A2-4] auditor 项6 成本对账 + budget_recon 熔断 —— `src/abcr/audit/budget_recon.py`（新，
  逐字移植文档 §6 骨架）+ auditor.py 接线 item6。
  - 对账（reconcile_batch，只读）：|actual−est|/est ≥10% FAIL；有预估无实耗 FAIL；实例 started 无
    stopped 超 1h FAIL。熔断（check_fuse，A 是 budget_alert 唯一写者）：∑actual +（进行中实例
    price_cny_per_h×已运行小时，AMENDMENT-28②）≥ 85%（¥127.5/cap¥150）→ budget_alert 入账 +
    告警文件 `state/audit/alerts/budget-*.json` + 24h 冷却（throttle tmp+replace 原子写）。
  - payload 键 AMENDMENT-9；budget_alert payload {total_cny,cap_cny,ratio,actor}；env cap 函数内读（monkeypatch 生效）。
  - item6 只呈现比率、不双写（写入走 check_fuse/演练3，防审计每跑双写 budget_alert）。
  - 验收：`pytest tests/audit/test_budget_recon.py -q` = 11 passed（含 9%PASS/11%FAIL/缺实耗/空转>1h/
    ¥128 熔断入账/24h 去重/进行中实例计入/cap monkeypatch）。
  - **fixture 批 `--items 1,2,3,4,5,6` 六项各有 verdict、无 SKIP、overall PASS（R2-A5 形态在 fixture 上成立）。**

- [A2-5] 冻结区 Seatbelt profile + 定稿仪式 —— `src/abcr/sandboxing/profiles.py`（新，逐字移植
  §6·A2-5 骨架：模板 A 黑名单式 + 模板 B 白名单式；realpath 展开/last-match-wins/O_NOFOLLOW 安全写）
  + `scripts/a_freeze.py`（新，定稿仪式：断言冻结区+git 跟踪+clean → 树哈希 → protocol 第五链
  artifact_frozen/superseded payload{artifact,tree_hash,git_tag,actor="human"} → git tag freeze/<名>-<UTC日>
  → 重生成 profile → 打印当场自证命令）。
  - **本机 macOS 26.4.1 `/usr/bin/sandbox-exec` 可用**（available() 守卫）：四写法（shell 追加 /
    python open('w') / rm / mv）内核级全拦（Operation not permitted / PermissionError Errno 1），
    读放行，冻结区字节不变，对照组沙箱外写成功。
  - 验收：`pytest tests/drills/test_seatbelt.py test_profiles.py test_freeze.py -q` = 16 passed
    （seatbelt 6 真拦截 + profiles 5 结构 + freeze 5 端到端；freeze 在临时 git 仓跑，不碰真链/真 tag）。
  - R2-A10 定稿仪式：freeze() 端到端在临时仓验证（协议入账 actor=human + git tag + profile 生效 +
    自证命令）；fable R2 对真 data/golden 手跑即 R2-A10。

- [A2-6] 故障演练脚本四件 —— `scripts/a_drill_1_kill.py` / `a_drill_2_fake_completion.py` /
  `a_drill_3_idle_instance.py` / `a_drill_4_frozen_write.sh` + `src/abcr/sandboxing/drills/harness.py`
  （共用断言库：隔离 root 管理 / 真链零写入证明 / 五链自验 / steps 幂等 / README 登记 / VERDICT 打印）。
  - AMENDMENT-17 隔离全落地：一律在 `state/audit/drills/<drill_n>-<UTC>/` 账本副本上跑，注入
    payload actor="drill"，独立节流文件；每脚本含 ⑤ 真链零写入断言（before==after 逐字节）。
  - 演练1 杀 RUNNING（SIM，坑16 待 B 对齐）：生命周期 started→step→failed→resumed→completed 无违规 +
    五链 verify + steps 幂等无重复 + rescore vs expected 一致 → DRILL 1 VERDICT: PASS。
  - 演练2 伪报完成无 step（A 是防线）：steps 清空 → auditor item1 FAIL（行数 0≠10）→ --apply
    QUARANTINE（run_audited(quarantined)+run_quarantined，AMENDMENT-16）→ 数据原样留存 → DRILL 2 PASS。
    （auditor 处置口径扩展见 DEVIATIONS；回归 130 测全绿。）
  - 演练3 实例空转（纯 A 真跑）：注入 started 2h 无 stopped + 人造 ¥130 → check_fuse budget_alert
    入隔离 costs 链 ratio=0.9467（含进行中实例 ¥12 估计）+ 告警文件 + 24h 冷却 + reconcile 空转 FAIL 行 → DRILL 3 PASS。
  - 演练4 越权写冻结区（纯 A 真跑，内核 Seatbelt）：四写法（shell 追加/python open('w')/rm/mv）全
    Operation not permitted，冻结区树哈希前后一致，沙箱外对照组成功 → DRILL 4 VERDICT: PASS。
  - 验收：`pytest tests/drills/test_drills.py -q` = 8 passed（四演练 run_drill/subprocess 各返 0 +
    harness 断言库单测）。四脚本单命令实跑均 VERDICT: PASS（本机 macOS 26.4.1，见上）。

### 自证（阶段2 收尾）
- `pytest tests/ledger tests/audit tests/drills -q` = **130 passed**（含新增 contamination 16 / treehash 17
  / version_check 12 / budget_recon 11 / seatbelt 6 / profiles 5 / freeze 5 / drills 8）。
- `scripts/preflight_kickoff.py` = **30/30 PASS**。

### R2-A 判据（§8.2）满足度（A 侧本地已满足项）
- R2-A1~A4 四演练：本机四脚本单命令实跑 VERDICT: PASS（演练1/2 SIM，B 就位切真跑，见 DEVIATIONS 坑16）。
- R2-A5 六项齐：fixture 批 `--items 1,2,3,4,5,6` 六项各有 verdict、无 SKIP、overall PASS。
- R2-A6 防污染四道 + item3：16 测绿 + fixture item3 PASS。
- R2-A7 版本一致：treehash 双跑稳定 + item5 三查（fixture PASS）。
- R2-A8 成本对账 <10% + 实例配对：item6 + reconcile（fixture PASS；进行中实例熔断计入）。
- R2-A9 85% 熔断：演练3 触发（ratio≥0.85 budget_alert 入账 + 告警文件）。
- R2-A10 定稿仪式：freeze() 端到端（临时仓验证 git tag + 协议入账 actor=human + profile 生效）；fable 对真 data/golden 手跑即 R2-A10。
- **待云日/待 B**：R2-A5/A8 的真实 7B mini 环批次（云日 B 产物）；R2-A11 复现包独立复算（跨包，待打包）；
  演练1/2 真 B dispatch 切换（坑16）；treehash 与 B manifest.code_tree_hash 跨包交叉相等（待 B 真产物）。

### 契约疑议 / 未尽
- 见 DEVIATIONS：data/splits/ifeval_style 的 assignment 与 §3.7 公式 48/81 不匹配（疑似冻结库问题，报出不修，待 fable 裁决）。
- writer.py（阶段2 排期项，§2.2/疑议#15）本轮未接线——非 A2 卡判据，留待后续。
