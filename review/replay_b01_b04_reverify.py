"""独立复放：簇 B 加固复验（B-01 / B-04）。

不复用 tests/probe/test_ollama_engine.py 的 FakeHTTP/fixture，独立构造：
- B-01: base_url=http://evil:11434（其余字段合法）→ 构造即拒，且全程零网络；
        localhost / 127.0.0.1 正例仍可载入（同样零网络）。
- B-04: mock /api/generate 缺 prompt_eval_count / eval_count → 抛异常而非 0-token 行；
        完整响应正常映射。
仅打印 PASS/FAIL 结论，任何一步失败即非零退出。
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import abcr.probe.ollama_engine as oe  # noqa: E402
from abcr.probe.contracts import EngineOutput  # noqa: E402
from abcr.probe.ollama_engine import (  # noqa: E402
    IncompleteResponseError,
    OllamaEngineError,
    OllamaProbeEngine,
)

PROFILE = REPO / "configs" / "probe" / "profiles" / "qwen25-7b-q4-v1.json"
AUTHORITATIVE = json.loads(PROFILE.read_text(encoding="utf-8"))

failures: list[str] = []
network_calls: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


def write_profile(tmp: Path, **overrides) -> Path:
    profile = json.loads(json.dumps(AUTHORITATIVE))
    profile.update(overrides)
    p = tmp / "profile.json"
    p.write_text(json.dumps(profile), encoding="utf-8")
    return p


def explode(req, timeout=None):
    network_calls.append(req.full_url)
    raise AssertionError(f"NETWORK TOUCHED: {req.full_url}")


with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    orig_urlopen = oe.urlopen
    oe.urlopen = explode  # 整个 B-01 段零网络铁证
    try:
        # ── B-01 反例：http://evil:11434 构造即拒 ─────────────────────────
        p = write_profile(tmp, base_url="http://evil:11434")
        try:
            OllamaProbeEngine(p)
            check("B-01 evil host refused at __init__", False, "no exception raised")
        except OllamaEngineError as exc:
            msg = str(exc)
            check("B-01 evil host refused at __init__", True)
            check("B-01 refusal message names loopback pin",
                  "loopback" in msg and "evil" in msg, msg[:120])
        except Exception as exc:  # AssertionError from explode 也会落到这
            check("B-01 evil host refused at __init__", False,
                  f"wrong exception type: {type(exc).__name__}: {exc}")

        # ── B-01 正例：localhost / 127.0.0.1 载入成功且零网络 ─────────────
        for host_url in ("http://localhost:11434", "http://127.0.0.1:11434"):
            p = write_profile(tmp, base_url=host_url)
            try:
                eng = OllamaProbeEngine(p)
                check(f"B-01 positive load {host_url}",
                      eng.base_url == host_url and not eng._verified)
            except Exception as exc:
                check(f"B-01 positive load {host_url}", False,
                      f"{type(exc).__name__}: {exc}")

        check("B-01 zero network throughout", not network_calls,
              f"calls={network_calls}")
    finally:
        oe.urlopen = orig_urlopen

    # ── B-04：独立 fake daemon（与 tests 的 FakeHTTP 不同实现）────────────
    class Resp:
        def __init__(self, payload: dict):
            self._b = json.dumps(payload).encode()
        def read(self):
            return self._b
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    template = "independent-replay-template {{ .Prompt }}"

    def make_fake(gen_payload: dict):
        prof = AUTHORITATIVE
        def fake(req, timeout=None):
            url = req.full_url
            if url.endswith("/api/version"):
                return Resp({"version": prof["backend"]["version"]})
            if url.endswith("/api/tags"):
                return Resp({"models": [{
                    "name": prof["model_tag"],
                    "digest": prof["artifact"]["manifest_digest"],
                    "details": {"quantization_level": prof["artifact"]["quantization"]},
                }]})
            if url.endswith("/api/show"):
                return Resp({
                    "template": template,
                    "modelfile": "FROM /blobs/sha256-"
                                 + prof["artifact"]["gguf_blob_sha256"] + "\n",
                })
            if url.endswith("/api/generate"):
                return Resp(gen_payload)
            raise AssertionError(f"non-allowlisted endpoint touched: {url}")
        return fake

    p = write_profile(
        tmp, template_sha256=hashlib.sha256(template.encode()).hexdigest())

    cases = [
        ("missing prompt_eval_count",
         {"done": True, "response": "确认", "eval_count": 2}),
        ("missing eval_count",
         {"done": True, "response": "确认", "prompt_eval_count": 37}),
        ("missing both counts",
         {"done": True, "response": "确认"}),
    ]
    for label, payload in cases:
        oe.urlopen = make_fake(payload)
        try:
            engine = OllamaProbeEngine(p)
            try:
                out = engine.generate(prompt="x", seed=1, max_output_tokens=8)
                check(f"B-04 {label} -> exception", False,
                      f"returned row instead: in={out.input_tokens} out={out.output_tokens}")
            except IncompleteResponseError as exc:
                msg = str(exc)
                missing = [k for k in ("prompt_eval_count", "eval_count")
                           if k not in payload]
                check(f"B-04 {label} -> IncompleteResponseError", True)
                check(f"B-04 {label} message names missing field(s)",
                      all(k in msg for k in missing), msg[:140])
        finally:
            oe.urlopen = orig_urlopen

    # B-04 正例：完整响应正常映射
    oe.urlopen = make_fake({"done": True, "response": "确认",
                            "prompt_eval_count": 37, "eval_count": 2})
    try:
        out = OllamaProbeEngine(p).generate(prompt="x", seed=1, max_output_tokens=8)
        check("B-04 complete response maps normally",
              isinstance(out, EngineOutput) and out.input_tokens == 37
              and out.output_tokens == 2 and out.text == "确认")
    finally:
        oe.urlopen = orig_urlopen

print()
if failures:
    print(f"REPLAY RESULT: {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("REPLAY RESULT: ALL CHECKS PASS")
