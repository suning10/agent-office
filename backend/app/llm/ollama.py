"""Ollama 客户端：本地测试用对话模型（OpenAI 兼容接口，无需 API Key）。

默认 base_url=http://localhost:11434/v1，模型 qwen3.5:0.8b。
"""
from __future__ import annotations

from typing import Any, Optional

from app.config import Settings
from app.llm.client import LLMClient


class OllamaClient(LLMClient):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            base_url=settings.ollama_base_url,
            # Ollama 不校验 key；占位以通过基类的“未配置 Key”检查
            api_key="ollama",
            model=settings.ollama_model,
            timeout=settings.ollama_timeout,
            temperature=settings.deepseek_temperature,
            max_tokens=settings.deepseek_max_tokens,
        )
        self.reasoning_effort = settings.ollama_reasoning_effort

    def _extra_payload(self) -> dict[str, Any]:
        return {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Any:
        """开启 Ollama JSON 模式：小模型常输出非法 JSON（如未加引号的字符串）。"""
        text = await self.complete(
            messages, temperature=temperature, max_tokens=max_tokens, response_format={"type": "json_object"}
        )
        return self._extract_json(text)

    def name(self) -> str:
        return "ollama"
