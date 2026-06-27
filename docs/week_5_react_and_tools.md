# 📅 Week 5: 手写 ReAct 框架与 Function Calling

> **第五周目标**：精通 ReAct 决策架构的状态流转，手写基于 Python 反射机制的动态工具注册中心，攻克高并发并行工具调用的异常隔离痛点，实现不依赖任何第三方 Agent 框架（如 LangChain/LangGraph）的工业级单 Agent 控制环。

---

## Day 29：ReAct 范式底层运行机制、死循环监测与状态转移图谱
*   **核心知识点**：
    *   **ReAct (Reasoning and Acting) 架构**的经典闭环公式：$Thought \to Action \to Observation \to Thought$。
    *   **有限状态机（FSM）映射**：将 Agent 的决策流抽象为状态节点，并清晰定义状态跳转条件。
    *   **Agent 死循环（Stuck Loop）检测算法**：通过构建滑动哈希窗口，检测大模型连续生成的 $Action + Parameter$ 组合是否存在语义高度重叠，以及如何计算工具调用的重复频率。
*   **Agent 核心关联**：在现实场景中，大模型经常因 Observation 错误或提示词偏离而发生逻辑打转，导致其在 `while` 循环中连续请求同一个工具且入参一模一样。如果在底层不进行死循环强拦截，将产生灾难性的费用账单与无谓的资源消耗。
*   **🎯 过关验证标准**：绘制出包含“决策分支、工具分发、异常拦截、终止判断”的 ReAct 完整状态转移图谱。手写一个轻量级 `StuckDetector` 辅助类，在检测到连续 3 次 Action 及其参数哈希值相同时，能够主动抛出自定义的 `AgentStuckError` 并打断决策循环。

---

## Day 30：动态 Tool 反射注册中心与 Pydantic 动态参数 Schema 提取器
*   **核心知识点**：
    *   **Python 运行时反射（Reflection）与函数签名检查**：使用内置的 `inspect` 模块提取异步函数的 `signature`、参数类型注解（Type Annotations）与 docstring。
    *   **Pydantic 动态建模（Dynamic Modeling）**：利用 `pydantic.create_model` 从 Python 函数参数动态组装出一个 `BaseModel` 校验类。
    *   **OpenAI 工具定义格式规范**：将导出的 Pydantic 模型转化为符合 OpenAI 原生工具调用规范的 `{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}` 声明字典。
*   **Agent 核心关联**：工业级 Agent 系统不能手动硬编码工具的 JSON schema。手写反射注册中心能让开发者仅通过一个 `@tool` 装饰器，就自动完成工具的“入参提取、描述提取、Schema 动态转换、运行时参数拦截”，极大提高工具库的扩展性。
*   **🎯 过关验证标准**：手写一个 `ToolRegistry` 工具类和 `@tool` 装饰器。只要在一个带有详细 docstring 和强类型注解的 Python 异步函数上打上该装饰器，它就能自动被 `ToolRegistry` 捕获注册，并能够通过方法输出符合大模型接口规范的标准 JSON Schema 字典。

---

## Day 31：手写 ReAct 核心（一）：主决策 `while` 控制流与历史状态深拷贝机制
*   **核心知识点**：
    *   **异步主决策循环**：构建 `while step < max_steps` 控制回路，并在循环开始前和结束后执行非阻塞状态迁移。
    *   **State 状态深拷贝（Deep Copy）记录**：利用 `copy.deepcopy` 实现每一次决策循环中消息历史、步骤计数、中间 Observation 的状态备份。
    *   **终止条件捕捉**：精准提取大模型输出中的 `finish_reason` 或自定义的 `Finish` 标识符。
*   **Agent 核心关联**：单 Agent 框架最核心的就是主控制循环。掌握主循环的状态转换是理解更复杂的工作流图（Graph）架构的基石。在循环中对 State 执行深拷贝备份，是实现“HITL（人在回路）”以及“Time Travel（时间旅行，返回特定步骤重新执行）”的前提。
*   **🎯 过关验证标准**：完成 `MiniReActEngine` 类的主体骨架。实现其 `run` 异步方法，能够在限制的最大步数（如 5 步）内自底向上循环。编写测试用例，验证当步骤超出最大限制时，能够平滑截断，并回滚到最近一次合法状态快照中。

---

## Day 32：手写 ReAct 核心（二）：动态反射分发调度、参数解包与 Observation 状态归约
*   **核心知识点**：
    *   **参数反射反序列化**：解析大模型返回的 `tool_calls` 中的 JSON 字符串参数，并利用 `ToolRegistry` 中对应的 Pydantic 模型进行强制类型转换与运行时校验。
    *   **动态函数反射分发（Reflective Dispatching）**：使用 `getattr` 或注册中心映射，解包参数并通过 `await` 动态调度执行本地异步函数。
    *   **Observation 状态归约（State Reducing）**：将工具执行结果包装成符合角色定义的 `tool` 消息类型，并利用特定的归约算法追加到历史消息流中，确保上下文链路清晰。
*   **Agent 核心关联**：大模型仅仅是做出了“调用工具”的决策，它并不能真正“执行”工具。Agent 框架的核心职责之一，就是将大模型的决策符号，反射映射到本地真实的 Python 代码中执行，并将执行的 Observation 反馈给大模型，形成闭环。
*   **🎯 过关验证标准**：在 `MiniReActEngine` 中编写 `dispatch_tool` 逻辑，绑定 Day 30 实现的 `ToolRegistry`。传入模拟的大模型 Tool Call JSON 数据，引擎能自动完成参数反序列化校验、动态调用真实的本地异步工具，并生成规范的 Observation 消息体追加回历史。

---

## Day 33：原生并行工具调用（Parallel Tool Calls）的并发非阻塞调度与部分失败隔离
*   **核心知识点**：
    *   **Parallel Tool Calls 协议**：提取大模型在单轮决策中输出的多个独立 `tool_call_id`。
    *   **并发非阻塞调度（Non-blocking Concurrency Dispatching）**：利用 `asyncio.gather(..., return_exceptions=True)` 并发执行所有分发的工具协程。
    *   **异常隔离机制（Exception Isolation）**：如果其中一个工具在运行中抛出异常或超时，不得破坏其他工具的正常运行。
    *   **并发 Observation 拼装**：确保生成的 Observation 消息与 original tool_call 消息在 ID 上完全匹配，且在消息流中的追加顺序合规。
*   **Agent 核心关联**：在复杂的 Agent 运行场景中，如果模型决定并发搜索 3 个网页，使用串行 ReAct 必须重复运行 3 次 LLM 决策，这会带来极高的费用和极慢的响应；使用并发非阻塞调度，能够在一轮迭代中完成所有并发工具的调度与返回。
*   **🎯 过关验证标准**：在 `MiniReActEngine` 中编写 `execute_parallel_tools` 核心协程。测试大模型同时下达 3 个计算工具调用的指令（其中一个工具被设计为必定抛出自定义的异常）。验证引擎能在 1 轮并发中执行完毕，且对抛错工具能正确将报错信息作为 `Observation` 注入，而其他 2 个正常工具的结果依然能被大模型正确接收。

---

## Day 34：工具层异常自愈与主控制流 Self-Correction 反思环
*   **核心知识点**：
    *   **错误边界提示词设计（Error-Boundary Prompting）**：将运行时捕获的工具异常（如 ValueError、API超时、数据缺失等错误堆栈），转化为带特定反思前缀的 Observation 输入。
    *   **自愈（Self-Correction）自适应控制**：设计控制分支，当大模型遇到工具异常时，并不直接退出，而是提示大模型在下一轮决策中利用 `Thought` 阶段反思“为什么出错，如何修正在上一轮中传入的非法参数”，并重新发起调用。
*   **Agent 核心关联**：工具运行环境千变万化，网络波动或数据变动是常态。通过在 ReAct 循环中注入“报错 -> 反思 -> 纠错 -> 重新发起”的自愈逻辑，能让 Agent 拥有在运行期自动修复参数漏洞的超级弹性，而不是遇到一个接口错就直接崩溃。
*   **🎯 过关验证标准**：注册一个数据库查询工具（要求参数必须为符合标准的 `YYYY-MM-DD` 格式，否则抛错）。在测试中，输入“查小明的注册记录”，大模型首次必定生成了错误的参数 “2026年6月”。验证主控制流能够捕获工具抛出的 ValueError，作为 Observation 喂回，并成功引导大模型生成“Thought: 日期格式错误，修正为 2026-06-01”，并在第二轮循环中成功自愈获取数据。

---

## Day 35：第五周综合实战（✅ 里程碑一）：从零手写工业级 ReAct 搜索引擎 Agent
*   **综合实战任务**：**在不使用 LangChain、LangGraph 等任何第三方 Agent 框架的前提下，纯手写实现一个具备高鲁棒性、高并发能力、且能异常自愈的 Parallel ReAct Agent 执行引擎。**
    *   **架构设计要求**：
        1. 基于动态反射的 `ToolRegistry` 完成工具的注册（包含 `web_search`、`get_weather`、`calculator` 三个本地异步工具）。
        2. 基于 Day 31 编写主循环类 `ReActAgentRunner`，具备 `max_steps=5` 拦截和 Day 29 设计的死循环（Stuck）动态监测器。
        3. 核心分发层能精准识别 Parallel Tool Calls，利用 `asyncio.gather` 实现多工具并发调度与异常隔离。
        4. 整个引擎具备 Day 34 的异常自愈（Self-Correction）机制，能够处理多轮工具报错自愈，只有在严重崩溃或超出步数时才抛出自定义的 `AgentExecutionFatalException`。
        5. 每一步的状态转移、工具入参、Observation 返回、大模型 Thought 推理、以及 Token/美元计费账单，都以统一的结构化 JSON 日志形式保存并打印，方便可观测性追溯。
    *   **🎯 交付件**：完整的 `ReActAgentRunner` 及相关的注册中心、死循环监测类、自愈决策逻辑代码，附带对并发调度、异常反思与死循环监控的单元测试，以及一键运行的模拟查询演示脚本。
