"""abcr.probe.ollama_engine — OllamaProbeEngine：冻结 profile 驱动的真实本地快道引擎。

方案 §6.3（L780-810）：V1 实现 OllamaEngine；engine profile 固定 backend 绝对路径/
version、model tag、artifact digest、quant、template hash、decoding、最大并发。
**不得在运行时自动拉取模型、自动换 tag 或自动升级 backend** —— 本模块不存在任何
模型下载代码路径；可触达端点是硬编码白名单（tests 另有源码级断言兜底）。

指纹漂移 → FingerprintDriftError，拒绝运行（fail-closed）：generate() 首次调用前
若尚未通过 verify_fingerprint()，会自动先验一次；漂移即抛异常，绝不静默降级。

残留纪律（对抗审查确认，规格允许 + 结构性遏制，显式记录、不改行为）：
- B-02：backend_version 来自 daemon /api/version 自报，探针不独立测量该值；其已被
  三层 non-citable 机制锁死，不可作为可引用证据，故接受自报。
- B-03：指纹校验为 per-run（每次运行首个 generate() 前强制一次），与方案 §6.3 一致；
  不做逐请求重验，run 内漂移由 fail-closed 异常路径兜底。

仅 stdlib（urllib/json/hashlib/time）；不引第三方 ollama 包。
"""
from __future__ import annotations

import hashlib
import json
import re
import stat
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from abcr.probe.contracts import EngineOutput

_BLOB_RE = re.compile(r"sha256-([0-9a-f]{64})")

#: 本引擎唯一允许触达的 API 端点（结构性排除 pull/push/create/delete）。
_ALLOWED_ENDPOINTS = ("/api/version", "/api/tags", "/api/show", "/api/generate")

#: base_url 唯一允许的主机（B-01：冻结的 backend 同时钉死网络位置=本机回环）。
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class OllamaEngineError(RuntimeError):
    """OllamaProbeEngine 的基异常。"""


class FingerprintDriftError(OllamaEngineError):
    """实时指纹与冻结 profile 不一致 —— 拒绝运行，不自动修复。"""


class ModelMissingError(OllamaEngineError):
    """冻结的 model tag 不在本机库中 —— 明确报错，绝不自动 pull。"""


class BackendUnreachableError(OllamaEngineError):
    """ollama daemon 不可达（连接失败/超时）。"""


class IncompleteResponseError(OllamaEngineError):
    """/api/generate 响应缺 token 计数字段 —— 后端异常，拒绝产出 0-token 行。"""


def _required(profile: dict, dotted: str):
    node = profile
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            raise OllamaEngineError(f"frozen profile missing required field: {dotted}")
        node = node[key]
    return node


class OllamaProbeEngine:
    """实现 abcr.probe.engine.ProbeEngine 协议（generate 关键字签名）。

    构造零网络：仅载入并校验冻结 profile 的形状。verify_fingerprint() 才触网。
    """

    def __init__(self, profile_path: str | Path) -> None:
        self.profile_path = Path(profile_path)
        profile = json.loads(self.profile_path.read_text(encoding="utf-8"))
        self.profile = profile
        self.profile_id: str = _required(profile, "profile_id")
        self.base_url: str = _required(profile, "base_url").rstrip("/")
        parsed_url = urlsplit(self.base_url)
        host = parsed_url.hostname
        if (parsed_url.scheme != "http" or host not in _LOOPBACK_HOSTS
                or parsed_url.username is not None or parsed_url.password is not None
                or parsed_url.path not in {"", "/"} or parsed_url.query
                or parsed_url.fragment):
            raise OllamaEngineError(
                f"frozen profile base_url must be a plain loopback HTTP origin "
                f"({', '.join(sorted(_LOOPBACK_HOSTS))}); got hostname {host!r} in "
                f"{self.base_url!r} — probe engine is pinned to the local daemon, "
                "refusing to load a remote-backend profile")
        self.model_tag: str = _required(profile, "model_tag")
        self.manifest_digest: str = _required(profile, "artifact.manifest_digest")
        self.blob_sha256: str = _required(profile, "artifact.gguf_blob_sha256")
        self.quantization: str = _required(profile, "artifact.quantization")
        self.template_sha256: str = _required(profile, "template_sha256")
        self.backend_version: str = _required(profile, "backend.version")
        self.backend_binary: str = _required(profile, "backend.binary")
        self.backend_binary_sha256: str = _required(profile, "backend.binary_sha256")
        self.max_concurrency: int = _required(profile, "max_concurrency")
        decoding = dict(_required(profile, "decoding"))
        decoding.pop("_note", None)
        if "seed" in decoding:
            raise OllamaEngineError(
                "frozen profile must not pin a seed; seed is passed per generate() call")
        if decoding.get("temperature") != 0.0:
            raise OllamaEngineError("frozen decoding must be deterministic (temperature=0)")
        self.decoding: dict = decoding
        if self.max_concurrency != 1:
            raise OllamaEngineError("probe fast lane is frozen at max_concurrency=1")
        for name, value in (("artifact.manifest_digest", self.manifest_digest),
                            ("artifact.gguf_blob_sha256", self.blob_sha256),
                            ("template_sha256", self.template_sha256),
                            ("backend.binary_sha256", self.backend_binary_sha256)):
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise OllamaEngineError(f"{name} must be a full 64-hex sha256, got: {value!r}")
        self._verified = False
        self._generate_lock = threading.Lock()

    def _verify_backend_binary(self) -> str:
        """验证冻结的绝对 backend 二进制字节；不执行、不升级该二进制。"""
        binary = Path(self.backend_binary)
        if not binary.is_absolute():
            raise FingerprintDriftError("backend.binary must be an absolute path")
        try:
            resolved = binary.resolve(strict=True)
            info = resolved.stat()
        except OSError as exc:
            raise FingerprintDriftError(
                f"frozen backend binary unavailable: {self.backend_binary}") from exc
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise FingerprintDriftError(
                f"frozen backend binary is not a single-link regular file: {resolved}")
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if digest != self.backend_binary_sha256:
            raise FingerprintDriftError(
                "backend binary digest drift: "
                f"frozen={self.backend_binary_sha256} live={digest}")
        return digest

    # ── HTTP（stdlib urllib 全部经此；端点白名单结构性排除 pull）─────────────
    def _call(self, endpoint: str, payload: dict | None = None, *, timeout: float) -> dict:
        if endpoint not in _ALLOWED_ENDPOINTS:  # pragma: no cover - 防御线
            raise OllamaEngineError(f"endpoint not allowed for probe engine: {endpoint}")
        url = self.base_url + endpoint
        if payload is None:
            req = Request(url, method="GET")
        else:
            req = Request(url, data=json.dumps(payload).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")[:400]
            except Exception:
                pass
            if exc.code == 404 and endpoint in ("/api/show", "/api/generate"):
                raise ModelMissingError(
                    f"model {self.model_tag!r} not found in local library "
                    f"(HTTP 404 on {endpoint}: {body}). Frozen profile "
                    f"{self.profile_id} forbids automatic download / tag switch / "
                    f"backend upgrade — restore the exact frozen artifact manually.") from exc
            raise OllamaEngineError(f"ollama HTTP {exc.code} on {endpoint}: {body}") from exc
        except URLError as exc:
            raise BackendUnreachableError(
                f"ollama daemon unreachable at {self.base_url} ({exc.reason}); "
                "refusing to run probe") from exc

    # ── 指纹 ────────────────────────────────────────────────────────────────
    def verify_fingerprint(self, *, timeout: float = 10.0) -> dict:
        """实时取 /api/version + /api/tags + /api/show，逐项对冻结 profile。

        任一项漂移 → FingerprintDriftError（列出全部漂移项），拒绝运行。
        通过后返回实测指纹 dict（供资格化记录）。
        """
        drift: list[str] = []
        live_binary_sha = self._verify_backend_binary()

        version = str(self._call("/api/version", timeout=timeout).get("version", ""))
        if version != self.backend_version:
            drift.append(f"backend_version: frozen={self.backend_version} live={version}")

        tags = self._call("/api/tags", timeout=timeout).get("models", [])
        entry = next((m for m in tags if m.get("name") == self.model_tag), None)
        if entry is None:
            raise ModelMissingError(
                f"model {self.model_tag!r} absent from /api/tags. Frozen profile "
                f"{self.profile_id} forbids automatic download / tag switch — "
                "restore the exact frozen artifact manually.")
        live_manifest = str(entry.get("digest", ""))
        if live_manifest != self.manifest_digest:
            drift.append(f"artifact.manifest_digest: frozen={self.manifest_digest} live={live_manifest}")
        live_quant = str(entry.get("details", {}).get("quantization_level", ""))
        if live_quant != self.quantization:
            drift.append(f"artifact.quantization: frozen={self.quantization} live={live_quant}")

        show = self._call("/api/show", {"model": self.model_tag}, timeout=timeout)
        live_template_sha = hashlib.sha256(
            str(show.get("template", "")).encode("utf-8")).hexdigest()
        if live_template_sha != self.template_sha256:
            drift.append(f"template_sha256: frozen={self.template_sha256} live={live_template_sha}")
        blob_match = _BLOB_RE.search(str(show.get("modelfile", "")))
        live_blob = blob_match.group(1) if blob_match else ""
        if live_blob != self.blob_sha256:
            drift.append(f"artifact.gguf_blob_sha256: frozen={self.blob_sha256} live={live_blob}")

        if drift:
            self._verified = False
            raise FingerprintDriftError(
                f"engine fingerprint drift vs frozen profile {self.profile_id}; "
                f"refusing to run. Drift: " + "; ".join(drift))
        self._verified = True
        # Deliberately do not claim ``exact_tokenizer_qualified`` or expose
        # tokenizer/chat-renderer digests here.  /api/show's template hash alone
        # cannot prove tokenizer bytes or /api/generate raw/template semantics;
        # ③L therefore remains fail-closed until a separately reviewed exact
        # tokenizer + renderer adapter exists.
        return {
            "profile_id": self.profile_id,
            "model_tag": self.model_tag,
            "backend_version": version,
            "manifest_digest": live_manifest,
            "gguf_blob_sha256": live_blob,
            "template_sha256": live_template_sha,
            "quantization": live_quant,
            "backend_binary": self.backend_binary,
            "backend_binary_sha256": live_binary_sha,
            "decoding": self.decoding,
        }

    def fingerprint(self) -> dict:
        """ProbeEngine 协议：每个 run 显式调用并重新核验实时指纹。"""
        return self.verify_fingerprint()

    @property
    def engine_version(self) -> str:
        return (f"ollama/{self.backend_version} {self.model_tag}"
                f"@{self.manifest_digest[:12]}")

    # ── ProbeEngine 协议 ────────────────────────────────────────────────────
    def generate(self, *, prompt: str, seed: int, max_output_tokens: int) -> EngineOutput:
        if not isinstance(prompt, str) or not prompt:
            raise OllamaEngineError("prompt must be a non-empty string")
        if isinstance(max_output_tokens, bool) or not isinstance(max_output_tokens, int) \
                or not 1 <= max_output_tokens <= 4096:
            raise OllamaEngineError("max_output_tokens must be an integer in [1, 4096]")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise OllamaEngineError("seed must be an integer")
        # profile 的 max_concurrency=1 不是注释：同一 engine 上的真实 generate
        # 由锁串行化，避免内存争用和两条快道并发造成不可解释的 SLO 漂移。
        with self._generate_lock:
            if not self._verified:
                self.verify_fingerprint()  # fail-closed：漂移则抛，绝不带病运行
            options = dict(self.decoding)
            options["seed"] = seed
            options["num_predict"] = max_output_tokens
            payload = {"model": self.model_tag, "prompt": prompt,
                       "stream": False, "options": options}
            t0 = time.monotonic()
            resp = self._call("/api/generate", payload, timeout=600.0)
            latency_ms = int((time.monotonic() - t0) * 1000)
            if not isinstance(resp, dict):
                raise IncompleteResponseError("/api/generate response must be a JSON object")
            if resp.get("done") is not True:
                raise OllamaEngineError(f"/api/generate returned done={resp.get('done')!r}")
            missing = [k for k in ("prompt_eval_count", "eval_count") if k not in resp]
            if missing:  # fail-closed：响应不完整=后端异常，绝不静默产出 0-token 行
                raise IncompleteResponseError(
                    "/api/generate response missing token count field(s): "
                    f"{', '.join(missing)} — incomplete backend response, refusing to "
                    "emit a zero-token row")
            text = resp.get("response")
            counts = (resp["prompt_eval_count"], resp["eval_count"])
            if not isinstance(text, str):
                raise IncompleteResponseError("/api/generate response text is not a string")
            if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in counts):
                raise IncompleteResponseError(
                    "/api/generate token counts must be non-negative integers")
            return EngineOutput(
                text=text,
                input_tokens=counts[0],
                output_tokens=counts[1],
                latency_ms=latency_ms,
                engine_version=self.engine_version,
            )
