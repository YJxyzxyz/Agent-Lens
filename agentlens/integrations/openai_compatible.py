"""通用 OpenAI-compatible API 自动追踪集成。

通过 monkey-patch ``openai.resources.chat.completions.Completions.create``
实现对所有兼容 OpenAI API 格式的 LLM provider 的自动 trace。

支持: DeepSeek / OpenAI / 任何兼容 `/v1/chat/completions` 的 provider。
"""

from __future__ import annotations

from typing import Any

from agentlens.context import get_current_run_id
from agentlens.serialization import safe_serialize, sanitize_mapping
from agentlens.tracer import record_llm_call

# ---------------------------------------------------------------------------
# 模块级状态
# ---------------------------------------------------------------------------

_original_create: Any = None
"""保存原始 ``Completions.create`` 方法。"""

_patched: bool = False
"""标记是否已完成 patch。"""


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def instrument_openai_compatible(
    provider: str,
    base_url_patterns: list[str] | None = None,
) -> None:
    """激活 OpenAI-compatible API 自动追踪。

    对 ``openai.resources.chat.completions.Completions.create`` 进行 monkey-patch，
    使每次调用自动记录 ``llm_call`` 事件到当前 AgentLens trace run。

    重复调用不会重复 patch。

    Args:
        provider: Provider 名称，如 ``"deepseek"``、``"openai"``。
        base_url_patterns: 可选的 base_url 匹配模式列表（当前版本未使用，保留扩展）。

    Raises:
        ImportError: 未安装 ``openai`` 包。
    """
    global _patched, _original_create  # noqa: PLW0603

    if _patched:
        return

    try:
        from openai.resources.chat.completions import (
            Completions,  # type: ignore[import-untyped,unused-ignore]
        )
    except ImportError:
        raise ImportError(
            "未安装 openai 包。请运行:\n"
            "  pip install agentlens[openai-compatible]\n"
            "或:\n"
            "  pip install openai"
        ) from None

    _original_create = Completions.create
    _patched = True

    def _patched_create(self_comp: Any, **kwargs: Any) -> Any:
        """替换后的 create 方法，自动记录 trace 事件。"""
        # 无 trace 上下文 → 直接调用原始方法，不崩溃
        if get_current_run_id() is None:
            return _original_create(self_comp, **kwargs)

        model = kwargs.get("model", provider)

        safe_input = _build_safe_input(kwargs)

        try:
            response = _original_create(self_comp, **kwargs)
        except Exception as exc:
            _record_error_event(provider, model, exc)
            raise

        safe_output = _build_safe_output(response)
        record_llm_call(
            model=model,
            input=safe_input,
            output=safe_output,
            metadata={
                "provider": provider,
                "api": "chat.completions.create",
                "model": model,
                "usage": _extract_usage(response),
            },
        )
        return response

    Completions.create = _patched_create  # type: ignore[assignment]


def uninstrument_openai_compatible() -> None:
    """恢复原始 ``Completions.create`` 方法，停用自动追踪。"""
    global _patched, _original_create  # noqa: PLW0603

    if not _patched or _original_create is None:
        return

    try:
        from openai.resources.chat.completions import (
            Completions,  # type: ignore[import-untyped,unused-ignore]
        )
    except ImportError:
        return

    Completions.create = _original_create  # type: ignore[method-assign]
    _original_create = None
    _patched = False


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _build_safe_input(kwargs: dict[str, Any]) -> dict[str, Any]:
    """从请求参数构建安全的 input 字典，脱敏并序列化。"""
    safe_kwargs = sanitize_mapping(kwargs)
    return safe_serialize(safe_kwargs, max_string_length=4000)


def _build_safe_output(response: Any) -> dict[str, Any]:
    """从原始响应对象提取安全摘要。"""
    try:
        raw = response.model_dump(mode="json")
    except AttributeError:
        raw = {"raw": repr(response)}

    summary: dict[str, Any] = {}
    for field in ("id", "model", "created", "usage"):
        if field in raw:
            summary[field] = raw[field]

    choices: list[dict[str, Any]] = []
    for choice in raw.get("choices", []):
        msg = choice.get("message", {})
        content = msg.get("content", "")
        if isinstance(content, str):
            content = content[:4000] + "..." if len(content) > 4000 else content
        choices.append(
            {
                "index": choice.get("index"),
                "finish_reason": choice.get("finish_reason"),
                "message": {"role": msg.get("role"), "content": content},
            }
        )
    summary["choices"] = choices

    return safe_serialize(summary, max_string_length=4000)


def _extract_usage(response: Any) -> dict[str, Any] | None:
    """从响应中提取 usage 信息。"""
    try:
        raw = response.model_dump(mode="json")
        usage = raw.get("usage")
        if usage:
            return safe_serialize(usage)
    except Exception:
        pass
    return None


def _record_error_event(provider: str, model: str, exc: Exception) -> None:
    """向当前 trace 记录 error 事件。"""
    from agentlens.tracer import record_event

    try:
        record_event(
            type="error",
            name=f"{provider}.chat.completions.create",
            error=f"{type(exc).__name__}: {exc}",
            metadata={
                "provider": provider,
                "api": "chat.completions.create",
                "model": model,
            },
        )
    except RuntimeError:
        pass  # 没有 trace 上下文时静默忽略
