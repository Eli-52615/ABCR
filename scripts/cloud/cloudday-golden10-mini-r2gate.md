# Cloud Day · golden10 mini环 R2 真批（真 7B bf16 → A 审计6项 + C 复算agreement=1.0）

> **这是什么**：R2 硬门要的「真 mini 环 golden10 批」。W1 云日跑的是 persona 抽取/转向 eval（trait_score
> 判官打分、非确定性），**不是** golden10 基准批；而 R2 的 A 真批审计（item1 步数==golden10、item2
> is_correct 确定性复算）和 C 真批复算（agreement=1.0 over 确定性指标）是为 golden10/mini环 设计的。
> 故 R2 真批需要**本 runbook 单独在云上跑一次真 7B 的 golden10 批**（楠 2026-07-15 裁决：补跑真 mini环）。
>
> **执行者**：租到 24GB GPU 卡、云箱有 torch 的人。零思考照抄。
> **预算**：¥150 上限（E16 熔断，超线立即关机、记账、提 STATUS-B）。golden10 只 6 run×10 题，
> 推理量远小于 persona 全量，预估 ≤¥30。
>
> **消费侧已本地证明就绪**（2026-07-15 dry-run，见 §6）：fixture golden10 批经真 dispatch →
> a_rescore → a_audit 得 item1/2/3/4/5 PASS（仅 item6 因 faketask 无实耗 FAIL，真云跑记账即过）；
> C 出包空 PYTHONPATH 仓库外独立复算 **agreement_deterministic_v1=1.0 / agreement_rescore_v1=1.0**
> （360 三元组）。**本 runbook 只把 faketask 换成真 7B + 补两件真云才有的东西（实耗记账、citable 字段）。**

---

## ✅ ⓪ 代码前置：已接好（2026-07-15，无需你动代码）

R2 审计要求每个 run 经 **dispatch 落 `run_registered` 等账本事件**。dispatch↔runner 的 engine 分支
**已接通并验证**（commit 见 `git log --grep=engine`）：

- `dispatch._process_run` 按 `cfg["model"]["engine"]` 分发：`fake`→faketask（R1 路径零变化）；
  非 fake→`runner.run_items(...)` 真模型驱动，**dispatch 恒握账本事件/队列收口/心跳/评分**。
- `runner.py`：`RUNS_ROOT` 已 env 化（`_runs_root()` 读 `ABCR_RUNS_ROOT`）；新增 `run_items()` 真执行器。
- torch-mock 单测 `tests/rig/test_dispatch_runner_engine.py`（3 用例，无 torch 也过）证：engine≠fake 路由
  到 runner、产真 48 字段 step（过 validate_step）+真 22 键 manifest（engine/model_id 真值）+全账本事件；
  engine=fake 仍走 faketask。**R1 selfcheck + 773 测全绿。**

**你要确认的（一条命令）**：
```bash
grep -nq 'engine == "fake"' src/abcr/ops/dispatch.py && echo "engine 分支在位 ✓"
```

**支持臂**：vanilla、inject/ablate（向量臂，需真 .pt 向量）、inject_random/ablate_random。
⚠️ **persona_text 臂**经 dispatch 暂不支持（需 trait 工件，run_items 会 fail-closed）——golden10 R2 批用
vanilla+向量臂即可；若必须跑 persona_text，走 `runner.run_config` 独立驱动或后续接 trait_artifacts。

---

## ① Provision 检查单

```bash
nvidia-smi                       # 期望 ≥24GB VRAM (4090/A5000/L20/A100), CUDA ≥12.1
# 记账（立即执行，不等跑完）——真云跑必须记 run_cost_actual，否则 auditor item6 对账 FAIL
cat >> costs/ledger.jsonl <<EOF
{"ts":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","provider":"<填>","instance":"<填>","rate_cny_h":<填>,"purpose":"golden10-mini-r2gate-7b"}
EOF
# 预估：6 run × 10 题 × (1-2 seed) 推理 + judge ≈ 20-40min，成本 ≤¥30
```

## ② 环境

```bash
cd /workspace/abcr                      # Mac→云传输方式自定（scp/rsync）
# 主 venv（judge + rig runner 用 transformers）
python -m pip install torch transformers openai==1.70.0 backoff==2.2.1 pyyaml==6.0.2
python -c "import torch; print('CUDA', torch.cuda.is_available())"
# 模型（Qwen 不 gated，走 HF 镜像）
# ⚠️ 关掉 Xet 加速——镜像不支持,不关会卡 0 字节报 401(cas-server.xethub.hf.co)
python -m pip uninstall -y hf_xet 2>/dev/null || true
export HF_HUB_DISABLE_XET=1
export HF_ENDPOINT=https://hf-mirror.com
python -c "
from transformers import AutoModelForCausalLM, AutoTokenizer
AutoModelForCausalLM.from_pretrained('Qwen/Qwen2.5-7B-Instruct', torch_dtype='bfloat16')
AutoTokenizer.from_pretrained('Qwen/Qwen2.5-7B-Instruct'); print('model OK')"
# 记录 snapshot sha → 更新 configs/models.yaml 的 revision（citable 溯源必需）
# judge key（每 shell 一次）——用主仓已验证的 35 字节 key（2026-07-15 冒烟 verdict.ok=True）
set -a; source .env; set +a
PYTHONPATH=src python scripts/b_judge_smoke.py   # 期望 verdict.ok=true, deepseek-chat valid
```

## ③ Smoke（不过即关机排障，别烧全量）

```bash
export PYTHONPATH=src
# 真 engine 的 R1 自证：先确认 ⓪ 的接线在真 engine 下也能收口（用 2 题微批）
# 用一个 engine≠fake 的微信封（configs/envelopes/smoke-golden10.json，benchmark.item_limit=2）
python -m abcr.ops.dispatch --envelope configs/envelopes/smoke-golden10.json --key state/approval.key
# 期望：dispatch 退出 0、data/runs/<rid>/steps.jsonl 有真模型输出（engine 非 fake、model_id=Qwen...）
ls data/runs/*/steps.jsonl && grep -m1 'Qwen' data/runs/*/manifest.json && echo "SMOKE OK" || echo "SMOKE FAIL→关机排障"
```

## ④ golden10 mini环 真批（R2 正本）

```bash
export PYTHONPATH=src
# 1) 造 R2 真批信封：configs/envelopes/<BATCH>.json（engine=transformers/vllm、model=Qwen2.5-7B、
#    benchmark.family=golden10 item_limit=10、6 个 config 覆盖 vanilla/inject/ablate 臂、seeds 按需）。
#    batch_id 形如 B-<UTC>-0001，须过 schema.validate_envelope；人签发令牌（sign_token）入 approval。
#    Gap3：configs/envelopes/ 目录此前不存在，C 出包也从这里读，务必建真信封（非 fixture fallback）。
BATCH="B-$(date -u +%Y%m%dT%H%M%SZ)-0001"     # 记下这个 BATCH，后续全用它
# 2) 真 dispatch 跑批（engine 非 fake → 走 runner 真 7B；隔离到 cloud-day 段避免污染主链，可选）
ABCR_LEDGER_DIR=ledger/cloud-day-r2 ABCR_RUNS_ROOT=data/runs ABCR_QUEUE_ROOT=queue \
  python -m abcr.ops.dispatch --envelope configs/envelopes/$BATCH.json --key state/approval.key
# 3) 补 run_cost_actual（真实耗记账，auditor item6 对账用）——用 ops/cloud.py 或直接记 costs 链
python -m abcr.ops.cloud stop --instance <id> --amount-cny <实耗> --verified-by <你> \
  --ledger-dir ledger/cloud-day-r2       # 若 CLI 名不同，见 scripts/b_instance.py
# 4) citable 合成（Gap6：让 non_citable=false，否则只是 non-citable 证据）：
#    确保 manifest git_clean=true + env_lock_ref 指向真实存在、含 python 版本行的 lock 文件 +
#    code_tree_hash 与云箱当前树一致。runner.write_manifest 已填多数字段，缺则补。
```

## ⑤ R2 门判定（回传后在任意有仓库的机器跑；消费侧已证就绪，见 §6）

```bash
export PYTHONPATH=src
# A 真批审计 6 项（先复算再审计——item2 依赖 rescore_v1 分数）
python scripts/a_rescore.py $BATCH --repo-root .
python scripts/a_audit.py $BATCH --items 1,2,3,4,5,6
#   期望：item1/2/3/4/5 PASS；item6 有真实耗记账后 PASS → overall PASS
# C 真批复算（出包 + 空 PYTHONPATH 仓库外独立复算）
python -c "from abcr.report.repro_pack import pack; print(pack('$BATCH'))"
cd demos/repro-$BATCH
env -i PATH=/usr/bin:/bin HOME=$HOME python tools/rescore_standalone.py --pack . --report /tmp/agree.json
#   期望：agreement_deterministic_v1=1.0  agreement_rescore_v1=1.0  integrity_ok=True
# 两侧齐 PASS = R2 硬门过。
```

## ⑥ 消费侧就绪凭证（本 runbook 前，Mac 2026-07-15 dry-run 已证）

| 环节 | 结果 | 备注 |
|---|---|---|
| 真 dispatch 产 golden10 fixture 批 | 6 run batch_settled | R1 selfcheck 同链 |
| a_rescore | +360 rescore_v1 行 | 6 run × 60 |
| a_audit item1/2/3/4/5 | **PASS** | golden10 形状、链完整、版本一致 |
| a_audit item6 | FAIL（仅 faketask 无实耗）| 真云跑记 run_cost_actual 即 PASS |
| C 出包独立复算 | **agreement 两组=1.0**（360 三元组，仓库外 `env -i`）| integrity_ok, 33 文件 |

**结论**：R2 消费链（A 审计 + C 复算）已就绪吃 golden10 批。真批过门只差本 runbook 在云上补：
真 7B 输出（§⓪+④）、真成本记账（§④.3）、citable 字段（§④.4）。

---

## 回滚 / 安全

- 超 ¥150：立即 `python -m abcr.ops.cloud stop ...` 关机、记账、STATUS-B 升级申请（E16）。
- 隔离建议：真批落 `ledger/cloud-day-r2/` 段（AMENDMENT-2 各段自成链，auditor/repro 自动 merge 读），
  主链不动；不放心可先 `ABCR_LEDGER_DIR` 指临时段跑通再并入。
- 本仓永不 git push（CLAUDE.md 规则6）；产物本地 commit + tar 回传。
```
