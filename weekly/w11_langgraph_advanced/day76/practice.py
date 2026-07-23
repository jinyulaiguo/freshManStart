"""Day 76 练习模版：持久化存储接口与自定义 Redis/Postgres Checkpointer 扩展

说明：
本文件为学员练习专用模版。请根据规范完成其中的 TODO 核心逻辑。
目标：继承 BaseCheckpointSaver 抽象基类，实现 put 与 get_tuple 核心接口，验证持久化存盘与解冻。
"""

import sys
from typing import Dict, Any, List, TypedDict, Optional, Iterator, Sequence, Tuple
from typing_extensions import Annotated
import operator

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    ChannelVersions,
)


# ============================================================================
# 1. 简易 CustomCheckpointer 练习骨架 (TODO)
# ============================================================================

class PracticeCheckpointer(BaseCheckpointSaver):
    """自定义 Checkpointer 练习实现"""
    
    def __init__(self, serde=None):
        super().__init__(serde=serde)
        self.db: Dict[str, bytes] = {}  # 模拟存储字典

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """保存新的 Checkpoint"""
        # TODO 1.1: 提取 thread_id, checkpoint_ns, checkpoint_id
        # TODO 1.2: 使用 self.serde.dumps_typed(checkpoint) 序列化字节流存入 self.db
        # TODO 1.3: 返回更新后的 RunnableConfig
        raise NotImplementedError("TODO: 请实现 PracticeCheckpointer.put 逻辑")

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """检索 CheckpointTuple"""
        # TODO 1.4: 按照 config 查找 self.db
        # TODO 1.5: 使用 self.serde.loads_typed 反序列化并构造 CheckpointTuple 返回
        raise NotImplementedError("TODO: 请实现 PracticeCheckpointer.get_tuple 逻辑")

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """遍历列表 (可选实现)"""
        return iter([])

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
    ) -> None:
        """保存挂起任务 (可选实现)"""
        pass


# ============================================================================
# 调试主入口 (带有友好的 TODO 拦截)
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Day 76 自定义 Checkpointer 扩展练习入口")
    print("=" * 60)
    
    try:
        checkpointer = PracticeCheckpointer()
        print("✅ PracticeCheckpointer 实例化成功")
        
        # 测试用例
        cfg = {"configurable": {"thread_id": "prac_t76", "checkpoint_id": "cp_01"}}
        checkpointer.get_tuple(cfg)
        
    except NotImplementedError as e:
        print(f"💡 [TODO 提示] 练习未完成: {e}")
    except Exception as e:
        print(f"❌ 运行报错: {e}")
