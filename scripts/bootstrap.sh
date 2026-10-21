#!/bin/bash
# ⚠️ 已归档(2026-07-16 迁移时注记):一次性历史引导脚本,禁止重跑——会重建仓库骨架造成双仓分裂。
set -euo pipefail
ROOT=/Users/superagent/shared-brain/ABCR/abcr
mkdir -p "$ROOT"; cd "$ROOT"
[ -f .bootstrap.done ] && { echo "bootstrap done"; exit 0; }
if ! mkdir .bootstrap.lock 2>/dev/null; then
  echo "另一窗口正在 bootstrap，等待（上限30分钟）..."
  for i in $(seq 1 360); do [ -f .bootstrap.done ] && exit 0; sleep 5; done
  echo "E: bootstrap 等待超时"; exit 1
fi
trap 'rmdir "$ROOT/.bootstrap.lock" 2>/dev/null || true' EXIT
[ -d .git ] || git init -b main
git config user.name "Yinan Wang"; git config user.email worldofnan130@gmail.com
mkdir -p configs/templates configs/runs data/items/ifeval_style data/splits artifacts/traits \
  vectors runs scores review repro_packs third_party patches pv_bridge/out scripts/cloud costs figures \
  src/abcr/interventions src/abcr/eval/deterministic src/abcr/eval/judge src/abcr/logging \
  tests/fixtures/golden_answers tests/unit tests/contract/stage1 tests/contract/stage2 tests/contract/stage3 tests/contract/stage4
for f in src/abcr/__init__.py src/abcr/interventions/__init__.py src/abcr/eval/__init__.py \
  src/abcr/eval/deterministic/__init__.py src/abcr/eval/judge/__init__.py src/abcr/logging/__init__.py; do
  [ -f "$f" ] || touch "$f"; done
for f in DEVIATIONS.md STATUS-A.md STATUS-B.md STATUS-C.md costs/ledger.jsonl; do [ -f "$f" ] || touch "$f"; done
[ -f .gitignore ] || cat > .gitignore <<'EOF'
.venv*/
third_party/
__pycache__/
.bootstrap.lock
.pytest_cache/
*.pyc
tests/fixtures/tinyqwen/
pv_bridge/out/
EOF
[ -d .venv ] || uv venv --python /opt/homebrew/bin/python3.11 .venv
uv pip install -p .venv/bin/python torch==2.6.0 transformers==4.52.3 accelerate==1.7.0 datasets==3.6.0 \
  pandas==2.3.1 pyarrow duckdb scipy statsmodels matplotlib typer pydantic==2.11.7 pyyaml==6.0.2 \
  pytest openai==1.70.0 backoff==2.2.1 tqdm huggingface_hub \
  || { echo "torch==2.6.0 失败则手动放宽 torch>=2.6,<2.8 重装并记 DEVIATIONS.md"; exit 1; }
.venv/bin/python - <<'PY'
import pathlib, hashlib, shutil, yaml, torch
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer, Qwen2Config, Qwen2ForCausalLM
pins = {}
for mid in ["Qwen/Qwen2.5-0.5B-Instruct", "Qwen/Qwen2.5-3B-Instruct"]:
    p = snapshot_download(mid); pins[mid] = pathlib.Path(p).name; print(mid, "->", pins[mid])
my = pathlib.Path("configs/models.yaml")
if not my.exists():
    my.write_text(yaml.safe_dump({"models": {
        "tinyqwen":              {"model_id": "tests/fixtures/tinyqwen",      "revision": "local-fixture-seed0"},
        "qwen2.5-0.5b-instruct": {"model_id": "Qwen/Qwen2.5-0.5B-Instruct", "revision": pins["Qwen/Qwen2.5-0.5B-Instruct"]},
        "qwen2.5-3b-instruct":   {"model_id": "Qwen/Qwen2.5-3B-Instruct",   "revision": pins["Qwen/Qwen2.5-3B-Instruct"]},
        "qwen2.5-7b-instruct":   {"model_id": "Qwen/Qwen2.5-7B-Instruct",   "revision": "PIN-AT-CLOUD-PROVISION"},
    }}, allow_unicode=True, sort_keys=False))
for key, mid in [("qwen2.5-0.5b-instruct","Qwen/Qwen2.5-0.5B-Instruct"),("qwen2.5-3b-instruct","Qwen/Qwen2.5-3B-Instruct")]:
    tok = AutoTokenizer.from_pretrained(mid, revision=pins[mid])
    tpl = tok.chat_template or ""
    h = hashlib.sha256(tpl.encode()).hexdigest()
    d = pathlib.Path(f"configs/templates/{key}"); d.mkdir(parents=True, exist_ok=True)
    (d/"chat_template.hash").exists() or (d/"chat_template.hash").write_text(h)
    samples = [
        [{"role":"user","content":"Hello, what is 2+2?"}],
        [{"role":"system","content":"You are a careful assistant."},{"role":"user","content":"List three fruits."}],
        [{"role":"system","content":"Respond optimistically."},{"role":"user","content":"How is the weather?"}],
    ]
    for i, msgs in enumerate(samples):
        f = d/f"sample_{i}.txt"
        f.exists() or f.write_text(tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True))
dst_t = pathlib.Path("configs/templates/tinyqwen")
if not dst_t.exists(): shutil.copytree("configs/templates/qwen2.5-0.5b-instruct", dst_t)
tq = pathlib.Path("tests/fixtures/tinyqwen")
if not (tq/"config.json").exists():
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-0.5B-Instruct", revision=pins["Qwen/Qwen2.5-0.5B-Instruct"])
    torch.manual_seed(0)
    cfg = Qwen2Config(hidden_size=64, num_hidden_layers=4, num_attention_heads=4, num_key_value_heads=2,
                      intermediate_size=128, vocab_size=len(tok), max_position_embeddings=512)
    m = Qwen2ForCausalLM(cfg); m = m.to(torch.float32)
    m.save_pretrained(tq); tok.save_pretrained(tq)
print("bootstrap python 段完成")
PY
touch .bootstrap.done
git add -A && git commit -m "[bootstrap] repo skeleton + env + model pins + template pins + tinyqwen" || true
echo "bootstrap 完成"
