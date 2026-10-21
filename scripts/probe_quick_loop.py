#!/usr/bin/env python3
"""probe_quick_loop.py —— ABCR 最小快道的启动入口与 CLI 后备。

每天只有一个入口：

    PYTHONPATH=src .venv312/bin/python scripts/probe_quick_loop.py

它启动本机页面并自动打开浏览器。页面用不了时，同一份逻辑有 CLI 后备：

    ... scripts/probe_quick_loop.py run  --hypothesis "…" --persona-file p.txt [-n 20] [--seed 1]
    ... scripts/probe_quick_loop.py list
    ... scripts/probe_quick_loop.py show <probe_id>
    ... scripts/probe_quick_loop.py check          # 只读体检：不跑实验

退出码：0=成功；1=快道自身的失败（含引擎停止、契约拒绝）；2=用法错误。

边界：只写 `lab/runs/`。不碰正式 ledger / 控制面 / 证据目录，不做 release、
不装服务、不执行 genesis。产出一律 `citable=false`。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# 入口脚本自带路径，免得每次都要记 PYTHONPATH 两段（src 给 abcr，根给 lab）。
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from abcr.control.contracts import ContractError                      # noqa: E402
from lab.fastlane import loop, web                                    # noqa: E402
from lab.fastlane.errors import FastlaneError                         # noqa: E402


def _read_persona(args: argparse.Namespace) -> str:
    if args.persona_file:
        return Path(args.persona_file).read_text(encoding="utf-8")
    if args.persona:
        return args.persona
    raise FastlaneError("bad_persona", "需要 --persona 或 --persona-file")


def cmd_serve(args: argparse.Namespace) -> int:
    """起页面。`--port` 给没给，语义是两回事。

    没给（无参数入口、Finder 双击都走这条）：`DEFAULT_PORT` 只是起点，
    被别的程序占着就让位到系统分配的空闲端口——人只是想打开页面。
    给了：那是人明确表达的意图，被占时当场报错，不替他换。
    """
    explicit_port = args.port is not None
    web.serve(args.host, args.port if explicit_port else web.DEFAULT_PORT,
              open_browser=not args.no_browser,
              fallback_to_ephemeral=not explicit_port)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    spec = loop.build_spec(hypothesis=args.hypothesis, persona_text=_read_persona(args),
                           count=args.count, seed=args.seed,
                           parent_probe_id=args.parent)
    # 身份闸必须早于复用判断：坏 split 下"直接复用"照样是把结果交付出去一次，
    # 而那一轮正是在这份坏 split 下产出的。见 loop.assert_frozen_inputs()。
    loop.assert_frozen_inputs()
    probe_id = loop.probe_id_for(spec)
    if loop.read_round(probe_id) is not None:
        print(f"该请求已经跑过，直接复用：{probe_id}（重复提交不重复造实验）")
        return 0
    print(f"probe_id  {probe_id}")
    print(f"人格      {spec.persona_ref}")
    print(f"题量/seed {spec.count} / {spec.seed}　臂 vanilla + persona")
    print(f"{loop.NOT_CITABLE_LABEL} —— 运行中，请稍候…")
    record = loop.run_round(spec)
    print(f"完成      {record['row_count']} 行 / 预期 {record['expected_row_count']} 行　"
          f"耗时 {record['elapsed_ms'] / 1000:.1f}s")
    _print_summary(record)
    return 0


def _print_summary(record: dict) -> None:
    rows = loop.round_rows(record)
    summary = loop.summarize(record, rows)
    persona_arm = summary.get("persona_arm") or ""
    print(f"\n{'指标':<24}{'vanilla':>12}{'persona':>12}{'差值':>12}")
    for key, label in web.METRIC_LABELS:
        base = summary["arms"].get("vanilla", {}).get("metrics", {}).get(key)
        treat = summary["arms"].get(persona_arm, {}).get("metrics", {}).get(key)
        delta = summary["deltas"].get(key)
        digits = 0 if key.startswith("output_len") else 3
        print(f"{label:<24}{web.fmt(base, digits):>12}{web.fmt(treat, digits):>12}"
              f"{web.fmt_delta(delta, digits):>12}")
    print(f"\ncitable = {str(record['citable']).lower()}　{record['label']}")


def cmd_list(args: argparse.Namespace) -> int:
    records, failures = loop.scan_rounds()
    # 坏轮先报，且**不被藏起来**。把校验失败的记录悄悄跳过，等于让被改过的
    # 一轮从历史上整条消失——那比报错更难发现。
    for failure in failures:
        print(f"[读不出来] {failure['probe_id']}  [{failure['code']}] {failure['message']}",
              file=sys.stderr)
    if failures:
        print(f"共 {len(failures)} 条轮次读不出来，内容不予展示。\n", file=sys.stderr)
    if not records:
        print("还没有任何可读轮次。" if failures else "还没有任何轮次。")
        return 1 if failures else 0
    for record in records:
        parent = record.get("parent_probe_id")
        print(f"{record['probe_id']}  {record.get('recorded_at', '')}  "
              f"{record.get('count')} 题 seed {record.get('seed')}  "
              f"{record.get('row_count')} 行"
              + (f"  承自 {parent}" if parent else ""))
        print(f"    假设  {record.get('hypothesis_raw', '')[:100]}")
    return 1 if failures else 0


def cmd_show(args: argparse.Namespace) -> int:
    record = loop.read_round(args.probe_id)
    if record is None:
        print(f"没有这一轮: {args.probe_id}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    print(f"probe_id        {record['probe_id']}")
    print(f"parent          {record.get('parent_probe_id') or '—'}")
    print(f"假设            {record.get('hypothesis_raw', '')}")
    print(f"人格 {record.get('persona_ref')}\n{record.get('persona_text', '')}")
    print(f"\n题量/seed       {record.get('count')} / {record.get('seed')}")
    # 身份值一律**完整**打印：截断过的指纹没法和 `ollama show`、notebook 目录名、
    # bundle 目录名做逐字比对，而能逐字比对正是它们存在的理由。
    print(f"bundle          {record.get('bundle_id', '')}")
    print(f"引擎指纹        {record.get('engine_fingerprint_sha256', '')}")
    print(f"数据集 sha256   {record.get('dataset_sha256', '')}")
    print(f"split sha256    {record.get('split_sha256', '')}")
    _print_summary(record)
    rows = loop.round_rows(record)
    # `load_items_for()` 抛的是 `FastlaneError`（它已经把核心的 `ContractError`
    # 翻译过一次）。只写 `ContractError` 等于什么都没接住——页面层的同一处
    # 错位正是本轮的阻断级缺陷之一。
    try:
        items = loop.load_items_for(record)
    except (FastlaneError, ContractError, OSError) as exc:
        # bundle 封印验签没过 → 不拿"题面留空"糊过去。封印的语义是防 holdout
        # 冒充 dev，验不过就无法证明这些输出对应的是 dev 题。
        print(f"\n快道停止 [{getattr(exc, 'code', type(exc).__name__)}] "
              f"dev bundle 校验失败：{exc}", file=sys.stderr)
        return 1
    print("\n逐题：")
    for index, entry in enumerate(loop.paired_items(record, rows, items), start=1):
        print(f"\n[{index}] {entry['item_id']}  {entry.get('check_type', '')}")
        print(f"    题目 {entry.get('prompt', '')}")
        for arm_id in record.get("arm_ids", []):
            arm = entry["arms"].get(arm_id)
            if arm is None:
                continue
            metrics = arm.get("metrics", {})
            print(f"    [{arm_id}] is_correct={metrics.get('is_correct')}")
            print(f"        row_hash {arm.get('row_hash', '')}")
            print(f"        {arm.get('output_text', '')!r}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """只读体检：把跑实验前会失败的东西提前暴露出来，不跑任何一题。"""
    ok = True

    def report(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

    for label, path in (("冻结 profile", loop.PROFILE_PATH),
                        ("数据集", loop.DATASET_PATH),
                        ("split", loop.SPLIT_PATH)):
        report(f"{label} 存在", path.exists(), str(path))
    p = loop.paths()
    report("lab 数据根可写", _writable(p.root), str(p.root))
    from lab.fastlane import split_adapter
    coords = split_adapter.frozen_coordinates()
    print(f"  仓内权威坐标  family={coords['family']}  salt={coords['salt']}  "
          f"split_hash={coords['split_hash'][:16]}…  dev={coords['distribution']['dev']}")
    try:
        split_adapter.assert_frozen_dataset(loop.DATASET_PATH)
        report("数据集身份 == 仓内冻结件", True, coords["dataset_sha256"])
    except FastlaneError as exc:
        report("数据集身份 == 仓内冻结件", False, f"[{exc.code}] {exc.message}")
    try:
        info = split_adapter.load_frozen_split(loop.SPLIT_PATH)
        counts = {k: len(v) for k, v in info["buckets"].items()}
        report("split 身份闸（路径 / 字节 / 语义坐标）", True, coords["split_sha256"])
        report("split 内容闸（family / salt / 计数 / split_hash / 切分规则复算）",
               True, str(counts))
        pool = len(info["buckets"]["dev"])
        report(f"dev 题池够跑 {loop.MAX_ITEMS} 题", pool >= loop.MAX_ITEMS, f"dev={pool}")
    except FastlaneError as exc:
        report("split 身份闸 + 内容闸", False, f"[{exc.code}] {exc.message}")
    try:
        fingerprint = loop.make_engine().fingerprint()
        report("Ollama 可达且模型指纹相符", True,
               f"profile_id={fingerprint.get('profile_id')}")
    except Exception as exc:  # noqa: BLE001 - 体检要报出任何原因，不挑类型
        report("Ollama 可达且模型指纹相符", False, f"{type(exc).__name__}: {exc}")
    print(f"\n{'全部通过' if ok else '存在 FAIL —— 快道会在这些点上明确停止，不会降级运行'}")
    return 0 if ok else 1


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="probe_quick_loop.py", description="ABCR 最小快道（学习数据 · 不可引用）")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="启动本机页面（默认动作）")
    serve.add_argument("--host", default=web.DEFAULT_HOST)
    # 缺省 None 而不是 DEFAULT_PORT：`cmd_serve` 要能分辨"人没说端口"和
    # "人正好指定了 8787"——前者被占可以让位，后者被占必须报错。
    serve.add_argument("--port", type=int, default=None,
                       help=f"默认 {web.DEFAULT_PORT}（被占用时自动改用空闲端口）；"
                            "显式指定则被占用时报错不改")
    serve.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    serve.set_defaults(func=cmd_serve)

    run = sub.add_parser("run", help="CLI 后备：跑一轮")
    run.add_argument("--hypothesis", required=True, help="本轮假设/预测")
    run.add_argument("--persona", help="人格文本")
    run.add_argument("--persona-file", help="人格文本文件")
    run.add_argument("-n", "--count", type=int, default=loop.DEFAULT_ITEMS,
                     help=f"题量 {loop.MIN_ITEMS}–{loop.MAX_ITEMS}")
    run.add_argument("--seed", type=int, default=loop.DEFAULT_SEED)
    run.add_argument("--parent", help="承自哪一轮（probe_id）")
    run.set_defaults(func=cmd_run)

    listing = sub.add_parser("list", help="列出全部轮次")
    listing.set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="看一轮的详情")
    show.add_argument("probe_id")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_show)

    check = sub.add_parser("check", help="只读体检，不跑实验")
    check.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["serve"]          # 无参数 = 每天那一条固定命令
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except FastlaneError as exc:
        print(f"快道停止 [{exc.code}] {exc.message}", file=sys.stderr)
        if exc.detail:
            print(f"  {exc.detail}", file=sys.stderr)
        return 1
    except ContractError as exc:
        print(f"契约拒绝 {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
