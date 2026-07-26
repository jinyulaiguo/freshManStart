from qdrant_client import AsyncQdrantClient
from langchain_core.embeddings import Embeddings
from src.infrastructure.observability import get_logger
import os

logger = get_logger("tool_router")

# 配置各个微服务的启动路径
MCP_SERVER_SCRIPTS = {
    "paper_fs": "src/mcp_servers/paper_fs/server.py",
    "research_db": "src/mcp_servers/research_db/server.py",
    "stat_engine": "src/mcp_servers/stat_engine/server.py"
}

class ToolRouter:
    """
    语义检索网关 (Semantic Tool Router)
    将可用工具 Schema 存入 Qdrant，运行时根据 User Query 动态召回。
    """
    def __init__(self, qdrant: AsyncQdrantClient, embeddings: Embeddings):
        self.qdrant = qdrant
        self.embeddings = embeddings
        self.collection_name = "mcp_tool_schemas"

    async def initialize_tool_schemas(self):
        """系统启动时，将所有 MCP 服务的工具定义灌入向量库"""
        # 在真实环境中，这里应该动态请求各个 MCP 服务器获取它们的 Schema
        # 为了防腐解耦，此处预定义其元数据描述
        tool_docs = [
            {"id": 1, "server": "paper_fs", "name": "read_paper", "desc": "读取科研文献、学术论文或实验记录。"},
            {"id": 2, "server": "research_db", "name": "query_experiment", "desc": "查询核心科研实验数据库中的表格数据，支持 SQL 分析。"},
            {"id": 3, "server": "stat_engine", "name": "generate_histogram", "desc": "长耗时数据分析与图表生成引擎，生成直方图。"}
        ]
        
        # 简单将 desc 转化为向量
        for t in tool_docs:
            vector = await self.embeddings.aembed_query(t["desc"])
            await self.qdrant.upsert(
                collection_name=self.collection_name,
                points=[
                    {"id": t["id"], "vector": vector, "payload": {"server": t["server"], "name": t["name"]}}
                ]
            )
        logger.info("Tool schemas successfully populated into Qdrant.")

    async def retrieve_relevant_servers(self, query: str, top_k: int = 2) -> list[str]:
        """根据用户请求动态召回最相关的 MCP Server 名称"""
        vector = await self.embeddings.aembed_query(query)
        results = await self.qdrant.search(
            collection_name=self.collection_name,
            query_vector=vector,
            limit=top_k
        )
        
        servers = set()
        for res in results:
            servers.add(res.payload["server"])
            
        logger.info("Tool routing completed", query=query, routed_servers=list(servers))
        return list(servers)
