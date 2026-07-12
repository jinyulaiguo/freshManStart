"""
AetherMind Storage Base Interfaces
==================================

设计方案:
---------
本模块使用 `typing.Protocol` 定义了关系型数据库存储适配器 (`SQLStore`) 与
向量数据库存储适配器 (`VectorStore`) 的静态类型契约。
使核心 Agent 逻辑（主引擎、记忆管理器、RAG 引擎）与具体的底层数据库实现隔离，
支持通过配置文件在运行时无缝切换底层存储后端。

结构说明:
---------
- SQLStore: 定义会话管理、历史消息记录、Trace 追踪日志及记忆变更审计日志的相关接口。
- VectorStore: 定义向量插入、检索与删除的核心接口。
"""

from typing import Protocol, List, Dict, Any, Optional


class SQLStore(Protocol):
    """
    关系型数据库存储契约。
    支持 Session 读写、历史消息滑窗、以及可观测性日志记录。
    """

    async def init_db(self) -> None:
        """
        初始化物理数据库表结构（创建表与索引）。
        """
        ...

    async def create_session(self, session_id: str, user_id: str) -> None:
        """
        创建新的会话。若已存在则忽略。

        Args:
            session_id (str): 会话唯一 ID。
            user_id (str): 关联的用户 ID。
        """
        ...

    async def save_message(self, session_id: str, role: str, content: str) -> None:
        """
        向数据库写入单轮对话消息。

        Args:
            session_id (str): 会话 ID。
            role (str): 角色（system / user / assistant）。
            content (str): 消息内容文本。
        """
        ...

    async def load_session_context(self, session_id: str) -> List[Dict[str, Any]]:
        """
        加载指定会话的历史对话消息列表。

        Args:
            session_id (str): 会话 ID。

        Returns:
            List[Dict[str, Any]]: 消息记录字典列表，按时间戳升序排序。
        """
        ...

    async def update_session_summary(self, session_id: str, summary: str) -> None:
        """
        异步后台更新会话的总结摘要。

        Args:
            session_id (str): 会话 ID。
            summary (str): 摘要文本。
        """
        ...

    async def get_session_summary(self, session_id: str) -> Optional[str]:
        """
        获取指定会话的累积背景摘要。

        Args:
            session_id (str): 会话 ID。

        Returns:
            Optional[str]: 摘要内容。如果不存在该会话，返回 None。
        """
        ...

    async def get_session_user(self, session_id: str) -> Optional[str]:
        """
        获取指定会话关联的用户 ID（用于多租户隔离）。

        Args:
            session_id (str): 会话 ID。

        Returns:
            Optional[str]: 用户 ID。
        """
        ...

    async def save_memory_log(
        self, user_id: str, action: str, fact_key: str, fact_value: str, details: Optional[str] = None
    ) -> None:
        """
        保存长期记忆事实变动的审计追踪日志。

        Args:
            user_id (str): 用户 ID。
            action (str): 操作类型 (insert / update / delete / decay)。
            fact_key (str): 长期记忆键。
            fact_value (str): 长期记忆值。
            details (str): 审计描述详情。
        """
        ...

    async def save_trace_log(
        self, session_id: str, step_name: str, duration_ms: int, input_data: str, output_data: str
    ) -> None:
        """
        保存 Trace 可观测性调用链追踪日志。

        Args:
            session_id (str): 会话 ID。
            step_name (str): 执行步骤名称（如 'router', 'react'）。
            duration_ms (int): 执行耗时（毫秒）。
            input_data (str): 该步骤的输入参数。
            output_data (str): 该步骤的输出结果。
        """
        ...


class VectorStore(Protocol):
    """
    向量数据库存储契约。
    支持高维向量及其关联 Payload 的写入、语义相似度搜索与点删除。
    """

    async def upsert_points(self, collection: str, points: List[Dict[str, Any]]) -> None:
        """
        向向量库插入或覆盖更新向量节点。

        Args:
            collection (str): 集合（Collection）名称。
            points (List[Dict[str, Any]]): 节点字典列表，格式如下：
                {
                    "id": UUID or int,
                    "vector": List[float],
                    "payload": Dict[str, Any]
                }
        """
        ...

    async def search_points(
        self,
        collection: str,
        query_vector: List[float],
        filter_dict: Optional[Dict[str, Any]] = None,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        对指定集合执行余弦相似度向量匹配。

        Args:
            collection (str): 集合名称。
            query_vector (List[float]): 查询特征向量。
            filter_dict (Optional[Dict[str, Any]]): Payload 过滤条件（如 {"user_id": "usr_123"} 确保租户隔离）。
            top_k (int): 返回的最相似候选条目上限。

        Returns:
            List[Dict[str, Any]]: 检索匹配节点列表（含相似度分数及原始 Payload）。
        """
        ...

    async def delete_points(self, collection: str, ids: List[Any]) -> None:
        """
        从指定集合中物理删除指定 ID 列表的向量节点。

        Args:
            collection (str): 集合名称。
            ids (List[Any]): 要删除的节点 ID 列表。
        """
        ...
