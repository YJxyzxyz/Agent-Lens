"""AgentLens 本地 Web Timeline Viewer。

基于 FastAPI 的轻量级本地 Web UI，用于浏览、查看和对比 trace run。
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agentlens.events import TraceEvent
from agentlens.storage import DEFAULT_BASE_DIR, JsonlTraceStore

# ---------------------------------------------------------------------------
# 视图逻辑（纯函数，可独立测试）
# ---------------------------------------------------------------------------


def get_run_summaries(store: JsonlTraceStore) -> list[dict[str, Any]]:
    """获取所有 run 的摘要信息。

    Returns:
        摘要列表，每个元素包含 run_id, name, start_time, event_count, has_error。
    """
    summaries: list[dict[str, Any]] = []
    for run_id in store.list_runs():
        events = store.load_run(run_id)
        name = _extract_run_name(events)
        start_time = _extract_start_time(events)
        has_error = any(e.type == "error" for e in events)
        summaries.append(
            {
                "run_id": run_id,
                "name": name,
                "start_time": start_time,
                "event_count": len(events),
                "has_error": has_error,
            }
        )
    summaries.sort(key=lambda s: s.get("start_time") or "", reverse=True)
    return summaries


def get_run_detail(store: JsonlTraceStore, run_id: str) -> dict[str, Any]:
    """获取单个 run 的详细信息。

    Returns:
        dict with run_id, name, events (list of serialized event dicts).
    """
    events = store.load_run(run_id)
    return {
        "run_id": run_id,
        "name": _extract_run_name(events),
        "events": [e.model_dump(mode="json") for e in events],
    }


def _extract_run_name(events: list[TraceEvent]) -> str:
    """从 run_start 事件中提取 run 名称。"""
    for e in events:
        if e.type == "run_start":
            return e.name
    return "unknown"


def _extract_start_time(events: list[TraceEvent]) -> str | None:
    """提取 run 的启动时间（ISO 格式）。"""
    for e in events:
        if e.type == "run_start":
            return e.started_at.isoformat()
    if events:
        return events[0].started_at.isoformat()
    return None


# ---------------------------------------------------------------------------
# HTML 渲染（内联 CSS，无外部依赖）
# ---------------------------------------------------------------------------

_STYLE = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #0d1117; color: #c9d1d9; padding: 24px; max-width: 1100px; margin: 0 auto; }
  h1 { font-size: 1.5rem; margin-bottom: 8px; color: #58a6ff; }
  h2 { font-size: 1.2rem; margin: 24px 0 12px; }
  a { color: #58a6ff; text-decoration: none; }
  a:hover { text-decoration: underline; }
  table { width: 100%; border-collapse: collapse; margin-top: 16px; }
  th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #21262d; }
  th { background: #161b22; font-weight: 600; font-size: 0.85rem; color: #8b949e; }
  tr:hover { background: #161b22; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px;
           font-size: 0.75rem; font-weight: 600; }
  .badge-error { background: #da3633; color: #fff; }
  .badge-ok { background: #238636; color: #fff; }
  .event { border: 1px solid #21262d; border-radius: 6px; margin: 8px
                  0; overflow: hidden; }
  .event-header { padding: 10px 14px; cursor: pointer; display: flex;
                  justify-content: space-between;
                   align-items: center; font-size: 0.9rem; }
  .event-header:hover { opacity: 0.85; }
  .event-body { display: none; padding: 12px 14px; background: #161b22; font-size: 0.82rem;
                 border-top: 1px solid #21262d; }
  .event-body.open { display: block; }
  .event-body pre { background: #0d1117; padding: 10px; border-radius: 4px; overflow-x: auto;
                    white-space: pre-wrap; word-break: break-all; font-size: 0.78rem; }
  .event-type-llm_call .event-header { background: #1f2a3a; }
  .event-type-tool_call .event-header { background: #2a1f3a; }
  .event-type-error .event-header { background: #3a1f1f; }
  .event-type-run_start .event-header { background: #1a2e1a; }
  .event-type-run_end .event-header { background: #1a2e1a; }
  .event-type-log .event-header { background: #1a1a2e; }
  .meta { font-size: 0.8rem; color: #8b949e; }
  .footer { margin-top: 40px; padding: 16px 0; border-top: 1px solid #21262d;
            font-size: 0.78rem; color: #8b949e; }
  .back-link { display: inline-block; margin-bottom: 16px; }
  .empty { text-align: center; padding: 60px 20px; color: #8b949e; }
  .empty h2 { color: #c9d1d9; }
  .diff-form { margin: 16px 0; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .diff-form button { padding: 6px 16px; background: #238636; color: #fff; border: none;
                      border-radius: 6px; cursor: pointer; font-size: 0.85rem; }
  .diff-form button:hover { background: #2ea043; }
  .diff-msg { color: #f85149; font-size: 0.85rem; margin-left: 8px; display: none; }
  .diff-table td { vertical-align: top; }
  .diff-same { color: #8b949e; }
  .diff-changed { background: rgba(210, 153, 34, 0.15); }
  .diff-missing_left { background: rgba(56, 139, 253, 0.12); }
  .diff-missing_right { background: rgba(56, 139, 253, 0.12); }
  .diff-summary { margin: 16px 0; font-size: 0.9rem; }
  .diff-summary span { margin-right: 24px; }
</style>
"""

_SCRIPT = """
<script>
  function toggleEvent(id) {
    var el = document.getElementById('body-' + id);
    el.classList.toggle('open');
  }
  function submitCompare() {
    var checked = document.querySelectorAll('.compare-cb:checked');
    if (checked.length !== 2) {
      var msg = document.getElementById('diff-msg');
      msg.style.display = 'inline';
      return false;
    }
    document.getElementById('left-id').value = checked[0].value;
    document.getElementById('right-id').value = checked[1].value;
    return true;
  }
</script>
"""


def _render_index(summaries: list[dict[str, Any]]) -> str:
    """渲染首页 run 列表（含 compare checkbox）。"""
    rows = ""
    for s in summaries:
        status = (
            '<span class="badge badge-error">error</span>'
            if s["has_error"]
            else '<span class="badge badge-ok">ok</span>'
        )
        rid = html.escape(s["run_id"])
        rows += (
            "<tr>"
            f'<td><input type="checkbox" class="compare-cb" value="{rid}"></td>'
            f'<td><a href="/run/{rid}">{rid}</a></td>'
            f"<td>{html.escape(s['name'])}</td>"
            f"<td>{html.escape(_fmt_time(s.get('start_time')))}</td>"
            f"<td>{s['event_count']}</td>"
            f"<td>{status}</td>"
            "</tr>"
        )

    if not summaries:
        body = '<div class="empty"><h2>暂无追踪记录</h2><p>运行你的 Agent 后刷新页面。</p></div>'
        compare_form = ""
    else:
        compare_form = (
            '<form class="diff-form" method="get" action="/diff" onsubmit="return submitCompare()">'
            '<input type="hidden" name="left" id="left-id">'
            '<input type="hidden" name="right" id="right-id">'
            '<button type="submit">Compare selected</button>'
            '<span id="diff-msg" class="diff-msg">Select exactly two runs to compare.</span>'
            "</form>"
        )
        body = (
            "<table>"
            "<thead><tr>"
            "<th></th><th>Run ID</th><th>Name</th><th>Start Time</th><th>Events</th><th>Status</th>"
            "</tr></thead>"
            f"<tbody>{rows}</tbody>"
            "</table>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentLens Timeline Viewer</title>
{_STYLE}
</head>
<body>
<h1>🔍 AgentLens Timeline Viewer</h1>
<p class="meta">Runs directory: {html.escape(str(DEFAULT_BASE_DIR))}</p>
{compare_form}
{body}
<div class="footer">
  ⚠️ Traces may contain prompts, responses, tool inputs, and file paths.
  Do not share sensitive traces.
</div>
{_SCRIPT}
</body>
</html>"""


def _render_detail(run_id: str, name: str, events: list[dict[str, Any]]) -> str:
    """渲染 run 详情页。"""
    event_html = ""
    for i, ev in enumerate(events):
        eid = f"ev{i}"
        ev_type = ev.get("type", "?")
        ev_name = html.escape(str(ev.get("name", "")))
        ev_error = ev.get("error")
        started = html.escape(_fmt_time(ev.get("started_at")))
        ended = ev.get("ended_at")
        duration = _compute_duration(ev.get("started_at"), ended)

        header_extra = ""
        if ev_error:
            header_extra += (
                f' <span style="color:#f85149">⚠ {html.escape(str(ev_error)[:100])}</span>'
            )
        if duration:
            header_extra += f' <span style="color:#8b949e;font-size:0.8rem">({duration}ms)</span>'

        input_json = _pretty_json(ev.get("input"))
        output_json = _pretty_json(ev.get("output"))
        meta_json = _pretty_json(ev.get("metadata"))
        error_full = html.escape(str(ev_error)) if ev_error else ""

        expanded = "open" if ev_type == "error" else ""

        event_html += f"""
<div class="event event-type-{html.escape(ev_type)}">
  <div class="event-header" onclick="toggleEvent('{eid}')">
    <span>[<strong>{html.escape(ev_type)}</strong>] {ev_name}{header_extra}</span>
    <span style="font-size:0.75rem;color:#8b949e">{started}</span>
  </div>
  <div class="event-body {expanded}" id="body-{eid}">
    {_section("Input", input_json)}
    {_section("Output", output_json)}
    {_section("Metadata", meta_json)}
    {_section("Error", error_full) if error_full else ""}
  </div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentLens — {html.escape(run_id)}</title>
{_STYLE}
</head>
<body>
<a class="back-link" href="/">← Back to runs</a>
<h1>{html.escape(run_id)}</h1>
<p class="meta">Name: {html.escape(name)} &nbsp;|&nbsp; Events: {len(events)}</p>
{event_html}
<div class="footer">
  ⚠️ Traces may contain prompts, responses, tool inputs, and file paths.
  Do not share sensitive traces.
</div>
{_SCRIPT}
</body>
</html>"""


def _section(title: str, content: str) -> str:
    if not content or content in ("null", "{}", '""', ""):
        return ""
    return (
        f'<div style="margin-bottom:10px">'
        f"<strong>{html.escape(title)}</strong>"
        f"<pre>{content}</pre>"
        f"</div>"
    )


def _pretty_json(value: Any) -> str:
    """安全地将值渲染为 HTML escaped JSON 字符串。"""
    if value is None:
        return ""
    try:
        s = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        return html.escape(s)
    except (TypeError, ValueError):
        return html.escape(str(value))


def _fmt_time(iso_str: Any) -> str:
    """格式化 ISO 时间字符串为可读格式。"""
    if not iso_str:
        return "-"
    try:
        s = str(iso_str)
        # 截断到秒级
        return s[:19].replace("T", " ")
    except Exception:
        return str(iso_str)


def _compute_duration(started_at: Any, ended_at: Any) -> int | None:
    """计算事件持续时间（毫秒）。"""
    if not started_at or not ended_at:
        return None
    try:
        s = datetime.fromisoformat(str(started_at))
        e = datetime.fromisoformat(str(ended_at))
        return int((e - s).total_seconds() * 1000)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Diff 逻辑
# ---------------------------------------------------------------------------


def _event_summary(ev: dict[str, Any]) -> dict[str, Any]:
    """从序列化事件提取摘要字段。"""
    return {
        "type": ev.get("type", "?"),
        "name": ev.get("name", ""),
        "started_at": ev.get("started_at"),
        "duration_ms": _compute_duration(ev.get("started_at"), ev.get("ended_at")),
        "error": ev.get("error"),
        "input": ev.get("input"),
        "output": ev.get("output"),
        "metadata": ev.get("metadata"),
    }


def compare_runs(
    left_events: list[dict[str, Any]], right_events: list[dict[str, Any]]
) -> dict[str, Any]:
    """对比两个事件序列，返回 diff 行列表和统计信息。

    Args:
        left_events: 左侧 run 的事件列表（已序列化为 dict）。
        right_events: 右侧 run 的事件列表。

    Returns:
        dict with rows, first_diff, left_count, right_count.
    """
    rows: list[dict[str, Any]] = []
    max_len = max(len(left_events), len(right_events))
    first_diff: int | None = None

    for i in range(max_len):
        left = left_events[i] if i < len(left_events) else None
        right = right_events[i] if i < len(right_events) else None

        if left is None:
            status = "missing_left"
        elif right is None:
            status = "missing_right"
        elif left.get("type") == right.get("type") and left.get("name") == right.get("name"):
            status = "same"
        else:
            status = "changed"

        if status != "same" and first_diff is None:
            first_diff = i

        rows.append(
            {
                "index": i,
                "status": status,
                "left": _event_summary(left) if left else None,
                "right": _event_summary(right) if right else None,
            }
        )

    return {
        "rows": rows,
        "first_diff": first_diff,
        "left_count": len(left_events),
        "right_count": len(right_events),
    }


def _render_diff(
    left_id: str,
    right_id: str,
    diff_result: dict[str, Any],
) -> str:
    """渲染 diff 页面。"""
    rows_html = ""
    for row in diff_result["rows"]:
        status = row["status"]
        idx = row["index"]
        left = row.get("left") or {}
        right = row.get("right") or {}

        left_text = (
            f"[{html.escape(str(left.get('type', '-')))}] {html.escape(str(left.get('name', '-')))}"
            if row.get("left")
            else "—"
        )
        right_text = (
            f"[{html.escape(str(right.get('type', '-')))}] "
            f"{html.escape(str(right.get('name', '-')))}"
            if row.get("right")
            else "—"
        )

        status_label = {
            "same": "=",
            "changed": "≠",
            "missing_left": "←",
            "missing_right": "→",
        }.get(status, "?")

        eid = f"d{idx}"
        left_detail = _event_detail_html(left, f"{eid}l")
        right_detail = _event_detail_html(right, f"{eid}r")

        rows_html += f"""
<tr class="diff-{status}">
  <td>{idx + 1}</td>
  <td>{status_label}</td>
  <td onclick="toggleEvent('{eid}l')" style="cursor:pointer">{left_text}</td>
  <td onclick="toggleEvent('{eid}r')" style="cursor:pointer">{right_text}</td>
</tr>
<tr class="diff-{status}" id="body-{eid}">
  <td colspan="4" style="padding:4px 14px">
    <div style="display:flex;gap:16px">
      <div style="flex:1">{left_detail}</div>
      <div style="flex:1">{right_detail}</div>
    </div>
  </td>
</tr>"""

    fd = diff_result.get("first_diff")
    first_diff_text = f"First difference at step #{fd + 1}" if fd is not None else "No differences"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentLens Diff — {html.escape(left_id)} vs {html.escape(right_id)}</title>
{_STYLE}
<style>
  #body-d0, #body-d1, #body-d2, #body-d3, #body-d4, #body-d5, #body-d6, #body-d7,
  #body-d8, #body-d9, #body-d10, #body-d11, #body-d12, #body-d13, #body-d14, #body-d15,
  #body-d16, #body-d17, #body-d18, #body-d19 {{
    display: none;
  }}
</style>
</head>
<body>
<a class="back-link" href="/">← Back to runs</a>
<h1>Run Diff</h1>
<div class="diff-summary">
  <span><strong>Left:</strong> {html.escape(left_id)} ({diff_result["left_count"]} events)</span>
  <span><strong>Right:</strong> {html.escape(right_id)} ({diff_result["right_count"]} events)</span>
  <span><strong>{first_diff_text}</strong></span>
</div>
<table class="diff-table">
<thead><tr>
  <th>#</th><th></th><th>Left</th><th>Right</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>
<div class="footer">
  ⚠️ Traces may contain prompts, responses, tool inputs, and file paths.
  Do not share sensitive traces.
</div>
{_SCRIPT}
</body>
</html>"""


def _event_detail_html(ev: dict[str, Any], eid: str) -> str:
    """渲染单个事件的详情 HTML 片段。"""
    if not ev:
        return '<span style="color:#8b949e">—</span>'
    dur = ev.get("duration_ms")
    dur_str = f" ({dur}ms)" if dur is not None else ""
    err = ev.get("error")
    err_str = f' <span style="color:#f85149">⚠ {html.escape(str(err)[:80])}</span>' if err else ""
    started = html.escape(ev.get("started_at", "-"))
    return (
        f'<div style="font-size:0.82rem">{started}{dur_str}{err_str}</div>'
        f"{_section('Input', _pretty_json(ev.get('input')))}"
        f"{_section('Output', _pretty_json(ev.get('output')))}"
        f"{_section('Metadata', _pretty_json(ev.get('metadata')))}"
    )


# ---------------------------------------------------------------------------
# FastAPI 应用工厂
# ---------------------------------------------------------------------------


def create_app(base_dir: Path | None = None):  # noqa: ANN202
    """创建 FastAPI 应用实例。

    Args:
        base_dir: 存储根目录，默认 .agentlens/runs/。

    Returns:
        FastAPI app 实例。
    """
    from fastapi import FastAPI, Query
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="AgentLens Viewer", docs_url=None, redoc_url=None)

    def _store() -> JsonlTraceStore:
        return JsonlTraceStore(base_dir=base_dir)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        store = _store()
        summaries = get_run_summaries(store)
        return _render_index(summaries)

    @app.get("/run/{run_id}", response_class=HTMLResponse)
    async def run_detail(run_id: str) -> str:
        store = _store()
        detail = get_run_detail(store, run_id)
        return _render_detail(detail["run_id"], detail["name"], detail["events"])

    @app.get("/diff", response_class=HTMLResponse)
    async def diff_runs(
        left: str = Query(..., description="Left run ID"),
        right: str = Query(..., description="Right run ID"),
    ) -> str:
        store = _store()
        left_events_raw = store.load_run(left)
        right_events_raw = store.load_run(right)

        if not left_events_raw:
            return _error_page(f"Run not found: {html.escape(left)}")
        if not right_events_raw:
            return _error_page(f"Run not found: {html.escape(right)}")

        left_ev = [e.model_dump(mode="json") for e in left_events_raw]
        right_ev = [e.model_dump(mode="json") for e in right_events_raw]
        diff_result = compare_runs(left_ev, right_ev)
        return _render_diff(left, right, diff_result)

    return app


def _error_page(message: str) -> str:
    """渲染错误提示页面。"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>AgentLens — Error</title>
{_STYLE}</head>
<body>
<a class="back-link" href="/">← Back to runs</a>
<h1>Error</h1>
<p style="color:#f85149">{message}</p>
</body>
</html>"""


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


def start_viewer(
    host: str = "127.0.0.1",
    port: int = 8765,
    base_dir: Path | None = None,
) -> None:
    """启动 Web viewer。

    Args:
        host: 绑定地址。
        port: 端口。
        base_dir: 存储根目录。
    """
    try:
        import uvicorn  # type: ignore[import-untyped,unused-ignore]
    except ImportError:
        raise ImportError(
            "未安装 web 依赖。请运行:\n"
            "  pip install agentlens[web]\n"
            "或:\n"
            "  pip install fastapi uvicorn"
        ) from None

    app = create_app(base_dir=base_dir)
    print(f"\n  AgentLens viewer running at http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")
