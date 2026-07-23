"""持久化存储接口与自定义真实 Redis Checkpointer 扩展 (Day 76 参考标准答案)

设计方案与架构说明：
----------------------------------------------------------------
本模块选择 Docker 中运行的真实 Redis 内存数据库作为唯一存储引擎，演示 `BaseCheckpointSaver` 的持久化与无损解冻恢复全流程。
架构设计与核心机制：
1. 真实数据库连接 (RealRedisCheckpointer)：从本地 .env 中动态读取 REDIS_HOST (127.0.0.1), REDIS_PORT (6379), REDIS_PASSWORD (Admin123!)，建立真实的 redis-py 读写通道。
2. 强类型二进制序列化：使用 `self.serde.dumps_typed` 与 `loads_typed` 进行防篡改快照转换，存入 Redis Hash。
3. 真实物理崩溃解冻：证明在 Graph 1 实例被彻底销毁（模拟服务崩溃）后，全新的 Graph 2 实例通过绑定的 Redis Checkpointer，从真实 Redis 中 `HGETALL` 还原 `StateSnapshot` 并原位恢复控制流。

数据流与生命周期：
------------------
[StateGraph 1] -> (触发中断打断) -> [真实 Docker Redis Hash 存盘] 
                                            │ (物理销毁 Graph 1 实例)
[StateGraph 2] <- (HGETALL 反序列化还原) ────┘ 调用 invoke(None) 解冻执行 -> END
"""

import os
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

# 动态将工作区根目录添加到 sys.path 中以支持跨模块导入
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from weekly.w04_prompt_and_http.utils import load_env_file
load_env_file()


# ============================================================================
# 1. 真实 Redis 持久化 Checkpointer 扩展组件 (Real Redis Checkpointer)
# ============================================================================

class RealRedisCheckpointer(BaseCheckpointSaver):
    """基于真实 Docker Redis 内存数据库的 Checkpoint 持久化扩展组件。
    
    所有配置参数纯粹从本地 .env 环境动态读取。
    """
    
    def __init__(self, host: str, port: int, password: str = "", db: int = 0, serde=None):
        super().__init__(serde=serde)
        try:
            import redis
        except ImportError:
            raise ImportError("未检测到 redis Python SDK，请运行 `uv pip install redis` 进行安装。")
            
        self.client = redis.Redis(
            host=host,
            port=port,
            password=password if password else None,
            db=db,
            decode_responses=False  # 保留二进制 bytes 字节流存储
        )

    def _make_key(self, thread_id: str, checkpoint_ns: str, checkpoint_id: str) -> str:
        """生成物理 Checkpoint Hash Key 格式: checkpoint:{thread}:{ns}:{id}"""
        return f"checkpoint:{thread_id}:{checkpoint_ns}:{checkpoint_id}"

    def _make_latest_key(self, thread_id: str, checkpoint_ns: str) -> str:
        """生成指向最新快照的 Hash Key 格式: checkpoint:{thread}:{ns}:latest"""
        return f"checkpoint:{thread_id}:{checkpoint_ns}:latest"

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """落盘保存 Checkpoint 快照至真实 Redis Hash。"""
        configurable = config["configurable"]
        thread_id = configurable["thread_id"]
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = checkpoint["id"]
        parent_cp_id = configurable.get("checkpoint_id", "")
        
        # 1. 强类型序列化
        serde_checkpoint = self.serde.dumps_typed(checkpoint)
        serde_metadata = self.serde.dumps_typed(metadata)
        
        key = self._make_key(thread_id, checkpoint_ns, checkpoint_id)
        latest_key = self._make_latest_key(thread_id, checkpoint_ns)
        
        # 2. 存入真实 Redis Hash
        mapping = {
            "checkpoint_type": serde_checkpoint[0],
            "checkpoint_bytes": serde_checkpoint[1],
            "metadata_type": serde_metadata[0],
            "metadata_bytes": serde_metadata[1],
            "parent_checkpoint_id": parent_cp_id or ""
        }
        
        self.client.hset(key, mapping=mapping)
        self.client.hset(latest_key, mapping=mapping)
        
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
        """保存挂起任务的中间写操作至真实 Redis。"""
        configurable = config["configurable"]
        thread_id = configurable["thread_id"]
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = configurable["checkpoint_id"]
        
        key = f"writes:{thread_id}:{checkpoint_ns}:{checkpoint_id}:{task_id}"
        for channel, value in writes:
            serde_val = self.serde.dumps_typed(value)
            self.client.hset(key, channel, f"{serde_val[0]}::{serde_val[1].hex()}")

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """从真实 Redis 中查询并反序列化 CheckpointTuple。"""
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
        if not config:
            return
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        
        pattern = f"checkpoint:{thread_id}:{checkpoint_ns}:*"
        keys = self.client.keys(pattern)
        
        for k in keys:
            k_str = k.decode("utf-8")
            if k_str.endswith(":latest"):
                continue
            cp_id = k_str.split(":")[-1]
            sub_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": cp_id
                }
            }
            tup = self.get_tuple(sub_config)
            if tup:
                yield tup


# ============================================================================
# 2. 业务图契约与工作流节点定义
# ============================================================================

class EnterpriseWorkflowState(TypedDict):
    """真实 Redis 持久化解冻工作流状态契约"""
    task_id: str
    status: str
    audit_trail: Annotated[List[str], operator.add]


def step_a_init_node(state: EnterpriseWorkflowState) -> Dict[str, Any]:
    print(f"\n[Node A] 初始化任务 ({state['task_id']})，准备写入真实 Redis Checkpointer 存盘...")
    return {
        "status": "STEP_A_COMPLETED",
        "audit_trail": [f"Task {state['task_id']} step A completed and saved to Redis."]
    }


def step_b_process_node(state: EnterpriseWorkflowState) -> Dict[str, Any]:
    print(f"\n[Node B] 从真实 Redis 还原恢复后，解冻继续执行步骤 B...")
    return {
        "status": "ALL_COMPLETED",
        "audit_trail": ["Step B processing completed after resume from Redis."]
    }


def build_workflow_graph(checkpointer: BaseCheckpointSaver):
    """构建 StateGraph 并绑定 Checkpointer 存储适配器。"""
    builder = StateGraph(EnterpriseWorkflowState)
    builder.add_node("step_a", step_a_init_node)
    builder.add_node("step_b", step_b_process_node)
    
    builder.add_edge(START, "step_a")
    builder.add_edge("step_a", "step_b")
    builder.add_edge("step_b", END)
    
    # 在 step_b 执行前打断挂起
    return builder.compile(checkpointer=checkpointer, interrupt_before=["step_b"])


# ============================================================================
# 3. 主运行程序 (Single Real Redis Persistence Suite)
# ============================================================================

def main():
    print("=" * 70)
    print("🚀 Day 76: 真实 Docker Redis 持久化存储与解冻恢复实战")
    print("=" * 70)
    
    # 从本地 .env 动态读取 Redis 配置
    redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_pwd = os.getenv("REDIS_PASSWORD", "")
    
    print(f"  • 连接 Docker 中的真实 Redis 内存数据库 ({redis_host}:{redis_port})...")
    redis_checkpointer = RealRedisCheckpointer(host=redis_host, port=redis_port, password=redis_pwd)
    redis_checkpointer.client.ping()
    print("  ✅ 成功建立与真实 Docker Redis 数据库的数据存盘通道！")
    
    config = {"configurable": {"thread_id": "real_redis_workflow_9900"}}
    
    # ------------------------------------------------------------------------
    # 阶段 A: 在 App 实例 1 中运行图，触发中断打断并自动写入真实 Redis
    # ------------------------------------------------------------------------
    print("\n--- 阶段 A: 图应用 App 1 运行，执行 Node A 并触发 Redis 存盘挂起 ---")
    app_1 = build_workflow_graph(redis_checkpointer)
    
    init_input = {
        "task_id": "TASK_REDIS_9900",
        "status": "INIT",
        "audit_trail": []
    }
    app_1.invoke(init_input, config)
    
    snapshot_1 = app_1.get_state(config)
    print(f"  • App 1 挂起成功！待执行节点: {snapshot_1.next}")
    print(f"  • App 1 当前状态 values: {snapshot_1.values.get('status')}")
    assert snapshot_1.next == ("step_b",), "错误：未能在 step_b 前触发挂起！"
    
    # ------------------------------------------------------------------------
    # 阶段 B: 模拟进程崩溃/服务重启 —— 物理销毁 app_1 内存对象！
    # ------------------------------------------------------------------------
    print("\n--- 阶段 B: 模拟服务进程崩溃 —— 彻底销毁 App 1 内存对象 ---")
    del app_1
    del redis_checkpointer
    print("  💥 App 1 内存对象已彻底物理销毁！数据完好保留在 Docker Redis 中。")
    
    # ------------------------------------------------------------------------
    # 阶段 C: 初始化全新的 App 实例 2，连接真实 Redis 恢复 StateSnapshot
    # ------------------------------------------------------------------------
    print("\n--- 阶段 C: 初始化全新 App 2，连接真实 Redis 从底座解冻还原 ---")
    restarted_checkpointer = RealRedisCheckpointer(host=redis_host, port=redis_port, password=redis_pwd)
    app_2 = build_workflow_graph(restarted_checkpointer)
    
    snapshot_2 = app_2.get_state(config)
    print(f"  • App 2 从 Docker Redis 成功还原出的待执行节点: {snapshot_2.next}")
    print(f"  • App 2 从 Redis 还原出的历史审计日志:")
    for log in snapshot_2.values.get("audit_trail", []):
        print(f"      - {log}")
        
    assert snapshot_2.next == ("step_b",), "解冻失败：App 2 未能从 Redis 恢复待执行节点！"
    
    # ------------------------------------------------------------------------
    # 阶段 D: 在 App 2 中调用 invoke(None, config) 继续解冻推进流程
    # ------------------------------------------------------------------------
    print("\n--- 阶段 D: 在 App 2 中调用 invoke(None, config) 解冻流转 ---")
    final_output = app_2.invoke(None, config)
    
    print("\n--- 阶段 E: 全流转完成，检查最终状态 ---")
    print(f"  • 最终状态 status: {final_output['status']}")
    print(f"  • 完整审计日志链 (audit_trail):")
    for log in final_output["audit_trail"]:
        print(f"      - {log}")
        
    assert final_output["status"] == "ALL_COMPLETED", "终局失败：未能推演至 END！"
    print("\n✅ 基于真实 Docker Redis 数据库的持久化存盘与无损解冻恢复全流程验证通过！")


if __name__ == "__main__":
    main()
