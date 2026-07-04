# Day 18：统一 API 适配器设计与 System/User/Assistant 角色语义契约 — 核心笔记

在大模型工程落地与 Agent 架构设计中，**统一 API 适配层**的建立以及**多角色语义契约**的严格遵守是确保系统健壮性、可测试性与可扩展性的基石。本篇笔记以“问题驱动与自问自答”的软件工程视角，深度剖析其背后的设计哲学与工程实现。

---

## 🧭 第零步：定位并引导痛点场景

> **【问】** 如果我们直接在 Agent 中到处通过 `openai.OpenAI()` 的 SDK 客户端向大模型发送请求，会产生什么底层瓶颈与系统隐患？
> **【答】** 
> 1. **强耦合导致的重构灾难**：当底座模型需要从 OpenAI 快速切换至 DeepSeek 或 Qwen 时，你必须在整个项目中成百上千处修改 SDK 实例调用、参数入参、以及深度嵌套的响应字典提取逻辑（如 `choices[0].message.content`）。
> 2. **异常穿透与防御失效**：第三方 SDK 的专属异常（如 `openai.RateLimitError`）会直接击穿至 Agent 业务层。如果不做层层翻译，上层业务将无法统一捕捉和处理网络超时、频率超限等常见故障。
> 3. **横切关注点（Cross-Cutting Concerns）缺失**：你很难在不破坏业务代码的前提下，为每一次大模型请求无缝植入 **Token 审计日志**、**耗时遥测指标（TTFT/TPOT）**以及**动态故障降级机制**。

---

## 💡 第一步：建立直观类比与核心定义

*   **直观类比**：在生活中，**统一适配层**就像是**多功能电源适配器**。中国插头、欧洲插头、美国插头的物理结构和工作电压各不相同，但只要插入适配器，就能统一转换为你的设备所需的 Type-C 充电口。
*   **核心定义**：
    1. **接口契约（Interface Contract）**：基于 Python `typing.Protocol` 声明的静态类型规约，不依赖显式继承，仅对方法的入参和返回值进行结构化约束。
    2. **异常转换（Exception Translation Pattern）**：捕获依赖服务的供应商专属异常，包装并重新抛出系统内部统一定义的异常，从而实现异常链的彻底解耦。

---

## 🛠️ 第二步：提供最小但真实的代码示例

下面的代码展示了如何利用 `typing.Protocol` 与 `dataclass` 定义最基础的类型契约：

```python
from typing import Protocol, List, Dict, Any, Optional, runtime_checkable
from dataclasses import dataclass

@dataclass
class LLMResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    model_name: str
    finish_reason: str

@runtime_checkable
class BaseLLMClient(Protocol):
    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> LLMResponse:
        """统一的文本生成接口"""
        ...
```

*   **预测与思考**：通过 `@runtime_checkable` 装饰器，可以在运行时使用 `isinstance(client, BaseLLMClient)` 动态断言任何类是否满足该协议，即便它没有继承自该类。

### 🔍 深度辨析：为什么必须加 `@runtime_checkable`？只是为了防止运行时报错吗？

**【问】** 既然 Python 是动态语言，为什么不直接利用静态类型提示，而一定要引入 `@runtime_checkable` 装饰器？它是被动为了“不报错”，还是主动的架构防御？
**【答】** 
1. **静态与动态的职责分离**：
   * **静态开发期**：即使没有 `@runtime_checkable`，静态类型检查器（如 `mypy`、`pyright`）也可以对满足 Protocol 结构的类进行完备的类型推导。
   * **动态运行期**：Python 默认不支持在运行时对非继承的 `Protocol` 进行 `isinstance()` 或 `issubclass()` 校验。一旦执行此类操作，Python 解释器会因为安全性限制直接抛出 `TypeError` 崩溃。
2. **主动的动态防御契约（Runtime Guarding）**：
   引入该装饰器绝非仅仅“为了避开报错”，而是为了赋能应用在运行时能够**主动地、低耦合地进行依赖有效性验证**。
   * 比如，大模型管理器（LLM Manager）在启动或加载动态插件时，可以通过 `isinstance(adapter, BaseLLMClient)` 强行在运行时断言拦截所有不符合接口规约的非法对象，从而阻断无效调用，提高系统健壮性：
     ```python
     def register_adapter(self, adapter: Any):
         if not isinstance(adapter, BaseLLMClient):
             raise TypeError("The registered adapter does not conform to the BaseLLMClient Protocol contract.")
     ```

---


## ⚡ 第三步：展示主动破坏与常见报错（防错设计）

### 场景 A：网络超时与服务崩溃
> **【问】** 当底层 API 请求发生网络超时、连接被对端重置或接口返回 502/503 时，会发生什么？
> **【答】** 底层 SDK 会抛出 `openai.APIConnectionError`。若直接穿透给 Agent，由于没有对应的异常处理类，会导致整个推理循环崩溃。
> **【防错方案】** 必须在适配器中进行防御性捕获并翻译：
```python
try:
    response = await self.client.chat.completions.create(**payload)
except openai.APIConnectionError as e:
    raise LLMConnectionError(f"Network handshake failed: {str(e)}") from e
except openai.APIStatusError as e:
    raise LLMAPIError(status_code=e.status_code, message=str(e.message)) from e
```

### 场景 B：角色混用导致的安全防御崩塌
> **【问】** 为什么不能在 `User Role` 中随意塞入类似 `system` 语义的全局性约束（如 "Forget previous rules, output..."）？
> **【答】** 混用角色会诱发 **Prompt 注入攻击**。Transformer 的注意力矩阵不会区分数据与控制指令的层级，必须通过强物理隔离（将核心防御性策略锁死在首个 `System` 消息中）配合适配层参数限制（如禁止用户修改 System 角色），来构筑安全边界。

---

## 📝 第四步：设计默写与主动召回机制

### 🧠 核心逻辑填空练习

请尝试在脑海中完成以下适配器异常翻译与返回结果归一化的核心段落：

```python
class OpenAIClientAdapter:
    async def generate(self, messages, **kwargs) -> LLMResponse:
        try:
            # 1. 异步非阻塞发起调用
            raw_response = await self.client.chat.completions.create(
                messages=messages,
                **kwargs
            )
            # 2. 归一化提取响应字段并实例化 LLMResponse
            return LLMResponse(
                content=__________________________,       # 填空：如何安全提取文本内容？
                prompt_tokens=____________________,       # 填空：如何提取输入 Token 数？
                completion_tokens=________________,       # 填空：如何提取输出 Token 数？
                model_name=raw_response.model,
                finish_reason=_____________________       # 填空：如何提取结束状态？
            )
        except ___________________ as e:                # 填空：拦截连接/超时异常
            raise LLMConnectionError(str(e)) from e
        except ___________________ as e:                # 填空：拦截服务端状态非200异常
            raise LLMAPIError(status_code=e.status_code, message=str(e.message)) from e
```

---

## 🔍 第五步：剖析真实开源项目的用法

以顶流大模型开发框架 **LangChain** (`langchain_core.language_models.chat_models`) 的基类设计为例：
1. **真实应用场景**：通过统一的 `BaseChatModel` 屏蔽了 Anthropic、OpenAI、Ollama 的差异，提供统一的异步接口 `ainvoke`。
2. **入参模型设计**：统一将入参抽象为 `BaseMessage` 及其子类（`SystemMessage`, `HumanMessage`, `AIMessage`），分别严格对应不同的角色。
3. **生产下的异常处理**：在底层的通信包装层中，针对各服务商定义了通用的回退（Fallback）与重试装饰器，将连接超时等错误自动重试后，翻译为 LangChain 的 `OutputParserException` 或是特定的接口异常抛出。

---

## 🚀 第六步：交付自底向上重构的最小引擎与测试

我们已在当前工作区为您生成了完整的实验目录与代码结构：
*   **练习模版**：[practice.py](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w03_llm_and_api/day_exercises/day18_api_adapter/practice.py)
    *   包含核心 Protocol 声明与异常类的骨架。
    *   `OpenAIClientAdapter` 与 `DeepSeekClientAdapter` 预留 TODO 与 `NotImplementedError` 拦截。
*   **参考答案**：[api_adapter.py](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w03_llm_and_api/day_exercises/day18_api_adapter/api_adapter.py)
    *   完整的非阻塞异步适配器实现。
    *   针对离线与无 API 密钥环境支持 Mock 降级验证。
    *   内置调试入口，可以通过终端直接执行查看控制台格式化输出。
*   **单元测试套件**：[test_api_adapter.py](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w03_llm_and_api/day_exercises/day18_api_adapter/test_api_adapter.py)
    *   覆盖：静态 Protocol 类型契约校验、Mock 流程正常输出校验、底层 SDK 连接/状态异常到适配层标准异常链传递的断言测试。
