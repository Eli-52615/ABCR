#!/usr/bin/env python3
"""scripts/b_gen_ifeval.py — ifeval_zh_v1 任务族 250 题确定性生成 + 自检。

设计（契约 B2-7）：8 类可验证指令，共 250 题 = exact_output 32 + json_object 32 +
其余六类各 31（32+32+31×6=250）。程序生成类用 random.Random(20260714) 保证确定性；
语言创作类由作者（窗口 B = Claude）以内置策展词表/主题模板亲自撰写并参数化组合。

硬门：每题必带 pass_sample / fail_sample，判分器自检 check(pass)=True 且 check(fail)=False
（250×2=500 断言全过才写盘）；题面与 golden10 十题零重合（构造保证，自检核验）。

用法：
  python scripts/b_gen_ifeval.py            # 生成并写 data/benchmarks/ifeval_zh_v1.json + splits
  python scripts/b_gen_ifeval.py --selfcheck  # 同上，强调打印 500/500 自检与 split 分布
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from abcr.rig import scorer
from abcr.rig.splits import assign_split, split_hash

FAMILY = "ifeval_zh_v1"
SEED = 20260714
REPO = Path(__file__).resolve().parents[1]


def _mk(check_type: str, prompt: str, check_args: dict, pass_sample: str, fail_sample: str) -> dict:
    return {"family": FAMILY, "check_type": check_type, "prompt": prompt,
            "check_args": check_args, "pass_sample": pass_sample, "fail_sample": fail_sample}


# ───────────────────────── 程序生成类 ─────────────────────────
def gen_exact_output(rng: random.Random) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    # 20 算术（加/乘/减；避开 golden g02 的 17×23）
    while len([i for i in items if "算术" == i.get("_", "算术")]) < 20 and len(items) < 20:
        op = rng.choice(["+", "×", "-"])
        a, b = rng.randint(11, 99), rng.randint(11, 99)
        if op == "-" and a < b:
            a, b = b, a
        if op == "×" and (a, b) in {(17, 23), (23, 17)}:
            continue
        val = {"+": a + b, "×": a * b, "-": a - b}[op]
        prompt = f"计算 {a}{op}{b}，只输出数字。"
        if prompt in seen:
            continue
        seen.add(prompt)
        items.append(_mk("exact_output", prompt, {"expected": str(val)},
                         str(val), f"答案是{val}"))
    # 12 字符串逆序（避开 golden g08 的 abcr）
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    while len(items) < 32:
        n = rng.randint(3, 6)
        s = "".join(rng.choice(alphabet) for _ in range(n))
        if s == "abcr" or s == s[::-1]:
            continue
        prompt = f"将字符串 {s} 逆序输出，只输出结果。"
        if prompt in seen:
            continue
        seen.add(prompt)
        items.append(_mk("exact_output", prompt, {"expected": s[::-1]},
                         s[::-1], f"逆序是{s[::-1]}"))
    return items


def gen_json_object(rng: random.Random) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    int_keys = ["x", "n", "k", "count", "val", "num", "size", "idx"]
    str_keys = ["name", "tag", "label", "code"]
    bool_keys = ["ok", "flag", "done", "valid"]
    while len(items) < 32:
        kind = rng.choice(["int", "str", "bool"])
        if kind == "int":
            key = rng.choice(int_keys)
            v = rng.randint(1, 99)
            if key == "a" and v == 1:  # 避开 golden g05
                continue
            expected = {key: v}
            prompt = f"以 JSON 对象输出，仅含键 {key} 值为整数 {v}。"
            fail = {key: v, "extra": 0}
        elif kind == "str":
            key = rng.choice(str_keys)
            sval = rng.choice(["abcr", "alpha", "beta", "gamma", "delta"])
            expected = {key: sval}
            prompt = f'以 JSON 对象输出，仅含键 {key} 值为字符串 "{sval}"。'
            fail = {key: sval + "x"}
        else:
            key = rng.choice(bool_keys)
            bval = rng.choice([True, False])
            expected = {key: bval}
            prompt = f"以 JSON 对象输出，仅含键 {key} 值为布尔 {str(bval).lower()}。"
            fail = {key: not bval}
        if prompt in seen:
            continue
        seen.add(prompt)
        items.append(_mk("json_object", prompt, {"expected": expected},
                         json.dumps(expected, ensure_ascii=False),
                         json.dumps(fail, ensure_ascii=False)))
    return items


def gen_option_letter(rng: random.Random) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    while len(items) < 31:
        a, b = rng.randint(10, 50), rng.randint(10, 50)
        correct = a + b
        distractors = {correct + rng.choice([-3, -2, -1, 1, 2, 3]),
                       correct + rng.choice([-5, 4, 5, 6])}
        distractors.discard(correct)
        distractors = list(distractors)[:2]
        if len(distractors) < 2:
            continue
        opts = [correct] + distractors
        rng.shuffle(opts)
        letters = ["A", "B", "C"]
        correct_letter = letters[opts.index(correct)]
        prompt = (f"计算 {a}+{b} 等于多少？"
                  f"A. {opts[0]} B. {opts[1]} C. {opts[2]}。只输出选项字母。")
        if prompt in seen:
            continue
        seen.add(prompt)
        items.append(_mk("option_letter", prompt, {"expected": correct_letter},
                         correct_letter, f"答案是{correct_letter}"))
    return items


def gen_separator_items(rng: random.Random) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    seps = [("，", "中文逗号"), ("、", "顿号"), ("；", "分号"), (",", "英文逗号"), (";", "英文分号")]
    rnd = 0
    while len(items) < 31:
        sep, sep_name = rng.choice(seps)
        n = rng.randint(3, 6)
        digits = rng.sample(range(0, 10), n)
        marker = f"（例{rnd}）" if rnd else ""
        prompt = f"输出 {n} 个各不相同的一位数字，用{sep_name}分隔，不加其他内容。{marker}"
        rnd += 1
        if prompt in seen:
            continue
        seen.add(prompt)
        pass_s = sep.join(str(d) for d in digits)
        fail_s = sep.join(str(d) for d in digits[:-1])  # n-1 项
        items.append(_mk("separator_items", prompt, {"sep": sep, "n": n}, pass_s, fail_s))
    return items


# ───────────────────────── 语言创作类（作者策展） ─────────────────────────
def gen_line_count_prefix() -> list[dict]:
    # (topic, [items...>=5], prefix)
    topics = [
        ("四季", ["春天万物复苏", "夏天骄阳似火", "秋天硕果累累", "冬天银装素裹", "四季各有风景"], "- "),
        ("方向", ["东方是日出之地", "南方气候温暖", "西方多有高山", "北方冬季漫长", "中央为交汇处"], "* "),
        ("三餐", ["早餐要吃得营养", "午餐要吃得饱足", "晚餐要吃得清淡", "加餐可补充能量", "夜宵尽量避免"], "· "),
        ("学习方法", ["制定明确计划", "专注单一任务", "及时复习巩固", "主动提出疑问", "定期自我检测"], "> "),
        ("备份原则", ["定期执行备份", "异地保存副本", "校验数据完整", "记录备份日志", "演练恢复流程"], "- "),
        ("运动好处", ["增强心肺功能", "改善睡眠质量", "缓解精神压力", "提升身体协调", "促进新陈代谢"], "* "),
        ("阅读步骤", ["浏览全文结构", "标注关键要点", "梳理逻辑脉络", "记录个人思考", "复述核心观点"], "· "),
    ]
    items: list[dict] = []
    idx = 0
    # 固定 31 条：round 记轮次保证题面唯一（不进入无限循环）
    while len(items) < 31:
        topic, pool, prefix = topics[idx % len(topics)]
        n = 2 + (idx % 4)  # 2,3,4,5 循环
        rnd = idx // len(topics)
        idx += 1
        if n > len(pool):
            continue
        suffix = f"（第{rnd + 1}组）" if rnd else ""
        prompt = f'用恰好 {n} 行列出关于{topic}的要点，每行以"{prefix}"开头。{suffix}'
        if any(it["prompt"] == prompt for it in items):
            continue
        pass_s = "\n".join(prefix + pool[i] for i in range(n))
        fail_s = "\n".join(prefix + pool[i] for i in range(n - 1))  # 少一行
        items.append(_mk("line_count_prefix", prompt, {"n": n, "prefix": prefix}, pass_s, fail_s))
    return items[:31]


def gen_keyword_min_count() -> list[dict]:
    specs = [
        ("备份的意义", "冗余"), ("猫的习性", "独立"), ("清晨的氛围", "安静"),
        ("坚持的价值", "坚持"), ("校对的重要", "仔细"), ("团队协作", "配合"),
        ("节约用电", "节约"), ("诚信为本", "诚信"), ("专注工作", "专注"),
        ("锻炼身体", "健康"), ("时间管理", "计划"), ("环境保护", "绿色"),
    ]
    items: list[dict] = []
    idx = 0
    while len(items) < 31:
        topic, kw = specs[idx % len(specs)]
        n = 2 + (idx // len(specs)) % 2  # 2 或 3
        rnd = idx // (len(specs) * 2)
        idx += 1
        suffix = f"（其{rnd + 1}）" if rnd else ""
        prompt = f'谈谈{topic}，回答中必须包含"{kw}"至少{n}次。{suffix}'
        if any(it["prompt"] == prompt for it in items):
            continue
        # pass：恰好 n 次；fail：n-1 次
        pass_s = "，".join(f"{kw}很关键" for _ in range(n)) + "。"
        fail_s = "，".join(f"{kw}很关键" for _ in range(n - 1)) + "。" if n - 1 > 0 else "无关内容。"
        items.append(_mk("keyword_min_count", prompt, {"keyword": kw, "n": n}, pass_s, fail_s))
    return items[:31]


def gen_forbidden_word() -> list[dict]:
    # 禁词均不出现在下方安全填充串中
    filler = "这段示范文字长度足够满足题目规定要求，内容仅用于演示格式合规。"
    words = ["电脑", "水", "光", "火", "钱", "车", "书", "花", "云", "风",
             "电脑", "光", "火", "钱", "车", "书", "花", "云", "风", "电脑",
             "光", "火", "钱", "车", "书", "花", "云", "风", "光", "火", "钱"]
    topics = ["介绍电子计算机", "描述雨天景象", "解释什么是友谊", "谈谈城市生活",
              "描述一片森林", "介绍一种乐器", "谈谈时间的价值", "描述夜晚的天空"]
    items: list[dict] = []
    idx = 0
    while len(items) < 31:
        word = words[idx % len(words)]
        topic = topics[idx % len(topics)]
        min_len = 10
        idx += 1
        prompt = f'{topic}，全文不得出现"{word}"字，不少于{min_len}字。'
        if any(it["prompt"] == prompt for it in items):
            continue
        # pass：不含禁词且够长；若 filler 恰含该字则加安全后缀（自检兜底）
        pass_s = filler if word not in filler else "示范内容用于演示题目格式合规达到规定字数收尾。"
        fail_s = filler + word  # 含禁词
        items.append(_mk("forbidden_word", prompt, {"word": word, "min_len": min_len}, pass_s, fail_s))
    return items[:31]


def gen_prefix_suffix_len() -> list[dict]:
    specs = [
        ("今天", "。", 15, "今天天气很好"),
        ("如果", "？", 25, "如果明天下雨怎么办"),
        ("科学", "！", 20, "科学改变了世界"),
        ("我们", "。", 18, "我们一起努力前行"),
        ("这个", "？", 22, "这个问题该如何解决"),
        ("未来", "！", 16, "未来充满了希望"),
        ("学习", "。", 20, "学习需要持之以恒"),
        ("时间", "？", 24, "时间都去哪儿了呢"),
    ]
    items: list[dict] = []
    idx = 0
    while len(items) < 31:
        prefix, suffix, max_len, body = specs[idx % len(specs)]
        idx += 1
        # 加一点变体避免重复
        variant = idx // len(specs)
        prompt = f'输出一句不超过 {max_len} 字的话，以"{prefix}"开头、以"{suffix}"结尾。（示例{variant}）'
        if any(it["prompt"] == prompt for it in items):
            continue
        pass_s = body if body.endswith(suffix) else body + suffix
        if not pass_s.startswith(prefix):
            pass_s = prefix + pass_s
        if len(pass_s) > max_len:
            pass_s = prefix + suffix  # 极简保底满足 len<=max
        fail_s = body[len(prefix):] if body.startswith(prefix) else body  # 去掉开头前缀
        if not fail_s.endswith(suffix):
            fail_s = fail_s + suffix
        items.append(_mk("prefix_suffix_len", prompt,
                         {"prefix": prefix, "suffix": suffix, "max_len": max_len}, pass_s, fail_s))
    return items[:31]


def build_items() -> list[dict]:
    rng = random.Random(SEED)
    groups = [
        gen_exact_output(rng),      # 32
        gen_json_object(rng),       # 32
        gen_option_letter(rng),     # 31
        gen_separator_items(rng),   # 31
        gen_line_count_prefix(),    # 31
        gen_keyword_min_count(),    # 31
        gen_forbidden_word(),       # 31
        gen_prefix_suffix_len(),    # 31
    ]
    items: list[dict] = []
    for g in groups:
        items.extend(g)
    for i, it in enumerate(items, start=1):
        it["item_id"] = f"ifzh-{i:04d}"
    # 稳定字段序
    ordered = [{"item_id": it["item_id"], "family": it["family"],
                "check_type": it["check_type"], "prompt": it["prompt"],
                "check_args": it["check_args"], "pass_sample": it["pass_sample"],
                "fail_sample": it["fail_sample"]} for it in items]
    return ordered


def selfcheck(items: list[dict]) -> tuple[int, int, list[str]]:
    passed = 0
    total = 0
    errs: list[str] = []
    golden = json.loads((REPO / "data/golden/golden10.json").read_text(encoding="utf-8"))["items"]
    golden_prompts = {g["prompt"] for g in golden}
    for it in items:
        # 判分器自检
        total += 2
        try:
            if scorer.check_ifeval(it, it["pass_sample"]) is True:
                passed += 1
            else:
                errs.append(f'{it["item_id"]} pass_sample 未判 True')
            if scorer.check_ifeval(it, it["fail_sample"]) is False:
                passed += 1
            else:
                errs.append(f'{it["item_id"]} fail_sample 未判 False')
        except Exception as e:  # noqa: BLE001
            errs.append(f'{it["item_id"]} 判分异常 {e!r}')
        # 与 golden10 零重合
        if it["prompt"] in golden_prompts:
            errs.append(f'{it["item_id"]} 题面与 golden10 重合')
    return passed, total, errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selfcheck", action="store_true", help="打印自检与 split 分布（仍会写盘）")
    ap.parse_args()

    items = build_items()
    assert len(items) == 250, f"应 250 题，实为 {len(items)}"
    passed, total, errs = selfcheck(items)
    if errs:
        for e in errs[:20]:
            print("SELFCHECK FAIL:", e, file=sys.stderr)
        print(f"{len(items)} items, {passed}/{total} selfcheck assertions passed", file=sys.stderr)
        return 1

    # split 分配 + hash
    assignments = {it["item_id"]: assign_split(FAMILY, it["item_id"]) for it in items}
    dist = {"dev": 0, "calibration": 0, "holdout": 0}
    for s in assignments.values():
        dist[s] += 1
    shash = split_hash(assignments)

    (REPO / "data/benchmarks").mkdir(parents=True, exist_ok=True)
    (REPO / "data/splits").mkdir(parents=True, exist_ok=True)
    bench = {"family": FAMILY, "schema_version": "1.0", "n_items": len(items),
             "note": "8 类可验证指令 250 题（B 定义权，b_gen_ifeval.py 确定性生成）", "items": items}
    (REPO / "data/benchmarks/ifeval_zh_v1.json").write_text(
        json.dumps(bench, ensure_ascii=False, indent=2), encoding="utf-8")
    split_doc = {"family": FAMILY, "salt": "abcr-w1-v1", "split_hash": shash,
                 "distribution": dist, "assignments": assignments}
    (REPO / "data/splits/ifeval_zh_v1.json").write_text(
        json.dumps(split_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{len(items)} items, {passed}/{total} selfcheck assertions passed, "
          f"split: dev={dist['dev']} cal={dist['calibration']} holdout={dist['holdout']}")
    print(f"split_hash = {shash}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
