"""
Day 18: 统一 API 适配器设计与 System/User/Assistant 角色语义契约 - 参考标准答案

=========================================
设计方案说明
=========================================
1. 设计意图：
   在大模型应用开发中，Agent 的决策循环不应直接依赖于具体的第三方模型 SDK。
   为了实现模型切换时的“对扩展开放、对修改关闭”，使用 Python `typing.Protocol` 声明
   统一的大模型调用契约，实现底层模型服务与上层 Agent 推理框架的彻底解耦。

2. 类与函数结构：
   - `LLMResponse` (dataclass): 归一化的响应数据模型，包含生成文本、Token 消耗统计、模型名称等。
   - `BaseLLMClient` (Protocol): 统一的大模型客户端接口，包含 `generate` 异步契约。
   - `OpenAIClientAdapter` (BaseLLMClient): 适配 OpenAI API 的客户端。
   - `DeepSeekClientAdapter` (BaseLLMClient): 适配 DeepSeek API 的客户端。
   - `LLMError` / `LLMAPIError` / `LLMConnectionError`: 统一的适配层自定义异常。

3. 关键数据流流向：
   `Agent 调用 generate` -> `参数规整与映射` -> `异步非阻塞调用特定 SDK`
   -> `截获供应商异常并包装为标准异常` -> `提取特定 JSON 响应并生成 LLMResponse`
   -> `返回 Agent 消费`
=========================================
"""

import os
import asyncio
from typing import Protocol, List, Dict, Any, Optional, runtime_checkable
from dataclasses import dataclass
import openai

# 1. 统一响应实体与异常
@dataclass
class LLMResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    model_name: str
    finish_reason: str


class LLMError(Exception):
    """大模型适配层标准异常基类"""
    pass


class LLMAPIError(LLMError):
    """大模型服务端 API 返回非 200 错误"""
    def __init__(self, status_code: int, message: str):
        super().__init__(f"LLM API Error (Status {status_code}): {message}")
        self.status_code = status_code


class LLMConnectionError(LLMError):
    """大模型客户端网络连接超时或解析失败"""
    pass


# 2. 声明统一 Protocol 契约
@runtime_checkable
class BaseLLMClient(Protocol):
    """
    大模型客户端统一类型契约
    """

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> LLMResponse:
        """
        统一的文本生成契约方法。
        
        Args:
            messages: 符合 ChatML 规范的多轮对话消息列表。
            temperature: 概率采样温度，0.0 表示完全确定性输出。
            max_tokens: 最大生成 Token 限制。
            **kwargs: 扩展的供应商私有参数。
            
        Returns:
            归一化的 LLMResponse 响应实体。
            
        Raises:
            LLMError: 统一适配层异常体系中的标准异常。
        """
        ...


# 3. 编写适配器类
class OpenAIClientAdapter:
    """
    OpenAI 客户端适配器，实现 BaseLLMClient 契约
    """
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: str = "gpt-4o"):
        """
        初始化 OpenAI 客户端。如果未传入凭证，则尝试从环境变量加载。
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.model = model
        
        # 判定是否启用 Mock 模式以利于本地测试与离线演示
        self.is_mock = not self.api_key or self.api_key == "mock_key"
        
        if not self.is_mock:
            # 延迟初始化 AsyncOpenAI 客户端
            self.client = openai.AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        else:
            self.client = None

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> LLMResponse:
        """
        适配 OpenAI 的异步生成实现。
        """
        if self.is_mock:
            await asyncio.sleep(0.1)  # 模拟网络延迟
            return LLMResponse(
                content=f"[Mock OpenAI Completion for {self.model}] Simulated response.",
                prompt_tokens=len(str(messages)) // 4,
                completion_tokens=20,
                model_name=self.model,
                finish_reason="stop"
            )

        # 参数映射转换
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs
        }

        try:
            response = await self.client.chat.completions.create(**payload)
            
            # 提取与归一化响应
            choice = response.choices[0]
            usage = response.usage
            
            return LLMResponse(
                content=choice.message.content or "",
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                model_name=response.model,
                finish_reason=choice.finish_reason or "stop"
            )
            
        except openai.APIConnectionError as e:
            # 将 SDK 私有异常翻译为适配器标准异常以解耦上层
            raise LLMConnectionError(f"OpenAI connection error: {str(e)}") from e
        except openai.APIStatusError as e:
            raise LLMAPIError(status_code=e.status_code, message=str(e.message)) from e
        except Exception as e:
            raise LLMError(f"Unexpected error in OpenAIClientAdapter: {str(e)}") from e


class DeepSeekClientAdapter:
    """
    DeepSeek 客户端适配器，实现 BaseLLMClient 契约
    """
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: str = "deepseek-chat"):
        """
        初始化 DeepSeek 客户端。如果未传入凭证，则尝试从环境变量加载。
        """
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        # 默认使用 DeepSeek 官方 API 端点
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
        self.model = model
        
        # 判定是否启用 Mock 模式以利于本地测试与离线演示
        self.is_mock = not self.api_key or self.api_key == "mock_key"
        
        if not self.is_mock:
            # DeepSeek 的 API 完全兼容 OpenAI 协议
            self.client = openai.AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        else:
            self.client = None

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> LLMResponse:
        """
        适配 DeepSeek 的异步生成实现。
        """
        if self.is_mock:
            await asyncio.sleep(0.1)  # 模拟网络延迟
            return LLMResponse(
                content=f"[Mock DeepSeek Completion for {self.model}] Simulated response.",
                prompt_tokens=len(str(messages)) // 4,
                completion_tokens=20,
                model_name=self.model,
                finish_reason="stop"
            )

        # 参数映射转换
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs
        }

        try:
            response = await self.client.chat.completions.create(**payload)
            
            # 提取与归一化响应
            choice = response.choices[0]
            usage = response.usage
            
            return LLMResponse(
                content=choice.message.content or "",
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                model_name=response.model,
                finish_reason=choice.finish_reason or "stop"
            )
            
        except openai.APIConnectionError as e:
            # 将 SDK 私有异常翻译为适配器标准异常以解耦上层
            raise LLMConnectionError(f"DeepSeek connection error: {str(e)}") from e
        except openai.APIStatusError as e:
            raise LLMAPIError(status_code=e.status_code, message=str(e.message)) from e
        except Exception as e:
            raise LLMError(f"Unexpected error in DeepSeekClientAdapter: {str(e)}") from e


# 4. 编写高可用路由管理器（实现 BaseLLMClient 契约）
class LLMRouter:
    """
    大模型高可用路由管理器（实现了 BaseLLMClient 契约）
    采用组合模式（Composite Pattern），对上层暴露一致的 generate 接口，
    底层自动维护备用客户端链条，在主服务异常时提供动态故障切换（Failover）容错能力。
    """
    def __init__(self, clients: List[BaseLLMClient]):
        if not clients:
            raise ValueError("LLMRouter requires at least one LLM client.")
        self.clients = clients

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> LLMResponse:
        """
        高可用文本生成。按优先级顺序遍历客户端列表，
        当主客户端抛出连接或 API 状态错误时，自动静默切换到备份客户端。
        """
        last_error = None
        for i, client in enumerate(self.clients):
            try:
                # 尝试通过当前客户端适配器调用
                return await client.generate(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs
                )
            except (LLMConnectionError, LLMAPIError) as e:
                last_error = e
                # 触发高可用降级警告日志
                print(f"[Warning] Client {client.__class__.__name__} failed (Attempt {i+1}/{len(self.clients)}): {e}. Fallbacking to next client...")
        
        # 链条中所有客户端均告崩溃，向上级抛出最终异常链关联
        raise LLMError(f"All registered LLM clients failed. Last error: {last_error}")


# --- 演示与测试执行入口 ---
if __name__ == "__main__":
    async def run_demo():
        print("==================================================")
        print("         Day 18 统一 API 适配器与路由管理器演示   ")
        print("==================================================")
        
        # 定义测试消息历史
        messages = [
            {"role": "system", "content": "You are a professional software architect."},
            {"role": "user", "content": "Explain why we prefer Protocol over ABC in 2 sentences."}
        ]
        
        # 1. 实例化两个适配器（Mock 模式）
        openai_adapter = OpenAIClientAdapter(api_key="mock_key")
        deepseek_adapter = DeepSeekClientAdapter(api_key="mock_key")
        
        # 2. 实例化高可用路由管理器（将两个适配器注入其中，模拟主备架构）
        # 假设 DeepSeek 作为首选主模型，OpenAI 作为备选备用模型
        router: BaseLLMClient = LLMRouter(clients=[deepseek_adapter, openai_adapter])
        
        print("\n--- [测试 1] 运行高可用路由管理器 (正常逻辑) ---")
        # 默认情况下，主客户端 DeepSeek 将直接响应
        response = await router.generate(messages=messages, temperature=0.3)
        print(f"实际响应来自模型: {response.model_name}")
        print(f"生成的文本内容: {response.content}")
        
        print("\n--- [测试 2] 模拟主服务故障，触发自动降级 (Failover) ---")
        # 制造一个一定会抛出网络错误的破坏性适配器，插入到首位
        class CrashingClientAdapter:
            async def generate(self, messages, **kwargs):
                raise LLMConnectionError("Connection timed out to primary cluster api.deepseek.com")
        
        faulty_router = LLMRouter(clients=[CrashingClientAdapter(), openai_adapter])
        
        # 当执行调用时，故障路由管理器应当静默拦截 CrashingClientAdapter 的连接异常，
        # 并无缝切换至下一个健康的客户端（openai_adapter），成功获取返回结果。
        fallback_response = await faulty_router.generate(messages=messages)
        print(f"自动降级后实际响应来自模型: {fallback_response.model_name}")
        print(f"生成的文本内容: {fallback_response.content}")
        
        print("\n==================================================")
        print("         高可用路由管理器降级演示验证成功！       ")
        print("==================================================")

    asyncio.run(run_demo())

