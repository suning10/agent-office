# LLM 客户端层

统一 OpenAI 兼容接口（httpx 异步）调用 DeepSeek（或本地 Ollama）；向量与重排在本地运行。

## 文件

- `client.py` —— `LLMClient` 基类：`complete` / `complete_json` / `stream`（SSE）
- `deepseek.py` —— DeepSeek 主力对话模型（`deepseek-v4-flash`）
- `ollama.py` —— 本地 Ollama 对话模型（`LLM_PROVIDER=ollama`，默认关闭思考）
- `embeddings.py` —— 向量模型（本地 sentence-transformers `BAAI/bge-m3` / 确定性 hash 回退）

## 约定

- 对话模型：DeepSeek（`DEEPSEEK_*` 环境变量）
- Embedding 与 bge reranker：本地 sentence-transformers（`EMBEDDING_*` / `RERANKER_*`），首次运行自动下载模型
- 未配置 Key 时快速失败（抛 `LLMError`），由上层 Agent 降级，不发起网络请求
