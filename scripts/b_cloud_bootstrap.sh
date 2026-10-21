#!/bin/bash
# scripts/b_cloud_bootstrap.sh — 云日上云引导（§7.1 第 3–6 步合并；scp 上云后直接跑）。
# 在**云实例**上执行（不是 Mac）。前置：pv_src.tar.gz 已 scp 到 /root/。
# 用法（云上）：
#   export DEEPSEEK_KEY='sk-...'          # 从 Mac abcr/.env 人工带过来，勿走聊天明文
#   bash b_cloud_bootstrap.sh
#
# ⚠️ B1（记账/预算）纪律：本脚本只做环境引导，不开机/不计费——发射钮永远在楠手里。
# ⚠️ 补丁定位以 vendor 实文件为准（B1-9 vendor clone 完成后细化行号）；未命中即告警不静默。
set -euo pipefail

PIN_COMMIT="b8e0f044fe2410a6fad579f38324f03f13b4e917"
HF_MIRROR="https://hf-mirror.com"
MODEL="${MODEL:-Qwen/Qwen2.5-7B-Instruct}"

echo "==== [3] 解包 + 校验固定点 + 打补丁 ===="
cd /root
[ -f pv_src.tar.gz ] || { echo "缺 /root/pv_src.tar.gz（先 scp 上云）" >&2; exit 1; }
tar xzf pv_src.tar.gz
cd persona_vectors
HEAD_SHA="$(git rev-parse HEAD)"
if [ "$HEAD_SHA" != "$PIN_COMMIT" ]; then
  echo "vendor commit 不是固定点：$HEAD_SHA != $PIN_COMMIT（停，核对 checkout）" >&2
  exit 1
fi
echo "vendor commit OK: $HEAD_SHA"

# 补丁1（D6）：config.py HF_TOKEN 可选化——缺 token 不 raise、不把空 token 传给 hub
python3 - <<'PYEOF'
import re, pathlib, sys
p = pathlib.Path("config.py")
if not p.exists():
    print("WARN: config.py 不存在，跳过补丁1", file=sys.stderr); raise SystemExit(0)
src = p.read_text(encoding="utf-8")
orig = src
# 把对 HF_TOKEN 缺失即 raise 的检查降级为告警（宽松匹配；未命中则告警不改）
src = re.sub(r'raise\s+\w*Error\(([^)]*HF_TOKEN[^)]*)\)',
             r'print("WARN: HF_TOKEN 缺失，Qwen2.5 非 gated 可下载，继续", flush=True)  # patch D6',
             src)
if src != orig:
    p.write_text(src, encoding="utf-8"); print("补丁1 已应用 (config.py HF_TOKEN 可选化)")
else:
    print("WARN: 补丁1 未命中 HF_TOKEN raise 模式——请按 vendor 实文件手工核对", file=sys.stderr)
PYEOF

# 补丁2（D7）：generate_vec.py bf16 加载防 OOM
python3 - <<'PYEOF'
import re, pathlib, sys
p = pathlib.Path("generate_vec.py")
if not p.exists():
    print("WARN: generate_vec.py 不存在，跳过补丁2", file=sys.stderr); raise SystemExit(0)
src = p.read_text(encoding="utf-8"); orig = src
# 给 from_pretrained(..., device_map="auto") 补 torch_dtype=torch.bfloat16
src = re.sub(r'(AutoModelForCausalLM\.from_pretrained\(\s*[^)]*?)device_map\s*=\s*["\']auto["\']',
             r'\1torch_dtype=torch.bfloat16, device_map="auto"', src, count=1)
if src != orig:
    if "import torch" not in src:
        src = "import torch\n" + src
    p.write_text(src, encoding="utf-8"); print("补丁2 已应用 (generate_vec.py bf16)")
else:
    print("WARN: 补丁2 未命中 from_pretrained device_map 模式——请按 vendor 实文件手工核对", file=sys.stderr)
PYEOF

git diff > /root/vendor_patches_applied.diff
echo "补丁 diff 存 /root/vendor_patches_applied.diff（回传并入 reports/b_vendor_patches.md）"

echo "==== [4] 环境安装（官方 requirements 精确 pin）===="
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # torch==2.6.0 vllm==0.8.5.post1 transformers==4.52.3 ...
python -c "import vllm, torch; print('vllm', vllm.__version__, 'torch', torch.__version__, 'cuda', torch.cuda.is_available())"

echo "==== [5] .env 配置（judge 改道 DeepSeek，零代码）===="
[ -n "${DEEPSEEK_KEY:-}" ] || { echo "缺 DEEPSEEK_KEY 环境变量（export 后重跑；勿写进脚本）" >&2; exit 1; }
cp -n .env.example .env 2>/dev/null || true
{
  echo "OPENAI_API_KEY=${DEEPSEEK_KEY}"
  echo "OPENAI_BASE_URL=https://api.deepseek.com"
  echo "WANDB_PROJECT=persona-vectors"
} > .env
export HF_ENDPOINT="$HF_MIRROR"
export WANDB_MODE=disabled
grep -q "HF_ENDPOINT" ~/.bashrc || echo "export HF_ENDPOINT=$HF_MIRROR" >> ~/.bashrc
echo ".env 写好（HF_TOKEN 行已省；补丁1 已使其可选）"

echo "==== [6] 模型预下载（后台先行）===="
HF_ENDPOINT="$HF_MIRROR" python - <<PYEOF
import os
os.environ.setdefault("HF_ENDPOINT", "$HF_MIRROR")
from huggingface_hub import snapshot_download
p = snapshot_download("$MODEL")
print("SNAPSHOT:", p)   # 路径含 snapshots/<commit> —— 记下 commit 回 Mac 钉 configs/models/qwen25_7b.json
PYEOF

echo "==== bootstrap 完成：可进 §7.1 第 7 步 5% smoke ===="
