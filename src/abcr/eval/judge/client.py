import json
import math
import os
import pathlib
import sys
import time
from typing import Optional
import backoff


class TraitJudge:
    def __init__(self, model: str = "deepseek-chat", mode: str = "text_parse",
                 base_url: Optional[str] = None):
        from openai import OpenAI

        self.model = model
        self.mode = mode
        api_key = os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com")

        if not api_key:
            print("E13: OPENAI_API_KEY not set", file=sys.stderr)
            sys.exit(1)

        self.client = OpenAI(api_key=api_key, base_url=self.base_url)
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_calls = 0

    @backoff.on_exception(backoff.expo, Exception, max_tries=5, max_time=120)
    def score(self, eval_prompt: str) -> dict:
        if self.mode == "logprob_weighted":
            return self._score_logprob(eval_prompt)
        else:
            return self._score_text(eval_prompt)

    def _score_logprob(self, eval_prompt: str) -> dict:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": eval_prompt}],
            max_tokens=1,
            temperature=0,
            seed=0,
            logprobs=True,
            top_logprobs=20,
        )
        self._count_tokens(resp)

        choice = resp.choices[0]
        raw = {
            "model": self.model,
            "mode": "logprob_weighted",
            "text": choice.message.content,
        }

        if choice.logprobs is None or choice.logprobs.content is None or len(choice.logprobs.content) == 0:
            raw["score"] = None
            raw["refusal"] = True
            raw["reason"] = "no logprobs returned"
            return raw

        top = choice.logprobs.content[0].top_logprobs
        raw["top_logprobs"] = [{"token": lp.token, "logprob": lp.logprob} for lp in top]

        numeric_tokens = []
        for lp in top:
            try:
                val = int(lp.token.strip())
                if 0 <= val <= 100:
                    numeric_tokens.append((val, lp.logprob))
            except (ValueError, TypeError):
                pass

        total_mass = sum(math.exp(lp) for _, lp in numeric_tokens)
        raw["numeric_mass"] = total_mass

        if total_mass < 0.25:
            raw["score"] = None
            raw["refusal"] = True
            raw["reason"] = f"numeric mass {total_mass:.4f} < 0.25"
            return raw

        weighted_score = sum(val * math.exp(lp) for val, lp in numeric_tokens) / total_mass
        raw["score"] = round(weighted_score, 4)
        raw["refusal"] = False
        return raw

    def _score_text(self, eval_prompt: str) -> dict:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": eval_prompt}],
            max_tokens=10,
            temperature=0,
            seed=0,
        )
        self._count_tokens(resp)

        text = resp.choices[0].message.content.strip()
        raw = {
            "model": self.model,
            "mode": "text_parse",
            "text": text,
        }

        try:
            val = int(text)
            if 0 <= val <= 100:
                raw["score"] = val
                raw["refusal"] = False
            else:
                raw["score"] = None
                raw["refusal"] = True
                raw["reason"] = f"parsed {val} out of 0-100 range"
        except ValueError:
            if "REFUSAL" in text.upper():
                raw["score"] = None
                raw["refusal"] = True
                raw["reason"] = "explicit REFUSAL"
            else:
                raw["score"] = None
                raw["refusal"] = True
                raw["reason"] = f"unparseable: {text}"

        return raw

    def _count_tokens(self, resp):
        self.total_calls += 1
        if resp.usage:
            self.total_input_tokens += resp.usage.prompt_tokens or 0
            self.total_output_tokens += resp.usage.completion_tokens or 0

    def cost_summary(self) -> dict:
        return {
            "calls": self.total_calls,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
        }
