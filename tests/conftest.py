"""V17 成本闸（cost gate）—— 全局、collection 之前生效的付费防线。

问题（R2 复验实证）：
  tests/contract/stage2/test_b_direction_3b.py 在 **模块顶层** 读
  ``~/oc-boss-state/deepseek.key`` 并写进 ``os.environ``；仓库根裸 ``pytest``
  在 ``testpaths=["tests"]`` 下 ``--collect-only`` 就会 import 该模块，
  key 于**收集期**即完整载入进程环境（配合 OPENAI_BASE_URL=api.deepseek.com
  → 实打实的计费路径）。``pytest.mark.skipif`` **救不了**它：skipif 在 collect
  期求值，而模块顶层代码在此之前已执行。

本闸的三条防线（都在 import 测试模块**之前**装好）：

  D1 静态源码扫描 + ``pytest_ignore_collect``
     任何测试文件，只要源码里出现付费凭据来源（deepseek.key / oc-boss-state /
     付费 API host / 付费 env 变量赋值），在**不设 APPROVE_COST 时直接不 import**。
     这是唯一能挡住"模块顶层读 key"的时机，且对**将来新增**的测试文件同样生效
     ——不是给那两个文件打补丁。

  D2 付费环境变量中和（含 .env 旁路）
     不设 APPROVE_COST 时把付费 env 变量**预置为空串**。这同时堵死
     ``src/abcr/notify.py`` 的 ``load_dotenv(ROOT/.env)`` 旁路：python-dotenv
     默认 ``override=False``，变量已存在（哪怕空串）就不会被 .env 覆盖。
     于是仓库根真实存在的 .env 里的 DEEPSEEK_API_KEY / OPENAI_API_KEY
     **进不了** os.environ。空串同时让下游 ``skipif(not OPENAI_API_KEY)`` 正常跳过。

  D3 sys.addaudithook 兜底（fail-closed）
     - ``open``：读付费凭据源（~/oc-boss-state/**、*deepseek*.key、
       ~/.aws/credentials 等）→ 抛 CostGateError（阻断，不是事后记账）。
     - ``subprocess.Popen`` / ``os.exec``：若显式传入的 env 带非空付费 key
       → 抛 CostGateError。子进程逃逸（test_b_pv_e2e_05b 把 key 塞进 env 交给
       subprocess.run）在 key **被读之前**就已被 D1/D3 判定，不依赖子进程内 hook。

放行方式（唯一）：``APPROVE_COST=1``（或 true/yes/on）。设了即视为人已授权计费，
本闸整体不 arm，行为与打闸前完全一致。

自检：``make cost-gate-check``。
"""
from __future__ import annotations

import os
import pathlib
import re
import sys

APPROVE_ENV = "APPROVE_COST"
_TRUTHY = {"1", "true", "yes", "on"}

#: 付费凭据类环境变量——不批准时中和为空串，并禁止随 subprocess 外传。
PAID_ENV_VARS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "DEEPSEEK_API_KEY",
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "TOGETHER_API_KEY",
    "GROQ_API_KEY",
)

#: 只对"能产生计费凭据的来源"命中；本地 HMAC 口令（fixtures/test_approval.key、
#: state/approval.key）**不在内**，否则会误伤既有 735 绿。
_PAID_PATH_RE = re.compile(
    r"(?:"
    r"oc-boss-state[/\\]"                                   # 本仓 key 存放点
    r"|(?:deepseek|openai|anthropic|azure|openrouter|together|groq)"
    r"[^/\\]*\.(?:key|token|secret)$"                       # *deepseek*.key 之类
    r"|[/\\]\.aws[/\\]credentials$"
    r"|[/\\]\.config[/\\]gcloud[/\\]"
    r")",
    re.IGNORECASE,
)

#: open 热路径的廉价前置过滤（小写子串），命中后才跑正则。
_PAID_PATH_HINTS = (
    "oc-boss-state", "deepseek", "openai", "anthropic", "azure",
    "openrouter", "together", "groq", "credentials", "gcloud",
)

#: 源码静态扫描：命中即判定该测试文件会触达付费路径。
_PAID_SOURCE_RE = re.compile(
    r"(?:"
    r"oc-boss-state"
    r"|deepseek\.key"
    r"|api\.deepseek\.com"
    r"|api\.openai\.com"
    r"|api\.anthropic\.com"
    r"|openrouter\.ai"
    r"|(?:environ|env)\s*(?:\[\s*[\"'](?:OPENAI_API_KEY|DEEPSEEK_API_KEY|ANTHROPIC_API_KEY|OPENAI_BASE_URL)[\"']\s*\]\s*="
    r"|\.setdefault\(\s*[\"'](?:OPENAI_API_KEY|DEEPSEEK_API_KEY|ANTHROPIC_API_KEY|OPENAI_BASE_URL)[\"'])"
    r")",
)


class CostGateError(RuntimeError):
    """付费闸拦截。不设 APPROVE_COST 时读付费凭据/外传付费 key 即抛此异常。"""


def cost_approved() -> bool:
    """人是否显式批准了计费。唯一放行开关。"""
    return os.environ.get(APPROVE_ENV, "").strip().lower() in _TRUTHY


def require_cost_approval(what: str = "paid API call") -> None:
    """生产/测试代码里的显式断言点：未批准即 fail-closed。"""
    if not cost_approved():
        raise CostGateError(
            f"cost gate: {what} requires {APPROVE_ENV}=1 (not set). "
            "Refusing to read paid credentials or issue billable calls."
        )


def is_paid_credential_path(path: object) -> bool:
    try:
        s = os.fspath(path)
    except TypeError:
        return False
    if not isinstance(s, str):
        try:
            s = s.decode("utf-8", "replace")
        except Exception:
            return False
    low = s.lower()
    # 快速前置过滤：open 是热路径，绝大多数路径连关键字都不含，直接放行。
    if not any(t in low for t in _PAID_PATH_HINTS):
        return False
    return bool(_PAID_PATH_RE.search(s))


def source_touches_paid_path(text: str) -> bool:
    return bool(_PAID_SOURCE_RE.search(text))


# --------------------------------------------------------------------------
# D3: audit hook（进程级、不可摘除、fail-closed）
# --------------------------------------------------------------------------
_HOOK_INSTALLED = False
BLOCKED_EVENTS: list[str] = []


def _install_audit_hook() -> None:
    global _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return
    _HOOK_INSTALLED = True

    def _hook(event: str, args) -> None:
        if cost_approved():          # 运行中被显式批准 → 放行
            return
        if event == "open":
            if args and is_paid_credential_path(args[0]):
                msg = f"cost gate: blocked read of paid credential source: {args[0]!r}"
                BLOCKED_EVENTS.append(msg)
                raise CostGateError(
                    msg + f" — set {APPROVE_ENV}=1 to authorize billable use."
                )
        elif event in ("subprocess.Popen", "os.posix_spawn", "os.exec"):
            env = args[3] if len(args) > 3 else None
            if isinstance(env, dict):
                leaked = [
                    k for k in PAID_ENV_VARS
                    if str(env.get(k) or env.get(k.encode(), b"") or "").strip()
                ]
                if leaked:
                    msg = (
                        "cost gate: blocked subprocess carrying paid credentials in env: "
                        + ",".join(leaked)
                    )
                    BLOCKED_EVENTS.append(msg)
                    raise CostGateError(
                        msg + f" — set {APPROVE_ENV}=1 to authorize billable use."
                    )

    sys.addaudithook(_hook)


# --------------------------------------------------------------------------
# pytest hooks
# --------------------------------------------------------------------------
_IGNORED_PAID_FILES: list[str] = []


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers", "paid: 触达付费 API/凭据；无 APPROVE_COST=1 时不收集。"
    )
    if cost_approved():
        return
    # D2：中和付费 env（同时堵死 .env / load_dotenv(override=False) 旁路）
    for var in PAID_ENV_VARS:
        os.environ[var] = ""
    # D3：装 audit hook
    _install_audit_hook()


def pytest_ignore_collect(collection_path: pathlib.Path, config):
    """D1：在 import 之前静态判定，命中付费源的测试文件直接不收集。"""
    if cost_approved():
        return None
    p = pathlib.Path(str(collection_path))
    if p.suffix != ".py" or not p.is_file():
        return None
    if p.name == "conftest.py":
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if source_touches_paid_path(text):
        rel = str(p)
        if rel not in _IGNORED_PAID_FILES:
            _IGNORED_PAID_FILES.append(rel)
        return True
    return None


def pytest_collection_modifyitems(config, items) -> None:
    """带 @pytest.mark.paid 的用例，未批准时整条剔除（不进入 run 阶段）。"""
    if cost_approved():
        return
    kept = []
    for item in items:
        if item.get_closest_marker("paid") is not None:
            _IGNORED_PAID_FILES.append(f"{item.nodeid} (marker=paid)")
        else:
            kept.append(item)
    if len(kept) != len(items):
        items[:] = kept


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    if cost_approved():
        terminalreporter.write_line(
            f"cost-gate: DISARMED ({APPROVE_ENV} set) — paid tests are collected and may bill."
        )
        return
    n = len(_IGNORED_PAID_FILES)
    terminalreporter.write_line(
        f"cost-gate: armed ({APPROVE_ENV} unset) — blocked {n} paid test file(s) "
        f"before import; paid env vars neutralized; credential reads fail-closed."
    )
    for f in _IGNORED_PAID_FILES:
        terminalreporter.write_line(f"cost-gate: blocked {f}")
