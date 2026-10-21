"""快道的本机页面：stdlib `http.server` + 手写 HTML。

为什么没有模板引擎
----------------
`.venv312` 里**没有任何 web 框架**（flask / fastapi / starlette / bottle /
tornado / jinja2 / werkzeug 全部实测缺席），而 `08` §4 要求"无新 runtime 依赖"。
于是页面只能手写字符串拼接，转义也得自己做——这不是偷懒，是约束推出的唯一解。

**人格文本与模型原始输出都会进页面**，二者都是不可信文本：模型完全可能吐出
`<script>` 或半个 `<div>`。所以本模块里凡是进 HTML 的值一律过 `esc()`，
没有例外。漏一个，页面结构就被输出内容掀翻。

异常在这一层必须**穷尽**
----------------------
`lab.fastlane.loop` 的读路径抛的是 `FastlaneError`，不是科学核心的 `ContractError`
——`round_rows()` / `load_items_for()` 已经在核心边界上把 `ContractError` 翻译过一次了。
上一版这里 `except ContractError`，捕获的正是那个**再也不会到达此处的类型**，
于是 `round_tampered`、`row_missing`、`bundle_seal_invalid` 全部直穿 `socketserver`：
连接被丢弃，人看到的是 `curl: (52) Empty reply from server`，服务端刷一屏 traceback。

对策是两层：每条路径显式捕获它真正会抛的类型；再加一个兜底 `_guard()`，
任何漏网异常也变成一页写清楚原因的错误页，而不是断开的连接。
**只在还没发出响应时兜底**——否则会把半截响应接上第二个响应头。

为什么实验跑在后台线程
--------------------
20 题 × 2 臂 × 3–9 秒 ≈ 1–3 分钟。同步阻塞在 POST 上会让页面白屏几分钟，
人会以为卡死而重复提交。所以提交后立刻 302 到结果页，结果页自刷新等结果。

并发是**结构性禁止**的：冻结 profile 写着 `max_concurrency: 1`，
`OllamaProbeEngine` 构造时强制校验。HTTP 层是多线程的（要能一边跑实验
一边响应刷新），所以必须自己用一把锁把实验串行化。
"""
from __future__ import annotations

import errno
import html
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from abcr.control.contracts import ContractError

from lab.fastlane import loop
from lab.fastlane.errors import FastlaneError
from lab.fastlane.loop import (DEFAULT_ITEMS, DEFAULT_SEED, MAX_ITEMS, MIN_ITEMS,
                               NOT_CITABLE_LABEL)

#: 只绑回环。快道是本机单用户工具，没有任何鉴权，绝不能对局域网可见。
DEFAULT_HOST = "127.0.0.1"
#: 没指定端口时的**起点**，不是硬性要求。本机上它完全可能已被别的长期服务占着，
#: 那时无参数入口会自动让位到系统分配的端口，见 `bind_server()`。
DEFAULT_PORT = 8787

#: 表单体量上限。人格 65536 字符 + 假设 8192 字节 + 余量，足够且不至于被灌爆。
_MAX_BODY_BYTES = 512 * 1024


def esc(value: Any) -> str:
    """进 HTML 的唯一入口。`quote=True` 连引号一起转，属性里也安全。"""
    return html.escape("" if value is None else str(value), quote=True)


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def fmt_delta(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    return f"{value:+.{digits}f}"


# ────────────────────────── 后台作业 ──────────────────────────
@dataclass
class Job:
    probe_id: str
    state: str = "running"          # running | done | failed
    error: str = ""
    error_code: str = ""
    started_at: float = field(default_factory=time.monotonic)

    @property
    def elapsed_s(self) -> int:
        return int(time.monotonic() - self.started_at)


_JOBS: dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()
#: 冻结 profile 的 `max_concurrency: 1` 在应用层的体现。同一时刻只跑一轮。
_RUN_LOCK = threading.Lock()


def _job(probe_id: str) -> Job | None:
    with _JOBS_LOCK:
        return _JOBS.get(probe_id)


def _set_job(job: Job) -> None:
    with _JOBS_LOCK:
        _JOBS[job.probe_id] = job


def _worker(spec: loop.RoundSpec, probe_id: str, engine: Any) -> None:
    with _RUN_LOCK:
        try:
            loop.run_round(spec, engine=engine)
            _set_job(Job(probe_id, state="done"))
        except (FastlaneError, ContractError) as exc:
            code = getattr(exc, "code", type(exc).__name__)
            _set_job(Job(probe_id, state="failed", error=str(exc), error_code=code))
        except Exception as exc:  # noqa: BLE001 - 页面必须显示原因，不能静默吞掉
            _set_job(Job(probe_id, state="failed", error=str(exc),
                         error_code=type(exc).__name__))


def start_round(spec: loop.RoundSpec) -> tuple[str, str]:
    """提交一轮。返回 `(probe_id, 状态)`，状态 ∈ {existing, running, started}。

    引擎在**这里**构造，不在后台线程里，有两个原因：

    1. `probe_id` 依赖实际引擎的 `profile_id`（夹具轮与真机轮物理隔离）。
       若这里按配置常量预测一个 id、后台线程按实际引擎算另一个，
       302 就会把人送到一个永远不会出现的页面。同一个 id 只能算一次。
    2. 构造不触网（只读冻结 profile + 核验后端二进制摘要），profile 对不上
       能在提交的那一刻就报出来，而不是转圈三秒后才说失败。
    """
    # 身份闸在**最前面**，早于"这轮跑过没有"。坏 split / 坏 dataset 下，
    # 返回 `existing` 同样是把结果交付出去一次——那一轮恰恰是在坏数据下产出的。
    # 只挡"再跑一次"而不挡"再交付一次"，等于没挡。见 loop.assert_frozen_inputs()。
    loop.assert_frozen_inputs()
    engine = loop.make_engine()
    probe_id = loop.probe_id_for(spec, engine_profile=engine.profile_id)
    if loop.read_round(probe_id) is not None:
        return probe_id, "existing"
    job = _job(probe_id)
    if job is not None and job.state == "running":
        return probe_id, "running"
    _set_job(Job(probe_id))
    threading.Thread(target=_worker, args=(spec, probe_id, engine), daemon=True,
                     name=f"fastlane-{probe_id}").start()
    return probe_id, "started"


# ────────────────────────── 页面 ──────────────────────────
_STYLE = """
:root { color-scheme: light dark; --fg:#1a1a1a; --bg:#fbfbfa; --line:#d8d5cf;
        --muted:#6b6862; --card:#fff; --warn-bg:#fff3cd; --warn-fg:#7a5b00;
        --warn-line:#e3c65a; --code:#f4f3f0; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e8e6e3; --bg:#1c1c1a; --line:#3a3833; --muted:#9a968e;
          --card:#252523; --warn-bg:#3d3113; --warn-fg:#f0d68a;
          --warn-line:#6b5a1f; --code:#2e2e2b; } }
* { box-sizing: border-box; }
body { margin:0; padding:0 0 4rem; background:var(--bg); color:var(--fg);
       font:15px/1.65 -apple-system,BlinkMacSystemFont,"Helvetica Neue",sans-serif; }
.wrap { max-width: 60rem; margin: 0 auto; padding: 0 1.25rem; }
.banner { background:var(--warn-bg); color:var(--warn-fg);
          border-bottom:2px solid var(--warn-line); padding:.6rem 1.25rem;
          font-weight:600; letter-spacing:.02em; position:sticky; top:0; z-index:9; }
h1 { font-size:1.35rem; margin:1.5rem 0 .3rem; }
h2 { font-size:1.05rem; margin:2rem 0 .6rem; padding-bottom:.3rem;
     border-bottom:1px solid var(--line); }
h3 { font-size:.95rem; margin:1.2rem 0 .4rem; }
.sub { color:var(--muted); font-size:.85rem; margin:0 0 1rem; }
label { display:block; margin:1rem 0 .3rem; font-weight:600; font-size:.9rem; }
.hint { font-weight:400; color:var(--muted); font-size:.8rem; }
textarea, input[type=number], input[type=text] {
  width:100%; padding:.55rem .7rem; border:1px solid var(--line); border-radius:6px;
  background:var(--card); color:var(--fg); font:inherit; }
textarea { min-height:5.5rem; resize:vertical; }
.row { display:flex; gap:1rem; flex-wrap:wrap; }
.row > div { flex:1 1 10rem; }
button { margin-top:1.2rem; padding:.6rem 1.4rem; font:inherit; font-weight:600;
         border:1px solid var(--line); border-radius:6px; background:var(--card);
         color:var(--fg); cursor:pointer; }
button.primary { background:#2f6f4f; border-color:#2f6f4f; color:#fff; }
table { border-collapse:collapse; width:100%; font-size:.85rem; margin:.5rem 0; }
th, td { border:1px solid var(--line); padding:.4rem .55rem; text-align:left;
         vertical-align:top; }
th { background:var(--card); font-weight:600; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px;
        padding:.9rem 1.1rem; margin:.8rem 0; }
pre { background:var(--code); border:1px solid var(--line); border-radius:6px;
      padding:.6rem .75rem; overflow-x:auto; white-space:pre-wrap;
      word-break:break-word; font-size:.83rem; margin:.35rem 0; }
code, .mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.82rem; }
/* 身份值一律**完整**显示，绝不截断。`user-select:all` 让单击就选中整条 64 位，
   不用手动拖选；`break-all` 让它在窄栏里换行而不撑破表格。 */
.hash { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.75rem;
        user-select:all; -webkit-user-select:all; word-break:break-all;
        background:var(--code); border:1px solid var(--line); border-radius:4px;
        padding:.05rem .3rem; display:inline-block; line-height:1.45; }
.meta { display:grid; grid-template-columns:repeat(auto-fit,minmax(13rem,1fr));
        gap:.4rem 1.2rem; font-size:.82rem; color:var(--muted); }
.meta b { color:var(--fg); font-weight:600; }
a { color:#2f6f4f; }
@media (prefers-color-scheme: dark) { a { color:#7fc4a0; } button.primary
  { background:#2f6f4f; border-color:#3f8f68; } }
.err { border-left:4px solid #b3261e; padding-left:.9rem; }
.tag { display:inline-block; padding:.05rem .45rem; border:1px solid var(--line);
       border-radius:4px; font-size:.75rem; color:var(--muted); }
ul.rounds { list-style:none; padding:0; }
ul.rounds li { border-bottom:1px solid var(--line); padding:.6rem 0; }
.scroll { overflow-x:auto; }
"""


def _page(title: str, body: str, *, refresh: int | None = None) -> bytes:
    meta_refresh = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"{meta_refresh}<title>{esc(title)}</title><style>{_STYLE}</style></head><body>"
        f'<div class="banner">{esc(NOT_CITABLE_LABEL)}　·　本机探索实验，'
        "结果不得用于任何对外结论或正式证据</div>"
        f'<div class="wrap">{body}</div></body></html>'
    ).encode("utf-8")


def hash_cell(value: Any, *, empty: str = "—") -> str:
    """身份值的唯一渲染方式：**完整 64 位**，可单击全选复制。

    上一版这里是 `[:32]…` / `[:16]…`。截断过的指纹没法和 `ollama show`、
    notebook 里的行、bundle 目录名做逐字比对——而"能逐字比对"正是这些值
    存在的全部理由。省下的那点版面换掉了它们的用处。
    """
    text = "" if value is None else str(value)
    if not text:
        return f'<span class="mono">{esc(empty)}</span>'
    return f'<code class="hash">{esc(text)}</code>'


def render_index(rounds: list[dict[str, Any]], *, prefill: loop.RoundSpec | None = None,
                 notice: str = "", failures: list[dict[str, Any]] | None = None) -> bytes:
    p = prefill
    parent = esc(p.parent_probe_id) if p and p.parent_probe_id else ""
    parent_note = (f'<p class="sub">基于轮次 <span class="mono">{parent}</span> 新建：'
                   "下面已预填上一轮的输入，改完再点开始。</p>" if parent else "")
    notice_html = f'<div class="card">{esc(notice)}</div>' if notice else ""
    body = [
        "<h1>ABCR 最小快道</h1>",
        f'<p class="sub">模型 <code>{esc(loop.MODEL_PROFILE)}</code>　题集 '
        f'<code>{esc(loop.FAMILY)}</code> 的 dev　实验臂 vanilla + 1 人格　'
        "③L 关闭　judge 关闭</p>",
        notice_html,
        "<h2>新实验</h2>",
        parent_note,
        '<form method="post" action="/run">',
        f'<input type="hidden" name="parent_probe_id" value="{parent}">',
        '<label>本轮假设 / 预测 <span class="hint">必填。会被折成单行'
        "（科学核心要求 prediction 单行），换行处以 <code> / </code> 连接</span></label>",
        f'<textarea name="hypothesis" required>'
        f'{esc(p.hypothesis_raw if p else "")}</textarea>',
        '<label>人格文本 <span class="hint">必填。会原样拼在题目前作为 persona 臂的 '
        "prompt；vanilla 臂始终是纯题面</span></label>",
        f'<textarea name="persona_text" required>{esc(p.persona_text if p else "")}</textarea>',
        '<div class="row"><div>',
        f'<label>题量 <span class="hint">{MIN_ITEMS}–{MAX_ITEMS}</span></label>',
        f'<input type="number" name="count" min="{MIN_ITEMS}" max="{MAX_ITEMS}" '
        f'value="{esc(p.count if p else DEFAULT_ITEMS)}" required>',
        "</div><div>",
        '<label>seed <span class="hint">同 seed + 同题量恒选同一批题</span></label>',
        f'<input type="number" name="seed" value="{esc(p.seed if p else DEFAULT_SEED)}" required>',
        "</div></div>",
        '<button class="primary" type="submit">开始实验</button>',
        "</form>",
        "<h2>轮次历史</h2>",
    ]
    # 读不出来的轮次**排在最前面且必须可见**。把它们 continue 掉会让被改过的
    # 一轮从历史上整条消失——篡改的效果变成"证据无声地不存在"，比报错更糟。
    for failure in (failures or []):
        body.append(
            f'<div class="card err"><b>这一轮读不出来：'
            f'<span class="mono">{esc(failure.get("probe_id"))}</span></b>'
            f'<p>错误码 <code>{esc(failure.get("code"))}</code>　'
            f'{esc(failure.get("message"))}</p>'
            f'<p class="sub">内容不予展示——校验没过的记录不能拿来看数字。'
            f'详情见 <a href="/round?id={esc(failure.get("probe_id"))}">这一轮的错误页</a>。</p>'
            "</div>")
    if not rounds:
        body.append('<p class="sub">还没有任何轮次。</p>')
    else:
        body.append('<ul class="rounds">')
        for record in rounds:
            pid = esc(record["probe_id"])
            parent_tag = (f'<span class="tag">承自 {esc(record["parent_probe_id"])}</span>'
                          if record.get("parent_probe_id") else "")
            body.append(
                f'<li><a href="/round?id={pid}"><span class="mono">{pid}</span></a> '
                f'{parent_tag}<br>{esc(record.get("hypothesis_raw", ""))[:160]}'
                f'<br><span class="sub">{esc(record.get("recorded_at", ""))}　'
                f'{esc(record.get("count"))} 题　seed {esc(record.get("seed"))}　'
                f'{esc(record.get("row_count"))} 行　'
                f'人格 <span class="mono">{esc(record.get("persona_ref"))}</span></span></li>')
        body.append("</ul>")
    return _page("ABCR 最小快道", "".join(body))


#: 页面与 CLI 共用同一套指标口径与顺序，避免两处各写一份而悄悄漂移。
METRIC_LABELS = (
    ("is_correct", "通过率"),
    ("parse_ok", "非空输出率"),
    ("output_len_chars", "输出长度(字符)"),
    ("output_len_tokens", "输出长度(token)"),
    ("hedging_rate", "hedging 句率"),
    ("self_check_marker_rate", "自检标记句率"),
)


def render_round(record: dict[str, Any], rows: list[dict[str, Any]],
                 summary: dict[str, Any], paired: list[dict[str, Any]]) -> bytes:
    """题面已经由 `loop.paired_items()` 归并进 `paired`，这里不再单收 items。"""
    pid = esc(record["probe_id"])
    arms = summary["arms"]
    persona_arm = summary.get("persona_arm") or ""
    body = [
        f'<h1>轮次 <span class="mono">{pid}</span></h1>',
        '<p class="sub">',
        (f'承自 <a href="/round?id={esc(record["parent_probe_id"])}">'
         f'<span class="mono">{esc(record["parent_probe_id"])}</span></a>　'
         if record.get("parent_probe_id") else ""),
        f'<a href="/">← 全部轮次</a></p>',
        f'<form method="get" action="/new"><input type="hidden" name="from" value="{pid}">'
        "<button type=\"submit\">基于本轮新建</button></form>",

        "<h2>本轮输入</h2>",
        '<div class="card"><h3>假设 / 预测</h3>',
        f'<pre>{esc(record.get("hypothesis_raw", ""))}</pre>',
        f'<p class="sub">进入实验的单行形态：<span class="mono">'
        f'{esc(record.get("prediction", ""))}</span></p>',
        f'<h3>人格文本 <span class="tag">{esc(record.get("persona_ref"))}</span></h3>',
        f'<pre>{esc(record.get("persona_text", ""))}</pre></div>',

        "<h2>结果</h2>",
        # 夹具引擎跑出来的数字必须显眼地标出来。`request_fingerprint()` 用的是
        # 配置常量，夹具与真机会共用 probe_id——不挂这条红字，夹具结果就能冒充真机。
        (f'<div class="card err"><b>这一轮不是真实模型跑的</b>'
         f'<p>实际引擎 <span class="mono">{esc(record.get("model_profile"))}</span>，'
         f'配置期望 <span class="mono">{esc(record.get("configured_model_profile"))}</span>。'
         "数字仅供代码自测，不能当作任何观察结果。</p></div>"
         if record.get("fixture_engine") else ""),
        '<p class="sub">系统只展示观察到的数字，不判断人格理论成立或失败。</p>',
        '<div class="scroll"><table><thead><tr><th>指标</th>'
        f'<th class="num">vanilla</th><th class="num">{esc(persona_arm)}</th>'
        '<th class="num">差值 (persona − vanilla)</th></tr></thead><tbody>',
    ]
    for key, label in METRIC_LABELS:
        digits = 0 if key.startswith("output_len") else 3
        base = arms.get("vanilla", {}).get("metrics", {}).get(key)
        treat = arms.get(persona_arm, {}).get("metrics", {}).get(key)
        delta = summary.get("deltas", {}).get(key)
        body.append(
            f'<tr><th>{esc(label)}</th><td class="num">{esc(fmt(base, digits))}</td>'
            f'<td class="num">{esc(fmt(treat, digits))}</td>'
            f'<td class="num">{esc(fmt_delta(delta, digits))}</td></tr>')
    body.append("</tbody></table></div>")

    n_vanilla = arms.get("vanilla", {}).get("n", 0)
    n_persona = arms.get(persona_arm, {}).get("n", 0)
    body += [
        "<h2>运行事实</h2>",
        '<div class="card meta">',
        f'<div>题量　<b>{esc(record.get("count"))}</b></div>',
        f'<div>seed　<b>{esc(record.get("seed"))}</b></div>',
        f'<div>行数　<b>{esc(record.get("row_count"))}</b> '
        f'(每臂 vanilla {esc(n_vanilla)} / persona {esc(n_persona)})</div>',
        f'<div>墙钟耗时　<b>{esc(round(record.get("elapsed_ms", 0) / 1000, 1))} 秒</b></div>',
        f'<div>推理耗时合计　<b>{esc(round(record.get("latency_ms_total", 0) / 1000, 1))} 秒</b></div>',
        f'<div>模型 profile　<b>{esc(record.get("model_profile"))}</b></div>',
        f'<div>题集 family　<b>{esc(record.get("family"))}</b></div>',
        f'<div>开始　<b>{esc(record.get("started_at"))}</b></div>',
        f'<div>结束　<b>{esc(record.get("completed_at"))}</b></div>',
        f'<div>性质　<b>citable = {esc(str(record.get("citable")).lower())}　'
        f'{esc(NOT_CITABLE_LABEL)}</b></div>',
        "</div>",

        # 身份值单独成块：`.meta` 那个 13rem 的网格塞不下 64 位十六进制，
        # 而这些值的用处恰恰是**逐字比对**（对 `ollama show`、对 notebook 目录名、
        # 对 bundle 目录名），少一位就没法比。
        "<h3>身份（完整值 · 单击可全选复制）</h3>",
        '<div class="card">',
        f'<div>引擎指纹 sha256　{hash_cell(record.get("engine_fingerprint_sha256"))}</div>',
        f'<div>dev bundle id　{hash_cell(record.get("bundle_id"))}</div>',
        f'<div>bundle manifest hash　{hash_cell(record.get("bundle_manifest_hash"))}</div>',
        f'<div>bundle source hash　{hash_cell(record.get("bundle_source_hash"))}</div>',
        f'<div>数据集 sha256　{hash_cell(record.get("dataset_sha256"))}</div>',
        f'<div>split sha256　{hash_cell(record.get("split_sha256"))}</div>',
        f'<div>封印公钥指纹　{hash_cell(record.get("sealer_fingerprint"))}</div>',
        f'<div>请求指纹　{hash_cell(record.get("request_fingerprint"))}</div>',
        "</div>",
        "<h2>逐题原始结果</h2>",
    ]
    for index, entry in enumerate(paired, start=1):
        body.append('<div class="card">')
        body.append(f'<h3>{index}. <span class="mono">{esc(entry["item_id"])}</span> '
                    f'<span class="tag">{esc(entry.get("check_type"))}</span></h3>')
        prompt = entry.get("prompt") or "（题面不可读：bundle 校验未通过）"
        body.append(f"<pre>{esc(prompt)}</pre>")
        body.append('<div class="scroll"><table><thead><tr><th>臂</th><th>原始输出</th>'
                    '<th class="num">判分</th><th class="num">长度</th>'
                    '<th class="num">hedging</th><th class="num">自检</th>'
                    "<th>row hash</th></tr></thead><tbody>")
        for arm_id in record.get("arm_ids", []):
            arm = entry["arms"].get(arm_id)
            if arm is None:
                continue
            metrics = arm.get("metrics", {})
            body.append(
                f'<tr><th>{esc(arm_id)}</th>'
                f'<td><pre>{esc(arm.get("output_text", ""))}</pre></td>'
                f'<td class="num">{esc(metrics.get("is_correct"))}</td>'
                f'<td class="num">{esc(metrics.get("output_len_chars"))}</td>'
                f'<td class="num">{esc(fmt(metrics.get("hedging_rate")))}</td>'
                f'<td class="num">{esc(fmt(metrics.get("self_check_marker_rate")))}</td>'
                f'<td>{hash_cell(arm.get("row_hash"))}</td></tr>')
        body.append("</tbody></table></div></div>")
    return _page(f"轮次 {record['probe_id']}", "".join(body))


def render_running(probe_id: str, job: Job) -> bytes:
    body = (
        f'<h1>实验运行中</h1><p class="sub">轮次 <span class="mono">{esc(probe_id)}</span>'
        f"　已用 {esc(job.elapsed_s)} 秒　本页每 3 秒自动刷新</p>"
        '<div class="card">同一时刻只跑一轮实验（冻结 profile 的 '
        "<code>max_concurrency: 1</code>）。20 题两臂通常需要 1–3 分钟。<br>"
        "重复提交同一份请求不会再造一轮实验，直接回到这一页。</div>"
        '<p><a href="/">← 全部轮次</a></p>')
    return _page("运行中", body, refresh=3)


def render_failed(probe_id: str, job: Job) -> bytes:
    body = (
        f'<h1>实验已停止</h1><p class="sub">轮次 <span class="mono">{esc(probe_id)}</span></p>'
        f'<div class="card err"><b>{esc(job.error_code)}</b><pre>{esc(job.error)}</pre>'
        "<p>快道在这种情况下**明确停止**：不下载模型、不换模型、不上云、"
        "不降级为夹具数据。修好原因后重新提交同一份请求即可。</p></div>"
        '<p><a href="/">← 全部轮次</a></p>')
    return _page("实验已停止", body)


def render_error(message: str, detail: str = "", *, code: str = "",
                 title: str = "无法提交") -> bytes:
    body = (f"<h1>{esc(title)}</h1><div class=\"card err\">"
            + (f'<p><code>{esc(code)}</code></p>' if code else "")
            + f"<b>{esc(message)}</b>"
            + (f"<pre>{esc(detail)}</pre>" if detail else "")
            + '</div><p><a href="/">← 返回</a></p>')
    return _page(title, body)


#: 校验失败的阶段 → 给人的一句话解释。三个阶段各自意味着不同的事，
#: 混成一句"读取失败"会让人不知道该去查哪里。
_BROKEN_STAGE_NOTES = {
    "轮次记录": "轮次文件里的假设、人格与汇总数字和它自带的 record_hash 对不上，"
            "说明 lab/runs/rounds/ 被人动过。",
    "notebook 行": "模型的原始输出行在 ProbeNotebook 里校验没过（被改过或被清理过）。"
                 "原始行是这一轮唯一的一手证据，它不可信，整轮就不可信。",
    "dev bundle": "题面所在的 dev bundle 封印验签没过。封印的科学语义是"
                  "「防 holdout 冒充 dev」——验不过就无法证明页面上的题目确实来自 dev，"
                  "所以这一轮的内容一律不展示。",
}


def render_broken_round(probe_id: str, stage: str, code: str, message: str,
                        detail: Any = None) -> bytes:
    """校验失败的轮次的**人类错误页**：说清哪一步、什么码、怎么办。

    这一页存在的理由很具体：上一版这三种失败都以未捕获异常的形式直穿
    `socketserver`，人看到的是 `curl: (52) Empty reply from server`——
    一个既不说发生了什么、也不说该做什么的空回复。fail-closed 不等于失联。
    """
    note = _BROKEN_STAGE_NOTES.get(stage, "")
    body = (
        f'<h1>这一轮读不出来</h1>'
        f'<p class="sub">轮次 <span class="mono">{esc(probe_id)}</span>　'
        f'失败于：{esc(stage)}校验</p>'
        f'<div class="card err"><p><code>{esc(code)}</code></p>'
        f'<b>{esc(message)}</b>'
        + (f"<pre>{esc(detail)}</pre>" if detail else "")
        + (f"<p>{esc(note)}</p>" if note else "")
        + "<p>快道在这里<b>明确停止</b>：不展示这一轮的任何数字，也不拿旧内容"
          "顶替——校验没过的记录不能当作观察结果。别的轮次不受影响。</p></div>"
        '<p><a href="/">← 全部轮次</a></p>')
    return _page(f"轮次 {probe_id} 读不出来", body)


# ────────────────────────── HTTP ──────────────────────────
class FastlaneHandler(BaseHTTPRequestHandler):
    server_version = "ABCRFastlane/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        print(f"[fastlane] {self.address_string()} {format % args}", flush=True)

    # ---- 兜底 ----
    def _guard(self, handler: Any, *args: Any) -> None:
        """跑一个路由处理器；任何漏网异常都变成错误页，而不是断开的连接。

        `socketserver` 对未捕获异常的处理是打一屏 traceback 然后关掉连接，
        客户端只看到 `curl: (52) Empty reply from server`。那既不是"清楚的
        错误"，也不是"明确停止"——只是失联。

        **已经发出响应之后不再兜底**：那时补发第二个响应头只会把响应流写坏。
        """
        self._responded = False
        try:
            handler(*args)
        except (FastlaneError, ContractError) as exc:
            self._fail(getattr(exc, "code", type(exc).__name__),
                       getattr(exc, "message", str(exc)), str(getattr(exc, "detail", "") or ""))
        except Exception as exc:  # noqa: BLE001 - 页面必须显示原因，不能变成空回复
            self._fail(type(exc).__name__, str(exc))

    def _fail(self, code: str, message: str, detail: str = "") -> None:
        self.log_message("未预期的失败 [%s] %s", code, message)
        if getattr(self, "_responded", False):
            return          # 响应已经发出去了，只能记日志，不能再写一个头
        try:
            self._send(render_error(message, detail, code=code, title="快道停止"),
                       status=500)
        except OSError:      # 连接已经断了：没有可送达的对象，静默即可
            pass

    # ---- 输出 ----
    def _send(self, payload: bytes, status: int = 200,
              content_type: str = "text/html; charset=utf-8") -> None:
        self._responded = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        # 本机页面不需要被任何东西嵌套或探测。
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, location: str) -> None:
        self._responded = True
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- 路由 ----
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
        self._guard(self._route_get)

    def _route_get(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/":
            self._get_index()
        elif parsed.path == "/new":
            self._get_new(query)
        elif parsed.path == "/round":
            self._get_round(query)
        elif parsed.path == "/healthz":
            self._send(b"ok", content_type="text/plain; charset=utf-8")
        else:
            self._send(render_error("没有这个页面"), status=404)

    def _get_index(self) -> None:
        rounds, failures = loop.scan_rounds()
        self._send(render_index(rounds, failures=failures))

    def _get_new(self, query: dict[str, list[str]]) -> None:
        source = (query.get("from") or [""])[0]
        rounds, failures = loop.scan_rounds()
        try:
            prefill = loop.revise_spec(source) if source else None
        except FastlaneError as exc:
            # "没有这一轮" 是 404；"这一轮校验没过" 不是——记录在那儿，只是不可信。
            # 两者混成 404 会让人以为文件丢了，跑去重建，而真正该做的是查谁动了它。
            if exc.code == "round_not_found":
                self._send(render_error(exc.message, source, code=exc.code), status=404)
            else:
                self._send(render_broken_round(source, "轮次记录", exc.code, exc.message,
                                               exc.detail or None), status=500)
            return
        self._send(render_index(rounds, prefill=prefill, failures=failures))

    def _get_round(self, query: dict[str, list[str]]) -> None:
        probe_id = (query.get("id") or [""])[0]
        # 三处 try 的类型都是 `FastlaneError` 优先：`loop` 已经在核心边界上把
        # `ContractError` 翻译过一次，这里只 catch `ContractError` 等于什么都没 catch。
        # `ContractError` 仍然并列写着，因为翻译层将来可能漏掉新的核心异常。
        try:
            record = loop.read_round(probe_id) if probe_id else None
        except (FastlaneError, ContractError) as exc:
            self._send(render_broken_round(probe_id, "轮次记录",
                                           getattr(exc, "code", "round_unreadable"),
                                           getattr(exc, "message", str(exc)),
                                           getattr(exc, "detail", None) or None), status=500)
            return
        if record is None:
            job = _job(probe_id)
            if job is None:
                self._send(render_error("没有这一轮", probe_id, code="round_not_found"),
                           status=404)
            elif job.state == "failed":
                self._send(render_failed(probe_id, job), status=200)
            else:
                self._send(render_running(probe_id, job))
            return
        try:
            rows = loop.round_rows(record)
        except (FastlaneError, ContractError) as exc:
            self._send(render_broken_round(probe_id, "notebook 行",
                                           getattr(exc, "code", "row_unreadable"),
                                           getattr(exc, "message", str(exc)),
                                           getattr(exc, "detail", None) or None), status=500)
            return
        try:
            items = loop.load_items_for(record)
        except (FastlaneError, ContractError, OSError) as exc:
            # 上一版这里把失败降级成"题面留空、照样出页面"。封印验签的科学语义是
            # 「防 holdout 冒充 dev」——验不过还把两臂输出摆出来，等于展示一组
            # **无法证明来自 dev** 的结果。fail-closed 方向要求整轮不展示。
            self._send(render_broken_round(probe_id, "dev bundle",
                                           getattr(exc, "code", type(exc).__name__),
                                           getattr(exc, "message", str(exc)),
                                           getattr(exc, "detail", None) or None), status=500)
            return
        summary = loop.summarize(record, rows)
        paired = loop.paired_items(record, rows, items)
        self._send(render_round(record, rows, summary, paired))

    def do_POST(self) -> None:  # noqa: N802
        self._guard(self._route_post)

    def _route_post(self) -> None:
        if urlparse(self.path).path != "/run":
            self._send(render_error("没有这个页面"), status=404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(render_error("请求体长度非法"), status=400)
            return
        if length <= 0 or length > _MAX_BODY_BYTES:
            self._send(render_error(f"请求体长度非法或超过 {_MAX_BODY_BYTES} 字节"), status=400)
            return
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        form = parse_qs(raw, keep_blank_values=True)

        def field_of(name: str, default: str = "") -> str:
            return (form.get(name) or [default])[0]

        try:
            spec = loop.build_spec(
                hypothesis=field_of("hypothesis"),
                persona_text=field_of("persona_text"),
                count=field_of("count", str(DEFAULT_ITEMS)),
                seed=field_of("seed", str(DEFAULT_SEED)),
                parent_probe_id=field_of("parent_probe_id") or None,
            )
        except FastlaneError as exc:
            self._send(render_error(exc.message, str(exc.detail or ""), code=exc.code),
                       status=400)
            return
        try:
            probe_id, _state = start_round(spec)
        except (FastlaneError, ContractError) as exc:
            # 引擎在提交这一刻构造，profile 对不上就当场说清楚，
            # 而不是先造一个注定失败的轮次再让人去结果页看错误。
            # 数据身份闸（split / dataset 与仓内冻结件不符）也在这条路上报出来。
            self._send(render_error(getattr(exc, "message", str(exc)),
                                    str(getattr(exc, "detail", "") or ""),
                                    code=getattr(exc, "code", type(exc).__name__),
                                    title="无法启动实验"), status=503)
            return
        self._redirect(f"/round?id={probe_id}")


def bind_server(host: str, port: int, *,
                fallback_to_ephemeral: bool = False) -> ThreadingHTTPServer:
    """绑一个回环端口，返回已绑定的服务器。**所有绑定都要走这里。**

    默认端口与显式端口是两回事
    ------------------------
    `DEFAULT_PORT` 只是"没说的时候用哪个"的方便值，本机上完全可能已经被别的
    长期服务占着（实测 8787 被 AILH BOSS 控制台占用，8788 被另一个服务占用）。
    这种时候无参数入口——尤其是 Finder 双击那条路——不该以一屏
    `OSError: [Errno 48] Address already in use` 收场：人只是想打开页面，
    而快道对"用哪个端口"其实没有任何要求。所以默认端口被占时**让位**，
    改用系统分配的临时端口，并把真实 URL 打出来。

    但 `--port 8787` 是人**明确表达的意图**，被占时必须当场报错。
    悄悄换到别的端口，会让指定了端口的人对着一个错误的地址干等——
    "帮了倒忙"比"没帮上忙"更难查。所以只有 `fallback_to_ephemeral=True`
    （即调用方知道这个端口是默认值而非人选的）才让位。

    回环边界也收在这里：绑定只有这一个入口，边界就不可能被某条路径绕开。
    """
    if host not in ("127.0.0.1", "localhost", "::1"):
        # 快道没有任何鉴权，暴露到回环之外等于把本机模型交出去。
        raise FastlaneError("host_not_loopback",
                            f"快道页面只允许绑回环地址，收到 {host!r}")
    try:
        return ThreadingHTTPServer((host, port), FastlaneHandler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise FastlaneError("port_unavailable",
                                f"绑不上 {host}:{port}：{exc}",
                                {"host": host, "port": port,
                                 "errno": exc.errno}) from exc
        if not fallback_to_ephemeral:
            raise FastlaneError(
                "port_in_use",
                f"{host}:{port} 已被别的程序占用。这个端口是你显式指定的，"
                "所以快道不替你换——要么腾出它，要么改用 `--port 0`（系统分配一个空闲端口）。",
                {"host": host, "port": port}) from exc
        print(f"[fastlane] {host}:{port} 已被别的程序占用，改用系统分配的空闲端口",
              flush=True)
        try:
            return ThreadingHTTPServer((host, 0), FastlaneHandler)
        except OSError as exc2:      # pragma: no cover - 回环上连临时端口都拿不到
            raise FastlaneError("port_unavailable",
                                f"{host}:{port} 被占用，改用临时端口也没成功：{exc2}",
                                {"host": host, "port": port}) from exc2


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, *,
          open_browser: bool = True, fallback_to_ephemeral: bool = False) -> None:
    httpd = bind_server(host, port, fallback_to_ephemeral=fallback_to_ephemeral)
    # URL 一律按**实际绑到的**端口拼。让位之后还打印 8787，等于把人送到别人家门口。
    url = f"http://{host}:{httpd.server_address[1]}/"
    print(f"[fastlane] {NOT_CITABLE_LABEL}", flush=True)
    print(f"[fastlane] 页面已启动: {url}", flush=True)
    print(f"[fastlane] 数据目录: {loop.lab_root()}", flush=True)
    print("[fastlane] Ctrl-C 停止", flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[fastlane] 已停止", flush=True)
    finally:
        httpd.server_close()
