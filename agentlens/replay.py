"""从已有 JSONL 事件回放一次 run。

回放只读取已经记下的事件，按记录顺序还原每一步的 type、name、input、output
和 error。它不重新执行 agent，不调用 LLM 或工具，也不产生新的副作用。

``duration_ms`` 由该步自己的起止时间算出，只用于展示。回归检查不比较它。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agentlens.events import TraceEvent

# 这些事件代表一次已记录的外部调用。log、error、run_start、run_end 留在完整回放里，
# 但不进入调用磁带：它们不是可以按顺序取出结果的那一类步骤。
REPLAY_CALL_TYPES: frozenset[str] = frozenset(
    {
        "llm_call",
        "tool_call",
        "file_read",
        "file_write",
        "browser_action",
    }
)

EventLike = TraceEvent | dict[str, Any]


class ReplayError(Exception):
    """已记录的调用和下一次 ``take`` 对不上，或磁带还没走完。"""


class _Unset:
    """区分「没传 input」和「input 就是 None」。"""


_UNSET = _Unset()


@dataclass(frozen=True)
class ReplayStep:
    """记录顺序里的一步。字段都来自已有事件，或由起止时间派生。

    ``index`` 是这条事件在 JSONL 里的 0-based 位置。``--calls`` 过滤后仍用这个
    编号，因此第 3 条事件即使是过滤结果里的第 1 条，也还是 ``#3``。
    """

    index: int
    event_id: str
    parent_event_id: str | None
    type: str
    name: str
    input: Any
    output: Any
    error: str | None
    duration_ms: int | None


@dataclass(frozen=True)
class RunReplay:
    """一次 run 的回放脚本。``steps`` 与 JSONL 的顺序相同。"""

    run_id: str
    steps: tuple[ReplayStep, ...]

    def call_steps(self) -> tuple[ReplayStep, ...]:
        """只保留 ``REPLAY_CALL_TYPES`` 里的步骤，顺序和编号都不变。"""
        return tuple(step for step in self.steps if step.type in REPLAY_CALL_TYPES)


def replay_run(events: Sequence[EventLike], *, run_id: str | None = None) -> RunReplay:
    """把已有事件变成回放脚本。

    不写存储，也不检查父事件是否存在。父 id 缺失的事件仍按原顺序留在脚本里。
    ``run_id`` 省略时，用第一条带 run_id 的事件。
    """
    items = list(events)
    steps = tuple(_step(index, event) for index, event in enumerate(items))
    return RunReplay(run_id=_run_id(run_id, items), steps=steps)


def format_replay(replay: RunReplay, *, calls_only: bool = False) -> str:
    """文本回放。空的 input、output、error 省略，步骤之间空一行。"""
    steps = replay.call_steps() if calls_only else replay.steps
    if calls_only:
        title = f"Run: {replay.run_id}（{len(steps)} 条调用，共 {len(replay.steps)} 步）"
    else:
        title = f"Run: {replay.run_id}（{len(replay.steps)} 步）"
    lines = [title]
    if not steps:
        empty = "没有可回放的调用。" if calls_only else "没有可回放的步骤。"
        lines.append(empty)
        return "\n".join(lines) + "\n"
    for step in steps:
        lines.append("")
        lines.extend(_step_lines(step))
    return "\n".join(lines) + "\n"


def replay_to_dict(replay: RunReplay, *, calls_only: bool = False) -> dict[str, Any]:
    """可 JSON 序列化的回放。这是派生文档，不是新的存储格式。"""
    steps = replay.call_steps() if calls_only else replay.steps
    return {
        "run_id": replay.run_id,
        "calls_only": calls_only,
        "event_count": len(replay.steps),
        "step_count": len(steps),
        "steps": [_step_dict(step) for step in steps],
    }


def replay_to_json(replay: RunReplay, *, calls_only: bool = False) -> str:
    payload = replay_to_dict(replay, calls_only=calls_only)
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"


def is_replay_call(event: EventLike) -> bool:
    """事件类型是否属于可按顺序取出结果的调用。"""
    return _text(_field(event, "type")) in REPLAY_CALL_TYPES


class RecordedCalls:
    """按记录顺序逐条取出已记录的调用结果。

    下一次 ``take`` 必须对上磁带里的下一条调用。对不上时不前进。
    相同的 type、name、input 出现多次时，按 JSONL 顺序依次给出。

    这里返回的是当时记下的 output。不会重新执行对应的函数或请求。
    """

    def __init__(self, events: Sequence[EventLike]) -> None:
        self._steps = replay_run(events).call_steps()
        self._index = 0

    def peek(self) -> ReplayStep | None:
        """下一条调用。磁带用完时是 ``None``。"""
        if self._index >= len(self._steps):
            return None
        return self._steps[self._index]

    def remaining(self) -> tuple[ReplayStep, ...]:
        """还没取出的调用，按记录顺序。"""
        return self._steps[self._index :]

    @property
    def exhausted(self) -> bool:
        return self._index >= len(self._steps)

    def take(self, event_type: str, name: str, input: Any = _UNSET) -> ReplayStep:
        """取出下一条调用。

        ``event_type`` 和 ``name`` 必须与下一条一致。传入 ``input`` 时，还要与
        记下的 input 一致；对象的键顺序不同不算差异。不传 ``input`` 则不比较输入。
        """
        step = self.peek()
        if step is None:
            raise ReplayError(f"已记录的调用已用完，还想取 [{event_type}] {name}")
        if step.type != event_type or step.name != name:
            raise ReplayError(
                f"下一条已记录调用是 [{step.type}] {step.name}，不是 [{event_type}] {name}"
            )
        if not isinstance(input, _Unset) and not _same_value(step.input, input):
            raise ReplayError(
                f"下一条 [{step.type}] {step.name} 的 input 与记录不一致: "
                f"{_short(step.input)} != {_short(input)}"
            )
        self._index += 1
        return step

    def assert_finished(self) -> None:
        """还有未取出的调用时抛出 ``ReplayError``。"""
        remaining = self.remaining()
        if not remaining:
            return
        labels = ", ".join(f"[{step.type}] {step.name}" for step in remaining)
        raise ReplayError(f"还有 {len(remaining)} 条已记录调用没有被回放: {labels}")


def recorded_calls(events: Sequence[EventLike]) -> RecordedCalls:
    """从已有事件建立调用磁带。"""
    return RecordedCalls(events)


def _run_id(explicit: str | None, events: Sequence[EventLike]) -> str:
    if explicit:
        return explicit
    for event in events:
        value = _field(event, "run_id")
        if value:
            return str(value)
    return ""


def _step(index: int, event: EventLike) -> ReplayStep:
    started = _as_datetime(_field(event, "started_at"))
    ended = _as_datetime(_field(event, "ended_at"))
    return ReplayStep(
        index=index,
        event_id=_text(_field(event, "id")),
        parent_event_id=_parent(event),
        type=_text(_field(event, "type")),
        name=_text(_field(event, "name")),
        input=_field(event, "input"),
        output=_field(event, "output"),
        error=_normalize_error(_field(event, "error")),
        duration_ms=_duration_ms(started, ended),
    )


def _step_dict(step: ReplayStep) -> dict[str, Any]:
    return {
        "index": step.index,
        "event_id": step.event_id,
        "parent_event_id": step.parent_event_id,
        "type": step.type,
        "name": step.name,
        "input": step.input,
        "output": step.output,
        "error": step.error,
        "duration_ms": step.duration_ms,
    }


def _step_lines(step: ReplayStep) -> list[str]:
    header = f"#{step.index + 1} [{step.type}] {step.name}"
    extras: list[str] = []
    if step.parent_event_id:
        extras.append(f"parent={step.parent_event_id}")
    if step.duration_ms is not None:
        extras.append(f"{step.duration_ms}ms")
    if extras:
        header = f"{header}  {'  '.join(extras)}"
    lines = [header]
    if step.input is not None:
        lines.append(f"    input: {_render_value(step.input)}")
    if step.output is not None:
        lines.append(f"    output: {_render_value(step.output)}")
    if step.error:
        lines.append(f"    error: {step.error}")
    return lines


def _parent(event: EventLike) -> str | None:
    if isinstance(event, TraceEvent):
        return _blank_to_none(event.parent_event_id)
    if "parent_event_id" in event:
        return _blank_to_none(event.get("parent_event_id"))
    return _blank_to_none(event.get("parent_id"))


def _field(event: EventLike, name: str) -> Any:
    if isinstance(event, TraceEvent):
        return getattr(event, name)
    return event.get(name)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _blank_to_none(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _normalize_error(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _duration_ms(started: datetime | None, ended: datetime | None) -> int | None:
    """与 CSV 导出同一口径：缺任一侧就是未知，负值记为 0。"""
    if started is None or ended is None:
        return None
    try:
        millis = int((ended - started).total_seconds() * 1000)
    except TypeError:
        return None
    return max(0, millis)


def _same_value(left: Any, right: Any) -> bool:
    return _canonical(left) == _canonical(right)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _render_value(value: Any) -> str:
    if isinstance(value, str):
        return value.replace("\n", "\\n")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _short(value: Any, limit: int = 80) -> str:
    text = " ".join(_render_value(value).split())
    if len(text) > limit:
        return text[:limit] + "..."
    return text
