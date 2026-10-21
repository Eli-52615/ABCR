# faketask_spec —— 确定性假任务定义（阶段1 三包共同的靶，§3.10 / §2.12）

> 冻结版（fable 广播 20260715 · AMENDMENT-41）：A 版主体 + B 版旋钮精确语义合并。
> 实现归属 B：`src/abcr/ops/faketask.py`。

## 语义

假任务对 `item_id=gXX`（golden10 各题）确定性输出该题的 `pass_sample`，
**其中 g03 / g07 输出 `fail_sample`**，制造已知错误分布（`is_correct` 8/10 题为 1）。
输出取自 `data/golden/golden10.json` 的 `pass_sample` / `fail_sample` 字段。
无任何随机性（seed 不影响输出）——期望分数因此可预生成。

- 每 item 耗时 0.2s（`latency_ms ≈ 200`）。
- `engine="fake"`、`model_id="fake/deterministic-v1"`、`model_revision="fixture"`、
  `dtype="none"`、`device="none"`、`chat_template_hash="fixture"`、`split_hash="fixture"`
  （AMENDMENT-31 冻结）、`torch_version=null`、`cuda_version=null`、`benchmark="golden10"`、
  `condition` 取自 run config、`action="generate"`、`stop_reason="fake"`、
  `trajectory_stop_reason="task_done"`、`trait_score=null`、`fluency_score=null`、
  `is_correct=null`（生成时留 null，权威值在 scores）、`safety_flags=[]`、
  `protocol_ref="W1-V0.9"`、`env_lock_ref="requirements-mac.txt"`。

## 故障旋钮（环境变量注入，名称冻结 AMENDMENT-3；取值语义冻结 AMENDMENT-24/41）

| 变量 | 语义 |
|---|---|
| `ABCR_FAKETASK_CRASH_AT_ITEM=<item_id>` | 到该 item 进程即死 `os._exit(1)`，dispatch 不捕获（崩溃演练→下次 dispatch 启动对账三步断点续跑） |
| `ABCR_FAKETASK_HANG_AT_ITEM=<item_id>` | 到该 item 永久挂起（停摆演练→watchdog STALLED 告警） |
| `ABCR_FAKETASK_SKIP_LEDGER_WRITES=1` | 照常"跑完"并宣称完成，但不落 step_progress/steps 行（伪报完成演练→A 审计是防线） |
| `ABCR_FAKETASK_EXIT_WITHOUT_DONE=1` | 写完首 step 后 `os._exit(0)`，不发完成信号（幽灵状态演练） |

注：旋钮取值一律为 **item_id**（如 `g05`），非序数（AMENDMENT-24）。

## fixture 批次结构

`envelope_fixture.json`：6 个假 run config = 2 condition（vanilla / persona_text）× 3 seed（1/2/3），
benchmark=golden10，engine=fake。每 run 跑全部 10 题。
批粒度总 steps = 10 题 × 3 seed × 2 condition = 60 行。
`expected_scores.jsonl`：60 行 is_correct 期望（g03/g07=0，余 8 题=1；口径 AMENDMENT-35）。
（AMENDMENT-29 注：fixture 的"每 seed 一 run"是阶段1 特例，不代表真实批次口径。）

## 正确的健康面板行为

g03/g07 是 `is_correct=0` 的**已知错误分布**（判分错，不是 parse 失败）——五率应全部为 0、
健康面板 PASS；item2 比对确认 g03/g07 的 0 分被双方一致复算。
