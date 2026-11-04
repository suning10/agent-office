"""LLM 客户端层。

- DeepSeekClient：主力对话模型（https://api.deepseek.com）
- OllamaClient：本地测试对话模型（http://localhost:11434/v1）
- EmbeddingClient：向量模型（默认本地 sentence-transformers 运行 bge-m3）
"""
from app.llm.client import LLMClient, LLMError
from app.config import Settings
from app.llm.deepseek import DeepSeekClient
from app.llm.embeddings import EmbeddingClient
from app.llm.ollama import OllamaClient


def build_llm_client(settings: Settings) -> LLMClient:
    """按 LLM_PROVIDER 构建对话模型客户端。"""
    provider = settings.llm_provider.lower()
    if provider == "ollama":
        return OllamaClient(settings)
    if provider != "deepseek":
        raise ValueError(f"未知 LLM_PROVIDER: {settings.llm_provider}（可选 deepseek | ollama）")
    return DeepSeekClient(settings)


__all__ = [
    "LLMClient",
    "LLMError",
    "DeepSeekClient",
    "OllamaClient",
    "build_llm_client",
    "EmbeddingClient",
]
