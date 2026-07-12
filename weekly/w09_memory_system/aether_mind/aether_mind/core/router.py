"""
AetherMind Memory Router
========================

设计方案:
---------
本模块实现自适应意图分流路由器 `MemoryRouter`。
基于大模型与结构化 JSON 输出规范，预测将用户 Query 分发至以下六路路由之一：
1. `NONE`：常识性、问候性闲聊，无需外部检索与长效记忆。
2. `MEM`：针对用户的人设、开发偏好、背景设定的主观提问。
3. `RAG`：针对特定技术白皮书、库用法、学术概念的客观文献提问。
4. `MEM+RAG`：混合查询，既需要关联用户长期偏好，又需要引入客观文档知识。
5. `TOOL`：执行单一工具调用（如直接抓取指定 Repo/论文）。
6. `PLAN`：需要多步推理、跨库比对或研究框架设计重构的复杂分析。

结构说明:
---------
- RouterDecision: 路由器决策输出模型。
- MemoryRouter: 自适应路由器核心类。
"""

import time
from typing import Optional
from pydantic import BaseModel, Field
from aether_mind.utils.client import AetherMindLLMClient
from aether_mind.utils.logging import TraceContext, logger


class RouterDecision(BaseModel):
    """
    意图路由器输出的决策数据模型。
    """
    route: str = Field(
        ...,
        description="目标路由分支。必须是之一: NONE | MEM | RAG | MEM+RAG | TOOL | PLAN"
    )
    reason: str = Field(
        ...,
        description="做出该意图路由分流决策的技术理由描述"
    )


class MemoryRouter:
    """
    意图分流路由器，预测 Query 的最优流控路线。
    """

    def __init__(self, client: AetherMindLLMClient):
        """
        初始化自适应意图路由器。

        Args:
            client (AetherMindLLMClient): 统一大模型客户端。
        """
        self.client = client

    async def route(self, query: str) -> str:
        """
        对用户 Query 进行语义特征提取与意图判断，输出分流目标标签。

        Args:
            query (str): 用户问题输入。

        Returns:
            str: 路由标签 (NONE / MEM / RAG / MEM+RAG / TOOL / PLAN)。
        """
        start_time = time.time()

        # 1. 设计 Few-shot 示例锚定，减少判断时延并确保稳定性
        prompt = [
            {
                "role": "system",
                "content": (
                    "你是一个极度精准的 AI Agent 意图分流路由器。\n"
                    "你需要根据用户的 Query 进行语义分析，选择最合适的六路分流标签之一：\n\n"
                    "分类标准与 Few-shot 示例：\n"
                    "- NONE: 基础问候、日常闲聊或常识解答。例如: '你好'、'推荐一下好玩的城市'。\n"
                    "- MEM: 查询用户个人的技术偏好、历史偏好、设定偏好。例如: '我喜欢用什么编程语言？'、'你知道我的开发习惯吗'。\n"
                    "- RAG: 对特定的 Agent 开源框架细节、底层代码机制、文献原理解析等客观事实的提问。例如: 'smolagents 的安全沙箱怎么限制 Python 代码运行？'、'解释下 Letta 怎么持久化会话'。\n"
                    "- MEM+RAG: 混合型提问，既需要结合用户历史偏好，又需要查技术白皮书。例如: '根据我的技术偏好，推荐我应该选用 smolagents 还是 LangGraph？'。\n"
                    "- TOOL: 执行特定的单步工具查询动作。例如: '帮我拉取并分析 GitHub 仓库 langchain-ai/langgraph 的结构'、'查一下 arXiv 上关于 Agentic OS 的最新论文'。\n"
                    "- PLAN: 涉及多步骤推理、学术分析、复杂比对或跨章节设计重构。例如: '帮我深度剖析 smolagents 与 Letta 在多租户设计、沙箱安全和状态图管理上的核心异同，并给出一份系统重构建议'。\n\n"
                    "必须严格输出符合 JSON 格式的决策，字段必须包含 route 和 reason，除 JSON 以外不要带任何自然语言前缀。"
                )
            },
            {
                "role": "user",
                "content": f"【用户 Query】: {query}\n\n请进行意图路由决策："
            }
        ]

        try:
            # 2. 调用结构化 JSON 提取
            decision = await self.client.request_llm_json(
                messages=prompt,
                response_model=RouterDecision,
                temperature=0.01
            )
            route_label = decision.route.strip().upper()
            
            # 3. 防御性降级判定，若大模型胡乱输出分类则强制规范为 PLAN/NONE
            valid_routes = {"NONE", "MEM", "RAG", "MEM+RAG", "TOOL", "PLAN"}
            if route_label not in valid_routes:
                logger.warning(f"[路由异常] LLM 返回了非规范标签: '{route_label}'，强制重置为 PLAN。")
                route_label = "PLAN"

            duration = int((time.time() - start_time) * 1000)
            TraceContext.add_step(
                "router",
                f"路由器判定结果为: {route_label}. 原因: {decision.reason}",
                duration
            )
            return route_label

        except Exception as e:
            logger.error(f"[路由决策异常] {str(e)}，默认降级路由为 PLAN。", exc_info=True)
            TraceContext.add_step("router", f"路由器异常降级为 PLAN。错误: {str(e)}")
            return "PLAN"
