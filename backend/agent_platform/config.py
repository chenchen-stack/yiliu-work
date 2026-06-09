"""Agent platform global configuration (env-driven)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_SKILLS = _BACKEND_DIR / "skill_packages"


class PlatformSettings(BaseSettings):
    """Settings for agent_platform; reads .env alongside app settings."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    skills_dir: Path = _DEFAULT_SKILLS
    skill_executor_max_retries: int = 3
    skill_executor_retry_delay_sec: float = 0.5

    # LLM (LiteLLM)
    litellm_model: str = "deepseek/deepseek-chat"
    litellm_api_key: str = ""
    litellm_api_base: str = ""
    use_mock_llm: bool = True  # env: USE_MOCK_LLM; sync with app USE_MOCK_AI in llm_gateway

    # RAG (ChromaDB path under data/)
    chroma_persist_dir: Path = _BACKEND_DIR / "data" / "chroma"
    rag_top_k_default: int = 5

    # Redis (optional async notifications)
    redis_url: str = ""

    # Workflow / Agent orchestration (LangGraph)
    use_langgraph_workflow: bool = True  # env: USE_LANGGRAPH_WORKFLOW
    use_dynamic_workflow_graph: bool = False  # env: USE_DYNAMIC_WORKFLOW_GRAPH — DB nodes → LangGraph
    use_langgraph_agent: bool = False  # env: USE_LANGGRAPH_AGENT — needs langchain-openai + API key
    use_platform_chat_sse: bool = True  # env: USE_PLATFORM_CHAT_SSE — /chat/stream 开放问答走 PlatformAgent
    workflow_default_graph: str = "fangtai_reconciliation"


platform_settings = PlatformSettings()
