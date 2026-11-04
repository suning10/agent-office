"""重排序。

优先级：
1. CrossEncoderReranker —— 本地 sentence-transformers 运行 bge-reranker-v2-m3
2. HeuristicReranker —— 关键词重叠启发式（零成本回退）
"""
from __future__ import annotations

import re
from typing import Any

from app.retrieval.bm25 import tokenize
from app.utils.logging import get_logger

logger = get_logger(__name__)


class Reranker:
    """重排序接口。"""

    async def rerank(self, query: str, candidates: list[dict[str, Any]], top_k: int = 5) -> list[dict[str, Any]]:
        raise NotImplementedError


class HeuristicReranker(Reranker):
    """启发式重排：关键词重叠率 + 条款编号命中加权（零成本回退）。"""

    async def rerank(self, query: str, candidates: list[dict[str, Any]], top_k: int = 5) -> list[dict[str, Any]]:
        q_tokens = set(tokenize(query))
        for c in candidates:
            content = c.get("content", "")
            c_tokens = set(tokenize(content))
            overlap = len(q_tokens & c_tokens) / max(len(q_tokens), 1)
            clause_hit = 1.0 if re.search(r"第[一二三四五六七八九十百0-9]+条", content) else 0.0
            base = float(c.get("score", 0.0))
            c["rerank_score"] = base + 0.3 * overlap + 0.2 * clause_hit
        ranked = sorted(candidates, key=lambda x: x.get("rerank_score", 0.0), reverse=True)
        return ranked[:top_k]


class CrossEncoderReranker(Reranker):
    """本地 cross-encoder 重排（可选，需 sentence-transformers）。"""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3") -> None:
        self.model_name = model_name
        self._model = None

    async def rerank(self, query: str, candidates: list[dict[str, Any]], top_k: int = 5) -> list[dict[str, Any]]:
        if not candidates:
            return []
        try:
            if self._model is None:
                from sentence_transformers import CrossEncoder  # 延迟导入

                self._model = CrossEncoder(self.model_name)
            pairs = [(query, c.get("content", "")) for c in candidates]
            scores = self._model.predict(pairs)
        except Exception as exc:  # noqa: BLE001 - 重排失败回退启发式
            logger.warning("本地 rerank 失败(%s)，回退启发式", exc)
            return await HeuristicReranker().rerank(query, candidates, top_k)
        for c, s in zip(candidates, scores):
            c["rerank_score"] = float(s)
        ranked = sorted(candidates, key=lambda x: x.get("rerank_score", 0.0), reverse=True)
        return ranked[:top_k]


def build_reranker(enabled: bool, model_name: str = "BAAI/bge-reranker-v2-m3") -> Reranker:
    if enabled:
        try:
            import sentence_transformers  # noqa: F401

            return CrossEncoderReranker(model_name)
        except ImportError:
            logger.warning("未安装 sentence-transformers，回退启发式重排")
    return HeuristicReranker()
