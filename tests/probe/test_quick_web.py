"""最小快道页面（`lab/fastlane/web.py`）的作者测试。

页面层最要紧的两件事：
1. **转义** —— 人格文本和模型原始输出都是不可信文本，进 HTML 前必须过 `esc()`；
2. **真的能用** —— 所以这里起一个真实的 `ThreadingHTTPServer`，用真实 HTTP
   请求走完"提交 → 等待 → 看结果 → 复制 → 再跑"，而不是只对着函数断言。

模型仍由 `FakeProbeEngine` 顶替（页面测试不该依赖 Ollama 在不在）；
真机验收另有其人，两者不互相冒充。
"""
from __future__ import annotations

import contextlib
import json
import shutil
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from abcr.probe.engine import FakeProbeEngine

from lab.fastlane import loop, web

INJECTION = '<script>alert("xss")</script><img src=x onerror=alert(1)>'
PERSONA = f"你是一位谨慎的助手。{INJECTION}"


@pytest.fixture()
def lab(tmp_path, monkeypatch):
    monkeypatch.setenv("ABCR_FASTLANE_ROOT", str(tmp_path / "runs"))
    # 页面测试不依赖 Ollama 在不在；真机验收另走一条路。
    monkeypatch.setattr(loop, "make_engine", lambda: FakeProbeEngine())
    web._JOBS.clear()
    yield tmp_path
    web._JOBS.clear()


@pytest.fixture()
def server(lab):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.FastlaneHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _get(url: str, *, allow_redirects: bool = True):
    request = urllib.request.Request(url, method="GET")
    opener = (urllib.request.build_opener() if allow_redirects
              else urllib.request.build_opener(_NoRedirect))
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8"), response.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8"), exc.headers


def _post(url: str, fields: dict[str, str]):
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, response.headers.get("Location", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Location", "")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _wait_for_round(base: str, location: str, timeout: float = 30.0) -> str:
    """轮询结果页，直到实验跑完。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _status, html, _headers = _get(base + location)
        if "实验运行中" not in html:
            return html
        time.sleep(0.15)
    raise AssertionError("实验没有在超时内完成")


# ───────────────────────── 转义 ─────────────────────────
def test_esc_neutralizes_markup_and_quotes():
    assert web.esc("<b>") == "&lt;b&gt;"
    assert web.esc('a"b') == "a&quot;b"
    assert web.esc("a'b") == "a&#x27;b"
    assert web.esc(None) == ""


def test_persona_and_model_output_are_escaped_on_the_result_page(lab):
    """人格文本与模型输出都进页面。漏一个转义，页面结构就被内容掀翻。"""
    spec = loop.build_spec(hypothesis=f"假设里也有 {INJECTION}", persona_text=PERSONA,
                           count=1, seed=1)
    record = loop.run_round(spec, engine=FakeProbeEngine())
    rows = loop.round_rows(record)
    # 把危险文本也塞进模型输出侧，模拟模型真的吐出 HTML 的情形。
    rows[0] = dict(rows[0], output_text=INJECTION)
    summary = loop.summarize(record, rows)
    paired = loop.paired_items(record, rows, loop.load_items_for(record))
    page = web.render_round(record, rows, summary, paired).decode("utf-8")

    # 安全性质的正确表述不是"页面里不许出现 onerror 这几个字"——原文本来就该看得见。
    # 而是：注入文本里的 `<` 一个都没能以**未转义**形态进入页面，于是浏览器
    # 不会把它们当成标签。`onerror=alert(1)` 留在 <pre> 里是纯文本，无害。
    for opener in ("<script", "<img", "<iframe", "<svg"):
        assert opener not in page.lower()
    assert "&lt;script&gt;" in page          # 原文仍然看得见，只是被中和了
    assert "&lt;img src=x onerror=alert(1)&gt;" in page


def test_index_escapes_prefilled_values(lab):
    spec = loop.build_spec(hypothesis=f"假设 {INJECTION}", persona_text=PERSONA, count=1, seed=1)
    page = web.render_index([], prefill=spec).decode("utf-8")
    assert "<script>alert" not in page and "&lt;script&gt;" in page


def test_round_listing_escapes_hypothesis(lab):
    record = loop.run_round(
        loop.build_spec(hypothesis=f"列表里的 {INJECTION}", persona_text=PERSONA,
                        count=1, seed=1),
        engine=FakeProbeEngine())
    page = web.render_index([record]).decode("utf-8")
    assert "<script>alert" not in page and "&lt;script&gt;" in page


def test_fixture_run_is_flagged_on_the_page(lab):
    """夹具跑的数字必须在页面上挂红字，不能看起来像真机结果。"""
    record = loop.run_round(
        loop.build_spec(hypothesis="夹具轮", persona_text="p", count=1, seed=1),
        engine=FakeProbeEngine())
    rows = loop.round_rows(record)
    page = web.render_round(record, rows, loop.summarize(record, rows),
                            loop.paired_items(record, rows, {})).decode("utf-8")
    assert "这一轮不是真实模型跑的" in page


def test_every_page_carries_the_not_citable_banner(lab):
    record = loop.run_round(
        loop.build_spec(hypothesis="横幅", persona_text="p", count=1, seed=1),
        engine=FakeProbeEngine())
    rows = loop.round_rows(record)
    pages = [
        web.render_index([record]),
        web.render_round(record, rows, loop.summarize(record, rows),
                         loop.paired_items(record, rows, {})),
        web.render_running("fl-x", web.Job("fl-x")),
        web.render_failed("fl-x", web.Job("fl-x", state="failed", error="boom")),
        web.render_error("bad"),
    ]
    for page in pages:
        assert loop.NOT_CITABLE_LABEL in page.decode("utf-8")


# ───────────────────────── 真实 HTTP ─────────────────────────
def test_full_journey_submit_view_copy_rerun(server, lab):
    """走完人真正会走的那条路，全程真实 HTTP。"""
    base = server
    status, home, _ = _get(base + "/")
    assert status == 200 and "新实验" in home

    status, location = _post(base + "/run", {
        "hypothesis": "第一轮假设\n分两行写", "persona_text": PERSONA,
        "count": "2", "seed": "1", "parent_probe_id": ""})
    # 页面拿到的是 `fx-` 而不是 `fl-`：夹具轮落在夹具命名空间，
    # 提交路径与实际执行路径算出的是同一个 probe_id（两处不能各算各的）。
    assert status == 303 and location.startswith(f"/round?id={loop.FIXTURE_PREFIX}")
    page = _wait_for_round(base, location)
    assert "逐题原始结果" in page and loop.NOT_CITABLE_LABEL in page
    assert "第一轮假设 / 分两行写" in page       # 多行折成单行后进了实验
    first_id = location.split("id=")[1]

    # 复制上一轮：预填、可改
    status, prefilled, _ = _get(f"{base}/new?from={first_id}")
    assert status == 200 and "基于轮次" in prefilled and "第一轮假设" in prefilled

    # 改假设再跑 → 新轮次，旧轮不变
    status, location2 = _post(base + "/run", {
        "hypothesis": "第二轮假设", "persona_text": PERSONA,
        "count": "2", "seed": "1", "parent_probe_id": first_id})
    assert status == 303
    second_id = location2.split("id=")[1]
    assert second_id != first_id
    page2 = _wait_for_round(base, location2)
    assert first_id in page2                       # 结果页显示血缘

    status, page1_again, _ = _get(f"{base}/round?id={first_id}")
    assert status == 200 and "第一轮假设 / 分两行写" in page1_again

    # 重开入口（新 server 对象、同一数据目录）后两轮仍在
    assert {r["probe_id"] for r in loop.list_rounds()} == {first_id, second_id}
    _status, home_again, _ = _get(base + "/")
    assert first_id in home_again and second_id in home_again


def test_resubmitting_the_same_form_does_not_create_a_second_round(server, lab):
    fields = {"hypothesis": "同一份请求", "persona_text": PERSONA,
              "count": "1", "seed": "1", "parent_probe_id": ""}
    status, first = _post(server + "/run", fields)
    assert status == 303
    _wait_for_round(server, first)
    status, second = _post(server + "/run", dict(fields))
    assert status == 303 and second == first
    assert len(loop.list_rounds()) == 1


def test_invalid_form_input_is_refused_with_a_reason(server, lab):
    for bad, expect in (
        ({"hypothesis": "", "persona_text": "p", "count": "1", "seed": "1"}, 400),
        ({"hypothesis": "h", "persona_text": "", "count": "1", "seed": "1"}, 400),
        ({"hypothesis": "h", "persona_text": "p", "count": "0", "seed": "1"}, 400),
        ({"hypothesis": "h", "persona_text": "p", "count": "21", "seed": "1"}, 400),
        ({"hypothesis": "h", "persona_text": "p", "count": "1", "seed": "x"}, 400),
    ):
        status, _ = _post(server + "/run", bad)
        assert status == expect
    assert loop.list_rounds() == []


def test_unknown_paths_and_rounds_are_404(server, lab):
    assert _get(server + "/nope")[0] == 404
    assert _get(server + "/round?id=fl-nonexistent")[0] == 404
    assert _get(server + "/new?from=fl-nonexistent")[0] == 404


def test_healthz_and_security_headers(server, lab):
    status, body, headers = _get(server + "/healthz")
    assert status == 200 and body == "ok"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("X-Content-Type-Options") == "nosniff"


def test_oversized_body_is_refused(server, lab):
    body = urllib.parse.urlencode({"hypothesis": "h", "persona_text": "p" * 600_000,
                                   "count": "1", "seed": "1"}).encode("utf-8")
    request = urllib.request.Request(server + "/run", data=body, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=30) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except urllib.error.URLError:
        # 服务端在读完 body 前就回了 400 并关闭连接，这同样是"拒绝"。
        status = 400
    assert status == 400


def test_serve_refuses_a_non_loopback_bind():
    """快道没有任何鉴权，绑到回环之外等于把本机模型交出去。"""
    with pytest.raises(loop.FastlaneError) as excinfo:
        web.serve("0.0.0.0", 0, open_browser=False)
    assert excinfo.value.code == "host_not_loopback"
    # 让位那条路也不能成为绕开回环边界的口子。
    with pytest.raises(loop.FastlaneError) as excinfo2:
        web.bind_server("0.0.0.0", 0, fallback_to_ephemeral=True)
    assert excinfo2.value.code == "host_not_loopback"


# ────────── 默认端口被占用时，无参数入口仍要起得来（V4 阻断）──────────
@contextlib.contextmanager
def _squatter():
    """占住一个回环端口，模拟"本机已有长期服务在用这个口"。

    用临时端口而不是真的去抢 8787：测试不该依赖也不该干扰本机上正在跑的服务。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        yield sock.getsockname()[1]


def test_the_no_argument_entry_still_starts_when_the_default_port_is_taken():
    """真实事故：8787 被 AILH BOSS 控制台长期占用，无参数入口以
    `OSError: [Errno 48] Address already in use` 一屏 traceback 退出。

    人只是想打开页面，快道对"用哪个端口"其实没有任何要求——所以让位，
    并且**按实际绑到的端口**给出 URL。
    """
    with _squatter() as taken:
        httpd = web.bind_server(web.DEFAULT_HOST, taken, fallback_to_ephemeral=True)
        try:
            host, port = httpd.server_address[0], httpd.server_address[1]
            assert port != taken and port > 0
            assert host == "127.0.0.1"          # 让位之后仍然只在回环上
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                status, body, _ = _get(f"http://127.0.0.1:{port}/healthz")
                assert status == 200 and body == "ok"
                assert _get(f"http://127.0.0.1:{port}/")[0] == 200
            finally:
                httpd.shutdown()
                thread.join(timeout=5)
        finally:
            httpd.server_close()


def test_an_explicitly_requested_port_is_never_silently_moved():
    """`--port 8787` 是人明确表达的意图。悄悄换到别处，人会对着错误地址干等。"""
    with _squatter() as taken:
        with pytest.raises(loop.FastlaneError) as excinfo:
            web.bind_server(web.DEFAULT_HOST, taken, fallback_to_ephemeral=False)
    assert excinfo.value.code == "port_in_use"
    assert excinfo.value.detail["port"] == taken
    assert "--port 0" in excinfo.value.message      # 告诉人下一步能做什么


def test_the_cli_only_enables_the_fallback_when_no_port_was_given(monkeypatch):
    """闸门在 CLI 这一层：无参数入口开让位，显式 `--port` 不开。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "probe_quick_loop_ports", loop.REPO_ROOT / "scripts" / "probe_quick_loop.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    captured: dict[str, object] = {}
    monkeypatch.setattr(cli.web, "serve",
                        lambda host, port, **kw: captured.update(host=host, port=port, **kw))

    cli.main([])                       # ← 无参数入口 / Finder 双击走的正是这条
    assert captured == {"host": web.DEFAULT_HOST, "port": web.DEFAULT_PORT,
                        "open_browser": True, "fallback_to_ephemeral": True}

    captured.clear()
    cli.main(["serve", "--port", "8787", "--no-browser"])
    assert captured["port"] == 8787
    assert captured["fallback_to_ephemeral"] is False      # 显式端口不让位


# ────────── 验签失败必须是一页人话，不是空回复（V1 阻断级缺陷）──────────
def _make_round(hypothesis: str = "一轮实验"):
    spec = loop.build_spec(hypothesis=hypothesis, persona_text=PERSONA, count=1, seed=1)
    return loop.run_round(spec, engine=FakeProbeEngine())


def _tamper_round_file(probe_id: str) -> None:
    target = loop.paths().round_file(probe_id)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["count"] = 999
    target.write_text(json.dumps(payload), encoding="utf-8")


def _assert_human_error_page(status: int, body: str, *, code: str) -> None:
    """一页"清楚的人类错误页"至少要满足这几条。

    最要紧的是**它必须存在**：上一版这里是 `curl: (52) Empty reply from server`
    ——连接被丢弃，客户端拿到零字节。所以先断言 body 非空且是完整 HTML。
    """
    assert status == 500
    assert body and "</html>" in body                    # 不是空回复，是一整页
    assert code in body                                  # 错误码可见
    assert loop.NOT_CITABLE_LABEL in body                # 横幅仍在
    assert "读不出来" in body or "快道停止" in body


def test_tampered_round_detail_is_a_human_error_page_not_an_empty_reply(server, lab):
    record = _make_round("会被改的一轮")
    _tamper_round_file(record["probe_id"])
    status, body, _ = _get(f"{server}/round?id={record['probe_id']}")
    _assert_human_error_page(status, body, code="round_tampered")
    assert "会被改的一轮" not in body          # 校验没过的记录，内容一律不展示


def test_missing_notebook_row_is_a_human_error_page(server, lab):
    record = _make_round("行会被删的一轮")
    shutil.rmtree(loop.paths().notebook / "rows" / record["row_hashes"][0])
    status, body, _ = _get(f"{server}/round?id={record['probe_id']}")
    _assert_human_error_page(status, body, code="row_missing")


def test_tampered_notebook_row_is_a_human_error_page(server, lab):
    record = _make_round("行会被改的一轮")
    target = loop.paths().notebook / "rows" / record["row_hashes"][0] / "row.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["output_text"] = "被人改过的输出"
    target.write_text(json.dumps(payload), encoding="utf-8")
    status, body, _ = _get(f"{server}/round?id={record['probe_id']}")
    _assert_human_error_page(status, body, code="row_probe_row_tampered")
    assert "被人改过的输出" not in body


def test_forged_bundle_seal_is_a_human_error_page_and_withholds_the_round(server, lab):
    """封印验签没过 → 整轮不展示。

    fail-closed 方向：封印的科学语义是"防 holdout 冒充 dev"。验不过还把两臂
    输出摆出来，等于展示一组**无法证明来自 dev** 的结果。
    """
    record = _make_round("封印会被伪造的一轮")
    seal = loop.paths().bundles / record["bundle_id"] / "seal.json"
    seal.write_text(json.dumps({"forged": True}), encoding="utf-8")
    status, body, _ = _get(f"{server}/round?id={record['probe_id']}")
    assert status == 500 and "</html>" in body
    assert "bundle_" in body and "dev bundle" in body
    assert "封印会被伪造的一轮" not in body      # 数字与原文都不展示


def test_history_page_shows_broken_rounds_instead_of_hiding_them(server, lab):
    """坏轮从历史页消失 = 篡改的效果是"证据无声地不存在"，比报错更糟。"""
    good = _make_round("好轮")
    bad = _make_round("坏轮")
    _tamper_round_file(bad["probe_id"])
    status, body, _ = _get(server + "/")
    assert status == 200
    assert good["probe_id"] in body                 # 好轮照常可见
    assert bad["probe_id"] in body                  # 坏轮**没有被藏起来**
    assert "round_tampered" in body and "这一轮读不出来" in body
    assert "坏轮" not in body                        # 但它的内容不展示


def test_new_from_a_tampered_round_is_not_disguised_as_a_404(server, lab):
    """"没有这一轮"和"这一轮不可信"是两件事，混成 404 会把人引去重建数据。"""
    record = _make_round("要复制的一轮")
    _tamper_round_file(record["probe_id"])
    status, body, _ = _get(f"{server}/new?from={record['probe_id']}")
    _assert_human_error_page(status, body, code="round_tampered")
    assert _get(f"{server}/new?from=fx-really-not-here")[0] == 404


def test_an_unexpected_handler_failure_becomes_a_page_not_a_dropped_connection(server, lab,
                                                                              monkeypatch):
    """兜底 `_guard()`：漏网异常也必须落成一页错误，而不是断开的连接。"""
    def boom():
        raise RuntimeError("路由里冒出来的意外")

    monkeypatch.setattr(loop, "scan_rounds", boom)
    status, body, _ = _get(server + "/")
    assert status == 500 and "</html>" in body
    assert "RuntimeError" in body and "路由里冒出来的意外" in body


# ────────────────── 身份值必须完整可复制（V1 阻断级缺陷）──────────────────
def test_result_page_shows_complete_64_char_identities(server, lab):
    """截断过的指纹没法逐字比对，而逐字比对正是它们存在的全部理由。"""
    record = _make_round("看完整指纹")
    status, body, _ = _get(f"{server}/round?id={record['probe_id']}")
    assert status == 200
    for field in ("engine_fingerprint_sha256", "bundle_id", "bundle_manifest_hash",
                  "bundle_source_hash", "dataset_sha256", "split_sha256",
                  "sealer_fingerprint", "request_fingerprint"):
        value = record[field]
        assert len(value) == 64, field
        assert value in body, f"{field} 的完整 64 位不在页面上"
    for row_hash in record["row_hashes"]:
        assert len(row_hash) == 64
        assert row_hash in body
    # 可复制：身份值用 `user-select:all` 的容器包着，单击即全选。
    assert 'class="hash"' in body and "user-select:all" in body


def test_no_identity_is_rendered_truncated(server, lab):
    """回归钉子：任何身份值都不许再以 `前缀…` 的形态出现在页面上。"""
    record = _make_round("不许再截断")
    _status, body, _ = _get(f"{server}/round?id={record['probe_id']}")
    for value in [record["engine_fingerprint_sha256"], record["bundle_id"],
                  record["dataset_sha256"], record["split_sha256"],
                  *record["row_hashes"]]:
        for cut in (16, 32):
            assert f"{value[:cut]}…" not in body, f"{value[:cut]}… 仍以截断形态出现"


# ────────── 坏数据下不得复用旧轮（B1）· 坏记录不得拖垮首页（B2）──────────
def _post_with_body(url: str, fields: dict[str, str]):
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def test_posting_a_request_already_run_under_a_drifted_split_is_refused(server, lab,
                                                                       tmp_path, monkeypatch):
    """真 HTTP：坏 split 下重提同一份表单，不能再回到那一轮，要当场停止。"""
    from lab.fastlane import split_adapter as SA

    copy = tmp_path / "ifeval_zh_v1.json"
    shutil.copyfile(loop.SPLIT_PATH, copy)
    monkeypatch.setattr(SA, "FROZEN_SPLIT_PATH", copy)
    monkeypatch.setattr(loop, "SPLIT_PATH", copy)
    copy.write_bytes(copy.read_bytes() + b"\n")            # 坏 split 就位

    fields = {"hypothesis": "坏 split 下跑过的一轮", "persona_text": PERSONA,
              "count": "1", "seed": "1", "parent_probe_id": ""}
    spec = loop.build_spec(hypothesis=fields["hypothesis"], persona_text=PERSONA,
                           count=1, seed=1)
    # 先造出"当初这份 split 还算数时"产出的那一轮：只在创建那一刻把字节坐标
    # 临时指向它（等价于 V1 当时的处境），退出后它就成了漂移过的文件。
    with monkeypatch.context() as m:
        m.setattr(SA, "FROZEN_SPLIT_SHA256", loop.sha256(copy.read_bytes()))
        made = loop.run_round(spec, engine=FakeProbeEngine())
        assert loop.run_round(spec, engine=FakeProbeEngine())["reused"] is True

    status, body = _post_with_body(server + "/run", fields)
    assert status == 503, "坏 split 下重提表单竟然被放行了"
    assert "split_bytes_not_frozen" in body
    assert "</html>" in body and loop.NOT_CITABLE_LABEL in body
    # 读路径不受影响：那一轮仍然打得开（它是历史事实，不该因今天的数据坏了而消失）
    assert _get(f"{server}/round?id={made['probe_id']}")[0] == 200


@pytest.mark.parametrize("payload,code", [("[]", "round_malformed"),
                                          ("{}", "round_incomplete")],
                         ids=["顶层是列表", "空对象"])
def test_a_malformed_round_does_not_take_down_the_history_page(server, lab, payload, code):
    """旧版本上这两种形状分别让首页 500（AttributeError / KeyError），
    并且**三条轮次全部从首页消失**。现在首页必须 200，好轮照列，坏轮带错误码露出来。
    """
    good_a = _make_round("好轮一")
    good_b = _make_round("好轮二")
    bad = _make_round("会被写坏的一轮")
    loop.paths().round_file(bad["probe_id"]).write_text(payload, encoding="utf-8")

    status, body, _ = _get(server + "/")
    assert status == 200, "一条文件写坏，整个历史页就打不开了"
    assert good_a["probe_id"] in body and good_b["probe_id"] in body
    assert bad["probe_id"] in body, "坏轮被藏起来了"
    assert code in body                                   # 稳定错误码，不是裸异常
    assert "AttributeError" not in body and "KeyError" not in body

    # 好轮详情照常
    assert _get(f"{server}/round?id={good_a['probe_id']}")[0] == 200
    # 坏轮详情：500 人话页，且不展示其内容
    status2, body2, _ = _get(f"{server}/round?id={bad['probe_id']}")
    _assert_human_error_page(status2, body2, code=code)
    assert "会被写坏的一轮" not in body2


def test_a_round_missing_required_fields_does_not_masquerade_as_a_good_one(server, lab):
    """只有 `probe_id` 的记录曾经一路通过、混进列表当正常轮，直到点开才炸。"""
    good = _make_round("好轮")
    bad = _make_round("残缺的一轮")
    target = loop.paths().round_file(bad["probe_id"])
    target.write_text(json.dumps({"probe_id": bad["probe_id"]}), encoding="utf-8")

    status, body, _ = _get(server + "/")
    assert status == 200 and good["probe_id"] in body
    assert "round_incomplete" in body and "这一轮读不出来" in body
    assert "残缺的一轮" not in body
    status2, body2, _ = _get(f"{server}/round?id={bad['probe_id']}")
    _assert_human_error_page(status2, body2, code="round_incomplete")


def test_failed_job_page_states_the_reason_and_refuses_to_degrade(lab):
    job = web.Job("fl-x", state="failed", error="ollama 后端不可达",
                  error_code="BackendUnreachableError")
    page = web.render_failed("fl-x", job).decode("utf-8")
    assert "BackendUnreachableError" in page and "ollama 后端不可达" in page
    assert "不下载模型" in page and "不上云" in page
