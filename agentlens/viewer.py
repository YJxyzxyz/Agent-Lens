"""AgentLens 本地 Web Timeline Viewer。

基于 FastAPI 的轻量级本地 Web UI，用于浏览和查看 trace run。
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
</style>
"""

_SCRIPT = """
<script>
  function toggleEvent(id) {
    var el = document.getElementById('body-' + id);
    el.classList.toggle('open');
  }
</script>
"""


def _render_index(summaries: list[dict[str, Any]]) -> str:
    """渲染首页 run 列表。"""
    rows = ""
    for s in summaries:
        status = (
            '<span class="badge badge-error">error</span>'
            if s["has_error"]
            else '<span class="badge badge-ok">ok</span>'
        )
        rows += (
            f"<tr>"
            f'<td><a href="/run/{html.escape(s["run_id"])}">{html.escape(s["run_id"])}</a></td>'
            f"<td>{html.escape(s['name'])}</td>"
            f"<td>{html.escape(_fmt_time(s.get('start_time')))}</td>"
            f"<td>{s['event_count']}</td>"
            f"<td>{status}</td>"
            f"</tr>"
        )

    if not summaries:
        body = '<div class="empty"><h2>暂无追踪记录</h2><p>运行你的 Agent 后刷新页面。</p></div>'
    else:
        body = (
            "<table>"
            "<thead><tr>"
            "<th>Run ID</th><th>Name</th><th>Start Time</th><th>Events</th><th>Status</th>"
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
# FastAPI 应用工厂
# ---------------------------------------------------------------------------


def create_app(base_dir: Path | None = None):  # noqa: ANN202
    """创建 FastAPI 应用实例。

    Args:
        base_dir: 存储根目录，默认 .agentlens/runs/。

    Returns:
        FastAPI app 实例。
    """
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="AgentLens Viewer", docs_url=None, redoc_url=None)

    def _store() -> JsonlTraceStore:
        return JsonlTraceStore(base_dir=base_dir)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> str:  # noqa: ARG001
        store = _store()
        summaries = get_run_summaries(store)
        return _render_index(summaries)

    @app.get("/run/{run_id}", response_class=HTMLResponse)
    async def run_detail(run_id: str) -> str:
        store = _store()
        detail = get_run_detail(store, run_id)
        return _render_detail(detail["run_id"], detail["name"], detail["events"])

    return app


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
