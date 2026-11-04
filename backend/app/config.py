"""集中配置：从环境变量 / .env 读取。

对话模型：DeepSeek（默认）或本地 Ollama（LLM_PROVIDER=ollama，开发测试用）；
Embedding / 重排在本地运行（sentence-transformers 或 Ollama）。
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 从 backend/ 本地运行时读仓库根目录的 .env；后者优先级更高
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore")

    # ---- 服务 ----
    app_name: str = "文枢 · 跨部门文档处理与问答助手"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    # 显式列出允许的前端来源（生产替换为实际域名）；带凭据请求不允许通配符
    cors_origins: str = "http://localhost:3000,http://localhost:8080"
    api_prefix: str = "/api/v1"

    # ---- 对话模型提供方：deepseek | ollama ----
    llm_provider: str = "deepseek"

    # ---- DeepSeek（主力对话模型） ----
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_temperature: float = 0.1
    deepseek_max_tokens: int = 2048
    deepseek_timeout: float = 60.0

    # ---- Ollama（本地测试：对话 + 可选 Embedding，OpenAI 兼容接口） ----
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3.5:0.8b"
    ollama_timeout: float = 120.0
    # 思考模型（qwen3.5 等）默认会把 max_tokens 全耗在 reasoning 上导致 content 为空，默认关闭
    ollama_reasoning_effort: str = "none"

    # ---- Embedding ----
    # provider: local（sentence-transformers）| ollama（EMBEDDING_MODEL=nomic-embed-text, DIM=768）
    #           | hash（离线确定性向量，仅开发/测试）
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024

    # ---- 存储 ----
    storage_mode: str = "mongo"  # mongo | memory
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "wenshu"
    redis_addr: str = "redis://localhost:6379"
    redis_db: int = 0
    async_stream_name: str = "wenshu:jobs"
    upload_storage_dir: str = "/tmp/wenshu-uploads"

    # ---- 检索 ----
    vector_backend: str = "memory"  # memory | mongo | chroma | milvus
    hybrid_topk: int = 5
    bm25_top: int = 20
    vector_top: int = 20
    reranker_enabled: bool = True
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # ---- Langfuse 链路追踪（未配置 key 时自动禁用） ----
    langfuse_enabled: bool = True
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_environment: str = "development"
    langfuse_sample_rate: float = 1.0

    # ---- pi 智能体服务（Harness + Loop 深度整合） ----
    # Python Harness 是唯一生产问答运行时；pi-agent 保留为实验服务，默认不接主链。
    pi_agent_enabled: bool = True
    pi_agent_url: str = "http://localhost:8100"
    pi_agent_timeout: float = 120.0
    pi_runtime_timeout_intent: float = 8.0
    pi_runtime_timeout_rewrite: float = 10.0
    pi_runtime_timeout_answer: float = 45.0
    pi_runtime_timeout_verify: float = 20.0
    pi_runtime_timeout_reflect: float = 45.0

    # ---- 部门 Agent 服务发现 ----
    dept_id: str = ""
    dept_agents_enabled: bool = False
    dept_agent_url_template: str = "http://dept-agent-{slug}:8000"
    dept_agent_timeout: float = 6.0
    dept_agent_partial_timeout: float = 2.0

    # ---- Loop 进化 ----
    loop_enabled: bool = True
    skill_min_cluster: int = 20      # 7 天窗口内同模式问题最小次数
    skill_sandbox_min_success: float = 0.85
    hook_high_confidence: float = 0.9  # 高置信度自动生效阈值
    loop_phase: str = "human_in_loop"  # human_in_loop | human_on_loop | human_out_of_loop（默认从 Phase 1 起步）
    loop_gray_percent: float = 0.1
    loop_rollback_min_samples: int = 10
    loop_rollback_margin: float = 0.1
    review_sample_rate: float = 0.1

    # ---- 记忆治理（事实平面 + 五个记忆平面）----
    memory_session_ttl_seconds: int = 1800
    memory_event_retention_days: int = 90
    memory_summary_retention_days: int = 180
    memory_user_retention_days: int = 180
    memory_topic_retention_days: int = 90
    memory_max_recent_messages: int = 10
    memory_context_max_chars: int = 6000
    memory_user_limit: int = 8
    memory_org_limit: int = 8

    # ---- 鉴权 ----
    auth_secret: str = "wenshu-dev-secret-change-me"
    auth_token_ttl_hours: int = 24
    # 内部接口（/internal/*）共享 Token：为空则内部接口不可用（fail-closed）
    internal_api_token: str = ""
    # 演示种子账号开关：生产务必 SEED_DEMO_USERS=false（并删除已创建的演示账号）
    seed_demo_users: bool = True
    # 登录限流（内存版，单进程有效）
    login_max_attempts: int = 5
    login_window_seconds: int = 300

    # ---- 上传限制 ----
    max_upload_mb: int = 20

    # ---- 人工审核 Loop（部门渐进退出）----
    review_question_count: int = 3       # 新文档入库后自动生成的测试题数量
    review_accuracy_threshold: float = 0.8   # 正确率超过该阈值后取消人工审核
    review_min_samples: int = 5          # 达到阈值所需的最小审核样本数

    # ---- 超时（全链路） ----
    timeout_intent: float = 1.0
    timeout_retrieval: float = 2.0
    timeout_answer: float = 5.0
    timeout_verify: float = 3.0

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
