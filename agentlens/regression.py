"""用一次已记录的 run 检查另一次 run。

比较方式和 ``diff_events`` 相同：默认按 ``(type, name)`` 做扁平序列对齐，再比较
``error``、``input``、``output``。不比较 id、``parent_event_id``、时间戳和 metadata，
也不看事件树。这是通过或失败的检查；``agentlens diff`` 有差异时仍然退出 0。

检查只读已经记下的事件。它不重新执行 LLM 或工具调用。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from agentlens.diff import COMPARED_FIELDS, AlignMode, EventLike, RunDiff, diff_events, diff_to_dict
from agentlens.events import TraceEvent
from agentlens.replay import is_replay_call


@dataclass(frozen=True)
class RegressionResult:
    """一次回归检查。``passed`` 表示对齐后的比较字段全部相同。"""

    passed: bool
    diff: RunDiff
    baseline_run_id: str
    candidate_run_id: str
    calls_only: bool


def check_regression(
    baseline: Sequence[EventLike],
    candidate: Sequence[EventLike],
    *,
    align: AlignMode = "sequence",
    baseline_run_id: str | None = None,
    candidate_run_id: str | None = None,
    calls_only: bool = False,
) -> RegressionResult:
    """比较基线和候选。

    ``calls_only=True`` 时只保留 llm / tool / file / browser 调用，再做同一种对齐。
    因此多出来的 log 或 error 事件不会让这次检查失败。默认比较全部事件。

    Args:
        baseline: 已记录的基线事件。
        candidate: 待检查的事件。
        align: ``sequence`` 按 type/name 对齐；``index`` 按记录位置对齐。
        baseline_run_id: 报告里的基线名称。省略时从事件里取。
        candidate_run_id: 报告里的候选名称。省略时从事件里取。
        calls_only: 为真时忽略 ``REPLAY_CALL_TYPES`` 以外的事件。

    Raises:
        ValueError: ``align`` 不是 ``sequence`` 或 ``index``。
    """
    left = _selected(baseline, calls_only)
    right = _selected(candidate, calls_only)
    if align == "sequence":
        diff = diff_events(left, right, align="sequence")
    elif align == "index":
        diff = diff_events(left, right, align="index")
    else:
        raise ValueError(f"unsupported align: {align}")
    return RegressionResult(
        passed=diff.first_diff is None,
        diff=diff,
        baseline_run_id=_label(baseline_run_id, baseline),
        candidate_run_id=_label(candidate_run_id, candidate),
        calls_only=calls_only,
    )


def regression_to_dict(result: RegressionResult) -> dict[str, Any]:
    """可 JSON 序列化的检查结果。``diff`` 与 ``diff_to_dict`` 的结构相同。"""
    return {
        "passed": result.passed,
        "calls_only": result.calls_only,
        "baseline_run_id": result.baseline_run_id,
        "candidate_run_id": result.candidate_run_id,
        "diff": diff_to_dict(
            result.diff,
            left_run_id=result.baseline_run_id,
            right_run_id=result.candidate_run_id,
        ),
    }


def regression_to_json(result: RegressionResult) -> str:
    payload = regression_to_dict(result)
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"


def format_regression(result: RegressionResult) -> str:
    """文本报告。相同的行省略，差异行带 1-based 行号。"""
    diff = result.diff
    counts = diff.counts()
    unit = "个调用" if result.calls_only else "个事件"
    scope = "仅调用" if result.calls_only else "全部事件"
    lines = [
        f"基线: {result.baseline_run_id} ({diff.left_count} {unit})",
        f"候选: {result.candidate_run_id} ({diff.right_count} {unit})",
        f"对齐: {diff.align}",
        f"范围: {scope}",
        f"结果: {'通过' if result.passed else '未通过'}",
        (
            f"相同 {counts['same']}，不同 {counts['changed']}，"
            f"仅基线 {counts['only_in_left']}，仅候选 {counts['only_in_right']}"
        ),
    ]
    if result.passed:
        lines.append(f"基线与候选的 {'、'.join(COMPARED_FIELDS)} 一致。")
    elif diff.first_diff is not None:
        lines.append(f"首处差异: #{diff.first_diff + 1}")

    for row in diff.rows:
        if row.status == "same":
            continue
        lines.append("")
        if row.status == "changed":
            field_text = ", ".join(row.fields) if row.fields else "-"
            lines.append(f"#{row.index + 1} 不同 ({field_text})")
            lines.append(f"  {result.baseline_run_id}: {_event_label(row.left)}")
            lines.append(f"  {result.candidate_run_id}: {_event_label(row.right)}")
            for field in row.fields:
                if field in {"type", "name"}:
                    continue
                lines.append(
                    f"  {field}: {_preview(_field(row.left, field))} -> "
                    f"{_preview(_field(row.right, field))}"
                )
        elif row.status == "missing_right":
            lines.append(f"#{row.index + 1} 仅基线")
            lines.append(f"  {result.baseline_run_id}: {_event_label(row.left)}")
        else:
            lines.append(f"#{row.index + 1} 仅候选")
            lines.append(f"  {result.candidate_run_id}: {_event_label(row.right)}")
    return "\n".join(lines) + "\n"


def _selected(events: Sequence[EventLike], calls_only: bool) -> list[EventLike]:
    items = list(events)
    if not calls_only:
        return items
    return [event for event in items if is_replay_call(event)]


def _label(explicit: str | None, events: Sequence[EventLike]) -> str:
    if explicit:
        return explicit
    for event in events:
        value = event.run_id if isinstance(event, TraceEvent) else event.get("run_id")
        if value:
            return str(value)
    return ""


def _field(event: EventLike | None, name: str) -> Any:
    if event is None:
        return None
    if isinstance(event, TraceEvent):
        return getattr(event, name)
    return event.get(name)


def _event_label(event: EventLike | None) -> str:
    if event is None:
        return "-"
    return f"[{_field(event, 'type')}] {_field(event, 'name')}"


def _preview(value: Any, limit: int = 80) -> str:
    if value is None:
        text = "null"
    elif isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[:limit] + "..."
    return text
