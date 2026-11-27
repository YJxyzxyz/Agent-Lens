"""通用 OpenAI-compatible API 自动追踪集成。

通过 monkey-patch ``Completions.create`` 与 ``AsyncCompletions.create``
实现对所有兼容 OpenAI API 格式的 LLM provider 的自动 trace。

支持同步 ``OpenAI`` 与异步 ``AsyncOpenAI``，以及 ``stream=True``。
兼容 DeepSeek / OpenAI / 任何兼容 ``/v1/chat/completions`` 的 provider。
"""

from __future__ import annotations

import inspect
import time
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from agentlens.context import (
    get_current_parent_event_id,
    get_current_run_id,
    get_current_store,
)
from agentlens.events import TraceEvent
from agentlens.serialization import REDACTED, safe_serialize, sanitize_mapping
from agentlens.storage import JsonlTraceStore

# ---------------------------------------------------------------------------
# 模块级状态
# ---------------------------------------------------------------------------

_original_create: Any = None
"""保存原始同步 ``Completions.create`` 方法。"""

_original_acreate: Any = None
"""保存原始异步 ``AsyncCompletions.create`` 方法。"""

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

    分别 monkey-patch 同步 ``Completions.create`` 与异步 ``AsyncCompletions.create``。
    异步路径是真正的协程，只 ``await`` 原始异步方法，不会调用同步方法，也不会阻塞事件循环。

    ``stream=True`` 时返回的流会被包装：用户照常迭代，流结束或中途失败时写入一条 ``llm_call``
    或 ``error`` 事件。

    重复调用不会重复 patch。

    Args:
        provider: Provider 名称，如 ``"deepseek"``、``"openai"``。
        base_url_patterns: 可选的 base_url 匹配模式列表（当前版本未使用，保留扩展）。

    Raises:
        ImportError: 未安装 ``openai`` 包。
    """
    global _patched, _original_create, _original_acreate  # noqa: PLW0603

    if _patched:
        return

    completions_cls, async_completions_cls = _import_completion_classes()

    _original_create = completions_cls.create
    _original_acreate = async_completions_cls.create if async_completions_cls is not None else None
    _patched = True

    def _patched_create(self_comp: Any, *args: Any, **kwargs: Any) -> Any:
        """替换后的同步 create。只调用保存下来的同步原方法。"""
        if get_current_run_id() is None:
            return _original_create(self_comp, *args, **kwargs)

        run_id, store, parent_event_id = _capture_context()
        model = _requested_model(kwargs, provider)
        safe_input = _build_safe_input(kwargs)
        base_meta = _base_metadata(provider, model, self_comp)
        started_at = datetime.now(timezone.utc)
        perf_start = time.perf_counter()

        try:
            response = _original_create(self_comp, *args, **kwargs)
        except Exception as exc:
            ended_at = datetime.now(timezone.utc)
            _write_error(
                store,
                run_id,
                provider=provider,
                model=model,
                exc=exc,
                metadata=_with_duration(base_meta, started_at, ended_at),
                started_at=started_at,
                ended_at=ended_at,
                parent_event_id=parent_event_id,
            )
            raise

        if kwargs.get("stream") is True and _is_sync_stream(response):
            return _TracedSyncStream(
                response,
                perf_start=perf_start,
                on_finalize=lambda summary, error, completed, ttft_ms: _finalize_stream(
                    store,
                    run_id,
                    provider=provider,
                    model=model,
                    safe_input=safe_input,
                    base_meta=base_meta,
                    started_at=started_at,
                    summary=summary,
                    error=error,
                    completed=completed,
                    ttft_ms=ttft_ms,
                    parent_event_id=parent_event_id,
                ),
            )

        _write_success(
            store,
            run_id,
            model=model,
            safe_input=safe_input,
            response=response,
            base_meta=base_meta,
            started_at=started_at,
            parent_event_id=parent_event_id,
        )
        return response

    async def _patched_acreate(self_comp: Any, *args: Any, **kwargs: Any) -> Any:
        """替换后的异步 create。只 await 保存下来的异步原方法。"""
        if get_current_run_id() is None:
            return await _maybe_await(_original_acreate(self_comp, *args, **kwargs))

        run_id, store, parent_event_id = _capture_context()
        model = _requested_model(kwargs, provider)
        safe_input = _build_safe_input(kwargs)
        base_meta = _base_metadata(provider, model, self_comp)
        started_at = datetime.now(timezone.utc)
        perf_start = time.perf_counter()

        try:
            response = await _maybe_await(_original_acreate(self_comp, *args, **kwargs))
        except Exception as exc:
            ended_at = datetime.now(timezone.utc)
            _write_error(
                store,
                run_id,
                provider=provider,
                model=model,
                exc=exc,
                metadata=_with_duration(base_meta, started_at, ended_at),
                started_at=started_at,
                ended_at=ended_at,
                parent_event_id=parent_event_id,
            )
            raise

        if kwargs.get("stream") is True and _is_async_stream(response):
            return _TracedAsyncStream(
                response,
                perf_start=perf_start,
                on_finalize=lambda summary, error, completed, ttft_ms: _finalize_stream(
                    store,
                    run_id,
                    provider=provider,
                    model=model,
                    safe_input=safe_input,
                    base_meta=base_meta,
                    started_at=started_at,
                    summary=summary,
                    error=error,
                    completed=completed,
                    ttft_ms=ttft_ms,
                    parent_event_id=parent_event_id,
                ),
            )

        _write_success(
            store,
            run_id,
            model=model,
            safe_input=safe_input,
            response=response,
            base_meta=base_meta,
            started_at=started_at,
            parent_event_id=parent_event_id,
        )
        return response

    completions_cls.create = _patched_create
    if async_completions_cls is not None:
        async_completions_cls.create = _patched_acreate


def uninstrument_openai_compatible() -> None:
    """恢复原始同步与异步 ``create`` 方法，停用自动追踪。"""
    global _patched, _original_create, _original_acreate  # noqa: PLW0603

    if not _patched:
        return

    completions_cls, async_completions_cls = _import_completion_classes(optional=True)
    if completions_cls is not None and _original_create is not None:
        completions_cls.create = _original_create
    if async_completions_cls is not None and _original_acreate is not None:
        async_completions_cls.create = _original_acreate

    _original_create = None
    _original_acreate = None
    _patched = False


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _import_completion_classes(*, optional: bool = False) -> tuple[Any, Any]:
    """导入同步与异步 Completions 类。

    Args:
        optional: 为 True 时导入失败返回 ``(None, None)``，而不是抛错。
    """
    try:
        from openai.resources.chat import completions as completions_mod
    except ImportError:
        if optional:
            return None, None
        raise ImportError(
            "未安装 openai 包。请运行:\n"
            "  pip install agentlens[openai-compatible]\n"
            "或:\n"
            "  pip install openai"
        ) from None

    completions_cls = getattr(completions_mod, "Completions", None)
    async_cls = getattr(completions_mod, "AsyncCompletions", None)
    if completions_cls is None and not optional:
        raise ImportError(
            "未安装 openai 包。请运行:\n"
            "  pip install agentlens[openai-compatible]\n"
            "或:\n"
            "  pip install openai"
        )
    return completions_cls, async_cls


async def _maybe_await(value: Any) -> Any:
    """await 协程；同步返回值原样传回。

    OpenAI SDK 的 ``@required_args`` 会把异步 ``create`` 包成同步函数，
    调用后得到协程对象。测试里的假实现则可能直接返回响应。
    """
    if inspect.isawaitable(value):
        return await value
    return value


def _capture_context() -> tuple[str | None, JsonlTraceStore | None, str | None]:
    """读取当前 trace 的 run_id、store 与父事件。

    流式响应可能在上下文退出后才消费完，所以父事件在调用开始时捕获。
    之后即使当前 contextvar 变成了别的 run 或别的 span，这条 llm_call
    仍然挂在发起调用的那次 run 的父事件上。
    """
    return get_current_run_id(), get_current_store(), get_current_parent_event_id()


def _requested_model(kwargs: dict[str, Any], provider: str) -> str:
    """从请求参数取模型名，缺失时回退到 provider。"""
    model = kwargs.get("model", provider)
    if not isinstance(model, str) or not model:
        return provider
    return model


def _base_metadata(provider: str, model: str, resource: Any) -> dict[str, Any]:
    """构造 llm_call / error 共用的 metadata。"""
    meta: dict[str, Any] = {
        "provider": provider,
        "api": "chat.completions.create",
        "model": model,
    }
    endpoint = _endpoint_metadata(resource)
    if endpoint is not None:
        meta["endpoint"] = endpoint
    return meta


def _endpoint_metadata(resource: Any) -> dict[str, str] | None:
    """从客户端 base_url 提取 host 与 path。

    不记录用户名、密码、query（可能含 api key）。
    """
    client = getattr(resource, "_client", None)
    if client is None:
        return None
    base_url = getattr(client, "base_url", None)
    if base_url is None:
        return None
    parts = urlsplit(str(base_url))
    if not parts.hostname:
        return None
    host = parts.hostname
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    return {"host": host, "path": parts.path or ""}


def _duration_ms(started_at: datetime, ended_at: datetime) -> int:
    """计算毫秒耗时，不为负数。"""
    return max(0, int((ended_at - started_at).total_seconds() * 1000))


def _with_duration(
    base_meta: dict[str, Any],
    started_at: datetime,
    ended_at: datetime,
) -> dict[str, Any]:
    """复制 metadata 并写入 duration_ms。"""
    meta = dict(base_meta)
    meta["duration_ms"] = _duration_ms(started_at, ended_at)
    return meta


def _write_event(
    store: JsonlTraceStore | None,
    run_id: str | None,
    *,
    type: str,
    name: str,
    input: Any | None = None,
    output: Any | None = None,
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    parent_event_id: str | None = None,
) -> None:
    """把事件写入发起调用时捕获的 store。没有上下文时静默跳过。"""
    if store is None or run_id is None:
        return
    now = datetime.now(timezone.utc)
    event = TraceEvent(
        run_id=run_id,
        parent_event_id=parent_event_id,
        type=type,  # type: ignore[arg-type]
        name=name,
        input=input,
        output=output,
        metadata=metadata or {},
        error=error,
        started_at=started_at or now,
        ended_at=ended_at or now,
    )
    store.append_event(event)


def _write_success(
    store: JsonlTraceStore | None,
    run_id: str | None,
    *,
    model: str,
    safe_input: dict[str, Any],
    response: Any,
    base_meta: dict[str, Any],
    started_at: datetime,
    parent_event_id: str | None = None,
) -> None:
    """记录一次非流式 llm_call。"""
    ended_at = datetime.now(timezone.utc)
    safe_output = _build_safe_output(response)
    meta = _with_duration(base_meta, started_at, ended_at)
    meta["stream"] = False
    meta["usage"] = _extract_usage(response)
    response_model = safe_output.get("model") if isinstance(safe_output, dict) else None
    if isinstance(response_model, str) and response_model:
        meta["response_model"] = response_model
    _write_event(
        store,
        run_id,
        type="llm_call",
        name=model,
        input=safe_input,
        output=safe_output,
        metadata=meta,
        started_at=started_at,
        ended_at=ended_at,
        parent_event_id=parent_event_id,
    )


def _write_error(
    store: JsonlTraceStore | None,
    run_id: str | None,
    *,
    provider: str,
    model: str,
    exc: BaseException,
    metadata: dict[str, Any],
    started_at: datetime,
    ended_at: datetime,
    output: Any | None = None,
    parent_event_id: str | None = None,
) -> None:
    """记录 error 事件。追踪失败不应覆盖原始异常，因此吞掉写入错误。"""
    try:
        _write_event(
            store,
            run_id,
            type="error",
            name=f"{provider}.chat.completions.create",
            output=output,
            metadata=metadata,
            error=f"{type(exc).__name__}: {exc}",
            started_at=started_at,
            ended_at=ended_at,
            parent_event_id=parent_event_id,
        )
    except Exception:
        return


def _finalize_stream(
    store: JsonlTraceStore | None,
    run_id: str | None,
    *,
    provider: str,
    model: str,
    safe_input: dict[str, Any],
    base_meta: dict[str, Any],
    started_at: datetime,
    summary: dict[str, Any],
    error: BaseException | None,
    completed: bool,
    ttft_ms: int | None,
    parent_event_id: str | None = None,
) -> None:
    """流结束或失败时写一条事件。"""
    ended_at = datetime.now(timezone.utc)
    safe_output = safe_serialize(summary, max_string_length=4000)
    meta = _with_duration(base_meta, started_at, ended_at)
    meta["stream"] = True
    meta["stream_completed"] = completed
    if ttft_ms is not None:
        meta["ttft_ms"] = ttft_ms
    usage = summary.get("usage") if isinstance(summary, dict) else None
    if usage:
        meta["usage"] = safe_serialize(usage)
    response_model = summary.get("model") if isinstance(summary, dict) else None
    if isinstance(response_model, str) and response_model:
        meta["response_model"] = response_model

    if error is not None:
        _write_error(
            store,
            run_id,
            provider=provider,
            model=model,
            exc=error,
            metadata=meta,
            started_at=started_at,
            ended_at=ended_at,
            output=safe_output,
            parent_event_id=parent_event_id,
        )
        return

    try:
        _write_event(
            store,
            run_id,
            type="llm_call",
            name=model,
            input=safe_input,
            output=safe_output,
            metadata=meta,
            started_at=started_at,
            ended_at=ended_at,
            parent_event_id=parent_event_id,
        )
    except Exception:
        return


def _build_safe_input(kwargs: dict[str, Any]) -> dict[str, Any]:
    """从请求参数构建安全的 input 字典，脱敏并序列化。"""
    safe_kwargs = sanitize_mapping(kwargs)
    serialized = safe_serialize(safe_kwargs, max_string_length=4000)
    if isinstance(serialized, dict):
        return serialized
    return {"value": serialized}


def _build_safe_output(response: Any) -> dict[str, Any]:
    """从原始响应对象提取安全摘要。"""
    try:
        raw = response.model_dump(mode="json")
    except AttributeError:
        raw = {"raw": repr(response)}
    except Exception:
        raw = {"raw": repr(response)}

    if not isinstance(raw, dict):
        return {"raw": repr(response)[:4000]}

    summary: dict[str, Any] = {}
    for field in ("id", "model", "created", "usage"):
        if field in raw:
            summary[field] = raw[field]

    choices: list[dict[str, Any]] = []
    for choice in raw.get("choices", []) or []:
        if not isinstance(choice, dict):
            continue
        msg = choice.get("message") or {}
        if not isinstance(msg, dict):
            msg = {}
        content = msg.get("content", "")
        if isinstance(content, str):
            content = content[:4000] + "..." if len(content) > 4000 else content
        message: dict[str, Any] = {"role": msg.get("role"), "content": content}
        tool_calls = _safe_tool_calls(msg.get("tool_calls"))
        if tool_calls:
            message["tool_calls"] = tool_calls
        choices.append(
            {
                "index": choice.get("index"),
                "finish_reason": choice.get("finish_reason"),
                "message": message,
            }
        )
    summary["choices"] = choices

    serialized = safe_serialize(summary, max_string_length=4000)
    if isinstance(serialized, dict):
        return serialized
    return {"raw": serialized}


def _safe_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
    """只保留 tool call 的 id 与 name，参数一律脱敏。"""
    if not isinstance(tool_calls, list):
        return []
    safe: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function") or {}
        if not isinstance(function, dict):
            function = {}
        item: dict[str, Any] = {
            "id": tool_call.get("id"),
            "name": function.get("name"),
        }
        if "arguments" in function or "arguments" in tool_call:
            item["arguments"] = REDACTED
        safe.append(item)
    return safe


def _extract_usage(response: Any) -> dict[str, Any] | None:
    """从响应中提取 usage 信息。"""
    try:
        raw = response.model_dump(mode="json")
        if not isinstance(raw, dict):
            return None
        usage = raw.get("usage")
        if usage:
            serialized = safe_serialize(usage)
            if isinstance(serialized, dict):
                return serialized
    except Exception:
        return None
    return None


def _as_dict(chunk: Any) -> dict[str, Any]:
    """把流式 chunk 转成 dict。无法转换时返回空 dict。"""
    if isinstance(chunk, dict):
        return chunk
    dump = getattr(chunk, "model_dump", None)
    if not callable(dump):
        return {}
    try:
        raw = dump(mode="json")
    except TypeError:
        try:
            raw = dump()
        except Exception:
            return {}
    except Exception:
        return {}
    if isinstance(raw, dict):
        return raw
    return {}


def _is_sync_stream(obj: Any) -> bool:
    """判断对象是不是可迭代的同步流。排除 Mock 与普通容器。"""
    if obj is None or isinstance(obj, str | bytes | dict | list | tuple):
        return False
    if "Mock" in type(obj).__name__:
        return False
    return hasattr(obj, "__next__") and hasattr(obj, "__iter__")


def _is_async_stream(obj: Any) -> bool:
    """判断对象是不是异步流。排除 Mock。"""
    if obj is None or isinstance(obj, str | bytes | dict | list | tuple):
        return False
    if "Mock" in type(obj).__name__:
        return False
    return hasattr(obj, "__anext__") or inspect.isasyncgen(obj)


class _StreamAggregator:
    """把流式 chunk 折叠成一条逻辑 llm_call 的输出摘要。"""

    def __init__(self) -> None:
        self.id: str | None = None
        self.model: str | None = None
        self.created: Any = None
        self.usage: Any = None
        self._contents: dict[int, str] = {}
        self._roles: dict[int, str] = {}
        self._finish: dict[int, Any] = {}
        self._tools: dict[int, dict[int, dict[str, Any]]] = {}
        self.saw_token = False

    def observe(self, chunk: Any) -> bool:
        """记录一个 chunk。若这是首个内容或 tool call token，返回 True。"""
        data = _as_dict(chunk)
        if not data:
            return False
        if data.get("id"):
            self.id = str(data["id"])
        if data.get("model"):
            self.model = str(data["model"])
        if data.get("created") is not None:
            self.created = data["created"]
        if data.get("usage"):
            self.usage = data["usage"]

        first = False
        for choice in data.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            index = choice.get("index", 0)
            if not isinstance(index, int):
                index = 0
            if choice.get("finish_reason"):
                self._finish[index] = choice.get("finish_reason")
            delta = choice.get("delta") or choice.get("message") or {}
            if not isinstance(delta, dict):
                continue
            role = delta.get("role")
            if isinstance(role, str) and role:
                self._roles[index] = role
            content = delta.get("content")
            if isinstance(content, str) and content:
                self._contents[index] = self._contents.get(index, "") + content
                if not self.saw_token:
                    first = True
                    self.saw_token = True
            if self._observe_tool_calls(index, delta.get("tool_calls")):
                first = True
        return first

    def _observe_tool_calls(self, choice_index: int, tool_calls: Any) -> bool:
        """合并 tool call 增量。只保留 id 与 name，丢弃 arguments。"""
        if not isinstance(tool_calls, list):
            return False
        first = False
        bucket = self._tools.setdefault(choice_index, {})
        for position, tool_call in enumerate(tool_calls):
            if not isinstance(tool_call, dict):
                continue
            tool_index = tool_call.get("index", position)
            if not isinstance(tool_index, int):
                tool_index = position
            entry = bucket.setdefault(
                tool_index,
                {"id": None, "name": None, "saw_arguments": False},
            )
            if tool_call.get("id"):
                entry["id"] = tool_call.get("id")
                if not self.saw_token:
                    first = True
                    self.saw_token = True
            function = tool_call.get("function") or {}
            if not isinstance(function, dict):
                function = {}
            if function.get("name"):
                entry["name"] = function.get("name")
                if not self.saw_token:
                    first = True
                    self.saw_token = True
            if "arguments" in function or "arguments" in tool_call:
                entry["saw_arguments"] = True
        return first

    def summary(self) -> dict[str, Any]:
        """导出与非流式输出相近的摘要。"""
        indexes = sorted(
            set(self._contents) | set(self._roles) | set(self._finish) | set(self._tools)
        )
        choices: list[dict[str, Any]] = []
        for index in indexes:
            message: dict[str, Any] = {
                "role": self._roles.get(index, "assistant"),
                "content": self._contents.get(index, ""),
            }
            tools = self._tools.get(index)
            if tools:
                message["tool_calls"] = [
                    {
                        "id": tools[tool_index].get("id"),
                        "name": tools[tool_index].get("name"),
                        **(
                            {"arguments": REDACTED}
                            if tools[tool_index].get("saw_arguments")
                            else {}
                        ),
                    }
                    for tool_index in sorted(tools)
                ]
            choices.append(
                {
                    "index": index,
                    "finish_reason": self._finish.get(index),
                    "message": message,
                }
            )
        summary: dict[str, Any] = {"choices": choices}
        if self.id is not None:
            summary["id"] = self.id
        if self.model is not None:
            summary["model"] = self.model
        if self.created is not None:
            summary["created"] = self.created
        if self.usage is not None:
            summary["usage"] = self.usage
        return summary


class _TracedSyncStream:
    """包装同步流，在迭代结束、提前关闭或失败时写一条事件。"""

    def __init__(self, stream: Any, on_finalize: Any, perf_start: float) -> None:
        self._stream = stream
        self._on_finalize = on_finalize
        self._agg = _StreamAggregator()
        self._finalized = False
        self._underlying_closed = False
        self._ttft_ms: int | None = None
        self._perf_start = perf_start

    def __iter__(self) -> Iterator[Any]:
        completed = False
        error: BaseException | None = None
        try:
            try:
                for chunk in self._stream:
                    self._note_chunk(chunk)
                    yield chunk
                completed = True
            except Exception as exc:
                error = exc
                raise
        finally:
            self._finalize(error, completed=completed)
            self._close_underlying()

    def __enter__(self) -> _TracedSyncStream:
        enter = getattr(self._stream, "__enter__", None)
        if enter is not None:
            enter()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        exit_fn = getattr(self._stream, "__exit__", None)
        result = exit_fn(exc_type, exc, tb) if exit_fn is not None else None
        # 用户代码抛出的异常不属于流失败；流自身的异常已在迭代中记录。
        self._finalize(None, completed=False)
        self._close_underlying()
        return result

    def close(self) -> None:
        """关闭底层流，并在尚未记录时补写事件。"""
        self._finalize(None, completed=False)
        self._close_underlying()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)

    def _note_chunk(self, chunk: Any) -> None:
        first = self._agg.observe(chunk)
        if first and self._ttft_ms is None:
            self._ttft_ms = max(0, int((time.perf_counter() - self._perf_start) * 1000))

    def _finalize(self, error: BaseException | None, *, completed: bool) -> None:
        if self._finalized:
            return
        self._finalized = True
        try:
            self._on_finalize(self._agg.summary(), error, completed, self._ttft_ms)
        except Exception:
            return

    def _close_underlying(self) -> None:
        if self._underlying_closed:
            return
        self._underlying_closed = True
        close = getattr(self._stream, "close", None)
        if close is None:
            return
        try:
            close()
        except Exception:
            return


class _TracedAsyncStream:
    """包装异步流，在迭代结束、提前关闭或失败时写一条事件。"""

    def __init__(self, stream: Any, on_finalize: Any, perf_start: float) -> None:
        self._stream = stream
        self._on_finalize = on_finalize
        self._agg = _StreamAggregator()
        self._finalized = False
        self._underlying_closed = False
        self._ttft_ms: int | None = None
        self._perf_start = perf_start

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Any]:
        completed = False
        error: BaseException | None = None
        try:
            try:
                async for chunk in self._stream:
                    self._note_chunk(chunk)
                    yield chunk
                completed = True
            except Exception as exc:
                error = exc
                raise
        finally:
            self._finalize(error, completed=completed)
            await self._aclose_underlying()

    async def __aenter__(self) -> _TracedAsyncStream:
        enter = getattr(self._stream, "__aenter__", None)
        if enter is not None:
            entered = enter()
            if inspect.isawaitable(entered):
                await entered
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        exit_fn = getattr(self._stream, "__aexit__", None)
        result = None
        if exit_fn is not None:
            result = exit_fn(exc_type, exc, tb)
            if inspect.isawaitable(result):
                result = await result
        # 用户代码抛出的异常不属于流失败；流自身的异常已在迭代中记录。
        self._finalize(None, completed=False)
        await self._aclose_underlying()
        return result

    async def close(self) -> None:
        """关闭底层流，并在尚未记录时补写事件。"""
        self._finalize(None, completed=False)
        await self._aclose_underlying()

    async def aclose(self) -> None:
        """``close`` 的别名，与 OpenAI ``AsyncStream`` 对齐。"""
        await self.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)

    def _note_chunk(self, chunk: Any) -> None:
        first = self._agg.observe(chunk)
        if first and self._ttft_ms is None:
            self._ttft_ms = max(0, int((time.perf_counter() - self._perf_start) * 1000))

    def _finalize(self, error: BaseException | None, *, completed: bool) -> None:
        if self._finalized:
            return
        self._finalized = True
        try:
            self._on_finalize(self._agg.summary(), error, completed, self._ttft_ms)
        except Exception:
            return

    async def _aclose_underlying(self) -> None:
        if self._underlying_closed:
            return
        self._underlying_closed = True
        close = getattr(self._stream, "aclose", None)
        if close is None:
            close = getattr(self._stream, "close", None)
        if close is None:
            return
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception:
            return
