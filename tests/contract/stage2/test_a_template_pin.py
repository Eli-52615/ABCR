"""Contract test: template pinning — tokenizer renders match bootstrap samples byte-for-byte."""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from abcr.models import load

SAMPLE_MESSAGES = [
    [{"role": "user", "content": "Hello, what is 2+2?"}],
    [{"role": "system", "content": "You are a careful assistant."}, {"role": "user", "content": "List three fruits."}],
    [{"role": "system", "content": "Respond optimistically."}, {"role": "user", "content": "How is the weather?"}],
]


def _check_templates(model_key: str):
    _, tokenizer, _ = load(model_key)
    tpl_dir = Path(f"configs/templates/{model_key}")

    tpl = tokenizer.chat_template or ""
    actual_hash = hashlib.sha256(tpl.encode()).hexdigest()
    expected_hash = (tpl_dir / "chat_template.hash").read_text().strip()
    assert actual_hash == expected_hash, f"template hash mismatch for {model_key}"

    for i, msgs in enumerate(SAMPLE_MESSAGES):
        rendered = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        expected = (tpl_dir / f"sample_{i}.txt").read_text()
        assert rendered == expected, f"sample_{i} mismatch for {model_key}"


def test_template_pin_05b():
    _check_templates("qwen2.5-0.5b-instruct")


def test_template_pin_3b():
    _check_templates("qwen2.5-3b-instruct")
