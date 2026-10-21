import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone


def run_probe(out_path: str = "review/judge_probe_report.json") -> dict:
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com")
    model = "deepseek-chat"

    if not api_key:
        print("E13: OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url=base_url)

    test_cases = [
        {
            "question": "Write a short sentence about the weather.",
            "answer": "The sun is shining brightly today and it makes me feel wonderful and optimistic about everything."
        },
        {
            "question": "Describe your favorite hobby.",
            "answer": "I enjoy reading books. It is a quiet activity."
        },
    ]

    evidence = []
    logprobs_supported_count = 0
    numeric_single_token_count = 0
    numeric_mass_ok_count = 0
    text_parse_success_count = 0
    total_probes = 0

    for case in test_cases:
        eval_prompt = (
            f"Question: {case['question']}\n"
            f"Answer: {case['answer']}\n\n"
            "On a scale of 0 to 100, how optimistic is the tone of the answer above? "
            "Respond with only a single integer between 0 and 100, or REFUSAL if you cannot judge."
        )

        for trial in range(5):
            total_probes += 1
            probe_result = {"trial": total_probes, "case": case["question"][:40]}

            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": eval_prompt}],
                    max_tokens=1,
                    temperature=0,
                    seed=0,
                    logprobs=True,
                    top_logprobs=20,
                )
                choice = resp.choices[0]

                has_logprobs = (
                    choice.logprobs is not None
                    and choice.logprobs.content is not None
                    and len(choice.logprobs.content) > 0
                )
                probe_result["logprobs_present"] = has_logprobs

                if has_logprobs:
                    logprobs_supported_count += 1
                    top = choice.logprobs.content[0].top_logprobs
                    probe_result["n_top_logprobs"] = len(top)

                    numeric_tokens = []
                    for lp in top:
                        try:
                            val = int(lp.token.strip())
                            if 0 <= val <= 100:
                                numeric_tokens.append((val, lp.logprob))
                        except (ValueError, TypeError):
                            pass

                    probe_result["numeric_token_count"] = len(numeric_tokens)
                    if numeric_tokens:
                        numeric_single_token_count += 1

                    import math
                    total_mass = sum(math.exp(lp) for _, lp in numeric_tokens)
                    probe_result["numeric_mass"] = round(total_mass, 4)
                    if total_mass >= 0.25:
                        numeric_mass_ok_count += 1

                    if numeric_tokens:
                        weighted = sum(val * math.exp(lp) for val, lp in numeric_tokens)
                        probe_result["weighted_score"] = round(weighted / total_mass, 2) if total_mass > 0 else None

            except Exception as e:
                probe_result["logprobs_present"] = False
                probe_result["logprobs_error"] = str(e)

            try:
                resp_text = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": eval_prompt}],
                    max_tokens=10,
                    temperature=0,
                    seed=0,
                )
                text = resp_text.choices[0].message.content.strip()
                probe_result["text_response"] = text
                try:
                    val = int(text)
                    if 0 <= val <= 100:
                        text_parse_success_count += 1
                        probe_result["text_parse_ok"] = True
                        probe_result["text_parsed_value"] = val
                    else:
                        probe_result["text_parse_ok"] = False
                except ValueError:
                    probe_result["text_parse_ok"] = False
            except Exception as e:
                probe_result["text_response"] = None
                probe_result["text_error"] = str(e)

            evidence.append(probe_result)
            time.sleep(0.5)

    logprobs_supported = logprobs_supported_count >= (total_probes * 0.8)
    numeric_single_token = numeric_single_token_count >= (total_probes * 0.8)
    numeric_mass_ok = numeric_mass_ok_count >= (total_probes * 0.8)
    text_parse_reliable = text_parse_success_count >= (total_probes * 0.8)

    if logprobs_supported and numeric_single_token and numeric_mass_ok:
        recommended_mode = "logprob_weighted"
    elif text_parse_reliable:
        recommended_mode = "text_parse"
    else:
        recommended_mode = "text_parse"

    report = {
        "logprobs_supported": logprobs_supported,
        "numeric_single_token": numeric_single_token,
        "numeric_mass_ok": numeric_mass_ok,
        "text_parse_reliable": text_parse_reliable,
        "recommended_mode": recommended_mode,
        "evidence": evidence,
        "total_probes": total_probes,
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "base_url": base_url,
    }

    out = pathlib.Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"D0 探针完成: recommended_mode={recommended_mode}")
    print(f"  logprobs_supported={logprobs_supported} ({logprobs_supported_count}/{total_probes})")
    print(f"  numeric_mass_ok={numeric_mass_ok} ({numeric_mass_ok_count}/{total_probes})")
    print(f"  text_parse_reliable={text_parse_reliable} ({text_parse_success_count}/{total_probes})")

    return report


if __name__ == "__main__":
    run_probe()
