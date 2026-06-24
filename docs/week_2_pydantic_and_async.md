# 📅 Week 2: 静态类型、Pydantic 与异步并发

> **第二周目标**：精通 Pydantic 数据校验与规范定义，攻克异步编程大关，具备徒手对接网络 API 与流式数据处理的能力。

---

## Day 8：静态类型注解与 TypedDict
*   **核心知识点**：
    *   基本类型注解与 `typing` 模块的高级用法（Optional, Union, List, Dict）
    *   **`TypedDict`** 的定义、强类型约束与使用限制
    *   **`Annotated`** 的基本概念（为类型附加元数据）
*   **Agent 核心关联**：LangGraph 的核心 `State` 状态管理完全基于 `TypedDict` 和 `Annotated` 进行归约（Reduce）。
*   **🎯 过关验证标准**：定义一个 `AgentState` 的 `TypedDict`，其中包含一个被 `Annotated` 标记的 `messages` 列表，编写一个类型安全的函数对其进行增删操作。

---

## Day 9：Pydantic 数据校验与 JSON Schema（P0 优先级）
*   **核心知识点**：
    *   `BaseModel` 的定义与字段类型约束
    *   `Field` 的使用：别名、默认值设置、描述信息（description）
    *   嵌套模型与模型继承
    *   **导出 JSON Schema**（`model_json_schema()`）
*   **Agent 核心关联**：大模型 Function Calling 的参数声明，本质就是把 Pydantic 模型转成 JSON Schema 喂给 LLM。
*   **🎯 过关验证标准**：用 Pydantic 定义一个 `WeatherToolArgs` 模型（包含城市名、日期、是否摄氏度），并将其导出为 OpenAI 格式的 JSON Schema 工具声明。

---

## Day 10：Pydantic 进阶与 Dataclass 对比
*   **核心知识点**：
    *   `model_validator`（模型级校验）与 `field_validator`（字段级校验）
    *   **`dataclass` 的定义与使用**
    *   `dataclass` vs `Pydantic BaseModel` 的底层区别与适用场景
*   **Agent 核心关联**：`dataclass` 用于轻量无校验的状态传递（如 LangGraph State），而 `Pydantic` 用于强校验的边界输入输出（如 Tool 参数）。
*   **🎯 过关验证标准**：分别用 `dataclass` 和 `Pydantic` 定义同一个数据结构，写一个测试：传入非法类型数据，观察并解释两者的行为差异（一个默许通过，一个抛出 ValidationError）。

---

## Day 11：异步编程基础（P0 优先级）
*   **核心知识点**：
    *   同步与异步的本质区别（阻塞 vs 非阻塞）
    *   `async def` 与 `await` 的语法规则
    *   事件循环（Event Loop）与 `asyncio.run()`
    *   **并发任务调度 `asyncio.gather`**
*   **Agent 核心关联**：大模型调用耗时极长，多个 Tool 并行调用（如并发搜索 3 个网页）必须依赖异步，否则时延爆炸。
*   **🎯 过关验证标准**：写 3 个模拟耗时不同的异步函数，使用 `asyncio.gather` 同时并发执行它们，并验证总耗时仅等于耗时最长的那个函数，而不是累加。

---

## Day 12：异步进阶与网络 API 调用
*   **核心知识点**：
    *   异步上下文管理器（`async with`）
    *   异步迭代器与生成器（`async for` 与 `async yield`）
    *   **使用 `httpx` 进行异步 HTTP 请求**（对比 requests）
    *   流式响应（Streaming）的处理机制
*   **Agent 核心关联**：Agent 调用 OpenAI/DeepSeek API，以及流式（stream）打字机输出，底层全是异步 HTTP 协议和异步生成器。
*   **🎯 过关验证标准**：用 `httpx.AsyncClient` 编写一个异步函数，请求一个公开的 Mock API（如 HTTPBin），使用流式模式读取响应，并用 `async for` 逐块打印。

---

## Day 13：日志工程、回调与事件钩子机制（🌟 新增）
*   **核心知识点**：
    *   `.env` 文件的规范与 `python-dotenv` 读取
    *   `logging` 模块的高级配置：Logger、Handler、Formatter、日志级别
    *   **回调函数（Callable）与事件钩子（Hooks）**：设计通用的事件监听器/订阅者模式，监听 Agent 内部的关键生命周期（如 `on_agent_start`, `on_tool_end`）
    *   结构化日志输出（JSON 格式日志初步）
*   **Agent 核心关联**：回调/钩子是实现 Agent 运行轨迹 Trace（如可视化看板、LangSmith 等）的基础底层。
*   **🎯 过关验证标准**：实现一个 `AgentRunner` 类，它支持注册回调类（必须包含 `on_step_start` 和 `on_step_end` 方法）。在执行模拟步骤时，自动触发这些注册的回调，打印步骤开始和结束的时间戳与状态。

---

## Day 14：第二周综合实战与复习
*   **任务**：**手写一个“异步工具调度器（Tool Runner）”**
    *   用户能用 Pydantic 定义工具的入参 Schema。
    *   调度器支持异步注册工具函数。
    *   当传入工具名 and JSON 字符串参数时，调度器自动进行 Pydantic 校验，并异步并发执行工具。
*   **🎯 交付件**：类型安全、完全异步、具备入参拦截与格式校验的 Tool Runner 核心代码。
