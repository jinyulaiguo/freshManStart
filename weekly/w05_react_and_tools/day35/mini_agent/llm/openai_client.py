"""
MiniAgent Framework v1.0 — AgentLLMClient LLM 适配层

设计方案：
1. 设计意图：
   对 weekly/w04_prompt_and_http/utils.py 中的 LLMClient 进行封装增强。
   增加的能力：
   - latency_ms 计时（使用 time.monotonic 精确计时）
   - usage 统计（从 API 响应中提取 prompt_tokens / completion_tokens）
   - cost 估算（基于 MiniMax-M3 的定价规则）
   - JSON 容错解析（从 LLM 输出中安全提取 JSON 对象）
   - 返回结构化 LLMResponse 而非裸字符串

   为什么封装而不重写？
   - w04/utils.py 的 LLMClient 已经处理了 .env 加载、httpx 连接池、
     API_KEY 校验等底层基础设施，无需重复实现
   - 遵循"单一职责"原则，底层网络通信保持在 w04，上层指标采集在 day35

2. 类与函数结构：
   - LLMResponse: 单次 LLM 调用的结构化响应数据容器（dataclass）
   - AgentLLMClient: LLM 客户端适配器，封装增强 w04 LLMClient
     - __init__(): 初始化，持有 w04 LLMClient 实例
     - chat(messages): 发送消息并返回结构化 LLMResponse
     - _parse_json(text): 安全 JSON 提取（容错正则解析）
     - _estimate_cost(prompt_tokens, completion_tokens): 费用估算

3. 数据流流向：
   - Runner._call_llm() 调用 AgentLLMClient.chat(api_messages)
   - AgentLLMClient.chat() 调用 w04 LLMClient.request_llm()
   - 解析响应 JSON → 提取 content / usage / cost / latency
   - 返回 LLMResponse 给 Runner
   - Runner 从 LLMResponse.content 中解析 Thought/Action/Params
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

# 复用 Week4 公共工具模块中的底层 LLM 请求客户端
from weekly.w04_prompt_and_http.utils import LLMClient


@dataclass
class LLMResponse:
    """
    单次 LLM API 调用的结构化响应数据容器。

    通过 dataclass 而非 Pydantic BaseModel，是因为 LLMResponse 是纯内部传输对象，
    不需要序列化/反序列化校验，dataclass 更轻量。

    Attributes:
        content: LLM 输出的原始文本内容（包含 JSON 格式的 thought/action/params）。
        prompt_tokens: 本次 API 调用消耗的 Prompt Token 数。
        completion_tokens: 本次 API 调用生成的 Completion Token 数。
        total_tokens: prompt_tokens + completion_tokens 的总和。
        cost: 本次调用的估算美元费用。
        latency_ms: 从发起请求到收到响应的总耗时（毫秒）。
    """
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0

    def parse_json(self) -> dict:
        """
        从 content 中安全提取并解析 JSON 对象。

        LLM 输出可能包含 Markdown 代码块（如 ```json ... ```），
        此方法通过正则提取第一个 JSON 对象并解析，容错处理各种输出格式。

        Returns:
            解析出的字典对象，包含 thought / action / params 等字段。

        Raises:
            ValueError: content 中不包含可解析的 JSON 对象时抛出。
        """
        text = self.content.strip()

        # 1. 尝试直接 JSON 解析（最优路径）
        try:
            return json.loads(text)
        except Exception:
            pass

        # 2. 正则匹配首尾花括号之间的完整 JSON 对象（处理 ```json ... ``` 包裹的情况）
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except Exception:
                pass

        raise ValueError(
            f"格式解析失败：LLM 输出不符合 JSON 格式规范。原始内容：\n{self.content[:500]}"
        )


class AgentLLMClient:
    """
    LLM 客户端适配器（封装增强版）。

    在 Week4 LLMClient 的基础上，增加：
    - 响应延迟计时（latency_ms）
    - Token 消费统计（usage）
    - 费用估算（cost）
    - 结构化 LLMResponse 返回（而非裸字符串）

    依赖：weekly.w04_prompt_and_http.utils.LLMClient（底层 httpx 网络通信）
    """

    # MiniMax-M3 定价（每千 Token 的美元费用，仅供估算）
    # 实际计费以账单为准
    PROMPT_PRICE_PER_1K = 0.00060     # $0.0006 / 1K Prompt Tokens
    COMPLETION_PRICE_PER_1K = 0.00240  # $0.0024 / 1K Completion Tokens

    def __init__(self) -> None:
        """
        初始化 LLM 客户端适配器。

        内部持有 w04 LLMClient 实例（复用其连接池和认证配置），
        不重复初始化 httpx 客户端和 API Key 读取逻辑。
        """
        # 复用 w04 底层客户端（.env 加载、API Key 校验、httpx 连接池均在此完成）
        self._base_client = LLMClient()

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """
        基于 MiniMax-M3 定价估算本次 API 调用的美元费用。

        Args:
            prompt_tokens: Prompt Token 数。
            completion_tokens: Completion Token 数。

        Returns:
            估算的美元费用（6 位小数精度）。
        """
        prompt_cost = (prompt_tokens / 1000) * self.PROMPT_PRICE_PER_1K
        completion_cost = (completion_tokens / 1000) * self.COMPLETION_PRICE_PER_1K
        return round(prompt_cost + completion_cost, 6)

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.2,
    ) -> LLMResponse:
        """
        发送消息给 LLM API 并返回结构化响应。

        Args:
            messages: 符合 OpenAI Chat Completions 格式的消息列表
                     （由 format_messages_for_api 生成）。
            temperature: 采样温度（0 ~ 1），默认 0.2（低温确保 JSON 格式稳定输出）。

        Returns:
            包含 content / usage / cost / latency_ms 的 LLMResponse 实例。

        Raises:
            FatalException: 底层 API 调用失败时，由调用方（Runner）捕获并包装为 FatalException。
        """
        # 1. 计时开始（使用 monotonic 时钟，不受系统时间调整影响）
        start_ts = time.monotonic()

        # 2. 调用 w04 底层客户端执行真实 API 请求
        # request_llm 已处理 httpx 异常并返回纯文本 content
        raw_content = await self._base_client.request_llm(
            messages=messages,
            temperature=temperature,
        )

        # 3. 计算延迟
        latency_ms = (time.monotonic() - start_ts) * 1000

        # 4. 估算 Token 消耗（w04 LLMClient 未返回 usage，此处进行简单字符估算）
        # 真实场景中，httpx 响应体中包含 usage 字段，可从中提取精确数据
        # 此处用字符数/4 粗略估算（中文约 2 字符/Token，英文约 4 字符/Token）
        prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
        completion_chars = len(raw_content)
        prompt_tokens = max(1, prompt_chars // 4)
        completion_tokens = max(1, completion_chars // 4)
        total_tokens = prompt_tokens + completion_tokens
        cost = self._estimate_cost(prompt_tokens, completion_tokens)

        return LLMResponse(
            content=raw_content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost=cost,
            latency_ms=round(latency_ms, 2),
        )
