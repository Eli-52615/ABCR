"""abcr.judge.deepseek_client — LLM judge 客户端（DeepSeek 主 / ollama 兼容端点）。

架构位置：judge(B)。官方打分机制：max_tokens=1, temperature=0, logprobs=True,
top_logprobs=20，取首 token 的 top_logprobs 对 0–100 数字 token 按概率加权平均
（数字总概率 <0.25 记 None）。ollama 不支持 logprobs → 文本解析模式（记偏离）。

judge 调用留痕（硬要求，AMENDMENT-8 冻结契约）：每次请求**发送前**追加一行到
judge_calls.jsonl，字段 = {ts, judge_model, item_id, messages 完整体, params}（**不含密钥**）——
A 防污染检查3（盲评审计）的数据源。

被试是 Qwen，judge 须异构：主 judge DeepSeek，第二家族 ollama gemma3（禁 Qwen/DASHSCOPE）。
"""
from __future__ import annotations

import json
import hashlib
import math
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

SCORER_ID = "judge_deepseek_v1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
OLLAMA_BASE_URL = "http://localhost:11434/v1"
PRODUCTION_EVIDENCE_ROOT = Path(
    "/Users/superagent/Library/Application Support/ABCR-Evidence")


def _safe_run_id(value: str) -> str:
    if (not isinstance(value, str) or not value or len(value) > 160
            or value in {".", ".."} or "/" in value or "\\" in value
            or any(ord(ch) < 0x20 for ch in value)):
        raise ValueError("invalid judge run_id")
    return value


def default_model() -> str:
    """从 reports/b_judge_smoke.json 取 chosen_judge_model，缺省 deepseek-chat。"""
    p = Path("reports/b_judge_smoke.json")
    if p.exists():
        try:
            chosen = json.loads(p.read_text(encoding="utf-8")).get("chosen_judge_model")
            if chosen:
                return chosen
        except (ValueError, OSError):
            pass
    return "deepseek-chat"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_messages(eval_prompt: str, question: str, answer: str) -> list[dict]:
    """把 (question, answer) 填入 trait 工件 eval_prompt——判 judge 输入**不含任何条件字段**
    （A 审计"judge 输入结构检查"硬项：只允许 question/answer 出现）。"""
    content = eval_prompt.replace("{question}", question).replace("{answer}", answer)
    return [{"role": "user", "content": content}]


def weighted_score_from_logprobs(top_logprobs: list, min_numeric_prob: float = 0.25) -> Optional[float]:
    """官方加权：对首 token top_logprobs 中 0–100 数字 token 按概率加权平均。
    top_logprobs: 列表，元素含 .token/.logprob 或 dict {token, logprob}。
    数字总概率 < min_numeric_prob → None（不可信）。"""
    num, denom = 0.0, 0.0
    for t in top_logprobs:
        token = t.token if hasattr(t, "token") else t["token"]
        logprob = t.logprob if hasattr(t, "logprob") else t["logprob"]
        s = token.strip()
        if s.isdigit() and 0 <= int(s) <= 100:
            p = math.exp(logprob)
            num += int(s) * p
            denom += p
    if denom < min_numeric_prob:
        return None
    return num / denom


def parse_score_text(text: str) -> Optional[float]:
    """文本解析模式（ollama 无 logprobs）：把回答折算到 0–100 制。

    根因②/量纲对抗：先识别"分数形式" ``N/10`` 或 ``N/100``——"8/10"是 **80** 分，
    裸取首个整数会误读成 8（0-100 制下低 10 倍，把强表达伪造成弱表达）。分子超过分母
    视为量纲损坏 → None。无分数形式再退回首个 0–100 整数，失败 None。
    """
    frac = re.search(r"\b(\d{1,3})\s*/\s*(10|100)\b", text)
    if frac:
        num, den = int(frac.group(1)), int(frac.group(2))
        if num > den:
            return None  # 分子 > 分母：量纲损坏，不可信
        val = num * (100 // den)  # /10 → ×10；/100 → ×1
        return float(val) if 0 <= val <= 100 else None
    m = re.search(r"\b(100|[0-9]{1,2})\b", text)
    if not m:
        return None
    v = int(m.group(1))
    return float(v) if 0 <= v <= 100 else None


class JudgeClient:
    """可注入 completion_fn 的 judge 客户端（测试用 mock，生产用 OpenAI SDK）。

    mode="logprobs"（DeepSeek 主）或 "text_parse"（ollama gemma3 第二家族）。
    """

    def __init__(self, model: Optional[str] = None, base_url: str = DEEPSEEK_BASE_URL,
                 api_key_env: str = "DEEPSEEK_API_KEY", mode: str = "logprobs",
                 completion_fn: Optional[Callable] = None,
                 log_path: Optional[Path] = None, run_id: Optional[str] = None,
                 arm_id: Optional[str] = None, config_hash: Optional[str] = None,
                 random_seed: Optional[int] = None,
                 condition: Optional[str] = None) -> None:
        self.model = model or default_model()
        self.base_url = base_url
        self.mode = mode
        launched = bool(os.environ.get("ABCR_SERVICE_LABEL"))
        if launched:
            if (log_path is not None or run_id is None or not isinstance(arm_id, str)
                    or not arm_id or not isinstance(config_hash, str)
                    or re.fullmatch(r"[0-9a-f]{64}", config_hash) is None
                    or type(random_seed) is not int or not isinstance(condition, str)
                    or not condition):
                raise ValueError("launched judge requires frozen run/arm/config/seed binding")
            # Production has one compile-time fixed evidence root.  The scored
            # payload selects only an opaque run id; it cannot redirect the
            # judge to a benchmark, split, repo or arbitrary output path.
            root_info = PRODUCTION_EVIDENCE_ROOT.lstat()
            if (PRODUCTION_EVIDENCE_ROOT.is_symlink() or not stat.S_ISDIR(root_info.st_mode)
                    or root_info.st_uid != os.geteuid() or root_info.st_mode & 0o022):
                raise ValueError("unsafe production evidence root")
            run_root = PRODUCTION_EVIDENCE_ROOT / "runs" / _safe_run_id(run_id)
            if run_root.exists() and run_root.is_symlink():
                raise ValueError("unsafe production judge run root")
            self.log_path = run_root / "logs" / "judge_calls.jsonl"
        elif run_id is not None:
            if log_path is None:
                raise ValueError("fixture run_id requires an explicit fixture log_path")
            candidate = Path(log_path)
            expected = candidate.parent.parent.name
            if expected != _safe_run_id(run_id) or candidate.name != "judge_calls.jsonl":
                raise ValueError("fixture judge log_path is not bound to run_id")
            self.log_path = candidate
        else:
            self.log_path = Path(log_path) if log_path else None
        self.run_id = run_id
        self.arm_id = arm_id
        self.config_hash = config_hash
        self.random_seed = random_seed
        self.condition = condition
        self._completion_fn = completion_fn
        self._api_key_env = api_key_env
        self._client = None  # 惰性构造，测试注入 completion_fn 时不触网

    def _openai_completion(self, messages: list[dict], params: dict):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=os.environ[self._api_key_env], base_url=self.base_url)
        return self._client.chat.completions.create(model=self.model, messages=messages, **params)

    def _log_call(self, item_id: str, messages: list[dict], params: dict) -> None:
        """AMENDMENT-8：请求发送前留痕（不含密钥）。"""
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": _now(), "judge_model": self.model, "item_id": item_id,
               "messages": messages, "params": params}
        if self.run_id is not None:
            # Do not place arm/condition labels in the blind judge record: the
            # contamination auditor scans every string field.  This opaque digest
            # is recomputable from the approved RunConfig but reveals no arm label
            # to the judge/log consumer.
            execution_key = "\0".join((self.run_id, str(self.config_hash),
                                        str(self.arm_id), str(self.random_seed)))
            rec.update(run_id=self.run_id, config_hash=self.config_hash,
                       random_seed=self.random_seed,
                       execution_key_hash=hashlib.sha256(execution_key.encode()).hexdigest())
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def score(self, item_id: str, question: str, answer: str, eval_prompt: str) -> Optional[float]:
        """判一维 0–100 分（trait 或 coherence 由 eval_prompt 决定）。返回 float 或 None。"""
        messages = build_messages(eval_prompt, question, answer)
        if self.mode == "logprobs":
            params = {"max_tokens": 1, "temperature": 0, "logprobs": True,
                      "top_logprobs": 20, "seed": 0}
        else:  # text_parse（ollama 无 logprobs）
            params = {"max_tokens": 8, "temperature": 0}
        self._log_call(item_id, messages, params)   # 发送前留痕（硬序）
        fn = self._completion_fn or self._openai_completion
        resp = fn(messages, params)
        if self.mode == "logprobs":
            ch = resp.choices[0]
            lp = ch.logprobs.content[0] if (ch.logprobs and ch.logprobs.content) else None
            if lp is None:
                return None
            return weighted_score_from_logprobs(lp.top_logprobs)
        text = resp.choices[0].message.content or ""
        return parse_score_text(text)
