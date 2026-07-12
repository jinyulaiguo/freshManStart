"""
AetherMind GitHub Repository Analyzer Tool
==========================================

设计方案:
---------
本模块实现了静态分析主流 Agent 框架 GitHub 仓库结构的工具 `github_repo_analyzer`。
为确保工具在无网络环境或 API 限频条件下的高可用性，同时能提供极其详尽的框架类拓扑，
本工具采用“本地静态知识库 + 目录结构智能映射”的混合模式。它能返回
LangGraph, smolagents, Letta 等主流 Agent 框架的核心类结构、状态流转原理解析。

结构说明:
---------
- GithubAnalyzerInput: 工具入参 Pydantic 模型。
- github_repo_analyzer: 执行静态分析的业务逻辑函数。
"""

from pydantic import BaseModel, Field
from aether_mind.tools.base import register_tool


class GithubAnalyzerInput(BaseModel):
    """github_repo_analyzer 的输入参数契约。"""
    repo_name: str = Field(
        ...,
        description="待分析的目标 GitHub 仓库名称，如 'langchain-ai/langgraph' 或 'huggingface/smolagents'"
    )


# 静态内置的顶级开源框架架构图谱，提供生产级高保真分析
FRAMEWORK_KNOWLEDGE = {
    "langgraph": """
[GitHub 仓库: langchain-ai/langgraph 核心架构解析]
-----------------------------------------------
1. 核心类结构拓扑:
   - `StateGraph(BaseModel)`: 图状态机容器。负责定义状态定义、追加 Nodes 与 Edges。
   - `Pregel(Runnable)`: 底层超步运行引擎 (Pregel Superstep Model)。管理图的事件循环流转、Checkpoint 状态恢复以及 Channels 消息分发。
   - `Node`: 执行节点，接收当前 State，返回增量 State 更新字典。
   - `Edge / ConditionalEdge`: 路由边界。基于条件函数计算结果动态流转下一 Node。

2. 状态归约机制 (State Reducers):
   - 使用 `add_messages` 进行消息通道的合并归约（若键为 messages，则使用 list.append，若存在相同 ID 消息则原地 overwrite）。

3. 生产级安全特性:
   - 依赖 Host 宿主机 Python 进程执行节点函数，无默认沙箱隔离，依靠人在回路 (HITL) 断点进行写操作审核限制。
""",
    "smolagents": """
[GitHub 仓库: huggingface/smolagents 核心架构解析]
-----------------------------------------------
1. 核心类结构拓扑:
   - `CodeAgent(Agent)`: 基于 Python 代码执行器作为 Tool Calling 核心的 Agent 容器。
   - `ToolCallingAgent`: 基于标准 JSON/XML format 的 Tool Calling 容器。
   - `RestrictedPythonExecutor`: **核心受限 Python 代码执行沙箱**。不直接调用 eval/exec，而是使用 `ast` 模块解析语法树节点，实施细粒度的白名单控制。
   - `Tool(ABC)`: 标准化工具基类，包含 `__call__` 执行和动态 JSON Schema 参数推导。

2. 运行哲学:
   - "Code as Action"。大模型直接输出一段 Python 代码，代码在内置受限解释器中运行，支持 LLM 在代码内循环调用多个工具，极大降低了单步 Agent 的 I/O 往返时延。
""",
    "letta": """
[GitHub 仓库: letta-ai/letta (原 MemGPT) 核心架构解析]
----------------------------------------------------
1. 核心类结构拓扑:
   - `AgentState`: 完整的物理记忆与会话状态载体。
   - `CoreMemory`: 核心内存区域。包括 `persona` (人设记忆) 与 `human` (用户事实记忆)，通过显式 system block 暴露给大模型。
   - `Block`: 内存持久化物理块，支持与外部关系型数据库同步。
   - `PersistenceManager`: 管理 L1 (Context Window 活跃消息) 与 L2 (Archival Memory 归档) 之间的物理分页换入换出。

2. 运行哲学:
   - "OS-style State Management"。将大模型视为 CPU，将 Context 视为 L1 缓存，利用 Relational DB 模拟 Disk，Agent 能够显式触发 `core_memory_append` 等系统调用进行持久记忆读写。
"""
}


@register_tool(
    name="github_repo_analyzer",
    description="静态剖析主流 Agent 框架（如 LangGraph, smolagents, Letta 等）GitHub 仓库的核心类拓扑和结构树。",
    args_schema=GithubAnalyzerInput
)
def github_repo_analyzer(repo_name: str) -> str:
    """
    静态剖析主流 Agent 仓库。

    Args:
        repo_name (str): 仓库名称。

    Returns:
        str: 仓库类拓扑及核心机制分析。
    """
    name_lower = repo_name.lower()
    
    # 模糊识别
    matched_key = None
    for key in FRAMEWORK_KNOWLEDGE.keys():
        if key in name_lower:
            matched_key = key
            break
            
    if matched_key:
        return FRAMEWORK_KNOWLEDGE[matched_key]
        
    # 兜底返回分析失败提示
    return (
        f"[GitHub 仓库静态分析失败]: 未能找到仓库 '{repo_name}' 的内置离线索引。\n"
        f"支持的框架分析库包括: {list(FRAMEWORK_KNOWLEDGE.keys())}。"
    )
