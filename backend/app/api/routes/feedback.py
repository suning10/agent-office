"""反馈收集接口（显式反馈）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.schemas import ApiResponse, FeedbackRequest, ImplicitFeedbackRequest
from app.api.deps import require_user
from app.utils import metrics, tracing
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", response_model=ApiResponse)
async def submit_feedback(body: FeedbackRequest, request: Request, user: dict = Depends(require_user)):
    container = request.app.state.container
    traces = await container.store.find("traces", {"session_id": body.session_id})
    owned = [t for t in traces if t.get("user_id") == user["id"]]
    if not body.session_id or not owned:
        raise HTTPException(status_code=404, detail="会话不存在")
    # 反馈必须对应本会话中的一条系统回答，防止伪造任意训练信号。
    matched = [t for t in owned if t.get("query") == body.query and t.get("answer") == body.answer]
    if not matched:
        raise HTTPException(status_code=400, detail="反馈与会话回答不匹配")
    await container.feedback_collector.collect_explicit(
        session_id=body.session_id,
        user_id=user["id"],
        query=body.query,
        answer=body.answer,
        signal=body.signal,
        detail=body.detail,
    )
    metrics.FEEDBACK_TOTAL.labels(kind=body.signal).inc()
    # 显式反馈写回 Langfuse trace，便于按差评筛选并回放问题请求
    tracing.score_trace(
        matched[-1].get("langfuse_trace_id") or "", "user_feedback",
        1.0 if body.signal == "up" else 0.0, comment=body.signal,
    )
    if body.signal == "up":
        metrics.record_adoption("up")
    elif body.signal == "down":
        metrics.record_adoption("down")
    # 更新用户记忆
    await container.user_memory.record_feedback(user["id"], body.signal, body.query)
    if body.signal in {"down", "correction"}:
        await container.job_queue.enqueue("feedback_received", {"feedback_user": user["id"]})
    return ApiResponse(data={"received": body.signal})


@router.post("/implicit", response_model=ApiResponse)
async def submit_implicit_feedback(
    body: ImplicitFeedbackRequest, request: Request, user: dict = Depends(require_user)
):
    if body.signal not in {"copy", "follow_up", "abandon"}:
        raise HTTPException(status_code=400, detail="非法隐式反馈类型")
    container = request.app.state.container
    traces = await container.store.find("traces", {"session_id": body.session_id})
    if not any(t.get("user_id") == user["id"] for t in traces):
        raise HTTPException(status_code=404, detail="会话不存在")
    await container.feedback_collector.collect_implicit(
        body.session_id, user["id"], body.query, body.answer, body.signal, body.detail
    )
    if body.signal in {"follow_up", "abandon"}:
        await container.job_queue.enqueue("feedback_received", {"feedback_user": user["id"]})
    return ApiResponse(data={"received": body.signal})
