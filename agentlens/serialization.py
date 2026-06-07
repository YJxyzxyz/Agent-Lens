"""AgentLens 安全序列化工具。

提供递归安全序列化、敏感字段脱敏、字符串截断等功能，
确保追踪数据中不包含 API key 等敏感信息。
"""

from __future__ import annotations

import dataclasses
from typing import Any

# ---------------------------------------------------------------------------
# 敏感字段名（小写匹配）
# ---------------------------------------------------------------------------

SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "api-key",
        "x-api-key",
        "authorization",
        "auth",
        "headers",
        "password",
        "passwd",
        "token",
        "access_token",
        "access-token",
        "bearer",
        "secret",
        "cookie",
        "set-cookie",
        "credentials",
    }
)

REDACTED = "[REDACTED]"
DEFAULT_MAX_STRING_LENGTH = 4000
MAX_RECURSION_DEPTH = 10


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def sanitize_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """对 dict 的 key 进行脱敏：匹配敏感字段名的 value 替换为 ``[REDACTED]``。

    Args:
        data: 待脱敏的 dict。

    Returns:
        脱敏后的新 dict（浅拷贝 + 值替换）。
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        if _is_sensitive_key(key):
            result[key] = REDACTED
        else:
            result[key] = value
    return result


def truncate_string(value: str, max_length: int = DEFAULT_MAX_STRING_LENGTH) -> str:
    """截断超长字符串。

    Args:
        value: 原始字符串。
        max_length: 最大长度。

    Returns:
        截断后的字符串。超过长度时末尾追加 ``...[truncated]``。
    """
    if len(value) <= max_length:
        return value
    return value[:max_length] + "...[truncated]"


def safe_serialize(
    value: Any,
    max_string_length: int = DEFAULT_MAX_STRING_LENGTH,
    _depth: int = 0,
) -> Any:
    """递归安全序列化任意值为可 JSON 化的结构。

    - 基本类型（str, int, float, bool, None）保持原样
    - str 超长则截断
    - list / tuple / set 递归处理每个元素
    - dict 递归处理每个 value（key 同时做脱敏检查）
    - Pydantic model → ``model_dump(mode="json")``
    - dataclass → ``dataclasses.asdict()``
    - 其他不可序列化对象 → ``repr(value)`` 并截断

    Args:
        value: 任意 Python 对象。
        max_string_length: 字符串最大长度。
        _depth: 内部递归深度计数器。

    Returns:
        安全序列化后的值。
    """
    if _depth > MAX_RECURSION_DEPTH:
        return "[max recursion depth exceeded]"

    # None
    if value is None:
        return None

    # 基本类型
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        return truncate_string(value, max_string_length)

    # 序列容器
    if isinstance(value, list | tuple | set):
        return type(value)(safe_serialize(item, max_string_length, _depth + 1) for item in value)

    # 映射
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and _is_sensitive_key(k):
                result[k] = REDACTED
            else:
                result[str(k)] = safe_serialize(v, max_string_length, _depth + 1)
        return result

    # Pydantic model
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            dumped = value.model_dump(mode="json")
            return safe_serialize(dumped, max_string_length, _depth + 1)
        except Exception:
            return truncate_string(repr(value), max_string_length)

    # dataclass
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        try:
            as_dict = dataclasses.asdict(value)
            return safe_serialize(as_dict, max_string_length, _depth + 1)
        except Exception:
            return truncate_string(repr(value), max_string_length)

    # 兜底
    return truncate_string(repr(value), max_string_length)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _is_sensitive_key(key: str) -> bool:
    """判断 key 是否属于敏感字段（大小写不敏感）。"""
    return key.lower() in SENSITIVE_KEYS
