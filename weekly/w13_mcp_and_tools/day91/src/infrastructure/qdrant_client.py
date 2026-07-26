from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
from tenacity import retry, stop_after_attempt, wait_exponential
from src.config.settings import settings
from src.infrastructure.observability import get_logger

logger = get_logger("qdrant_gateway")

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def get_qdrant_client() -> AsyncQdrantClient:
    """
    获取生产级 Qdrant 客户端 (带 Tenacity 重试容错)
    """
    logger.info("Connecting to Qdrant", host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
    client = AsyncQdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
    # Ping 检查连接是否健康
    await client.get_collections()
    return client

async def ensure_collection_exists(client: AsyncQdrantClient, collection_name: str, vector_size: int = 1536):
    """
    确保 Collection 存在，若不存在则创建。
    注意：MiniMax abab6.5 模型通常搭配自定义向量化，或者使用通用的 1536 维度。
    """
    collections = await client.get_collections()
    if not any(c.name == collection_name for c in collections.collections):
        logger.info(f"Creating Qdrant collection: {collection_name}")
        await client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE)
        )
    else:
        logger.info(f"Qdrant collection {collection_name} already exists.")
