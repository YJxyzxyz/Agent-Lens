"""对比两次 run 的事件序列。

默认按 ``(type, name)`` 做序列对齐，因此中间插入的一步不会把后面的事件
整段标成不同。对齐之后再比较 ``error``、``input``、``output``。

不比较 id、``parent_event_id``、时间戳和 metadata。这些字段在两次运行里
通常本来就不同。耗时和 token 用统计摘要看。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal

from agentlens.events import TraceEvent

DiffStatus = Literal["same", "changed", "missing_left", "missing_right"]
AlignMode = Literal["sequence", "index"]
EventLike = TraceEvent | dict[str, Any]

COMPARED_FIELDS: tuple[str, ...] = ("type", "name", "error", "input", "output")


@dataclass(frozen=True)
class DiffRow:
    """对齐后的一行。``index`` 是对齐结果里的 0-based 行号。"""

    index: int
    status: DiffStatus
    left: EventLike | None
    right: EventLike | None
    fields: tuple[str, ...]


@dataclass(frozen=True)
class RunDiff:
    """两次 run 的对齐结果。"""

    rows: tuple[DiffRow, ...]
    left_count: int
    right_count: int
    align: AlignMode

    @property
    def first_diff(self) -> int | None:
        """第一处非 same 行的 0-based 行号。没有差异时是 ``None``。"""
        for row in self.rows:
            if row.status != "same":
                return row.index
        return None

    def counts(self) -> dict[str, int]:
        """``only_in_left`` 对应 status ``missing_right``，反之亦然。"""
        same = 0
        changed = 0
        only_in_left = 0
        only_in_right = 0
        for row in self.rows:
            if row.status == "same":
                same += 1
            elif row.status == "changed":
                changed += 1
            elif row.status == "missing_right":
                only_in_left += 1
            elif row.status == "missing_left":
                only_in_right += 1
        return {
            "same": same,
            "changed": changed,
            "only_in_left": only_in_left,
            "only_in_right": only_in_right,
        }


def diff_events(
    left: Sequence[EventLike],
    right: Sequence[EventLike],
    *,
    align: AlignMode = "sequence",
) -> RunDiff:
    """对比两个事件序列。

    ``align="sequence"`` 用 ``(type, name)`` 对齐。
    ``align="index"`` 按记录位置逐条比较，多出来的尾部算缺失。
    """
    left_events = list(left)
    right_events = list(right)
    if align == "sequence":
        pending = _sequence_rows(left_events, right_events)
    elif align == "index":
        pending = _index_rows(left_events, right_events)
    else:
        raise ValueError(f"unsupported align: {align}")

    rows = tuple(
        DiffRow(
            index=index,
            status=status,
            left=left_event,
            right=right_event,
            fields=fields,
        )
        for index, (status, left_event, right_event, fields) in enumerate(pending)
    )
    return RunDiff(
        rows=rows,
        left_count=len(left_events),
        right_count=len(right_events),
        align=align,
    )


def diff_to_dict(result: RunDiff, *, left_run_id: str, right_run_id: str) -> dict[str, Any]:
    """可 JSON 序列化的 diff。只包含参与比较的字段。"""
    return {
        "left_run_id": left_run_id,
        "right_run_id": right_run_id,
        "align": result.align,
        "left_count": result.left_count,
        "right_count": result.right_count,
        "counts": result.counts(),
        "first_difference": result.first_diff,
        "compared_fields": list(COMPARED_FIELDS),
        "rows": [_row_to_dict(row) for row in result.rows],
    }


def diff_to_json(result: RunDiff, *, left_run_id: str, right_run_id: str) -> str:
    payload = diff_to_dict(result, left_run_id=left_run_id, right_run_id=right_run_id)
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def format_diff(result: RunDiff, *, left_run_id: str, right_run_id: str) -> str:
    """文本 diff。相同的行省略，差异行带 1-based 行号。"""
    counts = result.counts()
    lines = [
        f"左侧: {left_run_id} ({result.left_count} 个事件)",
        f"右侧: {right_run_id} ({result.right_count} 个事件)",
        f"对齐: {result.align}",
        (
            f"相同 {counts['same']}，不同 {counts['changed']}，"
            f"仅左侧 {counts['only_in_left']}，仅右侧 {counts['only_in_right']}"
        ),
    ]
    if result.first_diff is None:
        lines.append("对齐后的 type、name、error、input、output 一致。")
    else:
        lines.append(f"首处差异: #{result.first_diff + 1}")

    for row in result.rows:
        if row.status == "same":
            continue
        lines.append("")
        if row.status == "changed":
            field_text = ", ".join(row.fields) if row.fields else "-"
            lines.append(f"#{row.index + 1} 不同 ({field_text})")
            lines.append(f"  {left_run_id}: {_event_label(row.left)}")
            lines.append(f"  {right_run_id}: {_event_label(row.right)}")
            for field in row.fields:
                if field in {"type", "name"}:
                    continue
                lines.append(
                    f"  {field}: {_preview(_field(row.left, field))} -> "
                    f"{_preview(_field(row.right, field))}"
                )
        elif row.status == "missing_right":
            lines.append(f"#{row.index + 1} 仅左侧")
            lines.append(f"  {left_run_id}: {_event_label(row.left)}")
        else:
            lines.append(f"#{row.index + 1} 仅右侧")
            lines.append(f"  {right_run_id}: {_event_label(row.right)}")

    return "\n".join(lines) + "\n"


def _sequence_rows(
    left: list[EventLike], right: list[EventLike]
) -> list[tuple[DiffStatus, EventLike | None, EventLike | None, tuple[str, ...]]]:
    left_keys = [_align_key(event) for event in left]
    right_keys = [_align_key(event) for event in right]
    matcher = SequenceMatcher(a=left_keys, b=right_keys, autojunk=False)
    rows: list[tuple[DiffStatus, EventLike | None, EventLike | None, tuple[str, ...]]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                rows.append(_pair(left[i1 + offset], right[j1 + offset]))
        elif tag == "delete":
            rows.extend(_only_left(left[i1:i2]))
        elif tag == "insert":
            rows.extend(_only_right(right[j1:j2]))
        elif tag == "replace":
            left_slice = left[i1:i2]
            right_slice = right[j1:j2]
            shared = min(len(left_slice), len(right_slice))
            for offset in range(shared):
                rows.append(_pair(left_slice[offset], right_slice[offset]))
            rows.extend(_only_left(left_slice[shared:]))
            rows.extend(_only_right(right_slice[shared:]))
    return rows


def _index_rows(
    left: list[EventLike], right: list[EventLike]
) -> list[tuple[DiffStatus, EventLike | None, EventLike | None, tuple[str, ...]]]:
    rows: list[tuple[DiffStatus, EventLike | None, EventLike | None, tuple[str, ...]]] = []
    shared = min(len(left), len(right))
    for index in range(shared):
        rows.append(_pair(left[index], right[index]))
    rows.extend(_only_left(left[shared:]))
    rows.extend(_only_right(right[shared:]))
    return rows


def _pair(
    left: EventLike, right: EventLike
) -> tuple[DiffStatus, EventLike, EventLike, tuple[str, ...]]:
    fields = _diff_fields(left, right)
    status: DiffStatus = "same" if not fields else "changed"
    return status, left, right, fields


def _only_left(
    events: list[EventLike],
) -> list[tuple[DiffStatus, EventLike | None, EventLike | None, tuple[str, ...]]]:
    return [("missing_right", event, None, ()) for event in events]


def _only_right(
    events: list[EventLike],
) -> list[tuple[DiffStatus, EventLike | None, EventLike | None, tuple[str, ...]]]:
    return [("missing_left", None, event, ()) for event in events]


def _diff_fields(left: EventLike, right: EventLike) -> tuple[str, ...]:
    fields: list[str] = []
    for field in COMPARED_FIELDS:
        if _canonical_field(left, field) != _canonical_field(right, field):
            fields.append(field)
    return tuple(fields)


def _canonical_field(event: EventLike, field: str) -> str:
    value = _field(event, field)
    if field == "error":
        value = _normalize_error(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _normalize_error(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _align_key(event: EventLike) -> tuple[str, str]:
    return (str(_field(event, "type")), str(_field(event, "name")))


def _field(event: EventLike | None, field: str) -> Any:
    if event is None:
        return None
    if isinstance(event, TraceEvent):
        return getattr(event, field)
    return event.get(field)


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


def _row_to_dict(row: DiffRow) -> dict[str, Any]:
    return {
        "index": row.index,
        "status": row.status,
        "fields": list(row.fields),
        "left": _side_dict(row.left),
        "right": _side_dict(row.right),
    }


def _side_dict(event: EventLike | None) -> dict[str, Any] | None:
    if event is None:
        return None
    return {
        "id": _field(event, "id"),
        "type": _field(event, "type"),
        "name": _field(event, "name"),
        "error": _normalize_error(_field(event, "error")),
        "input": _field(event, "input"),
        "output": _field(event, "output"),
    }
