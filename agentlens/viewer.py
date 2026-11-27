"""AgentLens 本地 Web Timeline Viewer。

基于 FastAPI 的轻量级本地 Web UI，用于浏览、查看和对比 trace run。
"""

from __future__ import annotations

import html
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from agentlens.diff import diff_events
from agentlens.events import TraceEvent
from agentlens.replay import replay_run
from agentlens.storage import JsonlTraceStore
from agentlens.summary import summarize_run, summary_to_dict

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
        dict with run_id, name, events, and summary。
        summary 来自已有事件，不改变 JSONL。
    """
    events = store.load_run(run_id)
    summary = summarize_run(events, run_id=run_id)
    return {
        "run_id": run_id,
        "name": summary.name,
        "events": [e.model_dump(mode="json") for e in events],
        "summary": summary_to_dict(summary),
    }


class ReplayStepOutOfRange(ValueError):
    """详情页上的逐步查看请求落到了记录范围外面。"""

    def __init__(self, step: int, step_count: int) -> None:
        self.step = step
        self.step_count = step_count
        super().__init__(f"step {step} is outside 1..{step_count}")


def replay_frame(
    events: Sequence[Any],
    *,
    step: int,
    seen: int | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """逐步查看已经走到的前缀，并标出当前步。

    ``step`` 与 ``seen`` 都从 1 开始，对应 ``agentlens replay`` 文本里的 ``#N``。
    ``seen`` 省略时等于 ``step``。可见事件是记录顺序里的前 ``seen`` 条，
    当前步是第 ``step`` 条，并且必须落在这前缀里面。
    顺序来自 ``replay_run``：JSONL 的原顺序，不按父子关系或时间重排。
    父事件不在这次记录里时，``parent_missing`` 为真，但这一步仍留在原位置。
    这里只读入参里的事件，不写存储，也不执行调用。
    """
    recorded = replay_run(events, run_id=run_id)
    count = len(recorded.steps)
    if seen is None:
        seen = step
    invalid = count == 0 or step < 1 or seen < 1 or step > count or seen > count or step > seen
    if invalid:
        raise ReplayStepOutOfRange(step, count)
    known_ids = {item.event_id for item in recorded.steps}
    visible: list[dict[str, Any]] = []
    for position, item in enumerate(recorded.steps[:seen]):
        parent = item.parent_event_id
        visible.append(
            {
                "index": item.index,
                "event_id": item.event_id,
                "parent_event_id": parent,
                "parent_missing": parent is not None and parent not in known_ids,
                "current": position == step - 1,
            }
        )
    return {
        "run_id": recorded.run_id,
        "step": step,
        "seen": seen,
        "step_count": count,
        "has_previous": step > 1,
        "has_next": step < count,
        "order": [item.event_id for item in recorded.steps],
        "visible": visible,
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
  :root {
    --bg: #0a0a0b;
    --panel: #111214;
    --panel-soft: #16181d;
    --border: #1e2027;
    --text: #e1e4e8;
    --muted: #6e7681;
    --accent: #58a6ff;
    --success: #2ea043;
    --warning: #d29922;
    --danger: #da3633;
    --code-bg: #0d1117;
    --radius: 8px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
         'Helvetica Neue', sans-serif;
         background: var(--bg); color: var(--text); padding: 32px 24px;
         max-width: 1180px; margin: 0 auto; line-height: 1.5; }
  h1 { font-size: 1.4rem; font-weight: 700; color: var(--text); letter-spacing: -0.02em; }
  h2 { font-size: 1.1rem; margin: 28px 0 14px; font-weight: 600; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .header { display: flex; align-items: center; justify-content: space-between;
            padding-bottom: 20px; border-bottom: 1px solid var(--border);
            margin-bottom: 24px; flex-wrap: wrap; gap: 12px; }
  .header-left h1 { display: flex; align-items: center; gap: 8px; }
  .header-left .sub { font-size: 0.9rem; color: var(--muted); margin-top: 2px; }
  .header-right { display: flex; gap: 8px; flex-wrap: wrap; }
  .tag { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.7rem;
         font-weight: 600; border: 1px solid var(--border); color: var(--muted); }
  .tag-accent { border-color: var(--accent); color: var(--accent); }
  .stats { display: flex; gap: 20px; margin: 16px 0; flex-wrap: wrap; }
  .stat { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
          padding: 12px 18px; min-width: 100px; }
  .stat .num { font-size: 1.4rem; font-weight: 700; }
  .stat .label { font-size: 0.75rem; color: var(--muted); }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th, td { padding: 10px 14px; text-align: left;
           border-bottom: 1px solid var(--border); font-size: 0.88rem; }
  th { background: var(--panel); font-weight: 600; font-size: 0.78rem;
        color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
  tr:hover td { background: rgba(88,166,255,0.03); }
  .badge { display: inline-block; padding: 2px 10px; border-radius: 10px;
           font-size: 0.72rem; font-weight: 600; }
  .badge-error { background: rgba(218,54,51,0.18); color: var(--danger); }
  .badge-ok { background: rgba(46,160,67,0.15); color: var(--success); }
  .badge-accent { background: rgba(88,166,255,0.12); color: var(--accent); }
  .badge-warning { background: rgba(210,153,34,0.15); color: var(--warning); }
  .badge-muted { background: rgba(110,118,129,0.12); color: var(--muted); }
  .btn { display: inline-block; padding: 7px 16px; border-radius: 6px; border: 1px solid var(--border);
         background: var(--panel-soft); color: var(--text); cursor: pointer; font-size: 0.82rem;
         font-weight: 500; transition: all 0.15s; }
  .btn:hover { background: var(--border); }
  .btn-primary { background: var(--accent); color: #fff; border-color: var(--accent); }
  .btn-primary:hover { background: #4090e0; }
  .btn:disabled { opacity: 0.4; cursor: not-allowed; }
  /* timeline */
  .timeline { position: relative; padding-left: 28px; margin-top: 8px; }
  .timeline::before { content: ''; position: absolute; left: 10px; top: 0; bottom: 0;
                      width: 2px; background: var(--border); }
  .event-card { border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 10px;
                overflow: hidden; position: relative; }
  .event-card::before { content: ''; position: absolute; left: -22px; top: 16px;
                        width: 10px; height: 10px; border-radius: 50%; border: 2px solid var(--border);
                        background: var(--bg); z-index: 1; }
  .event-card.replay-current { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
  .event-card.replay-current::before { border-color: var(--accent); background: var(--accent); }
  .event-card-header { padding: 10px 14px; cursor: pointer; display: flex; justify-content: space-between;
                       align-items: center; font-size: 0.88rem; gap: 8px; }
  .event-card-header:hover { opacity: 0.88; }
  .event-card-body { display: none; padding: 10px 14px; background: var(--panel-soft);
                     border-top: 1px solid var(--border); font-size: 0.8rem; }
  .event-card-body.open { display: block; }
  .event-card-body pre { background: var(--code-bg); padding: 10px; border-radius: 6px;
                         overflow-x: auto; white-space: pre-wrap; word-break: break-all;
                         font-size: 0.76rem; line-height: 1.45; }
  .ev-llm_call .event-card-header { background: rgba(88,166,255,0.07); }
  .ev-tool_call .event-card-header { background: rgba(210,153,34,0.07); }
  .ev-error .event-card-header { background: rgba(218,54,51,0.08); }
  .ev-run_start .event-card-header, .ev-run_end .event-card-header { background: rgba(46,160,67,0.06); }
  .ev-log .event-card-header { background: rgba(110,118,129,0.05); }
  .ev-file_read .event-card-header, .ev-file_write .event-card-header { background: rgba(139,148,158,0.05); }
  .meta { font-size: 0.8rem; color: var(--muted); }
  .footer { margin-top: 40px; padding: 16px 0; border-top: 1px solid var(--border);
            font-size: 0.76rem; color: var(--muted); }
  .back-link { display: inline-block; margin-bottom: 16px; font-size: 0.85rem; }
  .empty { text-align: center; padding: 60px 20px; color: var(--muted); }
  .empty h2 { color: var(--text); margin-bottom: 8px; }
  .empty pre { display: inline-block; background: var(--panel); padding: 10px 18px;
               border-radius: 6px; margin-top: 12px; font-size: 0.82rem; }
  .diff-form { margin: 16px 0; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .diff-msg { color: var(--danger); font-size: 0.82rem; display: none; }
  .diff-summary { display: flex; gap: 12px; margin: 16px 0; flex-wrap: wrap; }
  .diff-table td { vertical-align: top; }
  .diff-same td { color: var(--muted); }
  .diff-changed td { background: rgba(210,153,34,0.07); }
  .diff-missing_left td, .diff-missing_right td { background: rgba(88,166,255,0.05); }
  tr.diff-detail { display: none; }
  tr.diff-detail.open { display: table-row; }
  .diff-fields { margin-left: 6px; }
  input[type=checkbox] { accent-color: var(--accent); width: 15px; height: 15px; cursor: pointer; }
  .replay-controls { display: flex; align-items: center; gap: 12px; margin: 8px 0 4px;
                     flex-wrap: wrap; }
  #replay-position { font-size: 0.85rem; color: var(--muted); }
  #replay-readonly { margin: 0 0 16px; }
</style>
"""

_SCRIPT = """
<script>
  function toggleEvent(id) {
    var el = document.getElementById('body-' + id);
    if (el) el.classList.toggle('open');
  }
  function updateCompareBtn() {
    var checked = document.querySelectorAll('.compare-cb:checked');
    var btn = document.getElementById('compare-btn');
    var msg = document.getElementById('diff-msg');
    if (!btn) return;
    btn.disabled = checked.length !== 2;
    msg.style.display = checked.length > 0 && checked.length !== 2 ? 'inline' : 'none';
  }
  function submitCompare() {
    var checked = document.querySelectorAll('.compare-cb:checked');
    if (checked.length !== 2) {
      var msg = document.getElementById('diff-msg');
      if (msg) msg.style.display = 'inline';
      return false;
    }
    document.getElementById('left-id').value = checked[0].value;
    document.getElementById('right-id').value = checked[1].value;
    return true;
  }
  document.addEventListener('DOMContentLoaded', function() {
    var cbs = document.querySelectorAll('.compare-cb');
    for (var i = 0; i < cbs.length; i++) {
      cbs[i].addEventListener('change', updateCompareBtn);
    }
  });
</script>
"""


def _render_index(summaries: list[dict[str, Any]]) -> str:
    """渲染首页 run dashboard。"""
    total = len(summaries)
    errors = sum(1 for s in summaries if s["has_error"])

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
            f'<td><a href="/run/{rid}" title="{rid}">{html.escape(_short_id(s["run_id"]))}</a></td>'
            f"<td>{html.escape(s['name'])}</td>"
            f"<td>{html.escape(_fmt_time(s.get('start_time')))}</td>"
            f"<td>{s['event_count']}</td>"
            f"<td>{status}</td>"
            f'<td><a class="btn" href="/run/{rid}">Open</a></td>'
            "</tr>"
        )

    stats_html = (
        f'<div class="stats">'
        f'<div class="stat"><div class="num">{total}</div><div class="label">Total Runs</div></div>'
        f'<div class="stat"><div class="num" style="color:var(--danger)">{errors}</div>'
        f'<div class="label">With Errors</div></div>'
        f"</div>"
    )

    if not summaries:
        body = (
            '<div class="empty"><h2>No runs yet</h2>'
            "<p>Run <code>examples/generic_agent.py</code> or start tracing your agent.</p>"
            "<pre>python examples/generic_agent.py</pre></div>"
        )
        compare_form = ""
    else:
        compare_form = (
            '<form class="diff-form" method="get" action="/diff" onsubmit="return submitCompare()">'
            '<input type="hidden" name="left" id="left-id">'
            '<input type="hidden" name="right" id="right-id">'
            '<button type="submit" class="btn btn-primary" id="compare-btn" disabled>'
            "Compare selected</button>"
            '<span id="diff-msg" class="diff-msg">Select exactly two runs to compare.</span>'
            "</form>"
        )
        body = (
            "<table>"
            "<thead><tr>"
            "<th></th><th>Run ID</th><th>Name</th><th>Start Time</th><th>Events</th><th>Status</th><th></th>"
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
<div class="header">
  <div class="header-left">
    <h1>🔍 AgentLens</h1>
    <div class="sub">Local flight recorder for AI agents.</div>
  </div>
  <div class="header-right">
    <span class="tag tag-accent">Local only</span>
    <span class="tag">Read-only</span>
    <span class="tag">No cloud</span>
  </div>
</div>
{stats_html}
{compare_form}
{body}
<div class="footer">
  ⚠️ Traces may contain prompts, responses, tool inputs, and file paths.
  Do not share sensitive traces.
</div>
{_SCRIPT}
</body>
</html>"""


def _replay_controls_html(
    run_id: str,
    *,
    step: int | None,
    seen: int | None,
    step_count: int,
) -> str:
    """详情页上的上一步 / 下一步。

    ``step`` 为空是完整时间线。下一步从第 1 条进入逐步查看。
    逐步查看时链接只移动一条。上一步保留已经出现的事件，只移动高亮。
    页面上没有跳转输入，也没有按类型过滤。
    """
    if step is None:
        previous = _disabled_step_button("replay-prev", "Previous step")
        if step_count > 0:
            nxt = _step_link("replay-next", _step_href(run_id, 1, 1), "Next step")
        else:
            nxt = _disabled_step_button("replay-next", "Next step")
        position = ""
        if step_count == 0:
            note = (
                '<p class="meta" id="replay-readonly">'
                "Read-only. This run has no recorded events to step through."
                "</p>"
            )
        else:
            note = (
                '<p class="meta" id="replay-readonly">'
                "Read-only. Next step starts at the first recorded event. "
                "Visited events stay on the timeline. "
                "Playback does not re-execute LLM or tool calls."
                "</p>"
            )
        attrs = f'data-replay-mode="timeline" data-step-count="{step_count}"'
    else:
        visited = step if seen is None else seen
        if step > 1:
            previous = _step_link(
                "replay-prev",
                _step_href(run_id, step - 1, visited),
                "Previous step",
            )
        else:
            previous = _disabled_step_button("replay-prev", "Previous step")
        if step < step_count:
            nxt = _step_link(
                "replay-next",
                _step_href(run_id, step + 1, max(visited, step + 1)),
                "Next step",
            )
        else:
            nxt = _disabled_step_button("replay-next", "Next step")
        position = f'<span id="replay-position">第 {step} / 共 {step_count} 步</span>'
        note = (
            '<p class="meta" id="replay-readonly">'
            "Read-only. Visited events stay on this timeline in the original JSONL order, "
            "and the current step is highlighted. "
            "Previous step and Next step do not re-execute LLM or tool calls "
            "or send recorded output to a model or client."
            "</p>"
        )
        attrs = (
            f'data-replay-mode="step" data-step="{step}" '
            f'data-seen="{visited}" data-step-count="{step_count}"'
        )
    return (
        f'<div class="replay-controls" id="replay-controls" {attrs}>'
        f"{previous}{position}{nxt}</div>{note}"
    )


def _step_href(run_id: str, step: int, seen: int) -> str:
    rid = html.escape(run_id)
    return f"/run/{rid}?step={step}&amp;seen={seen}"


def _step_link(element_id: str, href: str, label: str) -> str:
    return f'<a class="btn" id="{element_id}" href="{href}">{label}</a>'


def _disabled_step_button(element_id: str, label: str) -> str:
    return f'<button type="button" class="btn" id="{element_id}" disabled>{label}</button>'


def _parent_html(current: dict[str, Any]) -> str:
    """逐步查看时显示记下的父事件。缺失父事件不改变这一步的位置。"""
    parent = current.get("parent_event_id")
    if not parent:
        return ""
    text = f"parent={html.escape(str(parent))}"
    if current.get("parent_missing"):
        text += ' <span class="badge badge-warning">missing parent</span>'
    return f'<div class="meta">{text}</div>'


def _render_detail(
    run_id: str,
    name: str,
    events: list[dict[str, Any]],
    summary: dict[str, Any] | None = None,
    *,
    replay: dict[str, Any] | None = None,
) -> str:
    """渲染 run 详情页（timeline 风格）。

    ``replay`` 为空时列出全部事件。传入 ``replay_frame`` 的结果时，同一页按记录顺序
    保留已经走到的事件，并高亮当前步。
    """
    annotations: list[dict[str, Any] | None] = []
    shown: list[dict[str, Any]]
    if replay is None:
        shown = events
        annotations = [None] * len(events)
    else:
        shown = []
        for item in replay["visible"]:
            annotations.append(item)
            shown.append(events[int(item["index"])])

    event_html = ""
    for offset, ev in enumerate(shown):
        ann = annotations[offset]
        i = offset if ann is None else int(ann["index"])
        eid = f"ev{i}"
        ev_name = html.escape(str(ev.get("name", "")))
        ev_error = ev.get("error")
        started = html.escape(_fmt_time(ev.get("started_at")))
        duration = _compute_duration(ev.get("started_at"), ev.get("ended_at"))

        type_badge = _type_badge(ev.get("type", ""))
        dur_str = f"<span class='meta'> &middot; {duration}ms</span>" if duration else ""
        err_icon = (
            f' <span style="color:var(--danger)">⚠ {html.escape(str(ev_error)[:80])}</span>'
            if ev_error
            else ""
        )

        input_json = _pretty_json(ev.get("input"))
        output_json = _pretty_json(ev.get("output"))
        meta_json = _pretty_json(ev.get("metadata"))
        error_full = html.escape(str(ev_error)) if ev_error else ""

        current = bool(ann and ann["current"])
        parent_html = _parent_html(ann) if ann else ""
        parent_missing = bool(ann and ann["parent_missing"])
        body_cls = (
            "event-card-body open" if current or ev.get("type") == "error" else "event-card-body"
        )
        ev_cls = f"event-card ev-{ev.get('type', 'log')}"
        if current:
            ev_cls += " replay-current"
        event_id = html.escape(str(ev.get("id", "")), quote=True)
        missing_attr = ' data-parent-missing="true"' if parent_missing else ""
        current_attr = ' data-replay-current="true"' if current else ""

        event_html += f"""
<div class="{ev_cls}" data-event-id="{event_id}" data-index="{i}"{missing_attr}{current_attr}>
  <div class="event-card-header" onclick="toggleEvent('{eid}')">
    <span>{type_badge} <strong>{ev_name}</strong>{err_icon}</span>
    <span style="font-size:0.75rem;color:var(--muted)">{started}{dur_str}</span>
  </div>
  <div class="{body_cls}" id="body-{eid}">
    {parent_html}
    {_section("Input", input_json)}
    {_section("Output", output_json)}
    {_section("Metadata", meta_json)}
    {_section("Error", error_full) if error_full else ""}
  </div>
</div>"""

    step_number = None if replay is None else int(replay["step"])
    seen_number = None if replay is None else int(replay["seen"])
    step_count = len(events) if replay is None else int(replay["step_count"])
    controls = _replay_controls_html(
        run_id,
        step=step_number,
        seen=seen_number,
        step_count=step_count,
    )

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
<div class="header" style="margin-top:8px">
  <div class="header-left">
    <h1>{html.escape(name)}</h1>
    <div class="sub">{html.escape(run_id)}</div>
  </div>
</div>
{_detail_stats_html(events, summary)}
{controls}
<div class="timeline">
{event_html}
</div>
<div class="footer">
  ⚠️ Traces may contain prompts, responses, tool inputs, and file paths.
  Do not share sensitive traces.
</div>
{_SCRIPT}
</body>
</html>"""


def _detail_stats_html(events: list[dict[str, Any]], summary: dict[str, Any] | None) -> str:
    """详情页顶部的统计条。没有 summary 时退回事件数和错误数。"""
    if summary is None:
        error_count = sum(1 for event in events if event.get("type") == "error")
        cards = _stat_card(len(events), "Events") + _stat_card(
            error_count, "Errors", "var(--danger)"
        )
        return f'<div class="stats">{cards}</div>'

    duration = summary.get("duration_ms")
    duration_text = "-" if duration is None else f"{duration}ms"
    tokens = summary.get("total_tokens")
    token_text = "-" if tokens is None else str(tokens)
    cards = (
        _stat_card(summary.get("event_count", len(events)), "Events")
        + _stat_card(summary.get("error_count", 0), "Errors", "var(--danger)")
        + _stat_card(duration_text, "Duration")
        + _stat_card(summary.get("llm_call_count", 0), "LLM calls")
        + _stat_card(summary.get("tool_call_count", 0), "Tool calls")
        + _stat_card(token_text, "Tokens")
    )
    notes: list[str] = []
    tool_names = summary.get("tool_names") or []
    if tool_names:
        rendered = ", ".join(str(name) for name in tool_names)
        notes.append(f"Tools: {html.escape(rendered)}")
    orphan_count = int(summary.get("orphan_count") or 0)
    missing_parents = int(summary.get("missing_parent_count") or 0)
    if orphan_count or missing_parents:
        notes.append(f"{orphan_count} orphans, {missing_parents} missing parents")
    note_html = f'<p class="meta">{" · ".join(notes)}</p>' if notes else ""
    return f'<div class="stats">{cards}</div>{note_html}'


def _stat_card(value: Any, label: str, color: str | None = None) -> str:
    style = f' style="color:{color}"' if color else ""
    return (
        '<div class="stat">'
        f'<div class="num"{style}>{html.escape(str(value))}</div>'
        f'<div class="label">{html.escape(label)}</div>'
        "</div>"
    )


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


def _type_badge(ev_type: str) -> str:
    """返回事件类型的彩色 badge HTML。"""
    labels: dict[str, tuple[str, str]] = {
        "llm_call": ("LLM", "badge-accent"),
        "tool_call": ("Tool", "badge-warning"),
        "run_start": ("Start", "badge-ok"),
        "run_end": ("End", "badge-ok"),
        "error": ("Error", "badge-error"),
        "file_read": ("Read", "badge-muted"),
        "file_write": ("Write", "badge-muted"),
        "log": ("Log", "badge-muted"),
    }
    label, cls = labels.get(ev_type, (ev_type, "badge-muted"))
    return f'<span class="badge {cls}">{label}</span>'


def _short_id(run_id: str) -> str:
    """截断 run_id 为短显示。"""
    if len(run_id) > 30:
        return run_id[:14] + "..." + run_id[-12:]
    return run_id


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

    与 CLI ``agentlens diff`` 使用同一个序列对齐：先按 type/name 对齐，
    再比较 error、input、output。返回形状仍包含 rows、first_diff、
    left_count、right_count；每行额外带 fields。

    Args:
        left_events: 左侧 run 的事件列表（已序列化为 dict）。
        right_events: 右侧 run 的事件列表。

    Returns:
        dict with rows, first_diff, left_count, right_count.
    """
    result = diff_events(left_events, right_events, align="sequence")
    rows: list[dict[str, Any]] = []
    for row in result.rows:
        left = _as_event_dict(row.left)
        right = _as_event_dict(row.right)
        rows.append(
            {
                "index": row.index,
                "status": row.status,
                "fields": list(row.fields),
                "left": _event_summary(left) if left else None,
                "right": _event_summary(right) if right else None,
            }
        )

    return {
        "rows": rows,
        "first_diff": result.first_diff,
        "left_count": result.left_count,
        "right_count": result.right_count,
    }


def _as_event_dict(event: Any) -> dict[str, Any] | None:
    """把 diff 行里的事件还原成 viewer 使用的 dict。"""
    if event is None:
        return None
    if isinstance(event, TraceEvent):
        return event.model_dump(mode="json")
    if isinstance(event, dict):
        return event
    return None


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
        fields = row.get("fields") or []
        if fields:
            rendered_fields = html.escape(", ".join(str(field) for field in fields))
            status_label += f' &middot; <span class="diff-fields">{rendered_fields}</span>'

        eid = f"d{idx}"
        left_detail = _event_detail_html(left, f"{eid}l")
        right_detail = _event_detail_html(right, f"{eid}r")

        rows_html += f"""
<tr class="diff-{status}">
  <td>{idx + 1}</td>
  <td>{status_label}</td>
  <td onclick="toggleEvent('{eid}')" style="cursor:pointer">{left_text}</td>
  <td onclick="toggleEvent('{eid}')" style="cursor:pointer">{right_text}</td>
</tr>
<tr class="diff-{status} diff-detail" id="body-{eid}">
  <td colspan="4" style="padding:4px 14px">
    <div style="display:flex;gap:16px">
      <div style="flex:1">{left_detail}</div>
      <div style="flex:1">{right_detail}</div>
    </div>
  </td>
</tr>"""

    fd = diff_result.get("first_diff")
    first_diff_text = f"First difference at step #{fd + 1}" if fd is not None else "No differences"

    same = sum(1 for r in diff_result["rows"] if r["status"] == "same")
    changed = sum(1 for r in diff_result["rows"] if r["status"] == "changed")
    missing_left = sum(1 for r in diff_result["rows"] if r["status"] == "missing_left")
    missing_right = sum(1 for r in diff_result["rows"] if r["status"] == "missing_right")

    summary_cards = (
        f'<div class="diff-summary">'
        f'<div class="stat"><div class="num">{same}</div><div class="label">Same</div></div>'
        f'<div class="stat"><div class="num" style="color:var(--warning)">{changed}</div>'
        f'<div class="label">Changed</div></div>'
        f'<div class="stat"><div class="num" style="color:var(--accent)">{missing_left}</div>'
        f'<div class="label">Missing left</div></div>'
        f'<div class="stat"><div class="num" style="color:var(--accent)">{missing_right}</div>'
        f'<div class="label">Missing right</div></div>'
        f"</div>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentLens Diff — {html.escape(left_id)} vs {html.escape(right_id)}</title>
{_STYLE}
</head>
<body>
<a class="back-link" href="/">← Back to runs</a>
<h1>Run Diff</h1>
<div class="diff-summary" style="margin-top:12px">
  <span class="meta"><strong>Left:</strong> {html.escape(left_id)} ({diff_result["left_count"]} events)</span>
  <span class="meta"><strong>Right:</strong> {html.escape(right_id)} ({diff_result["right_count"]} events)</span>
  <span class="meta"><strong>{first_diff_text}</strong></span>
</div>
{summary_cards}
<p class="meta">Aligned by type and name. Compared fields: type, name, error, input, output.
Timestamps, ids, parent ids, and metadata are not compared.</p>
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
    async def run_detail(
        run_id: str,
        step: int | None = Query(default=None),
        seen: int | None = Query(default=None),
    ) -> str:
        store = _store()
        if step is not None and run_id not in store.list_runs():
            return _error_page(f"Run not found: {html.escape(run_id)}")
        detail = get_run_detail(store, run_id)
        replay = None
        if step is not None:
            try:
                replay = replay_frame(
                    detail["events"],
                    step=step,
                    seen=seen,
                    run_id=run_id,
                )
            except ReplayStepOutOfRange as exc:
                return _error_page(
                    "Step out of range: "
                    f"{html.escape(str(exc.step))} "
                    f"(this run has {html.escape(str(exc.step_count))} steps)"
                )
        return _render_detail(
            detail["run_id"],
            detail["name"],
            detail["events"],
            detail.get("summary"),
            replay=replay,
        )

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
