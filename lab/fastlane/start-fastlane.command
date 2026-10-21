#!/bin/bash
# 双击即启动 ABCR 最小快道页面（学习数据 · 不可引用）。
# 这只是 scripts/probe_quick_loop.py 的一层壳，不是 macOS App、不装服务、
# 不写 launchd —— 双击关掉窗口它就停了。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$ROOT/.venv312/bin/python"
# 在 worktree 里跑时 venv 在主仓，回落到主仓那一份（禁 pip install -e .，见 CLAUDE.md）。
[ -x "$PY" ] || PY="/Users/superagent/shared-brain/ABCR/abcr/.venv312/bin/python"

if [ ! -x "$PY" ]; then
  echo "找不到 .venv312 解释器：$PY" >&2
  echo "按回车关闭窗口" >&2; read -r _; exit 1
fi

cd "$ROOT"
# 不带参数（双击就是这种）时 probe_quick_loop.py 自己默认 serve，行为与从前一致；
# 带参数时可以直接跑 `./start-fastlane.command check`——这也让「可执行位是否真的
# 修好了」能被端到端验证，而不用起一个会自动开浏览器的服务。
exec "$PY" scripts/probe_quick_loop.py "$@"
