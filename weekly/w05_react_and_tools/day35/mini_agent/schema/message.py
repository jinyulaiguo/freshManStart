"""
MiniAgent Framework v1.0 — 消息格式标准工具函数集

设计方案：
1. 设计意图：
   Day29-34 的实现中，消息构建逻辑（assistant 消息、tool 消息、Error-Boundary 文本）
   散落在各个引擎文件的多个地方，修改格式需要改多处。
   本模块将所有消息构建逻辑收拢为一组纯函数，统一维护消息格式规范。

2. 函数结构：
   - build_assistant_message(): 构建 assistant 角色消息字典
   - build_tool_message(): 将 Observation 转换为 OpenAI tool 消息（别名封装）
   - build_error_boundary_prompt(): 组装 Error-Boundary 自愈反思引导文本
   - build_system_prompt(): 从 ToolRegistry schema 动态生成 System Prompt
   - format_messages_for_api(): 规整 AgentState 中的消息流为 API 兼容格式

3. 数据流流向：
   - StateReducer 调用 build_assistant_message / build_tool_message 构建消息
   - Runner._call_llm 调用 format_messages_for_api 规整后发送给 LLM API
   - Runner 在 Self-Correction 分支调用 build_error_boundary_prompt 构建反思引导
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .observation import Observation


def build_assistant_message(
    thought: str,
    action: str,
    params: dict,
    tool_calls_raw: list | None = None,
) -> dict:
    """
    构建 assistant 角色消息字典，记录 LLM 本轮的 Thought / Action / Params。

    内部同时保存原始的 OpenAI tool_calls 字段（若存在），方便后续消息流规整时
    恢复为 API 兼容格式。

    Args:
        thought: LLM 输出的推理思考文本。
        action: LLM 决定调用的工具名，或 "Finish" 表示终止。
        params: LLM 传递给工具的参数字典（Finish 时包含 result 键）。
        tool_calls_raw: 可选，原始 OpenAI tool_calls 结构（供 API 回放使用）。

    Returns:
        内部 assistant 消息字典，可追加到 AgentState.messages 列表。
    """
    msg: dict = {
        "role": "assistant",
        "content": thought,
        "action": action,
        "params": params,
    }
    if tool_calls_raw:
        msg["tool_calls_raw"] = tool_calls_raw
    return msg


def build_tool_message(observation: "Observation") -> dict:
    """
    将 Observation 对象转换为 OpenAI 格式的 role=tool 消息字典。

    OpenAI API 规范要求：在 assistant 输出了 tool_calls 后，后续消息中
    必须为每一个 tool_call_id 提供对应的 tool 消息（按 ID 关联）。

    Args:
        observation: Dispatcher 执行工具后返回的 Observation 对象。

    Returns:
        符合 OpenAI tool 消息规范的字典，可直接追加到 messages 列表。
    """
    return observation.to_openai_tool_message()


def build_error_boundary_prompt(tool_name: str, error_message: str) -> str:
    """
    组装 Error-Boundary 自愈反思引导文本（Self-Correction Prompt）。

    当工具调用因参数格式错误或运行时异常失败时，Runner 将捕获的异常
    规整为此格式的 Prompt，作为 tool 消息喂回大模型，引导模型在下一轮
    Thought 阶段反思并修正参数，而非直接终止。

    Args:
        tool_name: 调用失败的工具函数名称。
        error_message: 异常的详细错误描述文本。

    Returns:
        格式化的自愈反思引导文本字符串。
    """
    return (
        f"工具 '{tool_name}' 调用失败: {error_message}\n"
        f"这说明你在上一轮传入的参数存在格式错误或数据不合规。请在下一轮的 Thought 阶段："
        f"\n1. 分析本次报错原因，对照工具参数定义找出问题所在；"
        f"\n2. 生成修正后的合规参数，重新调用该工具完成任务。"
    )


def build_system_prompt(tools_schemas: list[dict]) -> str:
    """
    从 ToolRegistry 导出的所有工具 Schema 动态生成 System Prompt。

    System Prompt 包含：工具列表描述 + 严格的 JSON 输出格式约束，
    迫使大模型每次输出标准 JSON（包含 thought / action / params 三个字段）。

    Args:
        tools_schemas: ToolRegistry.get_all_schemas() 返回的 OpenAI 格式工具 Schema 列表。

    Returns:
        完整的 System Prompt 字符串，可直接作为 role=system 消息的 content。
    """
    # 1. 构建工具描述段落
    tool_descriptions = []
    for schema in tools_schemas:
        func = schema.get("function", {})
        name = func.get("name", "")
        description = func.get("description", "")
        parameters = func.get("parameters", {})
        tool_descriptions.append(
            f"- 工具名称: {name}\n"
            f"  功能描述: {description}\n"
            f"  参数定义: {json.dumps(parameters, ensure_ascii=False, indent=2)}"
        )
    tools_section = "\n\n".join(tool_descriptions) if tool_descriptions else "（暂无可用工具）"

    # 2. 组装完整 System Prompt
    return (
        "你是一个具备工具调用能力的智能 Agent。你可以使用以下工具来完成用户的任务：\n\n"
        f"{tools_section}\n\n"
        "【重要输出格式要求】\n"
        "你必须严格以单个 JSON 对象的格式输出，不得包含任何 Markdown 标记或额外文本。\n"
        "输出 JSON 结构如下：\n"
        "{\n"
        '  "thought": "你的推理思考过程（分析上一步工具是否报错、当前应该怎么做）",\n'
        '  "action": "调用的工具名称，若已得到最终答案则填 \'Finish\'",\n'
        '  "params": {\n'
        '    "参数名": "参数值"\n'
        "  }\n"
        "}\n"
        "注意：若 action 为 'Finish'，params 中必须包含 'result' 键，值为给用户的最终答复。"
    )


def format_messages_for_api(
    state_messages: list[dict],
    system_prompt: str,
) -> list[dict]:
    """
    将 AgentState.messages 内部格式的消息流规整为 OpenAI API 兼容的格式。

    内部消息格式与 API 消息格式存在以下差异：
    - internal assistant 消息包含 action / params 等内部字段，API 不认识
    - internal tool 消息已经是标准格式，可直接使用
    - 需要在最前面插入 system 消息

    Args:
        state_messages: AgentState.messages 中存储的内部格式消息列表。
        system_prompt: 已构建好的 System Prompt 文本。

    Returns:
        符合 OpenAI Chat Completions API 要求的消息列表。
    """
    # 插入 system 消息作为首条
    api_messages: list[dict] = [{"role": "system", "content": system_prompt}]

    for msg in state_messages:
        role = msg.get("role", "")

        if role == "user":
            # 用户消息直接透传
            api_messages.append({"role": "user", "content": msg["content"]})

        elif role == "assistant":
            # 将内部 assistant 消息重新序列化为大模型熟悉的 JSON 格式
            # 这样大模型在历史 Context 中能看到它自己之前输出的决策
            serialized = json.dumps(
                {
                    "thought": msg.get("content", ""),
                    "action": msg.get("action", ""),
                    "params": msg.get("params", {}),
                },
                ensure_ascii=False,
            )
            api_messages.append({"role": "assistant", "content": serialized})

        elif role == "tool":
            # tool 消息已是标准格式，但某些接口不支持 tool role，统一转换为 user 消息（兼容性最高）
            tool_name = msg.get("name", "tool")
            content = msg.get("content", "")
            api_messages.append({
                "role": "user",
                "content": f"工具 '{tool_name}' 返回结果: {content}",
            })

    return api_messages
