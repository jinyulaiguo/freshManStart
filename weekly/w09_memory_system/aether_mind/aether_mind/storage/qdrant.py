"""
AetherMind Qdrant Vector Storage Adapter
========================================

设计方案:
---------
本模块封装了 `qdrant-client` 官方 SDK，实现了 `VectorStore` 向量存储契约。
它支持双工作模式：
1. **物理服务模式**：通过配置文件读取物理 IP 及端口，建立与 Qdrant 服务器的物理连接。
2. **本地内存模拟模式**：若配置文件中 `host` 参数为空，自动建立内存模式 `:memory:` 连接，避免本地开发人员强依赖 Qdrant 物理服务。

此外，本类包含自动初始化机制，即在初始化连接后自动检测并创建系统所需的两个向量集合：
- `memory_collection`：存储长期记忆事实的向量（维度为1536）。
- `knowledge_collection`：存储外部 RAG 文档切片与特征（维度为1536）。

结构说明:
---------
- QdrantVectorStore: 实现了 `VectorStore` Protocol，完成向量 Upsert、相似度 Search 及 ID 物理 Delete 动作。
"""

import uuid
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
from aether_mind.storage.base import VectorStore
from aether_mind.utils.logging import logger


class QdrantVectorStore(VectorStore):
    """
    Qdrant 向量数据库适配器，支持物理服务模式与 `:memory:` 轻量模式，实现 VectorStore 协议。
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: int = 6333,
        api_key: Optional[str] = None,
        vector_dim: int = 1536
    ):
        """
        初始化向量数据库连接，并隐式建立双模式客户端。

        Args:
            host (Optional[str]): Qdrant 物理服务 IP 地址。如果为 None 且不配置，则采用内存模拟。
            port (int): 端口号，默认 6333。
            api_key (Optional[str]): 权限认证 Key。
            vector_dim (int): 向量维度，默认 1536。
        """
        self.vector_dim = vector_dim
        
        # 1. 判断并建立双模式客户端连接
        if host:
            logger.info(f"正在建立 Qdrant 物理服务器连接 -> {host}:{port}")
            self.client = QdrantClient(host=host, port=port, api_key=api_key or None)
        else:
            logger.info("未检测到 Qdrant 物理主机配置，自动开启本地 Qdrant [内存模拟 :memory:] 模式。")
            self.client = QdrantClient(":memory:")

    async def init_collections(self) -> None:
        """
        自动检查并建立核心向量集合 (Collection)。
        """
        collections = ["memory_collection", "knowledge_collection", "community_collection", "semantic_cache_collection"]
        for col in collections:
            # 2. 判断集合是否存在，如不存在则创建并配置为余弦相似度
            if not self.client.collection_exists(col):
                logger.info(f"自动初始化创建 Qdrant 向量集合: {col} (维度: {self.vector_dim})")
                self.client.create_collection(
                    collection_name=col,
                    vectors_config=VectorParams(size=self.vector_dim, distance=Distance.COSINE)
                )

    async def upsert_points(self, collection: str, points: List[Dict[str, Any]]) -> None:
        """
        向指定的集合插入或修改向量及元数据 Payload。

        Args:
            collection (str): 集合名称。
            points (List[Dict[str, Any]]): 节点字典列表。节点结构需包含:
                - "id": 唯一标识，int 或 UUID str。如果为空，则自动生成 UUID。
                - "vector": 浮点特征向量数组 (List[float])。
                - "payload": 键值对字典数据。
        """
        point_structs = []
        for p in points:
            # 确保 ID 合法
            point_id = p.get("id")
            if not point_id:
                point_id = str(uuid.uuid4())
            elif isinstance(point_id, int):
                pass
            else:
                point_id = str(point_id)

            # 如果 vector 缺失或为 None，说明只更新 payload
            if "vector" not in p or p["vector"] is None:
                self.client.set_payload(
                    collection_name=collection,
                    payload=p["payload"],
                    points=[point_id]
                )
                continue

            point_structs.append(
                PointStruct(
                    id=point_id,
                    vector=p["vector"],
                    payload=p["payload"]
                )
            )

        # 3. 异步/同步提交节点批量写入
        if point_structs:
            self.client.upsert(
                collection_name=collection,
                points=point_structs
            )

    async def search_points(
        self,
        collection: str,
        query_vector: List[float],
        filter_dict: Optional[Dict[str, Any]] = None,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        对特征向量执行余弦相似度检索，支持 Filter 过滤条件，保证多租户物理隔离。

        Args:
            collection (str): 集合名称。
            query_vector (List[float]): 检索特征向量。
            filter_dict (Optional[Dict[str, Any]]): 过滤字典。例如 {"user_id": "usr_9928"}。
            top_k (int): 召回前多少条记录。

        Returns:
            List[Dict[str, Any]]: 召回条目列表，格式化输出节点信息与分数。
        """
        # 4. 构建 Qdrant Filter 过滤器，用于多租户 user_id 或 status 条件隔离
        qdrant_filter = None
        if filter_dict:
            conditions = []
            for key, val in filter_dict.items():
                conditions.append(
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=val)
                    )
                )
            qdrant_filter = Filter(must=conditions)

        # 5. 执行近邻搜索
        response = self.client.query_points(
            collection_name=collection,
            query=query_vector,
            query_filter=qdrant_filter,
            limit=top_k
        )
        results = response.points


        # 6. 转换结果为基础 Python dict 格式返回
        output = []
        for res in results:
            output.append({
                "id": res.id,
                "score": res.score,
                "payload": res.payload
            })
        return output

    async def delete_points(self, collection: str, ids: List[Any]) -> None:
        """
        物理删除向量数据库中的某些节点，常用于冲突消歧、遗忘衰减及缓存驱逐。

        Args:
            collection (str): 集合名称。
            ids (List[Any]): 节点 ID 列表。
        """
        if not ids:
            return

        # 转换 ID 为合法 Qdrant ID 集合
        self.client.delete(
            collection_name=collection,
            points_selector=ids
        )
