import psycopg
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from src.config.settings import settings
from src.infrastructure.observability import get_logger

logger = get_logger("pg_checkpointer")

def get_db_uri() -> str:
    """构建 PostgreSQL 连接字符串"""
    return f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"

async def get_checkpointer() -> AsyncPostgresSaver:
    """
    初始化生产级的异步 Postgres 检查点 (AsyncPostgresSaver)
    支持真实多机分布式容错和 Human-in-the-loop 状态挂起
    """
    uri = get_db_uri()
    logger.info("Initializing AsyncPostgresSaver", host=settings.POSTGRES_HOST, db=settings.POSTGRES_DB)
    
    # 建立异步连接池
    pool = AsyncConnectionPool(
        conninfo=uri,
        max_size=20,
        kwargs={"autocommit": True, "prepare_threshold": 0}
    )
    
    # 获取 saver 实例，必须在 async 上下文中 setup
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    return checkpointer

async def close_checkpointer(checkpointer: AsyncPostgresSaver):
    """优雅关闭连接池"""
    if hasattr(checkpointer, "conn"):
        await checkpointer.conn.close()
