"""LangChain callback handler integration.

通过 LangChain callback 自动将 chain / LLM / tool 事件记录到 AgentLens trace run。

``AgentLensCallbackHandler`` 在安装了 ``langchain-core`` 时继承
``BaseCallbackHandler``，可以直接放进 Runnable 的 ``callbacks``。
未安装 ``langchain-core`` 时退化为普通对象，导入本模块不会失败。
``LangChainCallbackHandler`` 是同一个类的别名。

``serialized`` 为 ``None``（例如 ``RunnableLambda``）时不会抛出
``AttributeError``，事件名回退为 ``langchain.llm``、``langchain.chain``、
``langchain.tool``。

用法::

    from agentlens import trace
    from agentlens.integrations.langchain import LangChainCallbackHandler

    handler = LangChainCallbackHandler()

    @trace("langchain-demo")
    def run():
        return chain.invoke(
            {"question": "..."},
            config={"callbacks": [handler]},
        )

    run()
"""

from __future__ import annotations

import sys
import time
from typing import Any
from uuid import UUID

# ---------------------------------------------------------------------------
# Optional base class — 不安装 langchain-core 时导入本模块不会立刻崩溃
# ---------------------------------------------------------------------------


_LANGCHAIN_IMPORT_ERROR = (
    "未安装 langchain-core。请运行:\n"
    "  pip install agentlens[langchain]\n"
    "或:\n"
    "  pip install langchain-core"
)


def _get_base_handler() -> type:
    """获取 langchain BaseCallbackHandler，未安装时抛出 ImportError。"""
    # 父包被标成不可用时，即使子模块还留在缓存里，也视为未安装。
    if "langchain_core" in sys.modules and sys.modules["langchain_core"] is None:
        raise ImportError(_LANGCHAIN_IMPORT_ERROR)
    try:
        from langchain_core.callbacks.base import (  # type: ignore[import-untyped,unused-ignore]
            BaseCallbackHandler,
        )
    except ImportError:
        raise ImportError(_LANGCHAIN_IMPORT_ERROR) from None
    return BaseCallbackHandler


try:
    _CallbackHandlerBase = _get_base_handler()
except ImportError:
    _CallbackHandlerBase = object


def _serialized_dict(state: dict[str, Any]) -> dict[str, Any]:
    """取出 serialized 字典。

    LangChain 对部分 Runnable（例如 RunnableLambda）传入 ``serialized=None``。
    这时返回空字典，调用方再用默认事件名。
    """
    serialized = state.get("serialized")
    if isinstance(serialized, dict):
        return serialized
    return {}


# ---------------------------------------------------------------------------
# Callback Handler
# ---------------------------------------------------------------------------


class AgentLensCallbackHandler(_CallbackHandlerBase):  # type: ignore[misc, valid-type]
    """LangChain callback handler — 将 LangChain 事件写入 AgentLens trace。

    安装了 langchain-core 时继承 ``BaseCallbackHandler``。未安装时基类是
    ``object``，导入本模块仍然成功；实例化会抛出 ImportError。
    ``LangChainCallbackHandler`` 是本类的别名。

    记录的事件:
    - on_llm_start/end → llm_call 事件（默认名 ``langchain.llm``）
    - on_chain_start/end → tool_call 事件（默认名 ``langchain.chain``）
    - on_tool_start/end → tool_call 事件（默认名 ``langchain.tool``）
    - on_*_error → error 事件

    ``serialized`` 为 None（例如 RunnableLambda）时使用上面的默认名。
    """

    def __init__(self) -> None:
        """初始化 handler。

        Raises:
            ImportError: 未安装 langchain-core。
        """
        _get_base_handler()  # 验证依赖可用
        self._runs: dict[str, dict[str, Any]] = {}

    # -- LLM callbacks -------------------------------------------------------

    def on_llm_start(
        self,
        serialized: dict[str, Any] | None,
        prompts: list[str],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """LLM 开始。"""
        self._runs[str(run_id)] = {
            "type": "llm",
            "serialized": serialized,
            "prompts": prompts,
            "started_at": time.time() * 1000,
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "tags": tags or [],
            "metadata": metadata or {},
        }

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """LLM 结束 → 记录 llm_call 事件。"""
        rid = str(run_id)
        state = self._runs.pop(rid, None)
        if state is None:
            state = {}
        self._record_llm_event(rid, state, response=response, error=None)

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """LLM 错误 → 记录 error 事件。"""
        rid = str(run_id)
        state = self._runs.pop(rid, None)
        if state is None:
            state = {}
        self._record_llm_event(rid, state, response=None, error=error)

    # -- Chain callbacks -----------------------------------------------------

    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Chain 开始。"""
        self._runs[str(run_id)] = {
            "type": "chain",
            "serialized": serialized,
            "inputs": inputs,
            "started_at": time.time() * 1000,
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "tags": tags or [],
            "metadata": metadata or {},
        }

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Chain 结束 → 记录 tool_call 事件。"""
        rid = str(run_id)
        state = self._runs.pop(rid, None)
        if state is None:
            state = {}
        self._record_chain_event(rid, state, outputs=outputs, error=None)

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Chain 错误 → 记录 error 事件。"""
        rid = str(run_id)
        state = self._runs.pop(rid, None)
        if state is None:
            state = {}
        self._record_chain_event(rid, state, outputs=None, error=error)

    # -- Tool callbacks ------------------------------------------------------

    def on_tool_start(
        self,
        serialized: dict[str, Any] | None,
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Tool 开始。"""
        self._runs[str(run_id)] = {
            "type": "tool",
            "serialized": serialized,
            "input_str": input_str,
            "started_at": time.time() * 1000,
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "tags": tags or [],
            "metadata": metadata or {},
        }

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Tool 结束 → 记录 tool_call 事件。"""
        rid = str(run_id)
        state = self._runs.pop(rid, None)
        if state is None:
            state = {}
        self._record_tool_event(rid, state, output=output, error=None)

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Tool 错误 → 记录 error 事件。"""
        rid = str(run_id)
        state = self._runs.pop(rid, None)
        if state is None:
            state = {}
        self._record_tool_event(rid, state, output=None, error=error)

    # -- 内部记录方法 --------------------------------------------------------

    def _record_llm_event(
        self,
        run_id: str,
        state: dict[str, Any],
        response: Any,
        error: BaseException | None,
    ) -> None:
        """写入 llm_call 或 error 事件。"""
        from agentlens.context import get_current_run_id
        from agentlens.serialization import safe_serialize

        if get_current_run_id() is None:
            return

        raw_kwargs = _serialized_dict(state).get("kwargs")
        kwargs = raw_kwargs if isinstance(raw_kwargs, dict) else {}
        model = kwargs.get("model", "langchain.llm")
        if not isinstance(model, str):
            model = "langchain.llm"

        started_at = state.get("started_at", 0)
        duration_ms = int(time.time() * 1000 - started_at) if started_at else None
        meta = {
            "provider": "langchain",
            "run_id": run_id,
            "parent_run_id": state.get("parent_run_id"),
            "tags": state.get("tags", []),
        }
        if duration_ms is not None:
            meta["duration_ms"] = duration_ms

        if error is not None:
            self._emit_error(
                name="langchain.llm",
                error=error,
                metadata=meta,
            )
        else:
            from agentlens.tracer import record_llm_call

            safe_input = safe_serialize({"prompts": state.get("prompts", [])})
            safe_output = safe_serialize(_safe_repr(response))
            record_llm_call(
                model=str(model),
                input=safe_input,
                output=safe_output,
                metadata=meta,
            )

    def _record_chain_event(
        self,
        run_id: str,
        state: dict[str, Any],
        outputs: dict[str, Any] | None,
        error: BaseException | None,
    ) -> None:
        """写入 tool_call 或 error 事件（chain）。"""
        from agentlens.context import get_current_run_id
        from agentlens.serialization import safe_serialize

        if get_current_run_id() is None:
            return

        name = _serialized_dict(state).get("name", "langchain.chain")
        if not name:
            name = "langchain.chain"

        started_at = state.get("started_at", 0)
        duration_ms = int(time.time() * 1000 - started_at) if started_at else None
        meta = {
            "provider": "langchain",
            "run_id": run_id,
            "parent_run_id": state.get("parent_run_id"),
            "tags": state.get("tags", []),
        }
        if duration_ms is not None:
            meta["duration_ms"] = duration_ms

        if error is not None:
            self._emit_error(name=str(name), error=error, metadata=meta)
        else:
            from agentlens.tracer import record_tool_call

            safe_input = safe_serialize(state.get("inputs", {}))
            safe_output = safe_serialize(outputs) if outputs else None
            record_tool_call(
                name=str(name),
                input=safe_input,
                output=safe_output,
                metadata=meta,
            )

    def _record_tool_event(
        self,
        run_id: str,
        state: dict[str, Any],
        output: Any,
        error: BaseException | None,
    ) -> None:
        """写入 tool_call 或 error 事件（tool）。"""
        from agentlens.context import get_current_run_id
        from agentlens.serialization import safe_serialize

        if get_current_run_id() is None:
            return

        name = _serialized_dict(state).get("name", "langchain.tool")
        if not name:
            name = "langchain.tool"

        started_at = state.get("started_at", 0)
        duration_ms = int(time.time() * 1000 - started_at) if started_at else None
        meta = {
            "provider": "langchain",
            "run_id": run_id,
            "parent_run_id": state.get("parent_run_id"),
            "tags": state.get("tags", []),
        }
        if duration_ms is not None:
            meta["duration_ms"] = duration_ms

        if error is not None:
            self._emit_error(name=str(name), error=error, metadata=meta)
        else:
            from agentlens.tracer import record_tool_call

            safe_input = safe_serialize({"input": state.get("input_str", "")})
            safe_output = safe_serialize(_safe_repr(output))
            record_tool_call(
                name=str(name),
                input=safe_input,
                output=safe_output,
                metadata=meta,
            )

    @staticmethod
    def _emit_error(
        name: str,
        error: BaseException,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """记录 error 事件。"""
        from agentlens.tracer import record_event

        try:
            record_event(
                type="error",
                name=name,
                error=f"{type(error).__name__}: {error}",
                metadata=metadata or {},
            )
        except RuntimeError:
            pass  # 没有 trace 上下文


# issue #2 使用的公开名称，与 AgentLensCallbackHandler 是同一个类。
LangChainCallbackHandler = AgentLensCallbackHandler


def _safe_repr(obj: Any) -> Any:
    """安全转换任意对象为可序列化的值。"""
    if obj is None:
        return None
    if isinstance(obj, str | int | float | bool):
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe_repr(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_safe_repr(v) for v in obj]
    try:
        return str(obj)[:2000]
    except Exception:
        return f"<{type(obj).__name__}>"
