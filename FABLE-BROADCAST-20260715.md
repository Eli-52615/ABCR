# FABLE 广播 · 2026-07-15 —— 阶段0 补做裁决 + 契约修订 AMENDMENT-32~42

> 依据:三工程包 V1.0「契约修订权在 fable,修订即广播」。本广播是三窗口(A/B/C)自 R1 门起的
> 权威契约增量;与各工程包文档不一致处,**以本广播 + 仓库内契约库与契约测试为准**(各包文档尾注即此规则)。
> 本广播由 fable 于 2026-07-15 签发,经楠授权「独立解决修复」。

## 〇、事实认定与根因(三窗口疑议 #0 首裁)

1. **kickoff(阶段0)从未执行**。三份工程包文档声称"阶段0 接口冻结已由 fable 完成",实测主仓
   main(e02d4c3)无 `src/abcr/common/`、无 `fixtures/`、无 `data/golden/`、无控制面契约测试、
   无 pkg/b|c 分支、无 vendor 区、无 `.env`、无 `requirements-mac.txt`。文档是按"承诺态"写的,
   交付从未发生,且工作流没有任何"实物验收闸"能拦住这一缺口(修复见 AMENDMENT-42)。
2. **三窗口的 bootstrap 决策全部追认合法**(A 留旧仓 worktree 自建、B/C 各建独立仓——疑议 #0/#21)。
   三窗口在断网、禁读上位文档、"独立完成至 R1 不停工询问"的约束下做了唯一正确的事,且全部在
   PROGRESS 第一条如实上报。**无窗口失职;责任在 fable(kickoff 未交付)。**
3. 三套自建"冻结契约"互不兼容(审计实测:令牌六向互验全崩、三把测试密钥字节全不同、账本 API
   三套签名)。本广播以下逐件裁决收敛为唯一基线。
4. 内存/swap 看门狗(com.superagent.mem-swap-reaper)与本事故无关(日志全程未动作)。

## 一、拓扑裁决(疑议 #0/#21)

- 合并基座 = **主仓 `/Users/superagent/abcr` main 分支**(文档冻结路径不变;旧 W1 实验资产零触碰,
  永不 `git clean`/`stash -u`)。
- fable 在 main 上补做阶段0 基线提交(本广播随基线入库),此后:
  - pkg/a:merge main(基线),bootstrap 的"共"件让路给冻结版;
  - pkg/b、pkg/c:独立仓历史**全量导入**主仓(git fetch,原始提交 SHA 保留),在基线上
    `merge --allow-unrelated-histories` 收敛,原独立仓整目录留底备份后由真 worktree 替换;
  - R1 过门后 fable 合并三分支进 main(文档流程),各窗口阶段2 于各自 worktree `git merge main` 起步。
- 三仓 PROGRESS.md 同路径互撞:导入时改道为 `PROGRESS-A.md` / `PROGRESS-B.md` / `PROGRESS-C.md`
  (各包继续只写自己那份;文档中"PROGRESS.md"一律读作"PROGRESS-<X>.md")。B 仓自带 README.md/
  pytest.ini 不入 main(README 保主仓版;pytest 配置并入 pyproject,不引入根 pytest.ini)。

## 二、契约修订(AMENDMENT-32 ~ 42)

**AMENDMENT-32|契约测试权威路径 = `tests/contract_pkgabc/`。** 旧 W1 归档测试占位 `tests/contract/`
(stage1-4),归档零触碰。三包文档中一切 `pytest tests/contract` 命令读作 `pytest tests/contract_pkgabc`。
R1-A1 的"未被 A 改动"判据对象同步改此路径。(采 A 窗口隔离方案;疑议 #7,C-R1-1 随之解封。)

**AMENDMENT-33|envelope.run_configs 冻结为内联完整 RunConfig 对象列表**(B 定义的嵌套格式:
config_version/model{}/benchmark{}/condition/intervention/decoding{}/batch_id)。理由:envelope_sha256
必须覆盖全部实验参数;"路径列表"形态允许批准后改写所指文件而不破坏签名,是实质安全洞。
config_hash = sha256(canonical_compact(config))(紧凑 separators 口径,K1);AMENDMENT-22 唯一性
检查不变。dispatch 的 `_load_run_configs` 双形态兼容保留(路径形态仅限 `--dev` 人工裸跑)。
C 的 planner 起草信封时内联完整 config(P7"run_configs 实在"改为结构完备性检查)。

**AMENDMENT-34|fixtures/test_approval.key 冻结为确定性 32 字节** = `sha256(b"abcr-w1-fixture-test-approval-key")`,
0600,**入 git**(测试专用密钥,零秘密价值;此为"*.key 不入 git"的唯一显式豁免)。真实密钥
(state/approval.key、.env 内 API key)禁入 git 不变(K4)。fixture 令牌以此 key 预签,TTL 长效
(expires 2036;静态 fixture 不设演练日过期陷阱——疑议 #5 采 C 方案)。

**AMENDMENT-35|expected_scores.jsonl 冻结口径**(疑议 #6 采 B 方案):仅确定性 `is_correct` 行,
每行 5 字段 `{condition, item_id, metric_name, metric_value, random_seed}`(sort_keys 序列化),
行序 (condition, random_seed, item_id)。A 的 a_rescore_compare 四键 join 天然兼容;A 版 12 字段
形态废弃为比对基线(scored_at 墙钟与 run_id 依赖导致不可复现)。

**AMENDMENT-36|ledger_ref.py 权威 = 工程包A文档嵌入全码(A 窗口 A1-1 实物)+ 三项增补**(疑议 #3):
① 实例方法 `events(event=None, subject_id=None)` 过滤;② `has_event(event, subject_id)`(dispatch
幂等硬依赖);③ 模块级 `append_record(path, record)`——steps.jsonl 整记录挂链通道(补 prev_hash/
entry_hash,拒收已含链字段的记录;flock 互斥)。记录形状冻结 A 形
`{ts, run_id(=链 stem), event, ...payload, prev_hash, entry_hash}`;**B 形的 seq 字段废**
(B 历史链为运行时产物,R1 演练前重置,无迁移负担)。C 的单参构造让路,abcrctl 改
`RunLedger(dir, name)`(C 文档本就声明"签名以实物为准")。

**AMENDMENT-37|approval_token.py 权威 = 工程包C文档嵌入全码(C 窗口 C1-1 实物,零改动)**(疑议 #1):
字段名 `task_id`(承载 batch_id)/`changeset_sha256`(承载 envelope_sha256)/签名键 `sig`;
scope 冻结字符串 `"batch_approve"`(AMENDMENT-11);消费账本 `state/approvals/consumed.json`
单文件(K5 容错语义)。**B dispatch 适配**:verify 改为
`envelope_sha256(env)` + `verify_token(token, expected_envelope_sha256=…, verify_secret=…, consumed_store=…)`;
consume 改 `consume_token(token, store)`;`token.scope == envelope.scope` 的 dict 绑定校验废
(该职责由 dispatch 的 scope 强制独立承担,防护不减);B 侧原因码随 C 码表。B 的 fixtures 预签
令牌全部作废,由 fable 以冻结 key 重签。envelope_sha256/canonical_json 单点实现 =
`abcr.governor.envelope`(B 只读 import,勿自行序列化——C 文档原文)。

**AMENDMENT-38|constants.py 权威 = A 版为基座并入 B 三常量;statemachine 冻结 A 版**(疑议 #1/#2):
constants 并入 `HEARTBEAT_EVERY=5`、`LEDGER_CHAINS`、`STATE_DIR_DEFAULT="state"`(纯字面量;
env 一律调用时读),补 B 系事件集别名(RUNS_INDEX_EVENTS 等 = LEDGER_EVENTS[*] 引用)。TTL 命名
冻结 A 系(TTL_QUEUED_S / TTL_RUNNING_HEARTBEAT_S / TTL_COMPLETED_S / TTL_SCORED_S,**状态停留
语义**);env 变量 `ABCR_TTL_<同名>`,经 `statemachine.ttl_seconds()` 调用时读;B 的
TTL_HEARTBEAT_S/TTL_AUDITED_S 命名废,`ABCR_TTL_SCORED_S` 语义 = SCORED 态停留上限(A 义)。
statemachine 迁移表 = A 版(AMENDMENT-13/16 依据);B 独有 COMPLETED→CANCELLED、SCORED→CANCELLED
及批次 REJECTED 状态无修正案依据,废;冻结版补 `TransitionError` + `assert_run/assert_batch/
assert_protocol` 薄封装(B watchdog 调用形态零改动)。schema/statemachine 维护权仍归 A。

**AMENDMENT-39|schema.py 权威 = A 版四入口 + 三增补**(疑议 #2):① `metric_value` 可空
(B1-10 judge 数字总概率<0.25 记 None 的语义依据);② NaN/±Inf 一律拒(K9);③ `strict=True`
开关拒未知字段(写入前自检用;链封装键 prev_hash/entry_hash 豁免;审计重放用默认宽松)。
A 的 rescore_v1 与 B 的 deterministic_v1 **有意双实现纪律不变**(B 版 schema/statemachine 删除,
但判分函数各自独立实现、不许合并——AMENDMENT-20/21 照旧)。

**AMENDMENT-40|环境事实对齐**(疑议 #9):控制面 venv = 主仓 **`.venv312`**(uv venv --python
3.12.13,本广播时补建;pytest/duckdb/pandas/pyarrow/typer/pydantic/python-dotenv/openai/matplotlib);
旧 `.venv`(3.11.15,含 editable abcr → 旧 W1 回归专用)保留不动,控制面一律
`PYTHONPATH=$PWD/src` + `.venv312`,**禁 pip install -e .**(K1)。`requirements-mac.txt` 本广播时
补交(torch/transformers 等重件列出但延至阶段2 前置安装,B1-12 时核对)。`.env` 仍未交付——
DEEPSEEK_API_KEY 须楠注入,不阻塞 R1(只阻塞 R1-full 的 B1-10)。各包文档 §4.1/§4.3 环境条目
以本条为准(自检中 `python -V` 预期 3.12.x,激活 `.venv312`)。

**AMENDMENT-41|fixture 冻结参数**(疑议 #4):envelope_fixture.json = B 版原件**重签**
(batch_id `B-20260714T090000Z-0001`、scope 原样含 splits ["none"]、conditions [vanilla, persona_text]、
6×内联嵌套 RunConfig、budget 0/0、deadline 2027-01-01;approval 块由 fable 以冻结 key 按
AMENDMENT-37 口径重签)。**SPLIT_ENUM 增 "none"**(仅 golden10/fake 类无 split 基准合法;planner
P1 对真实批仍限 dev/calibration,防护不减)。golden10.json = A 版冻结(顶层 protocol_ref/note 保留;
判分规则 A/B 实测语义等价)。faketask_spec.md = A 版主体 + B 旋钮精确语义(CRASH_AT_ITEM 值=item_id
——AMENDMENT-24 原文;EXIT_WITHOUT_DONE=写完首 step 后 os._exit(0))。badtoken = 整信封、
`sig = "0"*64`(AMENDMENT-12 命名)。expected_scores.jsonl = B 版实物冻结(AMENDMENT-35 口径)。
fixture 生成器单点 = `scripts/kickoff_make_fixtures.py`(fable 维护),三包自产生成器
(_bootstrap_fixtures/b_make_fixtures/c_bootstrap_fixtures)废弃归档,只消费不自产。

**AMENDMENT-42|kickoff preflight 闸(防复发,治理条款)**:`scripts/preflight_kickoff.py` 核验
阶段门/kickoff 声明的全部实物前提(路径/分支/worktree/venv/契约库可 import/fixture 跨模块互验/
契约测试可收集),任一不实存即 FAIL 并要求停工上报。三包开工自检序列(§4.3)第一步改为跑此脚本。
**规范先于实物时,实物核验是开工闸,不是事后审计**——本次事故的结构性教训。

## 三、其余疑议处置(编号对审计疑议汇总表)

| # | 处置 |
|---|---|
| #8 | R1-A6/A7/A8 此前为 A 模拟 B 产物的"条件绿";本次 R1 演练即以 B 真实产物真跑,过门以真绿为准 |
| #10 | **追认** A 的 views 两处偏差(TIMESTAMP 时区修正;末态判定走 derive_run_state,SQL 视图降为便捷面)。derive_run_state 为末态判定权威,写入契约 |
| #11 | **明裁**:steps.jsonl 哈希链归 B 自验(R1-B8);A 审计验收面 = 五全局链 verify_chain + steps 逐条 validate_step,不验 steps 链 |
| #12 | 追认 argparse(零外部依赖偏好) |
| #13 | 追认 commit 前缀 [pkgA/pkgB/pkgC] 系;仓根 CLAUDE.md 增补新世界指引(旧文保留标注归档) |
| #15 | writer.py 空壳,入阶段2 排期 |
| #16/#17 | 追认"R1 门内各用各的、R1 后 C 自愿切换 A 的 views/statemachine"与 per_run_metrics 扩展;切换前跑 C 的 test_views 等价回归,#10 追认先于切换 |
| #18 | 追认 C 的 AMENDMENT-30 解读纠偏(阶段1 七卡全交付为既成合法事实) |
| #19 | B1-9~B1-12 排 R1 过门后、云日前;**B1-10/B1-11 需楠**(注入 DEEPSEEK_API_KEY 至 .env;trait 工件人工过目) |
| #20 | C 的 R1 演练备忘(--key 必带/演练后 git checkout -- fixtures/)固化进本广播 R1 runbook 节 |

## 四、R1 门 runbook(fable 主持,本广播签发后执行)

1. 前置:三分支对齐基线、全部单测+契约测试(tests/contract_pkgabc)绿;`.venv312` 激活;
   `export PYTHONPATH=$PWD/src`。
2. 全链(在 r1 集成 worktree,合并 a+b+c 后):
   `scripts/abcrctl approve fixtures/envelope_fixture.json --key fixtures/test_approval.key`(**必带 --key**)
   → 坏令牌信封 dispatch 拒绝(退出 2,双留痕) → 好令牌 dispatch:6 假 run(含 1 crash 续跑)
   → scorer → `scripts/a_rescore.py` + `a_rescore_compare --against fixtures/expected_scores.jsonl`
   (MATCH 60/60) → `scripts/a_audit.py <batch> --items 1,2,4 --apply`(overall PASS + g03/g07
   呈现句) → `scripts/abcrctl status` + C triage/sync/views 三连(R1-full 项,一并抽验)。
3. 判据矩阵:R1-A1~A9、R1-B1~B10、C-R1-1~4(+5~8 抽验),逐条留证于 R1 报告。
4. 演练后 `git checkout -- fixtures/`;运行时目录(ledger/queue/state/data/runs)不入 git。

## 五、各窗口阶段2 入口指引(R1 过门后生效)

- 三窗口重启第一动作:读本广播 + 各自 `PROGRESS-<X>.md` 尾部 fable 段 → 跑
  `python scripts/preflight_kickoff.py` → 于各自 worktree `git merge main`。
- A:阶段2 卡(A2-1~A2-6)+ writer.py;views/statemachine 供 C 切换支持。
- B:B1-9~B1-12(vendor clone 需网络窗口;B1-10 等 .env;B1-11 产物送楠过目)→ 阶段2 卡。
- C:阶段2 卡(C2-*);自愿切换窗口开启。

—— fable,2026-07-15
