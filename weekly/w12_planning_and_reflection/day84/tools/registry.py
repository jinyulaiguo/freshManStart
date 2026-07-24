"""
Day 84 综合实战: 工具统一注册表 (Tool Registry)

【设计说明】
解耦 Executor 与具体工具实现。提供统一的 async dispatch 接口，
根据 TaskStep 的 task_type 匹配底层对应的工具（Search / RAG / Database / Analyze）。
"""

from typing import Dict, Any
from weekly.w12_planning_and_reflection.day84.tools.search import WebSearchTool
from weekly.w12_planning_and_reflection.day84.tools.rag import QdrantRAGTool
from weekly.w12_planning_and_reflection.day84.tools.database import LocalDatabaseTool


class ToolRegistry:
    """工具分发注册中心"""

    def __init__(self):
        self.search_tool = WebSearchTool()
        self.rag_tool = QdrantRAGTool()
        self.db_tool = LocalDatabaseTool()

    async def dispatch(self, task_type: str, query: str) -> Dict[str, Any]:
        """
        统一分发执行工具
        """
        task_type_lower = task_type.lower()
        if "search" in task_type_lower:
            return await self.search_tool.execute(query)
        elif "rag" in task_type_lower or "vector" in task_type_lower:
            return await self.rag_tool.execute(query)
        elif "database" in task_type_lower or "db" in task_type_lower:
            return await self.db_tool.execute(query)
        else:
            # 默认降级使用 RAG 搜索
            return await self.rag_tool.execute(query)
