from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
import os

class Settings(BaseSettings):
    """
    企业级强类型配置契约
    所有基础设施连接和 API 密钥必须在此处声明并校验。
    """
    
    # LLM (MiniMax)
    MINIMAX_API_KEY: str = Field(..., description="MiniMax API Key")
    MINIMAX_BASE_URL: str = Field("https://api.minimax.chat/v1", description="MiniMax API Base URL")
    MINIMAX_MODEL: str = Field("abab6.5-chat", description="MiniMax Model Name")
    
    # Qdrant
    QDRANT_HOST: str = Field("localhost", description="Qdrant Server Host")
    QDRANT_PORT: int = Field(6333, description="Qdrant Server Port")
    
    # PostgreSQL
    POSTGRES_HOST: str = Field("localhost", description="PostgreSQL Host")
    POSTGRES_PORT: int = Field(5432, description="PostgreSQL Port")
    POSTGRES_USER: str = Field("postgres", description="PostgreSQL User")
    POSTGRES_PASSWORD: str = Field("postgres", description="PostgreSQL Password")
    POSTGRES_DB: str = Field("research_db", description="PostgreSQL Database")
    
    # LangGraph
    MAX_SUPERSTEPS: int = Field(20, description="最大超步数防死循环")
    
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "../../../../../.env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

# 单例配置对象
settings = Settings()
