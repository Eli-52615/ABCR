#!/bin/bash
# scripts/run_r2_batch.sh —— 一条命令跑完 golden10 R2 真批并判门（非技术人员照抄用）。
#
# 用法：
#   bash scripts/run_r2_batch.sh              # 云端真跑（真 7B，默认）
#   bash scripts/run_r2_batch.sh fake         # 本地自证（Mac 无 GPU 也能跑，验证流程通不通）
#
# 它依次做：生成并签信封 → dispatch 跑批 → 独立复算 → 六项审计 → C 出包+仓库外独立复算 → 打印 R2 判门。
set -euo pipefail
cd "$(dirname "$0")/.."          # 切到仓库根
export PYTHONPATH=src
ENGINE="${1:-transformers}"
PY="${PY:-python}"              # 若 python 不是想要的解释器，设 PY=/path/to/python

echo "════════════════════════════════════════════"
echo " R2 真批 · engine=$ENGINE"
echo "════════════════════════════════════════════"

echo; echo "==> 1/5 生成并签发信封"
GEN=$($PY scripts/make_r2_envelope.py --engine "$ENGINE")
echo "$GEN"
BATCH=$(echo "$GEN" | grep -oE 'B-[0-9]{8}T[0-9]{6}Z-0001' | head -1)
[ -n "$BATCH" ] || { echo "✗ 没抓到 batch_id，停"; exit 1; }

# 真 engine 前置:B2-1 chat_template 防漂移闸需冻结样例;缺则用真 tokenizer 自动冻结一次（非交互）。
if [ "$ENGINE" != "fake" ] && [ ! -f data/benchmarks/chat_template_samples.json ]; then
  echo; echo "==> 1.5/5 首次冻结 chat_template 样例（$MODEL_ID @ $REVISION;仅加载 tokenizer）"
  $PY scripts/b_freeze_template_samples.py --model "${MODEL_ID:-Qwen/Qwen2.5-7B-Instruct}" --revision "${REVISION:-main}"
fi

echo; echo "==> 2/5 dispatch 跑批（真 7B 会下载模型+逐题推理，请耐心；fake 秒完）"
$PY -m abcr.ops.dispatch --envelope "configs/envelopes/$BATCH.json" --key state/approval.key

echo; echo "==> 3/5 独立复算（追加 rescore_v1 分数）"
$PY scripts/a_rescore.py "$BATCH" --repo-root .

echo; echo "==> 4/5 六项审计"
$PY scripts/a_audit.py "$BATCH" --items 1,2,3,4,5,6 || true
echo "   （若只有 item6 成本对账 FAIL：那是还没记 GPU 实耗——见下方‹补记实耗›，其余项 PASS 即结构就绪）"

echo; echo "==> 5/5 C 出包 + 仓库外独立复算（R2 核心判据）"
$PY -c "from abcr.report.repro_pack import pack; print('pack:', pack('$BATCH'))"
( cd "demos/repro-$BATCH" && \
  env -i PATH=/usr/bin:/bin HOME="$HOME" "$($PY -c 'import sys;print(sys.executable)')" \
    tools/rescore_standalone.py --pack . --report /tmp/r2_agreement.json )
echo "   agreement 报告：$(cat /tmp/r2_agreement.json)"

echo
echo "════════════════════════════════════════════"
echo " R2 判门读法："
echo "   ✓ 上面 a_audit 的 item1~5 全 PASS（item6 见‹补记实耗›）"
echo "   ✓ agreement_deterministic_v1=1.0 且 agreement_rescore_v1=1.0"
echo "   两条都满足 = R2 硬门过。batch_id=$BATCH"
echo
echo " ‹补记实耗›（让 item6 也 PASS，把 <实耗元> 换成这次 GPU 花了多少钱）："
echo "   $PY -m abcr.ops.cloud stop --instance run --amount-cny <实耗元> --verified-by you || true"
echo "   然后重跑：$PY scripts/a_audit.py $BATCH --items 6"
echo "════════════════════════════════════════════"
