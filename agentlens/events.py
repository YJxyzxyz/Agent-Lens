"""AgentLens 事件模型定义。

所有追踪事件统一使用 TraceEvent，通过 type 字段区分事件类型。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field

# ---------------------------------------------------------------------------
# 事件类型
# ---------------------------------------------------------------------------

EventType = Literal[
    "run_start",
    "run_end",
    "llm_call",
    "tool_call",
    "file_read",
    "file_write",
    "browser_action",
    "error",
    "log",
]

ALL_EVENT_TYPES: tuple[EventType, ...] = (
    "run_start",
    "run_end",
    "llm_call",
    "tool_call",
    "file_read",
    "file_write",
    "browser_action",
    "error",
    "log",
)


# ---------------------------------------------------------------------------
# 事件模型
# ---------------------------------------------------------------------------


class TraceEvent(BaseModel):
    """一次 Agent 运行中的单个追踪事件。

    Attributes:
        id: 事件唯一标识符。
        run_id: 所属运行 ID。
        parent_event_id: 父事件 ID。根事件为 None。JSONL 使用这个字段名，
            以便之后按 id 还原事件树。构造时仍接受 ``parent_id``，
            ``event.parent_id`` 读到的是同一个值。
        type: 事件类型。
        name: 事件名称（如模型名、工具名、步骤名等）。
        input: 事件输入，可选。
        output: 事件输出，可选。
        metadata: 附加元数据。
        started_at: 事件开始时间（UTC）。
        ended_at: 事件结束时间（UTC），可选。
        error: 错误信息，仅 error 类型事件使用，可选。
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    run_id: str
    parent_event_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("parent_event_id", "parent_id"),
    )
    type: EventType
    name: str
    input: Any | None = None
    output: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    error: str | None = None

    model_config = {"extra": "forbid", "populate_by_name": True}

    @property
    def parent_id(self) -> str | None:
        """``parent_event_id`` 的兼容别名。"""
        return self.parent_event_id
