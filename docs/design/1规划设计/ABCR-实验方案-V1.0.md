# ABCR 实现执行方案 V1.0（三并行工程包上位文档 · 阶段化架构）

> 日期：2026-07-11 ｜ 作者：Claude（fable5，独立调研 + 设计）｜ 已吸收楠 2026-07-11 阶段化分工指示（阶段0–3、组件式三包、回归门制）
> 定位：把《ABCR-自动化实验流程设计-V0.9》全案与《ABCR-W1方案-最小纵向闭环-V0.9》落到代码层的**实际执行方案**。效力链：V1.3（唯一操作文档）> W1方案V0.9 > 自动化设计V0.9 > 楠阶段化指示 > 本文。配套文档：《ABCR-执行节奏方案-V1.0》（哪天干什么）、《工程包A/B/C》（三个执行窗口的完全自包含施工图）。
> 执行模型：三个 Claude Opus 4.6 high 独立窗口并行执行工程包 A/B/C，每日 4 小时；fable5 窗口在**阶段0 一次性冻结接口后退出日常编码**，只在回归门（R1/R2）做架构裁决与验收。**执行窗口全程不需要也不允许调研 shared-brain 任何文件**——所需事实已全部嵌入工程包。
> 调研依据：四份上位文档全文精读 + 7 路并行侦查（V2 可复用部件源码级、本机环境实测、补充文档增量、persona_vectors 官方仓库 commit b8e0f04 页面级）。

---

## 0. 一页结论

**总目标**：按自动化设计 V0.9 建成实验控制面（守证据链有效性与预算），同时完成 W1 最小纵向闭环的全部科学交付（G1–G7 出口门）。两者的结合点：**W1 科学载荷（Persona Vectors 复现线）是控制面阶段2 的第一个真实负载**——控制面先用假任务证明自己是对的，再用真实验证明自己是有用的。

**阶段路线（楠指示，回归门制，任一门不过不进下一阶段）**：

| 阶段 | 内容 | 回归门 |
|---|---|---|
| 0 接口冻结 | fable 一次性冻结三包边界、schema、状态机、权限矩阵、验收用例；交付目录骨架 + 契约库参考实现 + fixture + 契约测试 | R0：契约测试对骨架全绿；fable 审核一次后退出日常编码 |
| 1 无LLM最小闭环 | A=账本/状态机/复评/审计v0；B=假任务的队列/暂停/恢复/心跳；C=固定规则的计划草案/异常摘要/同步视图。三包对同一 fixture 运行 | R1：批准批次→运行→评分→复评→审计→报告 全闭环零人工（批准动作除外） |
| 2 真实执行 | B 接真实模型与云实例（rig+科学载荷+云日）；A 加预算对账/冻结区 Seatbelt/污染检查；C 进 shadow（计划草案人批人派）。**故障注入四演练** | R2：四演练全过 + 真实数据全闭环 + W1 出口门 G1–G7 + 复现包闭合验收 |
| 3 有限自治（W2+） | 20 run shadow 建议与人工决策无关键差异 → 信封内自动派发；才接飞书与控制台；确认期发射恒人工 | 事件制毕业（自动化设计 D4） |

**三包一览（楠切分 + fable 两项归属裁决）**：

| 包 | 组件 | 角色隐喻 | 核心交付 |
|---|---|---|---|
| A | 账本 + 状态机 + Auditor（+冻结区保护、预算对账、污染检查） | 裁判 + 验船师 | schema 校验器、哈希链账本维护、三层状态机、独立复评器、审计六项、Seatbelt、故障演练脚本 |
| B | Operator + 队列 + 恢复 + 云生命周期 + **rig + 科学载荷**（fable 裁决：试验台归运动员侧） | 运动员 | 假任务执行器、队列/断点续跑/进度心跳/看门狗、rig v0（hook 注入/消融）、Persona Vectors 复现线、云日 runbook、judge 客户端 |
| C | Governor + 审批信封 + 同步视图（+复现包出包；飞书接线留阶段3） | 大副 | 信封对象与审批令牌 CLI、固定规则计划器、异常分诊摘要、四段同步视图、三层钻取 CLI、周证据对象包 |

**三条铁律**（写入每包开头）：① 三包只通过稳定接口（§2 账本文件 + 信封文件 + 契约库 API）通信，**禁止互相直接读写对方内部状态**；② 只在自己 worktree 内动归属矩阵分给自己的路径，不访问 shared-brain，网络白名单 = pypi / hf-mirror.com / api.deepseek.com / github.com 克隆 / registry.ollama.ai（仅 B 拉第二 judge 模型一次）/ modelscope.cn（HF 镜像降级备选）/ 云实例 SSH 主机（云日回传）；③ 每日收工写 `PROGRESS.md`，阻塞超 30 分钟记 BLOCKER 换任务，不钻兔子洞。

**日历衔接的诚实声明**：楠的阶段化使 W1 科学交付比"直奔科学"晚约 1–2 天。两条保护：① trait 工件 / judge 冒烟 / runbook 属**非闭环预研**，B 在阶段1 内并行准备，不受回归门约束；② 云日 #1（官方 trait 复现 + 翻转 demo）走**人工派发合法降级**（自动化设计 D6："自动化永远不在关键路径上"），不等控制面全绿，目标 7/15 晚出 demo。

---

## 1. 环境事实表（2026-07-11 实测；工程包据此写死，不再探测）

| 项 | 实测值 | 工程含义 |
|---|---|---|
| 硬件 | Mac mini M4 16GB（Mac16,10），数据卷余 122Gi | 3B bf16 本机可跑；7B 及以上一律云卡 |
| Python | 默认 python3=3.14.6（brew）；uv 0.11.3 已装并缓存 CPython 3.12.13/3.13.12 | **一律 `uv venv --python 3.12`**；3.14 无 torch wheel 保证 |
| ML 栈 | 全空（无 torch/transformers/vllm；ollama 0.23.4 含 qwen3:8b） | venv 从零建；ollama 不暴露激活，rig 不用它 |
| HF 访问 | **huggingface.co 直连超时；hf-mirror.com HTTP 200** | 一切 HF 下载必须 `export HF_ENDPOINT=https://hf-mirror.com`；备选 modelscope |
| HF 缓存 | ~/.cache/huggingface 不存在 | Qwen 模型全部现下（3B bf16 ≈ 6GB） |
| API key | `DEEPSEEK_API_KEY` 在 `/Users/superagent/shared-brain/L2-project/V2/.env` 第 5 行（35 字符）；无 OPENAI key、无 HF_TOKEN；DASHSCOPE 存在但属 Qwen 家族（judge 禁用） | judge 走 DeepSeek OpenAI 兼容端点 `https://api.deepseek.com`（实测可达）；kickoff 时 fable 把值复制进 abcr/.env |
| Anthropic API | 已治理移除（2026-06-03），禁 API 计费 | trait 工件生成由执行窗口自身（订阅额度）完成 |
| git | 2.53.0；无全局身份、无 gh | repo 级 `git config`；**纯本地仓库不建远端不 push**（楠 2026-06-10 决策） |
| 沙箱 | /usr/bin/sandbox-exec 可用（macOS 26.4.1 实测 deny file-write* 拦截 shell 重定向/python open/rm） | 冻结区只读保护用 Seatbelt profile |
| 飞书 | lark-oapi 1.6.8 范式可用；AUDITOR_FEISHU_APP_ID/SECRET 在 V2/.env | 阶段3 接线；C 包预置 notify 代码 |
| SSH / GPU | ed25519 密钥就绪；无 GPU 租用 CLI/账号 | 云日走网页控制台（AutoDL 类），楠付费开机 |

---

## 2. 冻结契约（阶段0 产物，三包共同宪法；每包完整内嵌；修订权在 fable，修订即广播）

### 2.1 仓库、worktree 与路径归属矩阵

仓库 `/Users/superagent/abcr`，本地 git 无远端。fable 在 kickoff 创建三分支三 worktree：

```
主仓 /Users/superagent/abcr           分支 main（只由 fable 在回归门合并推进）
worktree /Users/superagent/abcr-wt/a  分支 pkg/a  ← 窗口 A
worktree /Users/superagent/abcr-wt/b  分支 pkg/b  ← 窗口 B
worktree /Users/superagent/abcr-wt/c  分支 pkg/c  ← 窗口 C
vendor   /Users/superagent/abcr-vendor/persona_vectors  ← 官方仓库 clone（git 之外，B 专属）
```

目录归属（**只有归属者可创建/修改；`共`= 阶段0 fable 交付后冻结，改动=契约修订**）：

```
abcr/
├── .env .gitignore requirements-mac.txt README.md        共
├── src/abcr/
│   ├── common/            共→维护权分置：ledger_ref.py(A) approval_token.py(C) constants.py(fable)
│   ├── ledger/            A（schema.py writer.py statemachine.py views.py）
│   ├── audit/             A（auditor.py rescore.py contamination.py health.py budget_recon.py）
│   ├── sandboxing/        A（profiles.py drills/）
│   ├── ops/               B（faketask.py queue.py dispatch.py runstate.py heartbeat.py watchdog.py cloud.py）
│   ├── rig/               B（models.py hooks.py interventions/ scorer.py runner.py splits.py）
│   ├── judge/             B（deepseek_client.py blind_protocol.py consistency.py）
│   ├── governor/          C（envelope.py planner.py triage.py）
│   ├── report/            C（views.py sync.py repro_pack.py weekly.py）
│   └── notify.py          C（阶段3 接线，代码先交付）
├── scripts/               前缀归属：a_*.py(A) b_*.py(B) c_*.py(C)；abcrctl(C，人侧 CLI)
├── configs/
│   ├── models/ experiments/ benchmarks/                  B
│   └── envelopes/                                        C
├── data/
│   ├── golden/golden10.json                              共（冻结）
│   ├── benchmarks/ splits/ traits/                       B（定稿即冻结入 git）
│   ├── vectors/                                          B（向量产物落位，非冻结区——AMENDMENT-27）
│   └── runs/                                             运行时（gitignore）
├── fixtures/              共（阶段0：批次信封样例+假任务定义+期望分数+测试密钥）
├── ledger/ queue/ state/ plans/                          运行时（gitignore）
├── reports/ demos/                                       产物（入 git 可选）
├── tests/
│   ├── contract/          共（阶段0 契约测试，fable 交付；三包必须保持全绿）
│   ├── ledger/ audit/ drills/                            A
│   ├── ops/ rig/ judge/                                  B
│   └── governor/ report/                                 C
└── PROGRESS.md            各 worktree 自己的（不合并）
```

Makefile 并行期不存在；各包在文档中定义 make 目标语义，fable 在 R1 门汇编。

### 2.2 权限矩阵（承自动化设计 §2；阶段1–2 靠 git 归属+审查，阶段2 起冻结区加 Seatbelt 内核强制）

| 路径/对象 | rig(B) | Operator(B) | Governor(C) | Auditor(A) | 人 |
|---|---|---|---|---|---|
| data/golden、data/splits、data/traits（冻结区） | 只读 | 只读 | 只读 | 只读 | 唯一写入者（经 B 起草、定稿仪式冻结） |
| data/runs/*/steps.jsonl、scores.jsonl | 追加(steps) / 追加(scorer 的 scores) | 只读 | 只读 | 追加(rescore 的 scores) | 只读 |
| ledger/*.jsonl（runs_index/batches/costs/instances） | 经账本 API 追加 | 经账本 API 追加 | 只读 | 追加(审计事件) | 只读 |
| queue/ | — | 读写 | 只读 | 只读 | 读写 |
| configs/envelopes/、plans/ | — | 只读 | 读写（草案） | 只读 | 审批签名 |
| state/（各包私有内部状态） | 各归属者私有 | 同 | 同 | 同 | — |

**接口 = 账本文件 + 信封文件 + data/runs 产物 + 契约库 API。各包内部状态（queue 细节、planner 中间物、审计工作区）互为黑箱。**

### 2.3 账本（单一事实源）：文件、事件词表、哈希链

`ledger/` 下五个 append-only JSONL（第五链 protocol.jsonl 系 AMENDMENT-7 增补），全部走哈希链（协议见 §2.7），**只能经 `src/abcr/common/ledger_ref.py` 的 API 写入**（并发写互斥见 AMENDMENT-15）：

- `runs_index.jsonl` —— run 生命周期事件。事件词表（枚举冻结）：`run_registered, run_queued, run_started, step_progress, run_paused, run_resumed, run_failed, run_completed, run_scored, run_audited, run_accepted, run_quarantined, run_cancelled`。`step_progress` 由 B 每完成 N=5 个 item 追加一次（payload 含 steps_done/items_done），**这就是进度心跳**——"在岗"的唯一定义是账本 step 推进（治"进程活着工作流停摆"）。
- `batches.jsonl` —— 批次事件：`batch_drafted, batch_approved, batch_rejected, batch_dispatch_rejected, batch_dispatch_started, batch_settled, batch_audited, batch_reported`。语义（AMENDMENT-13 裁决，取代 AMENDMENT-1 初版）：`batch_rejected` = 人工驳回，abcrctl 落账；`batch_dispatch_rejected` = 令牌校验失败或信封越界被 dispatch 拒绝，B 落账，payload 带原因码 + subject_id=batch_id。
- `protocol.jsonl` —— 协议对象冻结事件：`artifact_frozen, artifact_superseded`（AMENDMENT-7 第五链）。
- `costs.jsonl` —— `run_cost_estimated, run_cost_actual, budget_alert`。
- `instances.jsonl` —— `instance_registered, instance_started, instance_stopped, instance_idle_alert`（供应商、规格、时价、关联批次）。

### 2.4 三层状态机（A 实现迁移守卫；非终态携带 TTL，B 看门狗做全局对账）

- **协议对象**：`DRAFT → REVIEW → FROZEN →（AMENDMENT→新版本）→ SUPERSEDED`。W1 冻结对象 = golden10、splits、traits、黄金判据；冻结动作 = 人（楠或 fable 代）跑定稿仪式（git tag + 哈希入账 + 阶段2 起 Seatbelt 只读）。
- **批次对象**：`DRAFT → APPROVED → DISPATCHING → SETTLED → AUDITED → REPORTED`。APPROVED 必须携带有效审批令牌（§2.6）。
- **运行对象**：`PLANNED → QUEUED → RUNNING → {PAUSED, FAILED} → COMPLETED → SCORED → AUDITED → {ACCEPTED, REJECTED, QUARANTINED}`；终态另有 `CANCELLED`；FAILED 可 RESUME 回 RUNNING。
- **TTL 表（秒，constants.py 冻结，env 可覆盖）**：QUEUED 3600；RUNNING 心跳间隔上限 1800（零新 step_progress 即停摆告警）；COMPLETED→SCORED 7200；SCORED→AUDITED 7200。看门狗每周期对账"账本状态 vs 进程表 vs（阶段2）云实例清单"，超时转异常并告警——任何长活状态无活体证据即异常，绝不允许幽灵状态滞留。

### 2.5 step 与 scores 记录 schema v1

**steps.jsonl**（每行一条，append-only + 哈希链），48 业务字段。依据：交接文档 §6.2 基底 28 字段 + V1.3 §11 扩展 + W1方案 §3 补充。裁定：`stop_reason`（生成级）与 `trajectory_stop_reason`（轨迹级）拆分；`trait_score/fluency_score` 在 steps 恒 null（append-only 禁回写），权威值在 scores.jsonl。

| # | 字段 | 类型 | 可空 | 说明 |
|---|---|---|---|---|
| 1 | schema_version | str | 否 | 恒 "1.0" |
| 2 | run_id | str | 否 | §2.8 规则 |
| 3 | trajectory_id | str | 否 | 单轮任务 = 长度 1 轨迹 |
| 4 | step_id | int | 否 | 轨迹内 0 起递增 |
| 5 | parent_run | str | 是 | 续跑/派生指向源 run |
| 6 | git_commit | str | 否 | 启动时 HEAD |
| 7 | model_id | str | 否 | 假任务用 "fake/deterministic-v1" |
| 8 | model_revision | str | 否 | HF commit hash；假任务 "fixture" |
| 9 | dtype | str | 否 | bfloat16 / none |
| 10 | quantization | str | 是 | |
| 11 | device | str | 否 | mps / cuda:0 / cpu / none |
| 12 | engine | str | 否 | transformers / vllm / fake |
| 13 | engine_version | str | 否 | |
| 14 | torch_version | str | 是 | 假任务 null |
| 15 | cuda_version | str | 是 | Mac null |
| 16 | benchmark | str | 否 | 任务族 id，如 ifeval_zh_v1 / golden10 |
| 17 | split_hash | str | 否 | §2.7 |
| 18 | item_id | str | 否 | |
| 19 | condition | str | 否 | 枚举：vanilla / persona_text / neutral_token / length_instruct / inject / ablate / inject_random / ablate_random / synthetic_test / fake |
| 20 | trait | str | 是 | 干预臂必填 |
| 21 | trait_pole | str | 是 | pos / neg |
| 22 | method | str | 是 | prompt / residual_inject / residual_ablate |
| 23 | layer | int | 是 | |
| 24 | coefficient | float | 是 | |
| 25 | intervention_strength | float | 是 | W1 = coefficient |
| 26 | random_seed | int | 否 | |
| 27 | env_seed | int | 是 | 多轮用 |
| 28 | prompt_hash | str | 否 | sha256(最终渲染 prompt) |
| 29 | chat_template_hash | str | 否 | §2.7；假任务 "fixture" |
| 30 | config_hash | str | 否 | §2.8 |
| 31 | action | str | 是 | W1 单轮 "generate" |
| 32 | obs_hash | str | 是 | 多轮用 |
| 33 | remaining_budget | float | 是 | 多轮用 |
| 34 | output_text | str | 否 | 原始输出全文；铁律：不得只存汇总分 |
| 35 | parsed_answer | str | 是 | 解析失败 null 且 safety_flags 记 parse_fail |
| 36 | is_correct | bool | 是 | 生成时可 null；权威值在 scores |
| 37 | latency_ms | int | 否 | |
| 38 | input_tokens | int | 否 | |
| 39 | output_tokens | int | 否 | |
| 40 | stop_reason | str | 否 | eos / max_tokens / error / fake |
| 41 | trajectory_stop_reason | str | 是 | task_done / budget_exhausted / max_steps / error；中间步 null |
| 42 | trait_score | float | 是 | steps 内恒 null |
| 43 | fluency_score | float | 是 | steps 内恒 null |
| 44 | safety_flags | list[str] | 否 | 默认 []；parse_fail/truncated/empty/refusal/repetition |
| 45 | activation_summary | str | 是 | 摘要文件相对路径（§2.9 抽样）|
| 46 | state_snapshot_ref | str | 是 | 合成轨迹测试须演示非 null 写读 |
| 47 | protocol_ref | str | 否 | W1 = "W1-V0.9" |
| 48 | env_lock_ref | str | 否 | lockfile 相对路径 |

**scores.jsonl**（评分是独立 pass，可多 scorer 多次追加）：`schema_version, run_id, item_id, trajectory_id, step_id, condition, random_seed, metric_name, metric_value, scorer_id, scorer_version, scored_at`。metric_name 枚举：`is_correct / trait_score / coherence_score / fluency_score / output_len_chars / output_len_tokens / hedging_rate / self_check_marker_rate / parse_ok`。**manipulation-check 指标与能力指标分列**（v1.1 仍生效条款："行为动了但能力没动本身是发现"）。scorer_id：`deterministic_v1`（B，rig 侧）、`judge_deepseek_v1`（B）、`rescore_v1`（A，独立复评）——B 与 A 对确定性指标是**有意双实现**，对冲同源 bug；两者都必须过黄金十题（§2.10）。

校验器模式（A 实现，照 V2 tasklog 范式）：SCHEMA_VERSION 常量 + frozenset 枚举 + 表驱动必需/可选字段 + 不抛异常的 `ValidationResult(ok, missing, anomalies)`；int 字段先拒 bool。

### 2.6 批次信封与审批令牌（计划级批"信封"，运行级零审批）

**信封文件** `configs/envelopes/<batch_id>.json`：

```json
{
  "envelope_version": "1.0",
  "batch_id": "B-<UTC:%Y%m%dT%H%M%SZ>-<4位序号>",
  "protocol_ref": "W1-V0.9",
  "scope": {
    "benchmark_families": ["ifeval_zh_v1"],
    "conditions": ["vanilla", "persona_text", "inject"],
    "splits": ["dev"],
    "item_limit_per_run": 50,
    "seeds": [1, 2],
    "trait_whitelist": ["conscientiousness"]
  },
  "budget": {"gpu_hours_max": 4.0, "cost_cap_cny": 60.0},
  "deadline_utc": "...",
  "run_configs": ["configs/experiments/xxx.json", "..."],
  "drafted_by": "governor-rules-v1 | human",
  "approval": {"token": {"...": "见下"}, "approved_at": "..."}
}
```

**审批令牌**：V2 canonical 实现（HMAC-SHA256，纯 stdlib，工程包 C 内嵌全码）。载荷字段 `(token_id, scope, task_id→batch_id, changeset_sha256→envelope_sha256, expires_at, persona_change→false)`，序列化口径 `json.dumps(core, ensure_ascii=False, sort_keys=True)`；envelope_sha256 = 对信封去 approval 字段后的规范化 JSON（§2.8 同式）取 sha256。**签发权在人**：密钥 `state/approval.key`（32 字节，0600，abcrctl 首用生成；fixture 用 `fixtures/test_approval.key`）；人跑 `abcrctl approve <envelope>` 签发；B 的 dispatch 只接受 verify 通过的信封（校验顺序：结构→scope→恒时比较签名→envelope 哈希→过期→已消费；fail-closed）；批次 SETTLED 后才 consume。信封外任何一维（超预算、越 split、加臂）自动升协议级 = 拒绝执行 + 记账 + 告警。**确认期批次的"发射"永久保留人手（D8/自动化设计），W1 全部批次实际上都由人批准。**

### 2.7 哈希协议（全项目统一）

- **账本哈希链**（照 V2 TraceWriter 协议 + fsync 增强，contract 库 `ledger_ref.py` 为权威实现）：`GENESIS_HASH="0"*64`；`entry_hash = sha256(json.dumps(含prev_hash不含entry_hash的本条, ensure_ascii=False, sort_keys=True).encode() + prev_hash.encode())`；append 后 flush+fsync；每文件一条链、单写者进程（并发写者必须经队列串行化——这是 Operator 的职责之一）。
- **code_tree_hash**：对 `src/ scripts/ configs/ data/traits data/golden data/benchmarks data/splits` 逐文件 sha256（exts = .py .json .md .yaml .txt，排除 `__pycache__ .git .venv`），`sha256(json.dumps(树, sort_keys=True))`。
- **chat_template_hash**：`sha256(tokenizer.chat_template.encode())` + 三条钉死样例逐字节比对（样例在工程包 B）。
- **split_hash**：`sha256("\n".join(sorted(f"{item_id}\t{split}")).encode())`。切分：`int(sha256(f"{family}:{item_id}:abcr-w1-v1".encode()).hexdigest()[:8],16)%100`；<20 dev，<60 calibration，其余 holdout。salt `abcr-w1-v1` 为协议常量。
- **prompt_hash / obs_hash / envelope_sha256 / config_hash**：sha256(UTF-8 字节)，JSON 一律 `ensure_ascii=False, sort_keys=True, separators=(",", ":")` 规范化。

### 2.8 config 与 run_id

run config 单 JSON（格式见工程包 B §契约摘录；必含 model/benchmark/condition/decoding/steering_position/protocol_ref）。`config_hash = sha256(规范化 JSON)`；`run_id = f"{batch_id时间戳段}-{config_hash[:12]}"`（AMENDMENT-22：时间戳取信封 batch_id 内嵌时间戳——确定性，同信封同 config 恒同 run_id，这是 dispatch 幂等的根基；仅无信封的 `--dev` 裸跑用当刻 UTC。信封内 run_configs 的 config_hash 必须唯一，dispatch 发现重复即拒）。启动前置检查（不过拒跑）：git clean（否则仅 `--dev` 且 manifest 打 `non_citable:true`）；model_revision / chat_template_hash / split_hash 与冻结清单逐项一致。

run 产物布局：`data/runs/<run_id>/{manifest.json, steps.jsonl, scores.jsonl, activations/, logs/}`。manifest 必含：run_id、config 全文内嵌、config_hash、git_commit、git_clean、code_tree_hash、model_id、model_revision、chat_template_hash、split_hash、engine/engine_version、torch_version、python_version、env_lock_ref、seeds、started_at/finished_at、status、non_citable、protocol_ref、batch_id。

### 2.9 激活存储策略（承 W1方案 §3）

全量激活不落盘。只存：① 抽取语料分层均值激活（B，官方流水线自产）；② 评测运行中按 item_id 哈希尾数确定性抽样 10% 题目的逐响应 token 在 v_p 上的投影标量序列 + 分层统计摘要（mean/P50/P90），存 `activations/<item_id>_<seed>.npz`。合成向量阶段同样走通此通路。

### 2.10 黄金十题（golden10 —— B 判分器与 A 复评器的共同真值；阶段0 写入 `data/golden/golden10.json` 冻结）

判分语义精确定义（两包独立实现；10 题 pass_sample 判 1、fail_sample 判 0 全对才过门）：

| id | prompt | 判分规则 |
|---|---|---|
| g01 | 请用恰好三行回答，每行以"- "开头，分别用一句话介绍红、黄、蓝三种颜色。 | strip 后按 \n 切分 == 3 行且每行 startswith("- ") |
| g02 | 计算 17×23，只输出数字。 | strip 后 == "391" |
| g03 | 输出单词 hello 重复 5 次，用英文逗号分隔，不加任何其他内容。 | strip 后 == "hello,hello,hello,hello,hello" |
| g04 | 谈谈实验记录的重要性，回答中必须包含词语"可复现"至少两次。 | output_text.count("可复现") >= 2 |
| g05 | 以 JSON 对象输出，仅含键 a 和 b，值分别为整数 1 和 2。 | 剥 ```json 围栏后 json.loads == {"a":1,"b":2} |
| g06 | 只输出英文大写字母表的前五个字母，不加分隔与其他内容。 | strip 后 == "ABCDE" |
| g07 | "实验"一词在下句中出现几次？只输出数字："实验是科学的基础，好的实验需要设计，实验记录要完整。" | strip 后 == "3" |
| g08 | 将字符串 abcr 逆序输出，只输出结果。 | strip 后 == "rcba" |
| g09 | 地球的天然卫星是什么？A. 月球 B. 太阳 C. 火星。只输出选项字母。 | strip 后取首字符 == "A" |
| g10 | 输出一句不超过 20 个字的话，必须以"数据"开头、以"。"结尾。 | strip 后 startswith("数据") 且 endswith("。") 且 len<=20 |

### 2.11 hook 正确性判据（黄金测试之 hook 检，bf16 容差）

- **注入检**：固定 seed 随机向量（`torch.manual_seed(42); v=randn(hidden)` 单位化），c=4.0，3B 取 layer 18。base vs steered 前向在注入位置的 hidden delta（cast fp32）：`cos(delta, v) > 0.99` 且 `|delta|/(c·|v|) ∈ [0.95, 1.05]`。
- **消融检**：`|proj_after|/|proj_before| < 0.02`（proj_before < 1e-3 时直接判 |proj_after| < 1e-3）。
- **双跑一致检**：同 config temp=0 连跑两遍逐题 output_text 与判分一致。
- **注入位置**：response tokens（生成每步最后位置 + prefill 最后 prompt token），与官方 `--steering_type response` 一致。

### 2.12 fixture（阶段0 交付，阶段1 三包共同的靶）

`fixtures/` 内容：① `envelope_fixture.json`——一个含 6 个假 run config 的信封（2 condition × 3 seed，benchmark=golden10，engine=fake）+ 用 `test_approval.key` 预签的有效令牌 + 一个坏令牌样例；② `faketask_spec.md`——确定性假任务定义：对 item_id=gXX 输出 golden10 的 pass_sample（其中 g03/g07 输出 fail_sample，制造已知错误分布），每 item 耗时 0.2s，暴露故障旋钮环境变量（名称冻结）：`ABCR_FAKETASK_CRASH_AT_ITEM / ABCR_FAKETASK_HANG_AT_ITEM / ABCR_FAKETASK_SKIP_LEDGER_WRITES / ABCR_FAKETASK_EXIT_WITHOUT_DONE`；golden10.json 顶层结构冻结为 `{"schema_version":"1.0","items":[{id,prompt,rule,pass_sample,fail_sample}×10]}`；③ `expected_scores.jsonl`——该信封跑完后确定性期望分数（is_correct 8/10 题为 1）；④ `test_approval.key`。契约测试 `tests/contract/`：schema 校验器接受 fixture 全部记录、拒绝 12 个变异样本（缺字段/错类型/bool 混 int/枚举外值）；令牌正样验证通过、坏令牌六种失败路径各返回正确原因码；哈希链断链检测；状态机非法迁移拒绝。

### 2.13 术语表与否证标准（嵌入每包）

术语（v1.0 §3.1 逐字）：**人格标签** = Big Five 等外部理论标签，仅用于对表文献；**行为控制原语** = 可测量、可干预并影响任务轨迹的内部方向或神经元集合（例：探索、验证、坚持、校准、质疑）；**自适应行为策略** = 按任务特征与历史反馈选择原语、方向、层和强度的路由策略。

否证标准（v1.0 §3.3 逐字，v1.1 §1.4 全部保留；任一出现记**有效负结果**入账本，不得丢弃或重跑覆盖）：人格评分变化明显但能力变化在控制长度和格式后消失※；只有单个 benchmark、单个系数、单个模型有效；随机等范数方向产生同等增益；calibration 有增益 held-out 反转；动态路由不优于按 benchmark 固定人格（G1 后适用）；内部干预普遍不如文本提示；正负 steering 均只导致输出质量下降；量化模型有效而 BF16 不复现；LLM judge 喜欢 steered 输出但确定性准确率不变。※修正注（V1.3 M9）：长度不再作硬性条件化变量，改三段分解报告；硬性否证前提仅随机方向对照 / 流畅性 PPL / 格式遵循三项。

呈现纪律：W1 一切数字带 `exploratory / rig-validation` 标注；mini 环产出不构成任何假设的证据；对外材料数字必须出自账本视图（三轨共享同一事实源）。QUARANTINED 批不删除、不采纳、不重跑覆盖——留证 + 人裁决。

---

## 3. 工程包范围界定（详细任务在各工程包文档）

### 3.1 包 A · 账本 + 状态机 + Auditor（裁判 + 验船师）

**阶段1**：接管 `common/ledger_ref.py` 维护权并补测试；`ledger/schema.py`（§2.5 全字段校验器 + scores/信封/事件校验）；`statemachine.py`（三层状态机迁移守卫 + TTL 表）；`views.py`（DuckDB read_json 只读视图：run 汇总/批次进度/异常清单——推荐查询面；阶段1 并行期 C 可依契约 schema 自建只读查询，R1 后自愿切换，两者都只许只读）；`rescore_v1`（从 steps.jsonl 原始输出独立重算确定性指标，黄金十题 fixture 绿）；auditor v0（六项中的 1 manifest 完整性、2 重评分比对、4 健康面板——parse 失败率/拒答率/截断率/空输出/重复退化，超阈整批 QUARANTINED）；audit 报告格式（JSON+MD，逐项 PASS/FAIL+证据指针）。
**阶段2**：auditor 补全（3 防污染：抽取语料∩评测题=∅ 哈希级、split hash 核对、judge 输入结构检查不含条件字段、泄漏词表 grep；5 版本一致：git clean/code_tree_hash/env lock；6 成本对账：预估 vs 实耗偏差 <10%）；`budget_recon.py`（¥150 W1 顶、85% 熔断线）；冻结区 Seatbelt profile + 定稿仪式脚本；**故障演练脚本四件**（drills/：杀进程、伪报完成无 step、实例空转模拟、越权写冻结区）。
**不做**：一切生成/评分（scorer 是 B 的；A 只复评）；界面。

### 3.2 包 B · Operator + 队列 + 恢复 + 云生命周期 + rig + 科学载荷（运动员）

**阶段1（闭环件）**：`faketask.py`（§2.12 规格 + 故障旋钮）；`queue.py`（信封→run 展开入队，目录式队列 pending/running/done/failed 原子改名）；`dispatch.py`（只接受令牌验证通过的信封；逐 run 驱动执行器；账本事件全程落）；`runstate.py`（item 级断点续跑对账，V2 resumable 范式：register→pending_items→mark_item_done→scan_orphans→can_resume 毒丸上限+冷却）；`heartbeat`（每 5 item 落 step_progress）；`watchdog.py`（停摆/孤儿/TTL 超时检测，冷却去重，只告警不自修）。
**阶段1（非闭环预研，不受门约束）**：vendor clone（pin `b8e0f044fe2410a6fad579f38324f03f13b4e917`）；judge 冒烟四验（deepseek-chat 有效性 / logprobs+top_logprobs=20 / 0–100 数字单 token 化 / seed 参数不 400）；3 锚 trait 工件生成（尽责/开放/神经质，官方元 prompt，窗口自身生成，送楠过目）；云日 runbook 初稿。
**阶段2**：rig v0（models.py 加载+模板哈希+三样例逐字节检；hooks.py 注入/消融；interventions 三件 prompt_persona/residual_vector/controls 等范数随机方向；scorer deterministic_v1 黄金十题绿；runner config→前置检查→逐 item 逐 seed→step 落盘→幂等续跑）；黄金测试四件 + 合成 2-step 轨迹；splits + ifeval_zh_v1 任务族 250 题 + hash 入 git；云生命周期（instance 登记接账本、完成即关机核验）；**云日 #1/#2 执行**（官方 trait 五阶段复现对表→翻转 demo；锚 trait 抽取→表达检盲评→小系数扫描；7B mini 环走完整闭环；20 题 temp0 双引擎 parity）；两个官方代码最小补丁（generate_vec.py 加 bf16、config.py HF_TOKEN 可选化）谱系记录。
**不做**：复评（A）、审计、信封起草（C）、同步视图。

### 3.3 包 C · Governor + 审批信封 + 同步视图（大副）

**阶段1**：`envelope.py`（§2.6 格式与校验）+ `approval_token.py` 维护权（canonical 全码内嵌）+ `abcrctl`（人侧 CLI：draft/approve/reject/status；首用生成密钥）；`planner.py` 固定规则计划器 v0（输入 plan-spec JSON → 信封草案 + 预算预估 + 符合性预检清单：split 只 dev、预算内、条件在白名单——**零 LLM**）；`triage.py` 异常分诊 v0（账本事件规则分桶→异常摘要 MD，例外驱动：正常一行、篇幅给偏差失败待决）；`sync.py` 四段同步视图（上午计划与待批/下午进展与偏差/晚间结果失败与明日建议/紧急仅 A 级——**只读 A 的 views.py，禁止自由回忆，逐数带 run_id**）；`report.py` 三层钻取 CLI（宏观→臂→单题原始输出 ≤1 分钟）。
**阶段2**：shadow 模式运转（对真实批次出计划草案与偏差报告，人批人派，草案 vs 人工决策差异记录——阶段3 毕业的证据流）；`repro_pack.py`（复现包出包：manifest+configs+steps+scores+激活摘要+env lock+复跑复评 README+主图+诚实条款+exploratory 标注）+ 闭合验收协议文档；周证据对象包模板（一图+一段可复现说明+本周失败+下周假设）；方向锁盲规则内建（确认期同步不含效应方向——W1 即写入代码路径，硬编码 phase 判断）。
**阶段3（本轮只交代码不接线）**：notify.py（飞书告警+按类 24h 冷却，auditor bot 凭证）；信封内自动派发开关（毕业判据：20 run shadow 零关键差异 + auditor 全绿）。
**不做**：一切执行与评分；boss_console 式界面。

---

## 4. 阶段门协议（fable 职责）

### 4.0 R0 · kickoff（fable 单独执行，≈2h）

1. 建仓 `/Users/superagent/abcr`（git init；repo 级身份 abcr/abcr@local；.gitignore：.env、data/runs/、ledger/、queue/、state/、plans/、.venv、__pycache__）。
2. 目录骨架（§2.1 全目录 + .gitkeep）；`data/golden/golden10.json`（§2.10 + pass/fail 样例）；`fixtures/` 四件（§2.12）；`src/abcr/common/`（ledger_ref.py 权威实现、approval_token.py canonical 全码、constants.py：枚举/TTL/GENESIS/salt）；`tests/contract/` 契约测试。
3. `uv venv --python 3.12 .venv`；requirements-mac.txt（torch transformers accelerate datasets duckdb pandas pyarrow typer pydantic pytest scipy statsmodels openai backoff lark-oapi python-dotenv matplotlib）；.env 注入（DeepSeek key 自 V2/.env 复制；OPENAI_BASE_URL=https://api.deepseek.com；HF_ENDPOINT=https://hf-mirror.com；AUDITOR bot 凭证对；ABCR_STATE_DIR）。
4. 契约测试对骨架全绿 → 首 commit → 三分支三 worktree → 三窗口开工。fable 退出日常编码。

### 4.1 R1 · 无LLM闭环回归门（阶段1 末，fable 主持 ≈1h）

**R1-core 最小集裁定（AMENDMENT-30）**：R1 门只验 fixture 闭环六步所需最小件——A（ledger+schema+statemachine+rescore+auditor v0 items 1/2/4）、B（faketask+queue+dispatch+runstate+heartbeat）、C（envelope+approval_token+abcrctl）。A 的 views、C 的 planner/triage/sync/report、B 的 watchdog 调优与预研件属 **R1-full**，在阶段2 期间完成、R2 前齐——这样阶段1 两个 4h 窗的工时才立得住。

演练脚本（fable 手跑）：`scripts/abcrctl approve fixtures/envelope_fixture.json --key fixtures/test_approval.key` → B dispatch 消费 → 6 假 run 执行（含 1 个注入 crash 的 run 断点续跑成功）→ scorer 评分 → A rescore 比对一致（与 expected_scores.jsonl 全同）→ auditor 出报告（含对 g03/g07 已知错误分布的正确呈现）→ `abcrctl status` 显示批次全貌 + 最小账本查询钻取到单题原始输出（C 的四段 sync 属 R1-full，不卡此门）。**判据：全链零人工（批准动作除外）；契约测试仍全绿；任一步失败不进阶段2。** 通过后 fable 合并三分支→main，汇编 Makefile。

### 4.2 R2 · 真实执行回归门（阶段2 末，fable 主持 ≈2h）

① **故障注入四演练**：杀 RUNNING 进程（B 恢复+对账续跑）；faketask `skip_ledger_writes` 伪报完成（A auditor manifest 完整性拦截→QUARANTINED）；实例空转模拟（预算告警触发，阶段2 落文件/控制台）；沙箱内越权写冻结区（EPERM+留痕）。② 真实数据闭环：7B mini 环批次从信封到审计报告全链。③ W1 出口门 G1–G7 逐项核验（可重复/schema 就绪/配方校准/首批向量/闭环闭合/预算 ≤¥150/呈现纪律）。④ 复现包闭合验收：fable 开全新会话仅给包，从原始输出复算全部确定性分数一致。⑤ 楠验收 + 决定阶段3 开启时点。

### 4.3 日常纪律（阶段内，fable 不编码）

每窗口每日收工写 PROGRESS.md（完成/未完成/BLOCKER/契约疑议四节）；fable 每日读一遍、只裁决 BLOCKER 与契约疑议（异步、≤20 分钟）；**契约修订权在 fable**：任何窗口不得自行偏离契约，疑议走 PROGRESS，修订即广播三窗口并记 AMENDMENT 于本文档。

---

## 5. 云日方案（阶段2 内；B 包 runbook 上位约束）

- 供应商：AutoDL 类网页控制台，24GB 卡（4090 级）；**楠开机付费 = 发射钮**；下单当日核价入 instances.jsonl。
- 标准序：官方 requirements（Python 3.10–3.12 镜像）→ HF 端点按机房定（境内设 hf-mirror）→ 5% smoke（单 trait 单 instruction 2 响应走通阶段 2）→ 全量。checkpoint 常态化、产物即时回传+哈希校验、**完成即关机**（runbook 末尾核验 + 账本 instance_stopped）。
- 云日 #1（目标 7/15，**人工派发合法降级**，不等控制面）：官方 trait（默认 optimistic，备选 sycophantic）五阶段复现→对表校准→**翻转 demo 素材**（晚间楠向爱人展示）。
- 云日 #2（目标 7/17，走完整闭环）：3 锚 trait 抽取→向量→表达检→小系数扫描；abcr rig（git bundle 部署）跑 7B mini 环（50 题 ×3 臂 ×2–3 seed，信封→审计全链）；20 题 temp0 parity 烟检。
- 预算：W1 云实耗上限 **¥150**；预计 ¥40–100；85% 熔断告警。
- 云侧账本裁决（AMENDMENT-2）：云机上产生的账本事件写**独立哈希链段**（`ledger/cloud-day<N>/` 子目录，各文件自成一链），随产物整体回传归档，不与 Mac 侧链拼接；Auditor 对账时按段独立 verify_chain。

---

## AMENDMENT 记录

- **AMENDMENT-1**（2026-07-11，源：包B起草 GAP）：batches 事件词表增补 `batch_rejected`。
- **AMENDMENT-2**（2026-07-11，源：包B起草 GAP）：云侧账本独立链段设计获批。
- **AMENDMENT-3**（2026-07-11）：golden10.json 顶层结构与 faketask 故障旋钮环境变量名冻结（见 §2.12）。
- **AMENDMENT-4**（2026-07-11，源：包A GAP）：全局账本文件（runs_index/batches/costs/instances）中事件主体用 `subject_id` 键（run 事件填 run_id 值、batch 事件填 batch_id 值）——因 RunLedger.append 的保留键限制，payload 不得再用 run_id/batch_id 作键名者改用 subject_id + 辅助键。
- **AMENDMENT-5**（2026-07-11，源：包A GAP）：REJECTED 状态经 `run_audited` 事件 payload `verdict:"rejected"` 表达；整批隔离 = 批内逐 run `run_quarantined` + `batch_audited` payload `verdict:"quarantined"`。事件词表不再扩枚举。
- **AMENDMENT-6**（2026-07-11，源：包A GAP）：hedging_rate / self_check_marker_rate 公式冻结 = 句级命中率（含 ≥1 词表词的句子数 / 总句数；句切分符 。！？!?.；换行）；词表采纳包 A §A1-5 提案，kickoff 时由 fable 抄入 `src/abcr/common/constants.py`，A/B 共享词表常量、独立实现计数。
- **AMENDMENT-7**（2026-07-11，源：包A GAP）：健康面板 W1 默认阈值获批（parse_fail>0.20 / refusal>0.20 / truncated>0.30 / empty>0.05 / repetition>0.20，env 可覆盖且写入报告头）；协议对象冻结事件立第五链 `ledger/protocol.jsonl`（事件：artifact_frozen / artifact_superseded）。
- **AMENDMENT-8**（2026-07-11，源：包A GAP）：judge 调用留痕契约 = `data/runs/<run_id>/logs/judge_calls.jsonl`，每行 {ts, judge_model, item_id, messages 完整体, params}（不含任何密钥）；Auditor 盲评检查断言 messages 中不出现 condition/trait_pole/臂标识。B 的 judge 客户端必须落此档。
- **AMENDMENT-9**（2026-07-11，源：包A GAP）：costs 事件 payload 必含 {subject_id, amount_cny, basis}；instances 事件必含 {instance_id, vendor, spec, price_cny_per_h, batch_id}。
- **AMENDMENT-10**（2026-07-11，源：包C GAP）：`batch_drafted / batch_approved / batch_rejected(人工驳回)` 三事件由 **abcrctl（人侧 CLI）以"人"身份追加**至 batches.jsonl——权限矩阵"人"行修订为"batches.jsonl 限此三事件经 abcrctl 追加"；Governor 进程本体仍对账本只读；B 的 dispatch 落 batch_dispatch_started 起的事件。信封文件仍是 DRAFT/APPROVED 态的权威载体，账本事件为审计镜像。
- **AMENDMENT-11**（2026-07-11，源：包C GAP）：审批令牌 `scope` 值冻结为 `"batch_approve"`（verify 校验断言此值）；consumed 账本路径冻结为 `state/approvals/consumed.json`。
- **AMENDMENT-12**（2026-07-11，源：包C GAP）：坏令牌 fixture 文件名冻结为 `fixtures/envelope_fixture_badtoken.json`（§2.12 的"坏令牌样例"即此独立文件）。

> 以下 AMENDMENT-13~30 源自五路对抗校验（3 模拟执行者 + 跨文档一致性 + 科学保真），为 fable 统一裁决；与三包正文冲突处以本块为准，修复已回填。

- **AMENDMENT-13**：batch_rejected 语义分裂裁决——`batch_rejected` 专指人工驳回（abcrctl 落账）；dispatch 侧拒绝另立 `batch_dispatch_rejected`（B 落账，payload 原因码 + subject_id）。B 的拒绝路径改为"账本事件 + 告警文件双留痕"。
- **AMENDMENT-14**：`data/runs/<run_id>/scores.jsonl` 为**非哈希链** append-only JSONL（多 scorer 直接文件级追加，写后 flush；只追加、不改行）；防篡改由复现包整体哈希 + A/B 双实现比对承担。"经账本 API 写 scores"的表述作废。
- **AMENDMENT-15**：ledger/ 全局五链的并发写互斥——ledger_ref.append 对 `<chain>.jsonl.lock` 持 fcntl.flock(LOCK_EX)，锁内重读链尾再写（全局链放弃链尾内存缓存）；`data/runs/<id>/steps.jsonl` 单写者，保留缓存。kickoff 的 ledger_ref 按此实现。
- **AMENDMENT-16**：状态机审计豁免迁移——COMPLETED/FAILED/SCORED → AUDITED 均合法（审计可介入任何非终态后）；ACCEPTED/REJECTED/QUARANTINED 只能自 AUDITED 进入。审计处置落账序：一律先 `run_audited`（payload verdict）再终态事件；`--apply` 且 PASS 时逐 run 落 run_audited(verdict:"pass")+run_accepted，批次落 batch_audited(verdict:"pass")。
- **AMENDMENT-17**：故障演练一律在临时隔离 root（`state/audit/drills/<ts>/` 下的账本副本）上跑，真链零写入；演练注入事件 payload 必带 actor="drill"；演练用独立节流文件。演练所需 instances 事件由 A 的 drill 脚本在隔离副本内自行追加（隔离副本非生产账本，不算越权）。
- **AMENDMENT-18**：`state/alerts/*.json` 升格为告警文件接口（豁免"私有黑箱"铁律）：B 写、A/C 只读；文件名 `<ts>-<kind>.json`，JSON 至少 {ts, kind, severity(A/B/C), subject_id, reason}。
- **AMENDMENT-19**：`run_registered` 事件 payload 必含 `batch_id` 辅助键（run↔batch 关联的账本通道）；未启动 run 的钻取降级用信封 run_configs 对账。
- **AMENDMENT-20**：B 的 scorer.py 确定性判分函数保持 stdlib 自包含（不 import torch/numpy/abcr 他模块）；复现包同时打包 A 的 rescore 判分副本与 B 的 scorer 副本，独立复算以 **A 副本为主**，与包内 deterministic_v1 与 rescore_v1 两组分数分别比对；出包自检 = 空 PYTHONPATH subprocess import 两副本，失败拒绝出包。
- **AMENDMENT-21**：指标语义冻结——`parse_ok = int(bool(output_text.strip()))`；`output_len_chars = len(output_text)`（不 strip）；`output_len_tokens` = output_tokens 值。hedging/self_check 句切分符集 = `。！？!?.；` + 换行（维持 AMENDMENT-6），词表与切分符集入 constants.py，A/B 共 import。
- **AMENDMENT-22**：run_id 幂等化（正文 §2.8 已改）——时间戳分量取 batch_id 内嵌时间戳；信封内 config_hash 唯一。
- **AMENDMENT-23**：dispatch 对已 batch_settled 的信封：先查账本，命中打印 already-settled 并**退出 0**、零新事件、不触碰令牌（令牌校验在此检查之后）。
- **AMENDMENT-24**：faketask 的 CRASH_AT_ITEM 语义 = 进程即死（os._exit(1)，dispatch 不捕获）；dispatch 启动对账三步 = scan_orphans → queue/running 中已 suspended 且 can_resume=ok 者重驱动 → queue/failed 中 can_resume=ok 者 requeue 再正常 claim。"继续下一 run"仅适用于非 crash 类被捕获异常。
- **AMENDMENT-25**：续跑去重以 steps 为准——resume 驱动前读该 run 已有 steps.jsonl 的 (item_id, random_seed) 集合，命中者跳过 emit_step 只补 mark_item_done。
- **AMENDMENT-26**：网络白名单增补（正文铁律②已改）：registry.ollama.ai / modelscope.cn / 云实例 SSH。
- **AMENDMENT-27**：新增 `data/vectors/` 归 B（非冻结区）作向量产物落位；config 的 vector_path 指向 data/vectors/；data/traits/ 只存 trait 工件 JSON（冻结）。
- **AMENDMENT-28**：预算失明修复——① dispatch 消费信封时逐 run 落 `run_cost_estimated`（信封 cost_cap 均摊或 planner 预估，AMENDMENT-9 键名 + batch_id）；② check_fuse 计入进行中实例估计（started 无 stopped × price_cny_per_h × 已运行小时）；③ watchdog 增第三类检测：instances 有 started 无 stopped 且无 RUNNING run（或最近 step_progress >15min）→ instance_idle_alert + state/alerts 文件；④ 云日 runbook 长跑段每 30 分钟 `watchdog --once`、每 60 分钟预算检查、每阶段产物增量回传（rsync/scp + sha256）；⑤ 云日#2 在全量抽取前插入 5% smoke 步。
- **AMENDMENT-29**：mini 环 seed 制 = 每 config 的 seeds 在 run 内循环（3 config = 3 run，steps 内 random_seed 区分）；阶段1 fixture 的每-seed-一-run 是 fixture 特例。
- **AMENDMENT-30**：R1 拆 R1-core（fixture 闭环六步最小件，7/14 上午过门）与 R1-full（A views、C planner/triage/sync/report、B watchdog 调优与预研件，R2 前齐）；正文 §4.1 已改。B 预研件（judge 冒烟/trait 工件/runbook 初稿）排 R1-core 后、云日前。
- **AMENDMENT-31**（杂项打包）：A2-1 检查3 泄漏断言集 = condition 枚举词 + trait_pole 标签 + 臂标识词，**不含 trait 名**（官方 eval_prompt 必然含 trait 名，豁免）；manifest 必含键显式编号 22 项；reports/demos 命名分区（B 产物 b_* 与 flip_demo_*，C 产物 sync-/triage-/weekly/repro-*）；信封故障时手工起草主体 = 楠或 C 窗口，B 永不起草；fake step 的 split_hash 取 "fixture"；triage 增 A/B/C 三级桶与"今日 A+B 告警数 N/3"计数行；mini 环主图 = 双联图（左：三臂逐 seed is_correct 点图；右：每臂 output_len_tokens 分布），注 "rig-validation, not evidence"；云日#2 选参依据为在线非盲 judge 分属校准动作，须显式偏离标注，盲评翻转时按 rig 验证引用。

---

## 6. 风险与止损

| 风险 | 信号 | 应对 |
|---|---|---|
| 契约缺陷致包间不齐 | 契约测试红 / R1 失败 | 修订权在 fable，修订广播 + AMENDMENT 记录；fixture 先行暴露大部分此类问题 |
| 窗口越界 | merge 冲突 / 契约测试被改 | 归属矩阵仲裁，越界改动整体 revert 重做 |
| DeepSeek judge 三坑（数字非单 token / deepseek-chat 失效 / seed 400） | 冒烟四验失败 | 降级：deepseek-v4-flash → judge 文本解析模式（记偏离）→ 报楠 |
| hf-mirror 缺仓/限速 | 下载失败 | 备选 modelscope；模型下载 D1 后台先行 |
| 云日失败/卡回收 | smoke 不过或中断 | checkpoint+幂等续跑；顺延一天并砍 mini 环题量 50→30 |
| MPS 数值怪癖致 hook 检假红 | Mac 红且逻辑无误 | 容差已留裕量；仍红移云日 CUDA 复验，Mac 结果标 non-citable |
| 阶段1 拖期挤压科学交付 | R1 未按期 | 非闭环预研已并行；云日#1 人工降级路径与控制面解耦；最坏砍 parity 与 3B 路径，主链（复现+闭环闭合）不砍 |
| 控制面吞噬研究时间（自动化设计 D6 红线） | 阶段2 中控制面新特性冲动 | 特性由实际痛点拉动；W1 后控制面 ≤20% 周工时；界面/飞书恒排阶段3 |
| 探索期算力越线 | W3 周三仍未收口 | V1.2 §13 仍生效：硬切确认期，未完成 trait 弃用 |

---

## 7. 嵌入决策清单（可否决；未否决即按此执行）

- **D1** 仓库 `/Users/superagent/abcr`，本地 git 无远端，repo 级身份 abcr/abcr@local。
- **D2** Python 钉 3.12；Mac venv 与云端 venv 分离；vendor 在 `/Users/superagent/abcr-vendor/`（git 外）。
- **D3** 三窗口=三 worktree 三分支；fable 只在回归门合并；Makefile R1 时汇编。
- **D4** schema 裁定：stop_reason / trajectory_stop_reason 拆分；trait_score/fluency_score 在 steps 恒 null，权威值在 scores.jsonl。
- **D5** judge：DeepSeek OpenAI 兼容端点 + deepseek-chat（冒烟验证，失效换 v4-flash）；过滤 judge 与表达检 judge 同为 DeepSeek；第二家族一致性抽样用本地 ollama gemma3（楠给 OpenAI key 则升级官方对表）。
- **D6** HF_TOKEN 缺失：官方 config.py 2 行补丁使其可选（谱系记录）；楠提供真 token 则撤。
- **D7** generate_vec.py 加 bf16 补丁（否则 fp32 7B 在 24GB OOM）；谱系记录。
- **D8** 官方 trait 复现默认 optimistic；sycophantic 预算富余加跑。
- **D9** 飞书复用 AUDITOR bot + V2-1 群（阶段3 接线；新建群改 .env 一字段）。
- **D10** 锚 trait 工件由窗口 B 生成（订阅额度），provenance 记"Claude Opus 4.6 生成、楠人工过目"。
- **D11** rig 归 B（运动员），Auditor 归 A（验船师）——楠三包切分下的归属裁决；科学载荷=阶段2 第一真实负载；trait 工件/judge 冒烟/runbook 为非闭环预研可在阶段1 并行。
- **D12** 云日#1 走人工派发合法降级（目标 7/15 出 demo）；云日#2 走完整闭环。
- **D13** W1 全批次人工批准；阶段3 毕业判据 = 20 run shadow 零关键差异 + auditor 全绿（事件制，弃时间制）。

---

## 8. 引用映射与效力声明

v1.0 完整文档（1675 行）**不在盘上**（全盘搜索确认；盘上同名文件为 221 行节选且其 §3.2 旧假设已作废）。工程包内一切 "v1.0 §X" 引用按下表解引用，禁止写"参见 v1.0"：§5.1→交接文档§6.1；§5.2→§6.2；§4.2→§6.3；§6.2(切分)→§6.4；§7.4→§6.5；§8→§6.6；§9.1→§6.7；§10→§6.8；§12–13→§6.9；§14→§6.10；§15/16/19→§6.11；§3.3 否证标准→本文 §2.13 逐字嵌入。遇摘要未覆盖边界：以 V1.3+交接文档为准，缺口记账本，不脑补 v1.0。V1.2 §13 风险表七行经 V1.3 显式保留仍生效（探索期超 30% 硬切、T1 顺延 W11、孪生检重抽一次、探针换层一次等）。v1.1 残余增量三条（向量卡 W6 起每周≥一张、manipulation check 与能力指标分列、反馈冷淡不换命题）已分别落入 §2.5、周模板与不做清单。
