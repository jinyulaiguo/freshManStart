# Day 14 实战：手写“异步工具调度器 (Tool Runner)”

本实战项目要求你自底向上实现一个用于管理和执行本地函数的“异步工具调度器 (Tool Runner)”。

为了帮助你理清整个项目从零开始的开发逻辑，我们将以问题为导向，通过“自问自答”的形式梳理 **Tool Runner 内部组件的开发脉络**，并明确指出每个步骤解决的具体问题与对应的每日知识点：

---

## 🗺️ Tool Runner 核心开发流程与路线图

### 1. 第一步：声明工具参数并实现注册机制（解决工具描述与格式对齐问题）
*   **问**：本地工具函数编写好了，调度器怎么管理它们？大模型需要特定格式的入参描述（JSON Schema），难道要手写拼装描述吗？
*   **答**：不需要手写。我们必须在调度器中实现一个注册机制，将工具函数与对应的 Pydantic 参数模型（如 `CalculatorArgs`）绑定。随后，利用 Pydantic 提供的反射能力自动向外导出工具描述。
*   **解决什么问题**：解决了手动维护工具描述时极易产生的格式语法错误，实现了本地函数与标准工具描述协议的自动对齐。
*   **对应代码组件**：`CalculatorArgs` / `WeatherArgs` 模型定义 与 `register_tool` / `get_tool_schemas` 方法。
*   **需要知识点**：Pydantic BaseModel 与 `model_json_schema()` 导出。
*   **对应学习天数**：**Day 9** & **Day 10**
*   **🎯 学习入口**：[Day 9 学习入口（数据校验与 JSON Schema）](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w02_pydantic_and_async/day_exercises/day9_pydantic/)

---

### 2. 第二步：实现入参解析与强校验网关（解决外部输入参数不可控的安全隐患）
*   **问**：外部（大模型）发送了 JSON 字符串参数要求调用某个工具，如果参数类型写错了，或者参数字段漏了，我们能直接执行本地函数吗？
*   **答**：绝对不能。外部文本输入是不可靠的。我们需要在调用工具函数前，使用 Pydantic 对传入的 JSON 字符串进行反序列化，强校验每个字段的类型，并利用模型校验器过滤逻辑冲突的非法参数（如起止日期倒置），直接在入口处予以拦截。
*   **解决什么问题**：解决了不可信输入带来的运行时安全隐患，将结构校验与业务语义约束统一在调度器最前端，保护底层核心代码。
*   **对应代码组件**：`run_tool` 方法的前置校验逻辑。
*   **需要知识点**：Pydantic 的 `model_validate_json()` 与 `@model_validator` 联合校验器。
*   **对应学习天数**：**Day 9** & **Day 10**
*   **🎯 学习链接**：[Day 10 学习入口（校验进阶与 Dataclass）](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w02_pydantic_and_async/day_exercises/day10_pydantic_adv/)

---

### 3. 第三步：构建非阻塞的异步并发调度核心（解决网络 I/O 阻塞与时延瓶颈）
*   **问**：大模型要求同时调用多个工具（如并发查询三个网页），如果在调度器里使用同步阻塞方式排队请求外部网络 API，速度太慢卡死主线程怎么办？
*   **答**：整个调度执行流和注册的工具函数必须全面异步协程化（async）。遇到批量工具调用需求时，使用异步非阻塞网络库发起请求，并使用 `asyncio.gather` 并发派发，将总等待时间压缩至最慢单次请求的时间。
*   **解决什么问题**：解决了网络 I/O 阻塞造成的单线程等待瓶颈，提升了系统的并发吞吐量与执行效率。
*   **对应代码组件**：`run_concurrent_tools` 并发调度方法。
*   **需要知识点**：`async/await` 协程、`asyncio.gather` 并发调度与 `httpx` 异步请求。
*   **对应学习天数**：**Day 11** & **Day 12**
*   **🎯 学习链接**：
    *   [Day 11 学习入口（异步编程基础）](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w02_pydantic_and_async/day_exercises/day11_async_basics/)
    *   [Day 12 学习入口（异步网络 I/O 与 httpx）](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w02_pydantic_and_async/day_exercises/day12_async_adv/)

---

### 4. 第四步：设计生命周期回调以支持无耦合监控（解决监控逻辑与核心引擎强耦合的维护痛点）
*   **问**：工具在调度器内部默默执行，外部（如前端控制台）怎么知道它执行到了哪一步？如果直接在调度器内部写死 print，代码失去通用性怎么办？
*   **答**：设计一套统一的回调基类，在工具执行的开始、成功和失败等关键生命周期节点抛出事件通知（回调钩子）。调度器只管干活并触发事件，具体的监控、打字机流式输出或入库记录逻辑完全由外部传入的回调子类决定。
*   **解决什么问题**：实现了调度器核心逻辑与外部监控追踪系统的解耦，确保了引擎代码的内聚与复用性。
*   **对应代码组件**：`BaseCallback` 定义与 `run_tool` 中回调钩子的触发现场。
*   **需要知识点**：控制反转设计模式、回调函数机制。
*   **对应学习天数**：**Day 13**
*   **🎯 学习链接**：[Day 13 学习入口（日志、异常链与回调机制）](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w02_pydantic_and_async/day_exercises/day13_callbacks_exceptions/)

---

### 5. 第五步：建立异常链因果关联以追踪调用栈（解决异常封装导致底层崩溃第一现场丢失痛点）
*   **问**：工具在执行中如果发生网络异常或运行时崩溃，我们要捕获它并反馈友好提示。但如果直接用 `try-except` 吞掉报错，开发人员怎么定位底层的具体出错行号？
*   **答**：在捕获异常时，必须抛出统一的自定义包装异常 `ToolExecuteError`，并使用设置 `__cause__` 的语法将底层原始异常（如 ZeroDivisionError、httpx.ConnectError）关联到该包装异常上。在错误回调中，利用 `traceback` 记录下完整的报错链条。
*   **解决什么问题**：解决了错误信息在层层封装中被吞没的痛点，确保系统在保持健壮性的同时，保留事故的第一现场线索。
*   **对应代码组件**：`ToolExecuteError` 自定义异常定义与 `run_tool` 内的异常捕获块。
*   **需要知识点**：异常链因果关联（raise from）、`traceback` 堆栈追溯。
*   **对应学习天数**：**Day 13**
*   **🎯 学习链接**：[Day 13 学习入口（日志、异常链与回调机制）](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w02_pydantic_and_async/day_exercises/day13_callbacks_exceptions/)

---

### 6. 第六步：设计类型安全的状态管理契约（解决并发状态写入时的拼写错误与覆盖冲突）
*   **问**：工具运行结束后，其执行步数、当前运行名、运行消息日志等全局状态要在调度器内部安全流转。如何防止开发重构时由于手误拼错状态的键名，或高并发写状态时产生数据覆盖？
*   **答**：使用 `TypedDict` 定义严格的运行状态类型规范。同时，使用 `Annotated` 在类型层为日志列表字段绑定专门的状态更新函数（Reducer），规范化状态在多协程并发环境下的写入合并。
*   **解决什么问题**：消除了字典类型的静态键名检查缺陷，保证了状态机内部数据流转的一致性与安全。
*   **对应代码组件**：`RunnerState` 状态契约、`merge_messages` 合并函数与 `self.state` 初始化。
*   **需要知识点**：`TypedDict` 类型契约、`Annotated` 绑定元数据与 Reducer 状态归约。
*   **对应学习天数**：**Day 8**
*   **🎯 学习链接**：
    *   [Day 8 核心概念笔记](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w02_pydantic_and_async/day_exercises/day8_static_typing/notes.md) | [Day 8 单元练习代码](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w02_pydantic_and_async/day_exercises/day8_static_typing/practice.py)

---

## 🧪 最终集成与测试 (Day 14)

当完成了上述 5 个步骤的前置练习后，即可回到本目录，在 [practice.py](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w02_pydantic_and_async/day_exercises/day14_tool_runner/practice.py) 中进行最终的代码整合。

在终端中运行以下命令以检验你的实现是否达到交付标准：

```bash
pytest weekly/w02_pydantic_and_async/day_exercises/day14_tool_runner/test_tool_runner.py
```
