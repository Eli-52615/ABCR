"""tests/probe/test_ollama_engine — OllamaProbeEngine 零网络全覆盖 + 1 条 golden 真跑。

零网络部分 mock 掉 abcr.probe.ollama_engine.urlopen（模块内 from-import 的名字），
并用端点白名单式 FakeHTTP 结构性证明：整个引擎生命周期只触达
/api/version /api/tags /api/show /api/generate —— 不存在 pull/create/delete。

golden 部分（local_7b 门 "one-item load pass"）：默认回归跳过（需显式
ABCR_RUN_GOLDEN=1 且带 -m golden 习惯跑法），开启时对本机 daemon 真跑 1 题。
"""
from __future__ import annotations

import io
import json
import os
import urllib.error
from pathlib import Path

import pytest

import abcr.probe.ollama_engine as oe
from abcr.probe.contracts import EngineOutput
from abcr.probe.ollama_engine import (
    BackendUnreachableError,
    FingerprintDriftError,
    IncompleteResponseError,
    ModelMissingError,
    OllamaEngineError,
    OllamaProbeEngine,
)

REPO = Path(__file__).resolve().parents[2]
PROFILE = REPO / "configs" / "probe" / "profiles" / "qwen25-7b-q4-v1.json"

# ── 与冻结 profile 一致的 fake 现场 ─────────────────────────────────────────


def _profile() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8"))


def _live_state(profile: dict) -> dict:
    """按 profile 构造与之完全一致的『实时』daemon 状态（可被单项篡改制造漂移）。"""
    template = "{{ .System }}{{ .Prompt }}"  # 内容任意；hash 由它现算
    return {
        "version": profile["backend"]["version"],
        "model_tag": profile["model_tag"],
        "manifest_digest": profile["artifact"]["manifest_digest"],
        "blob_sha256": profile["artifact"]["gguf_blob_sha256"],
        "quantization": profile["artifact"]["quantization"],
        "template": template,
    }


class FakeHTTP:
    """替身 urlopen：端点白名单 + 请求全记录。未知端点直接 AssertionError ——
    这就是『无 pull 行为』的结构性证明（任何测试路径打到别的端点都会炸）。"""

    def __init__(self, state: dict, *, generate_response: dict | None = None,
                 model_absent: bool = False, show_404: bool = False):
        self.state = state
        self.model_absent = model_absent
        self.show_404 = show_404
        self.generate_response = generate_response or {
            "done": True, "response": "确认",
            "prompt_eval_count": 37, "eval_count": 2,
        }
        self.requests: list[dict] = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        body = json.loads(req.data.decode()) if req.data else None
        self.requests.append({"url": url, "method": req.get_method(),
                              "body": body, "timeout": timeout})
        s = self.state
        if url.endswith("/api/version"):
            return _resp({"version": s["version"]})
        if url.endswith("/api/tags"):
            models = [] if self.model_absent else [{
                "name": s["model_tag"], "digest": s["manifest_digest"],
                "details": {"quantization_level": s["quantization"]},
            }]
            return _resp({"models": models})
        if url.endswith("/api/show"):
            if self.model_absent or self.show_404:
                raise urllib.error.HTTPError(url, 404, "Not Found", None,
                                             io.BytesIO(b'{"error":"model not found"}'))
            return _resp({
                "template": s["template"],
                "modelfile": f"FROM /blobs/sha256-{s['blob_sha256']}\n",
            })
        if url.endswith("/api/generate"):
            return _resp(self.generate_response)
        raise AssertionError(f"engine touched a non-allowlisted endpoint: {url}")


class _resp:
    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def frozen(monkeypatch, tmp_path):
    """profile 的 template_sha256 改成 fake template 的真 hash 后落盘，
    返回 (engine, fake)。其余指纹字段与权威 profile 完全一致。"""
    import hashlib
    profile = _profile()
    state = _live_state(profile)
    profile["template_sha256"] = hashlib.sha256(state["template"].encode()).hexdigest()
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    fake = FakeHTTP(state)
    monkeypatch.setattr(oe, "urlopen", fake)
    return OllamaProbeEngine(path), fake


# ── 指纹：一致放行 ──────────────────────────────────────────────────────────


def test_fingerprint_match_passes(frozen):
    engine, fake = frozen
    fp = engine.verify_fingerprint()
    assert fp["model_tag"] == engine.model_tag
    assert fp["manifest_digest"] == engine.manifest_digest
    assert fp["backend_version"] == engine.backend_version
    assert fp["gguf_blob_sha256"] == engine.blob_sha256
    urls = [r["url"] for r in fake.requests]
    assert [u.rsplit("/", 2)[-2] + "/" + u.rsplit("/", 1)[-1] for u in urls] == [
        "api/version", "api/tags", "api/show"]


def test_ollama_fingerprint_does_not_claim_exact_3l_tokenizer_or_renderer(
        frozen, monkeypatch):
    engine, _ = frozen
    # This contract test freezes the returned capability surface, not the host's
    # Ollama installation path (binary-byte verification has its own tests).
    monkeypatch.setattr(engine, "_verify_backend_binary",
                        lambda: engine.backend_binary_sha256)
    fingerprint = engine.verify_fingerprint()
    assert "exact_tokenizer_qualified" not in fingerprint
    assert "tokenizer_sha256" not in fingerprint
    assert "chat_template_sha256" not in fingerprint


# ── 指纹：任一项漂移拒绝 ────────────────────────────────────────────────────


@pytest.mark.parametrize("field,mutate", [
    ("backend_version", lambda s: s.update(version="0.99.0")),
    ("artifact.manifest_digest", lambda s: s.update(manifest_digest="f" * 64)),
    ("artifact.quantization", lambda s: s.update(quantization="Q8_0")),
    ("template_sha256", lambda s: s.update(template="{{ tampered }}")),
    ("artifact.gguf_blob_sha256", lambda s: s.update(blob_sha256="e" * 64)),
])
def test_fingerprint_any_drift_refuses(frozen, field, mutate):
    engine, fake = frozen
    mutate(fake.state)
    with pytest.raises(FingerprintDriftError) as exc:
        engine.verify_fingerprint()
    assert field in str(exc.value)
    # 漂移后 generate 同样拒绝运行（fail-closed，先验指纹再生成）
    with pytest.raises(FingerprintDriftError):
        engine.generate(prompt="x", seed=1, max_output_tokens=8)
    assert not any(r["url"].endswith("/api/generate") for r in fake.requests)


def test_drift_after_pass_is_recaught_on_reverify(frozen):
    engine, fake = frozen
    engine.verify_fingerprint()
    fake.state.update(version="0.99.0")
    with pytest.raises(FingerprintDriftError):
        engine.verify_fingerprint()


# ── generate：组包与映射 ────────────────────────────────────────────────────


def test_generate_request_shape_and_mapping(frozen):
    engine, fake = frozen
    out = engine.generate(prompt="你好，只回答两个字", seed=42, max_output_tokens=16)
    assert isinstance(out, EngineOutput)
    assert out.text == "确认"
    assert out.input_tokens == 37 and out.output_tokens == 2
    assert out.latency_ms >= 0
    # engine_version 含 backend 版本 + model_tag + digest 短前缀
    assert engine.backend_version in out.engine_version
    assert engine.model_tag in out.engine_version
    assert engine.manifest_digest[:12] in out.engine_version

    gen = [r for r in fake.requests if r["url"].endswith("/api/generate")]
    assert len(gen) == 1 and gen[0]["method"] == "POST"
    body = gen[0]["body"]
    assert body["model"] == engine.model_tag
    assert body["prompt"] == "你好，只回答两个字"
    assert body["stream"] is False
    assert body["options"]["seed"] == 42
    assert body["options"]["temperature"] == 0.0
    assert body["options"]["num_predict"] == 16
    # 首次 generate 自动先验指纹（version/tags/show 在 generate 之前）
    order = [r["url"].rsplit("/", 1)[-1] for r in fake.requests]
    assert order == ["version", "tags", "show", "generate"]


def test_generate_incomplete_response_rejected(frozen):
    engine, fake = frozen
    fake.generate_response = {"done": False, "response": "截断"}
    with pytest.raises(OllamaEngineError, match="done"):
        engine.generate(prompt="x", seed=1, max_output_tokens=8)


# ── B-04：token 计数字段缺失 → fail-closed，绝不产出 0-token 行 ─────────────


@pytest.mark.parametrize("drop", [
    ("prompt_eval_count",),
    ("eval_count",),
    ("prompt_eval_count", "eval_count"),
])
def test_generate_missing_token_counts_fail_closed(frozen, drop):
    engine, fake = frozen
    resp = {"done": True, "response": "确认",
            "prompt_eval_count": 37, "eval_count": 2}
    for key in drop:
        del resp[key]
    fake.generate_response = resp
    with pytest.raises(IncompleteResponseError) as exc:
        engine.generate(prompt="x", seed=1, max_output_tokens=8)
    msg = str(exc.value)
    for key in drop:
        assert key in msg
    assert "zero-token" in msg
    # 专用异常隶属引擎基异常，且不是「done 缺失」那类泛化错误
    assert isinstance(exc.value, OllamaEngineError)


# ── 模型缺失：明确报错，绝不 pull ───────────────────────────────────────────


def test_model_missing_errors_and_never_pulls(monkeypatch, tmp_path):
    import hashlib
    profile = _profile()
    state = _live_state(profile)
    profile["template_sha256"] = hashlib.sha256(state["template"].encode()).hexdigest()
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    fake = FakeHTTP(state, model_absent=True)
    monkeypatch.setattr(oe, "urlopen", fake)
    engine = OllamaProbeEngine(path)
    with pytest.raises(ModelMissingError) as exc:
        engine.verify_fingerprint()
    msg = str(exc.value)
    assert engine.model_tag in msg and "forbids automatic download" in msg
    # 缺模型后引擎发出的每个请求仍只在白名单端点（FakeHTTP 未知端点会炸），
    # 且没有任何后续『补救』请求
    assert [r["url"].rsplit("/", 1)[-1] for r in fake.requests] == ["version", "tags"]


def test_show_404_maps_to_model_missing(monkeypatch, tmp_path):
    """tags 有条目但 /api/show 404（工件被删）→ 同样 ModelMissingError，不补救。"""
    import hashlib
    profile = _profile()
    state = _live_state(profile)
    profile["template_sha256"] = hashlib.sha256(state["template"].encode()).hexdigest()
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    fake = FakeHTTP(state, show_404=True)
    monkeypatch.setattr(oe, "urlopen", fake)
    with pytest.raises(ModelMissingError, match="forbids automatic download"):
        OllamaProbeEngine(path).verify_fingerprint()
    assert [r["url"].rsplit("/", 1)[-1] for r in fake.requests] == ["version", "tags", "show"]


def test_backend_unreachable(monkeypatch, tmp_path):
    profile = _profile()
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")

    def dead(req, timeout=None):
        raise urllib.error.URLError(ConnectionRefusedError(61, "refused"))

    monkeypatch.setattr(oe, "urlopen", dead)
    with pytest.raises(BackendUnreachableError):
        OllamaProbeEngine(path).verify_fingerprint()


def test_backend_binary_digest_drift_refuses_before_http(monkeypatch, tmp_path):
    """Profile 里的 binary 不能只是装饰字段；字节漂移必须先于 API 触网拒绝。"""
    import hashlib
    binary = tmp_path / "ollama"
    binary.write_bytes(b"frozen-ollama-binary")
    binary.chmod(0o755)
    profile = _profile()
    profile["backend"]["binary"] = str(binary)
    profile["backend"]["binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
    state = _live_state(profile)
    profile["template_sha256"] = hashlib.sha256(state["template"].encode()).hexdigest()
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    fake = FakeHTTP(state)
    monkeypatch.setattr(oe, "urlopen", fake)
    engine = OllamaProbeEngine(path)
    assert engine.verify_fingerprint()["backend_binary_sha256"] == \
        profile["backend"]["binary_sha256"]
    fake.requests.clear()
    binary.write_bytes(b"tampered")
    with pytest.raises(FingerprintDriftError, match="binary digest drift"):
        engine.verify_fingerprint()
    assert fake.requests == []


# ── 无 pull 行为：源码级断言 ────────────────────────────────────────────────


def test_no_pull_path_in_source():
    src = Path(oe.__file__).read_text(encoding="utf-8")
    assert "api/pull" not in src and "/pull" not in src
    assert "api/create" not in src and "api/delete" not in src and "api/push" not in src
    # 端点白名单本身就是结构性排除
    assert set(oe._ALLOWED_ENDPOINTS) == {
        "/api/version", "/api/tags", "/api/show", "/api/generate"}


# ── profile 形状硬校验 ──────────────────────────────────────────────────────


def test_frozen_profile_shape_is_enforced(tmp_path):
    profile = _profile()
    profile["decoding"]["temperature"] = 0.7
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(OllamaEngineError, match="deterministic"):
        OllamaProbeEngine(p)

    profile = _profile()
    profile["decoding"]["seed"] = 1
    p.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(OllamaEngineError, match="seed"):
        OllamaProbeEngine(p)

    profile = _profile()
    profile["artifact"]["manifest_digest"] = "845dbda0ea48"  # 只给前缀不行
    p.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(OllamaEngineError, match="64-hex"):
        OllamaProbeEngine(p)

    profile = _profile()
    profile["max_concurrency"] = 4
    p.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(OllamaEngineError, match="max_concurrency"):
        OllamaProbeEngine(p)


# ── B-01：base_url 钉死回环 —— 远端 profile 载入即拒（零网络）─────────────


@pytest.mark.parametrize("remote_url", [
    "http://10.0.0.5:11434",
    "http://192.168.1.20:11434",
    "http://ollama.internal:11434",
    "https://example.com:11434",
    "http://0.0.0.0:11434",
    "http://localhost.evil.example:11434",
    "http://[fe80::1]:11434",
    "https://localhost:11434",
    "http://localhost:11434/api",
    "http://user@localhost:11434",
    "http://localhost:11434?model=other",
])
def test_remote_base_url_profile_refused_at_load(monkeypatch, tmp_path, remote_url):
    """非回环 base_url 的 profile 必须在构造期抛异常，且全程零网络。"""
    def explode(req, timeout=None):  # pragma: no cover - 触网即失败
        raise AssertionError(f"network touched during profile load: {req.full_url}")

    monkeypatch.setattr(oe, "urlopen", explode)
    profile = _profile()
    profile["base_url"] = remote_url
    p = tmp_path / "remote.json"
    p.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(OllamaEngineError, match="loopback"):
        OllamaProbeEngine(p)


@pytest.mark.parametrize("loop_url", [
    "http://127.0.0.1:11434",
    "http://localhost:11434",
    "http://[::1]:11434",
])
def test_loopback_base_url_profile_loads(monkeypatch, tmp_path, loop_url):
    """回环三主机（127.0.0.1 / localhost / ::1）均可载入，构造仍零网络。"""
    def explode(req, timeout=None):  # pragma: no cover - 触网即失败
        raise AssertionError(f"network touched during profile load: {req.full_url}")

    monkeypatch.setattr(oe, "urlopen", explode)
    profile = _profile()
    profile["base_url"] = loop_url
    p = tmp_path / "loop.json"
    p.write_text(json.dumps(profile), encoding="utf-8")
    engine = OllamaProbeEngine(p)
    assert engine.base_url == loop_url
    assert not engine._verified


def test_authoritative_profile_loads_clean():
    """权威冻结 profile 必须直接可载入（字段全、形状合法）。零网络。"""
    engine = OllamaProbeEngine(PROFILE)
    assert engine.profile_id == "qwen25-7b-q4-v1"
    assert engine.model_tag == "qwen2.5:7b"
    assert engine.manifest_digest.startswith("845dbda0ea48")
    assert engine.blob_sha256.startswith("2bada8a74506")
    assert engine.quantization == "Q4_K_M"
    assert engine.backend_version == "0.32.1"
    assert engine.base_url == "http://127.0.0.1:11434"
    assert not engine._verified  # 构造零网络，未验先不算通过


# ── golden：真实 1 题加载（local_7b 门 one-item load pass）──────────────────


@pytest.mark.golden
@pytest.mark.skipif(
    os.environ.get("ABCR_RUN_GOLDEN", "").strip().lower() not in {"1", "true", "yes", "on"},
    reason="真实 ollama 1 题加载：默认回归零网络跳过；ABCR_RUN_GOLDEN=1 时真跑")
def test_golden_one_item_load_pass_real_ollama():
    engine = OllamaProbeEngine(PROFILE)
    fp = engine.verify_fingerprint()
    assert fp["manifest_digest"] == engine.manifest_digest
    out = engine.generate(prompt="只回答两个字：确认。不要输出任何其他内容。",
                          seed=7, max_output_tokens=8)
    assert isinstance(out, EngineOutput)
    assert out.text.strip()
    assert out.output_tokens >= 1 and out.input_tokens >= 1
    assert out.latency_ms > 0
    assert engine.model_tag in out.engine_version
