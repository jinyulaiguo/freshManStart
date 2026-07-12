"""
AetherMind ReAct Planner
========================

设计方案:
---------
本模块实现了手写的 ReAct 规划器 `AgentExecutor`。
对于复杂的 `PLAN` 和 `TOOL` 流量，规划器通过 `while` 循环进行多步推理，最大迭代 5 轮。
为保障生产级的解析稳定性，本规划器摒弃了传统的非结构化正则解析，
采用 **Pydantic 结构化步骤控制契约 (ReActStep)**，强制要求大模型在每一步以 JSON 输出：
- `thought`：当前推理过程思考。
- `action_name`：拟调用的工具名称。如果准备输出最终解答，此项为 None。
- `action_args`：拟调用工具的字典参数。
- `final_answer`：合并得出的最终解答。

此外，规划器包含**异常反射自纠错机制**：当工具执行抛出任何异常时，
异常会被捕获并作为 `Observation`（观察）作为历史输入，大模型在下一步的 `thought` 中
可以看见该报错，并自我修正参数重新发起调用。

结构说明:
---------
- ReActStep: ReAct 循环单步的模型定义。
- AgentExecutor: 手写规划器核心控制类。
"""

import time
import asyncio
from typing import List, Dict, Any, Optional, AsyncGenerator
from pydantic import BaseModel, Field
from aether_mind.tools.base import TOOL_REGISTRY
from aether_mind.utils.client import AetherMindLLMClient
from aether_mind.utils.logging import TraceContext, logger


class ReActStep(BaseModel):
    """
    ReAct 推理单步的结构化输出契约。
    """
    thought: str = Field(
        ...,
        description="推理思考过程，思考当前任务状态、下一步需要什么信息或如何解决错误。"
    )
    action_name: Optional[str] = Field(
        default=None,
        description="要调用的工具名称（必须是 github_repo_analyzer 或 arxiv_paper_fetcher 之一）。如果已得到最终答案并准备输出，设为 None。"
    )
    action_args: Optional[Dict[str, Any]] = Field(
        default=None,
        description="工具调用的参数字典。不需要调工具时设为 None。"
    )
    final_answer: Optional[str] = Field(
        default=None,
        description="对用户问题的最终合并总结解答。需要调用工具时，此字段为 None。"
    )


class AgentExecutor:
    """
    手写 ReAct 5-loop 规划执行引擎。
    """

    def __init__(self, client: AetherMindLLMClient):
        """
        初始化规划器。

        Args:
            client (AetherMindLLMClient): 统一大模型客户端。
        """
        self.client = client
        self.max_steps = 5

    async def execute(
        self,
        query: str,
        context_str: str,
        session_id: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        启动 ReAct 5轮推理环。逐步 Yield 执行轨迹（Trace）和最终生成的回复内容。

        Args:
            query (str): 用户提问。
            context_str (str): RAG 检索及长短期背景文本。
            session_id (str): 会话唯一 ID。

        Yields:
            AsyncGenerator[Dict[str, Any], None]: SSE 消息节点字典流。格式如下：
                - {"type": "trace", "step": "planner", "content": "..."}
                - {"type": "token", "content": "..."}
        """
        # 1. 组装工具说明元数据，供模型在 System Prompt 中识别
        tools_desc = []
        for name, tool in TOOL_REGISTRY.items():
            schema_json = tool.args_schema.model_json_schema()
            tools_desc.append(
                f"工具名称: {name}\n"
                f"描述: {tool.description}\n"
                f"参数要求: {schema_json}\n"
            )
        tools_str = "\n---\n".join(tools_desc)

        # 2. 构造 ReAct 规划器专属的 System Prompt
        system_content = (
            "你是一个具备多步自主规划与反思纠错能力的 ReAct 执行引擎。\n"
            "你需要根据已有的背景知识与可用的工具，逐步分析并解决用户的问题。\n\n"
            "【可用的外部工具列表】:\n"
            f"{tools_str}\n\n"
            "【已知上下文背景】:\n"
            f"{context_str}\n\n"
            "运行规范：\n"
            "1. 每一轮推理，你必须严格输出满足指定 JSON Schema 结构的单步计划。\n"
            "2. 如果你认为已知背景或先前步骤的信息已经足够解答用户问题，请将 final_answer 设为您的最终技术陈述（注意：此时 action_name 设为 None）。\n"
            "3. 如果需要调用工具获取增量知识，指定 action_name 和对应参数 action_args（此时 final_answer 设为 None）。\n"
            "4. 严禁捏造或猜测未提供的事实，所有工具调用出错的信息将真实反馈给你用于反思修正。"
        )

        react_history = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"请针对问题进行 ReAct 推理：'{query}'"}
        ]

        step_idx = 0
        final_response = ""

        # 3. 开启 max_steps 5轮推理循环
        while step_idx < self.max_steps:
            step_idx += 1
            step_start = time.time()

            yield {
                "type": "trace",
                "step": "planner",
                "content": f"【ReAct 第 {step_idx} 轮推理】正在决策计划..."
            }

            try:
                # 4. 调用大模型，得到下一步的 Pydantic 结构化动作对象
                step_decision: ReActStep = await self.client.request_llm_json(
                    messages=react_history,
                    response_model=ReActStep,
                    temperature=0.1,
                    max_tokens=3000
                )

                # 将推理的 thought 作为 trace 实时透传给前端 Dashboard 展示
                yield {
                    "type": "trace",
                    "step": "planner",
                    "content": f"【第 {step_idx} 轮 Thought】: {step_decision.thought}"
                }

                # 5. 情况 A：LLM 给出最终答案
                if step_decision.final_answer:
                    final_response = step_decision.final_answer
                    yield {
                        "type": "trace",
                        "step": "planner",
                        "content": f"【第 {step_idx} 轮 Final Answer】: 推理结束，已得出答案。"
                    }
                    break

                # 6. 情况 B：LLM 申请调用外部工具
                action_name = step_decision.action_name
                action_args = step_decision.action_args or {}

                if not action_name or action_name not in TOOL_REGISTRY:
                    # 如果工具名非规范，记录错误作为 Observation 塞给大模型反思
                    error_obs = f"Observation: Selected action '{action_name}' is invalid. Please select from {list(TOOL_REGISTRY.keys())}."
                    react_history.append({
                        "role": "assistant",
                        "content": f"Thought: {step_decision.thought}\nAction invalid, retrying."
                    })
                    react_history.append({"role": "user", "content": error_obs})
                    continue

                yield {
                    "type": "trace",
                    "step": "planner",
                    "content": f"【第 {step_idx} 轮 Action】: 触发工具 '{action_name}'。入参: {action_args}"
                }

                # 7. 物理调度并执行工具函数，实现底层反射异常防御
                tool_instance = TOOL_REGISTRY[action_name]
                observation = await tool_instance.run(**action_args)

                # 耗时统计
                duration_ms = int((time.time() - step_start) * 1000)
                TraceContext.add_step(
                    f"react_step_{step_idx}",
                    f"Thought: {step_decision.thought} | Action: {action_name}({action_args}) -> Obs: {observation[:100]}...",
                    duration_ms
                )

                yield {
                    "type": "trace",
                    "step": "planner",
                    "content": f"【第 {step_idx} 轮 Observation】: {observation[:200]}..."
                }

                # 8. 将 Thought、Action、Observation 追加到会话记忆链中，提供给下一轮迭代
                react_history.append({
                    "role": "assistant",
                    "content": f"Thought: {step_decision.thought}\nAction: Call tool '{action_name}' with {action_args}."
                })
                react_history.append({
                    "role": "user",
                    "content": f"Observation: {observation}"
                })

            except Exception as e:
                # 异常反思自纠错
                error_msg = f"Observation (Exception): ReAct step execution encountered error: {str(e)}"
                logger.error(f"[ReAct 迭代异常] 第 {step_idx} 步失败: {str(e)}")
                react_history.append({"role": "user", "content": error_msg})

        # 4. 推理结束，流式输出最终解答（模拟 SSE token 输出流以维持与 NONE/RAG 一致的渐进体验）
        if not final_response:
            final_response = "规划器未能在最大步数内得出结论，请稍后重试。"

        # 逐字符/词输出 Token 块
        chunk_size = 10
        for i in range(0, len(final_response), chunk_size):
            await asyncio.sleep(0.02)  # 轻微延时提供更平滑的打字机流式效果
            yield {
                "type": "token",
                "content": final_response[i:i + chunk_size]
            }
