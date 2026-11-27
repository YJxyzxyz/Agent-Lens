"""从已有事件推导一次 run 的统计摘要。

不写回 JSONL，也不增加事件字段。token 只累加事件里已经记下的
``metadata.usage`` 或 ``metadata.tokens``。耗时来自 ``run_start`` / ``run_end``
或事件自身的起止时间。孤儿数与 ``agentlens tree`` 使用同一个事件树。
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from agentlens.events import ALL_EVENT_TYPES, TraceEvent
from agentlens.tree import build_event_tree

SUMMARY_CSV_COLUMNS: tuple[str, ...] = (
    "run_id",
    "name",
    "event_count",
    "error_count",
    "run_start_count",
    "run_end_count",
    "llm_call_count",
    "tool_call_count",
    "file_read_count",
    "file_write_count",
    "browser_action_count",
    "log_count",
    "duration_ms",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "orphan_count",
    "missing_parent_count",
    "tool_names",
    "started_at",
    "ended_at",
)


@dataclass(frozen=True)
class RunSummary:
    """一次 run 的派生统计。数字都来自已有事件。"""

    run_id: str
    name: str
    event_count: int
    counts_by_type: dict[str, int]
    error_count: int
    llm_call_count: int
    tool_call_count: int
    file_read_count: int
    file_write_count: int
    browser_action_count: int
    log_count: int
    tool_names: tuple[str, ...]
    started_at: datetime | None
    ended_at: datetime | None
    duration_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    orphan_count: int
    missing_parent_count: int


def summarize_run(events: list[TraceEvent], *, run_id: str | None = None) -> RunSummary:
    """汇总一次 run。

    ``error_count`` 只数 ``type == "error"`` 的事件，和 Web 首页的错误标记一致。
    其他类型事件上附带的 ``error`` 字符串留给 diff 比较。

    token 三个数互相独立：某一侧没有记录时是 ``None``，不是 0。
    单条事件若同时有 prompt 与 completion、但没有 total，则用两者之和补上该条的 total。
    ``metadata.tokens`` 只在该条事件没有 total 时计入 total。
    """
    resolved_run_id = run_id
    if resolved_run_id is None:
        resolved_run_id = events[0].run_id if events else ""

    counts: dict[str, int] = {event_type: 0 for event_type in ALL_EVENT_TYPES}
    for event in events:
        counts[event.type] = counts.get(event.type, 0) + 1

    name = "unknown"
    for event in events:
        if event.type == "run_start":
            name = event.name
            break

    started_at, ended_at, duration_ms = _run_span(events)
    prompt_tokens, completion_tokens, total_tokens = _token_totals(events)
    tool_names = tuple(sorted({event.name for event in events if event.type == "tool_call"}))
    tree = build_event_tree(events)

    return RunSummary(
        run_id=resolved_run_id,
        name=name,
        event_count=len(events),
        counts_by_type=counts,
        error_count=counts.get("error", 0),
        llm_call_count=counts.get("llm_call", 0),
        tool_call_count=counts.get("tool_call", 0),
        file_read_count=counts.get("file_read", 0),
        file_write_count=counts.get("file_write", 0),
        browser_action_count=counts.get("browser_action", 0),
        log_count=counts.get("log", 0),
        tool_names=tool_names,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        orphan_count=tree.orphan_count,
        missing_parent_count=tree.missing_parent_count,
    )


def summary_to_dict(summary: RunSummary) -> dict[str, Any]:
    """变成可 JSON 序列化的字典。时间是 ISO 字符串。"""
    return {
        "run_id": summary.run_id,
        "name": summary.name,
        "event_count": summary.event_count,
        "counts_by_type": dict(summary.counts_by_type),
        "error_count": summary.error_count,
        "llm_call_count": summary.llm_call_count,
        "tool_call_count": summary.tool_call_count,
        "file_read_count": summary.file_read_count,
        "file_write_count": summary.file_write_count,
        "browser_action_count": summary.browser_action_count,
        "log_count": summary.log_count,
        "tool_names": list(summary.tool_names),
        "started_at": _iso(summary.started_at),
        "ended_at": _iso(summary.ended_at),
        "duration_ms": summary.duration_ms,
        "prompt_tokens": summary.prompt_tokens,
        "completion_tokens": summary.completion_tokens,
        "total_tokens": summary.total_tokens,
        "orphan_count": summary.orphan_count,
        "missing_parent_count": summary.missing_parent_count,
    }


def summaries_to_json(summaries: list[RunSummary], *, single: bool = False) -> str:
    """单个摘要输出对象；多个摘要输出数组。"""
    if single:
        payload: Any = summary_to_dict(summaries[0]) if summaries else {}
    else:
        payload = [summary_to_dict(summary) for summary in summaries]
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def summaries_to_csv(summaries: list[RunSummary]) -> str:
    """每个 run 一行。没有的 token 或耗时留空，不写成 0。"""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=SUMMARY_CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for summary in summaries:
        data = summary_to_dict(summary)
        data["run_start_count"] = summary.counts_by_type.get("run_start", 0)
        data["run_end_count"] = summary.counts_by_type.get("run_end", 0)
        data["tool_names"] = "|".join(summary.tool_names)
        row = {column: _csv_cell(data.get(column)) for column in SUMMARY_CSV_COLUMNS}
        writer.writerow(row)
    return buffer.getvalue()


def format_run_summary(summary: RunSummary) -> str:
    """单个 run 的多行文本摘要。"""
    tools = ", ".join(summary.tool_names) if summary.tool_names else "-"
    lines = [
        f"Run: {summary.run_id}",
        f"Name: {summary.name}",
        f"Events: {summary.event_count}",
        f"Errors: {summary.error_count}",
        f"Duration: {_ms(summary.duration_ms)}",
        f"Started: {_iso(summary.started_at) or '-'}",
        f"Ended: {_iso(summary.ended_at) or '-'}",
        f"LLM calls: {summary.llm_call_count}",
        f"Tool calls: {summary.tool_call_count}",
        f"Tools: {tools}",
        f"File reads: {summary.file_read_count}",
        f"File writes: {summary.file_write_count}",
        f"Browser actions: {summary.browser_action_count}",
        f"Logs: {summary.log_count}",
        f"Prompt tokens: {_optional_int(summary.prompt_tokens)}",
        f"Completion tokens: {_optional_int(summary.completion_tokens)}",
        f"Total tokens: {_optional_int(summary.total_tokens)}",
        f"Orphans: {summary.orphan_count}",
        f"Missing parents: {summary.missing_parent_count}",
        "",
        "Counts by type:",
    ]
    for event_type in ALL_EVENT_TYPES:
        lines.append(f"  {event_type}: {summary.counts_by_type.get(event_type, 0)}")
    return "\n".join(lines) + "\n"


def format_summary_list(summaries: list[RunSummary]) -> str:
    """全部 run 的紧凑文本。没有记录时与 ``agentlens list`` 一样提示。"""
    if not summaries:
        return "暂无追踪记录。\n"
    lines = [f"Runs: {len(summaries)}", ""]
    for summary in summaries:
        lines.append(
            f"{summary.run_id}  name={summary.name}  events={summary.event_count}  "
            f"errors={summary.error_count}  duration_ms={_optional_int(summary.duration_ms)}  "
            f"llm_calls={summary.llm_call_count}  tool_calls={summary.tool_call_count}  "
            f"total_tokens={_optional_int(summary.total_tokens)}  "
            f"orphans={summary.orphan_count}"
        )
    return "\n".join(lines) + "\n"


def _run_span(
    events: list[TraceEvent],
) -> tuple[datetime | None, datetime | None, int | None]:
    """取 run 的起止时间。

    起点优先用第一条 ``run_start``，否则用第一条事件的 ``started_at``。
    终点优先用最后一条 ``run_end`` 的 ``ended_at``（没有则用它的 ``started_at``）。
    没有 ``run_end`` 时，用各事件 ``ended_at`` 的最大值。
    只有时间点、没有任何结束时间时，耗时是 ``None``。
    """
    if not events:
        return None, None, None

    run_starts = [event for event in events if event.type == "run_start"]
    run_ends = [event for event in events if event.type == "run_end"]
    started_at = run_starts[0].started_at if run_starts else events[0].started_at

    ended_at: datetime | None = None
    if run_ends:
        last = run_ends[-1]
        ended_at = last.ended_at or last.started_at
    else:
        ended_values = [event.ended_at for event in events if event.ended_at is not None]
        if ended_values:
            ended_at = max(ended_values)

    if started_at is None or ended_at is None:
        return started_at, ended_at, None

    delta_ms = int((_as_utc(ended_at) - _as_utc(started_at)).total_seconds() * 1000)
    return started_at, ended_at, max(0, delta_ms)


def _token_totals(events: list[TraceEvent]) -> tuple[int | None, int | None, int | None]:
    prompt_sum = 0
    completion_sum = 0
    total_sum = 0
    saw_prompt = False
    saw_completion = False
    saw_total = False

    for event in events:
        metadata = event.metadata if isinstance(event.metadata, dict) else {}
        usage = metadata.get("usage")
        event_prompt: int | None = None
        event_completion: int | None = None
        event_total: int | None = None
        if isinstance(usage, dict):
            event_prompt = _first_int(usage, ("prompt_tokens", "input_tokens"))
            event_completion = _first_int(usage, ("completion_tokens", "output_tokens"))
            event_total = _as_int(usage.get("total_tokens"))
        if event_total is None and event_prompt is not None and event_completion is not None:
            event_total = event_prompt + event_completion
        if event_total is None:
            event_total = _as_int(metadata.get("tokens"))

        if event_prompt is not None:
            saw_prompt = True
            prompt_sum += event_prompt
        if event_completion is not None:
            saw_completion = True
            completion_sum += event_completion
        if event_total is not None:
            saw_total = True
            total_sum += event_total

    return (
        prompt_sum if saw_prompt else None,
        completion_sum if saw_completion else None,
        total_sum if saw_total else None,
    )


def _first_int(payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        number = _as_int(payload.get(key))
        if number is not None:
            return number
    return None


def _as_int(value: Any) -> int | None:
    """只接受非负整数。布尔值不是 token。"""
    if isinstance(value, bool) or value is None:
        return None
    number: int | None = None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    if number is None or number < 0:
        return None
    return number


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _ms(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value}ms"


def _optional_int(value: int | None) -> str:
    if value is None:
        return "-"
    return str(value)


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
