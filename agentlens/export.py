"""把已有事件导出为 JSON 数组或 CSV。

JSON 的每个对象与 JSONL 里的一行相同，不增加字段。
CSV 多一列由起止时间算出的 ``duration_ms``，嵌套的 input、output、metadata
放在单元格里的 JSON 文本中。存储格式仍然是 JSONL。
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any

from agentlens.events import TraceEvent

EVENT_CSV_COLUMNS: tuple[str, ...] = (
    "id",
    "run_id",
    "parent_event_id",
    "type",
    "name",
    "started_at",
    "ended_at",
    "duration_ms",
    "error",
    "input",
    "output",
    "metadata",
)

_JSON_CELL_COLUMNS = frozenset({"input", "output", "metadata"})


def events_to_json(events: list[TraceEvent]) -> str:
    """导出为缩进的 JSON 数组。字段与 ``TraceEvent.model_dump(mode='json')`` 一致。"""
    payload = [event.model_dump(mode="json") for event in events]
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def events_to_csv(events: list[TraceEvent]) -> str:
    """导出为 CSV。嵌套字段是 JSON 文本，键按字母排序，便于稳定比较。"""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=EVENT_CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for event in events:
        data = event.model_dump(mode="json")
        row: dict[str, str] = {}
        for column in EVENT_CSV_COLUMNS:
            if column == "duration_ms":
                row[column] = _duration_cell(event.started_at, event.ended_at)
                continue
            value = data.get(column)
            if column in _JSON_CELL_COLUMNS:
                row[column] = "" if value is None else _json_cell(value)
            elif value is None:
                row[column] = ""
            else:
                row[column] = str(value)
        writer.writerow(row)
    return buffer.getvalue()


def export_events(events: list[TraceEvent], fmt: str) -> str:
    """按 ``json`` 或 ``csv`` 导出。其他格式抛出 ``ValueError``。"""
    if fmt == "json":
        return events_to_json(events)
    if fmt == "csv":
        return events_to_csv(events)
    raise ValueError(f"unsupported format: {fmt}")


def _json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _duration_cell(started_at: datetime | None, ended_at: datetime | None) -> str:
    if started_at is None or ended_at is None:
        return ""
    try:
        millis = int((ended_at - started_at).total_seconds() * 1000)
    except TypeError:
        return ""
    return str(max(0, millis))
