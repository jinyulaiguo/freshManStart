"""
AetherMind Config Module
=======================

设计方案:
---------
该模块负责整个系统的配置项加载与强类型校验。使用 Pydantic Settings 从环境变量
及本地 `.env` 文件中异步或同步读取配置，并暴露出全局配置单例 `settings`。

结构说明:
---------
- Settings: 继承自 `BaseSettings` 的强类型配置类。
- get_settings(): 获取配置单例的函数。

数据流向:
---------
1. 启动时或模块导入时，Pydantic 自动寻找同级目录或根目录下的 `.env` 文件。
2. 读取系统环境变量，若有同名变量则覆盖 `.env`。
3. 执行 Pydantic 校验（如端口号类型转换等），生成强类型配置实例。
"""

import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    系统全局配置类，管理大模型凭证、数据库连接、向量库配置等。
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # === LLM Client API Credentials ===
    minimax_api_key: str = Field(
        default="",
        validation_alias="MINIMAX_API_KEY",
        description="MiniMax API 密钥"
    )
    minimax_base_url: str = Field(
        default="https://api.minimax.chat/v1",
        validation_alias="MINIMAX_BASE_URL",
        description="MiniMax API 基础端点"
    )
    llm_model: str = Field(
        default="abab6.5g-chat",
        validation_alias="LLM_MODEL",
        description="用于会话与推理的目标大模型"
    )

    # === Database Backend Selection ===
    db_backend: str = Field(
        default="sqlite",
        validation_alias="DB_BACKEND",
        description="关系型数据库后端: sqlite | postgres"
    )

    # === PostgreSQL Configurations ===
    postgres_user: str = Field(default="postgres", validation_alias="POSTGRES_USER")
    postgres_password: str = Field(default="secret", validation_alias="POSTGRES_PASSWORD")
    postgres_host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    postgres_db: str = Field(default="aether_mind", validation_alias="POSTGRES_DB")

    # === Qdrant Configurations ===
    qdrant_host: Optional[str] = Field(default=None, validation_alias="QDRANT_HOST")
    qdrant_port: int = Field(default=6333, validation_alias="QDRANT_PORT")
    qdrant_api_key: Optional[str] = Field(default=None, validation_alias="QDRANT_API_KEY")

    # === SQLite Configurations ===
    sqlite_db_path: str = Field(
        default="aether_mind.db",
        validation_alias="SQLITE_DB_PATH",
        description="SQLite 本地数据库物理路径"
    )

    # === Engine & Memory Parameters ===
    token_limit: int = Field(
        default=2000,
        description="工作记忆滑动窗口字符数（近似Token数）上限，触发异步摘要"
    )
    memory_decay_rate: float = Field(
        default=0.05,
        description="长期记忆艾宾浩斯时间遗忘衰减率"
    )

    # === Semantic Cache Parameters ===
    semantic_cache_enabled: bool = Field(
        default=True,
        validation_alias="SEMANTIC_CACHE_ENABLED",
        description="语义缓存总开关，False 时完全绕过缓存层"
    )
    semantic_cache_threshold: float = Field(
        default=0.92,
        validation_alias="SEMANTIC_CACHE_THRESHOLD",
        description="L2 向量语义缓存命中的余弦相似度阈值（0.0~1.0）"
    )
    semantic_cache_ttl_seconds: int = Field(
        default=3600,
        validation_alias="SEMANTIC_CACHE_TTL_SECONDS",
        description="缓存条目有效期（秒），L1 和 L2 共用同一 TTL 配置"
    )
    semantic_cache_l1_max_size: int = Field(
        default=500,
        validation_alias="SEMANTIC_CACHE_L1_MAX_SIZE",
        description="L1 内存缓存最大条目数，超出时按 LRU 策略驱逐"
    )


# 实例化全局单例配置
settings = Settings()
