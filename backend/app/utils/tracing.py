"""Langfuse 链路追踪：记录每次问答的 Agent DAG 与 LLM 调用（输入/输出/token/耗时）。

未配置 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 或 LANGFUSE_ENABLED=false 时全部为 no-op，
业务代码无需判断开关。与 Prometheus 指标互补：指标看聚合趋势，Langfuse 看单次请求明细。
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from typing import Any, Callable, Iterator, Optional, TypeVar

from app.config import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

_client: Any = None
_enabled = False


def _ensure_client() -> bool:
    """懒初始化 Langfuse 单例；返回是否启用追踪。"""
    global _client, _enabled
    if _client is not None:
        return _enabled
    settings = get_settings()
    _enabled = bool(settings.langfuse_enabled and settings.langfuse_public_key and settings.langfuse_secret_key)
    if not _enabled:
        # 禁用时不创建客户端，observe 直接返回原函数（避免 SDK 无 key 告警）
        _client = False
        return False
    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_host,
            environment=settings.langfuse_environment,
            sample_rate=settings.langfuse_sample_rate,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Langfuse 初始化失败(%s)，追踪已禁用", exc)
        _client, _enabled = False, False
    if _enabled:
        logger.info("Langfuse 追踪已启用: %s", settings.langfuse_host)
    return _enabled


def enabled() -> bool:
    return _ensure_client()


def observe(name: Optional[str] = None, as_type: Optional[str] = None, **kwargs: Any) -> Callable[[F], F]:
    """包装 langfuse.observe：自动记录函数入参/返回值为一个 observation。"""

    def decorator(func: F) -> F:
        _ensure_client()
        if _client is False:
            return func
        from langfuse import observe as lf_observe

        return lf_observe(name=name, as_type=as_type, **kwargs)(func)

    return decorator


@contextmanager
def observation(name: str, as_type: str = "span", **kwargs: Any) -> Iterator[Any]:
    """以当前上下文为父节点开启 observation；禁用时 yield None。"""
    if not _ensure_client():
        yield None
        return
    with _client.start_as_current_observation(name=name, as_type=as_type, **kwargs) as obs:
        yield obs


def start_generation(name: str, **kwargs: Any) -> Any:
    """开启不切换上下文的 generation（用于 async generator，避免跨 yield 的 context 泄漏）。需手动 end()。"""
    if not _ensure_client():
        return None
    return _client.start_observation(name=name, as_type="generation", **kwargs)


def update(obs: Any, **kwargs: Any) -> None:
    if obs is not None:
        obs.update(**kwargs)


def trace_attributes(
    session_id: Optional[str] = None, user_id: Optional[str] = None, **kwargs: Any
) -> Any:
    """把 session_id / user_id 等传播到当前及后续所有子 observation（Langfuse 按会话/用户聚合）。"""
    if not _ensure_client():
        return nullcontext()
    from langfuse import propagate_attributes

    return propagate_attributes(session_id=session_id, user_id=user_id, **kwargs)


def current_trace_id() -> Optional[str]:
    if not _ensure_client():
        return None
    return _client.get_current_trace_id()


def score_trace(trace_id: str, name: str, value: float, comment: Optional[str] = None) -> None:
    """把用户反馈（点赞/点踩）作为分数写回对应 trace。"""
    if not trace_id or not _ensure_client():
        return
    try:
        _client.create_score(trace_id=trace_id, name=name, value=value, comment=comment)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Langfuse 打分失败: %s", exc)


def usage_from_openai(data: dict[str, Any]) -> Optional[dict[str, int]]:
    """OpenAI 兼容响应的 usage → Langfuse usage_details。"""
    usage = data.get("usage") or {}
    if not usage:
        return None
    details = {
        "input": int(usage.get("prompt_tokens") or 0),
        "output": int(usage.get("completion_tokens") or 0),
    }
    # DeepSeek 的 prompt_tokens 含缓存命中部分，拆开以免 Langfuse 汇总 total 时重复计数
    cache_hit = int(usage.get("prompt_cache_hit_tokens") or 0)
    if cache_hit:
        details["input"] -= cache_hit
        details["input_cache_read"] = cache_hit
    return details


def flush() -> None:
    if _client:
        try:
            _client.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse flush 失败: %s", exc)


def shutdown() -> None:
    if _client:
        try:
            _client.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse shutdown 失败: %s", exc)
