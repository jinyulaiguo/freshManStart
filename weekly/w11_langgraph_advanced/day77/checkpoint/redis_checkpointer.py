"""生产级 Redis 持久化 Checkpointer 插件 (Day 77 企业级实战)

设计方案与架构说明：
----------------------------------------------------------------
本模块从零实现继承自 `BaseCheckpointSaver` 的生产级分布式 Checkpoint 持久化驱动。
1. 双重索引设计：使用 Redis Hash 存储快照数据，使用 Redis Sorted Set (ZSet) 维护 Checkpoint 时间线索引。
2. 完美支持时间旅行 (Time Travel)：`list()` 方法基于 ZSet 的 `zrevrangebyscore` 指令，精准支持倒序排列、`before` 分页过滤与 `limit` 限制。
3. 强类型序列化：集成 LangGraph 底层 `SerializerProtocol`，确保自定义 Reducer/Complex Payload 的序列化无损与安全性。
4. 同步与异步无缝兼容：同时实现 `put/get_tuple/list/put_writes` 与 `aput/aget_tuple/alist/aput_writes` 异步代理。

数据流与生命周期：
------------------
[put()/aput()] -> Hash 存盘 (lg:cp:...) -> ZSet 写索引 (lg:idx:...) -> 更新 lg:cp:...:latest
[get_tuple()/aget_tuple()] -> 读取 Hash -> 反序列化 -> 组装 CheckpointTuple
[list()/alist()] -> ZSet 倒序查 ID 序列 -> 批量读取 Hash -> Yield 历史列表
"""

import os
import sys
import time
from typing import Dict, Any, List, Optional, Iterator, AsyncIterator, Sequence, Tuple
from langchain_core.runnables import RunnableConfig

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    ChannelVersions,
)

# 动态将工作区根目录添加到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from weekly.w04_prompt_and_http.utils import load_env_file

load_env_file()


class ProductionRedisCheckpointer(BaseCheckpointSaver):
    """基于真实 Redis 的生产级持久化 Checkpoint 驱动实现。"""

    def __init__(self, host: str = None, port: int = None, password: str = None, db: int = 0, serde=None):
        super().__init__(serde=serde)
        try:
            import redis
        except ImportError:
            raise ImportError("未安装 redis Python SDK，请运行 `uv pip install redis` 进行安装。")

        self.host = host or os.getenv("REDIS_HOST", "127.0.0.1")
        self.port = port or int(os.getenv("REDIS_PORT", "6379"))
        self.password = password or os.getenv("REDIS_PASSWORD", "")
        self.db = db

        self.client = redis.Redis(
            host=self.host,
            port=self.port,
            password=self.password if self.password else None,
            db=self.db,
            decode_responses=False  # 保留字节流以存储二进制序列化数据
        )

    def _make_key(self, thread_id: str, checkpoint_ns: str, checkpoint_id: str) -> str:
        """生成物理 Hash Key"""
        return f"lg:cp:{thread_id}:{checkpoint_ns}:{checkpoint_id}"

    def _make_latest_key(self, thread_id: str, checkpoint_ns: str) -> str:
        """生成 Latest Hash Key"""
        return f"lg:cp:{thread_id}:{checkpoint_ns}:latest"

    def _make_idx_key(self, thread_id: str, checkpoint_ns: str) -> str:
        """生成 ZSet 时间索引 Key"""
        return f"lg:idx:{thread_id}:{checkpoint_ns}"

    # ------------------------------------------------------------------------
    # 同步核心契约实现
    # ------------------------------------------------------------------------

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """持久化保存 Checkpoint 快照至 Redis Hash，并同时更新 ZSet 索引。"""
        configurable = config["configurable"]
        thread_id = configurable["thread_id"]
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = checkpoint["id"]
        parent_cp_id = configurable.get("checkpoint_id", "")

        now_ts = time.time()

        # 1. 使用底座 serde 强类型序列化
        serde_checkpoint = self.serde.dumps_typed(checkpoint)
        serde_metadata = self.serde.dumps_typed(metadata)

        key = self._make_key(thread_id, checkpoint_ns, checkpoint_id)
        latest_key = self._make_latest_key(thread_id, checkpoint_ns)
        idx_key = self._make_idx_key(thread_id, checkpoint_ns)

        mapping = {
            "checkpoint_type": serde_checkpoint[0],
            "checkpoint_bytes": serde_checkpoint[1],
            "metadata_type": serde_metadata[0],
            "metadata_bytes": serde_metadata[1],
            "parent_checkpoint_id": parent_cp_id or "",
            "timestamp": str(now_ts)
        }

        # 2. 存入 Redis Hash 与 Latest Key
        self.client.hset(key, mapping=mapping)
        self.client.hset(latest_key, mapping=mapping)

        # 3. 写入 ZSet 索引 (Score 为 timestamp，Member 为 checkpoint_id)
        self.client.zadd(idx_key, {checkpoint_id: now_ts})

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        """保存挂起任务的中间写操作 Payload。"""
        configurable = config["configurable"]
        thread_id = configurable["thread_id"]
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = configurable["checkpoint_id"]

        key = f"lg:writes:{thread_id}:{checkpoint_ns}:{checkpoint_id}:{task_id}"
        for channel, value in writes:
            serde_val = self.serde.dumps_typed(value)
            self.client.hset(key, channel, f"{serde_val[0]}::{serde_val[1].hex()}")

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """根据 config 获取单条 CheckpointTuple。"""
        configurable = config["configurable"]
        thread_id = configurable["thread_id"]
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = configurable.get("checkpoint_id")

        if checkpoint_id:
            key = self._make_key(thread_id, checkpoint_ns, checkpoint_id)
        else:
            key = self._make_latest_key(thread_id, checkpoint_ns)

        data = self.client.hgetall(key)
        if not data:
            return None

        cp_type = data[b"checkpoint_type"].decode("utf-8")
        cp_bytes = data[b"checkpoint_bytes"]
        meta_type = data[b"metadata_type"].decode("utf-8")
        meta_bytes = data[b"metadata_bytes"]
        parent_cp_id = data[b"parent_checkpoint_id"].decode("utf-8")

        checkpoint = self.serde.loads_typed((cp_type, cp_bytes))
        metadata = self.serde.loads_typed((meta_type, meta_bytes))

        parent_config = None
        if parent_cp_id:
            parent_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": parent_cp_id,
                }
            }

        final_config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

        return CheckpointTuple(
            config=final_config,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=[]
        )

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """使用 Redis ZSet 进行倒序检索与分页历史遍历。"""
        if not config:
            return

        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        checkpoint_ns = configurable.get("checkpoint_ns", "")

        idx_key = self._make_idx_key(thread_id, checkpoint_ns)

        max_score = "+inf"
        # 如果指定了 before，先获取该 checkpoint_id 的 timestamp 作为 upper bound
        if before and before.get("configurable", {}).get("checkpoint_id"):
            before_cp_id = before["configurable"]["checkpoint_id"]
            before_score = self.client.zscore(idx_key, before_cp_id)
            if before_score is not None:
                max_score = f"({before_score}"  # 开区间：小于该 score

        # 防御修复：如果指定了 limit，同时传 start=0 与 num=limit；否则只传 score 范围
        if limit is not None:
            cp_ids = self.client.zrevrangebyscore(idx_key, max=max_score, min="-inf", start=0, num=limit)
        else:
            cp_ids = self.client.zrevrangebyscore(idx_key, max=max_score, min="-inf")

        for cp_id in cp_ids:
            cp_id_str = cp_id.decode("utf-8") if isinstance(cp_id, bytes) else cp_id
            sub_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": cp_id_str
                }
            }
            tup = self.get_tuple(sub_config)
            if tup:
                yield tup

    # ------------------------------------------------------------------------
    # 异步代理实现 (支持 ainvoke / astream 运行模式)
    # ------------------------------------------------------------------------

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """异步获取 CheckpointTuple 代理方法。"""
        return self.get_tuple(config)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """异步保存 Checkpoint 代理方法。"""
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        """异步保存写入 Payload 代理方法。"""
        return self.put_writes(config, writes, task_id)

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """异步迭代获取 Checkpoint 历史列表代理方法。"""
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item
