# 📅 Week 10: LangGraph 核心

> **第十周目标**：理解 LangChain Core 的基础抽象协议，掌握 LangGraph 图状态机（Node、Edge）的搭建逻辑，精通 TypedDict 状态与 add_messages 归约器的工作原理，具备构建带持久化 Checkpoint 状态流转的能力。
> 
> **🟢 开源参与启动**：本阶段开始阅读 LangGraph 源码，学习其底层编译（compile）与控制环实现，针对阅读中的文档缺失或类型注解遗漏，尝试提 Issue/PR 进行参与。

---

## Day 64：LangChain Core 基础抽象与可运行协议（Runnable Protocol）
*   **核心知识点**：
    *   **Runnable 契约**：接口的统一声明（`BaseChatModel`、`Runnable` 等）。
    *   **方法矩阵生命周期**：`invoke` 与 `ainvoke` 的数据通路机制；`stream` 与 `astream` 异步生成器的数据传输。
    *   **链式操作符的限制**：旧版 LCEL (LangChain Expression Language) 的管道符 `|` 的内部装载过程及被图状态机取代的历史原因。
*   **Agent 核心关联**：LangGraph 的核心 Node 本质上都是 Runnable 的底层变形。理解 Runnable 抽象能够确保我们在自定义 Node 时，其输入和输出契约完全被 LangGraph 编译器所接纳。
*   **🎯 过关验证标准**：手写一个自定义的 `Runnable` 实体类，实现其异步 `ainvoke` 与流式 `astream`，并在其中注入输入参数的防御性转换拦截，通过代码验证其与大模型调用的流式闭环。

---

## Day 65：图状态机与有向图 StateGraph 基础
*   **核心知识点**：
    *   **有向图（Directed Graph）模型**：状态顶点（Nodes）、有向转移边（Edges）的几何拓扑关系。
    *   **StateGraph 实例化**：定义共享的状态对象（State），并将各节点进行物理绑定。
    *   **编译（Compile）机制**：`graph.compile()` 的内部逻辑（把图形结构转化为符合 `Runnable` 协议的运行时状态流转引擎）。
*   **Agent 核心关联**：LangGraph 将 Agent 的决策从隐式的 LLM Prompt 循环升级为了显式的图状态转移。这是目前构建工业级、可预测业务逻辑 Agent 的绝对标准。
*   **🎯 过关验证标准**：实例化一个最简 `StateGraph`，定义两个空 Nodes（A 与 B），用普通有向边连结。对其编译后运行，输入初始化状态，验证状态能够在两个节点间顺序流转并返回最终输出。

---

## Day 66：TypedDict 状态定义与 add_messages 状态归约器（Reducer）
*   **核心知识点**：
    *   **TypedDict 强类型契约**：作为图的 State 对象，限制状态只能读写指定 Key 的静态类型。
    *   **add_messages 归约器（Reducer）**的底层更新算法：判断新消息的 `id` 是否已存在，若存在则更新/覆盖（常用于人工干预修改），若不存在则 Append。
    *   **自定义 Reducer 实现**：控制状态在并发读写时的覆盖策略（如取最大值、列表合并去重）。
*   **Agent 核心关联**：LangGraph 所有的 Node 执行后都只返回需要更新的 State 字典。Reducer 决定了 Node 返回的新变量是如何合并进主状态字典的，这对于维护庞大的对话消息历史极为关键。
*   **🎯 过关验证标准**：手写一个自定义状态字典，其中包含一个被 `Annotated` 标记并绑定了自定义 Reducer 的数值属性。编写测试，并发写入多个状态片段，验证归约器是否能准确按照“过滤负数并去重追加”的自定义规则执行合并。

---

## Day 67：路由边（Conditional Edges）与动态决策流
*   **核心知识点**：
    *   **条件分支路由**：通过路由函数（Router Function）分析当前 State，决定图下一步的跳转 Node。
    *   **Conditional Edges 的绑定**：`graph.add_conditional_edges(source, router, path_map)` 中 `path_map` 映射字典的安全配置。
    *   **意图分流与状态过滤**。
*   **Agent 核心关联**：这是 ReAct 主控制循环在 LangGraph 里的真正体现。大模型根据当前的 Thought 决定是去调用工具 Node（路由到 Action），还是直接输出结论（路由到 Finish 终止符）。
*   **🎯 过关验证标准**：编写一个条件路由器函数。当大模型输出的文本以 `CALL:` 开头时路由到 `tool_executor` 节点，以 `FINAL:` 开头时路由到 `end` 节点。通过模拟数据验证分支的 100% 路由分流成功率。

---

## Day 68：图运行次数限制（recursion_limit）与死循环熔断保护
*   **核心知识点**：
    *   **recursion_limit 参数**：在调用 `.invoke()` 时指定的运行安全阈值（默认 25 步）。
    *   **GraphRecursionError 异常拦截**：超出次数后，底层直接抛出特定的编译异常。
    *   **防循环兜底策略**：在异常捕获链条中执行状态回滚或返回降级结论。
*   **Agent 核心关联**：在复杂的条件边路由中，大模型如果决策失误，极易在 Node-A 和 Node-B 之间反复横跳（死循环）。通过设置 `recursion_limit`，能在物理层面上直接限死死循环，防止 Token 消耗失控。
*   **🎯 过关验证标准**：故意设计一个环路图（A 节点永远路由回 B，B 节点路由回 A），设置 `recursion_limit=5`。执行该图，使用 `try...except` 成功捕获并拦截 `GraphRecursionError`，并在此之后安全输出降级回复。

---

## Day 69：内存校验器（Memory Saver）与持久化状态机
*   **核心知识点**：
    *   **MemorySaver 组件**：内存级别的持久化 Checkpointer 原理。
    *   **Thread ID 会话隔离**：利用 `configurable = {"thread_id": "xxx"}` 参数从 Checkpointer 中唯一定位并反序列化出特定用户的运行状态。
    *   **Checkpoint 历史版本**：状态快照存储。
*   **Agent 核心关联**：生产环境下的多用户 Agent 系统必须依赖 Thread ID。它能在内存中完全隔离不同的对话会话，且当大模型调用发生网络中断时，能基于最新的 Checkpoint 顺畅重启，而不会丢失之前的对话状态。
*   **🎯 过关验证标准**：实例化一个支持 `MemorySaver` 的编译图。使用不同的 `thread_id` 并发发起多次对话，验证各 thread 之间的消息状态绝对隔离，且在相同 `thread_id` 下继续发送能够正确加载前文历史。

---

## Day 70：第十周综合实战：基于 LangGraph 的类型安全、环路熔断客服机器人
*   **实战任务**：**利用 LangGraph 图状态机架构重新开发“AI 研究助手”的控制层。**
    *   **要求**：
        1. 使用 TypedDict 定义全局 State，并为 messages 绑定原生的 `add_messages` 归约器。
        2. 构建包含“意图分类 -> 知识检索 -> 工具执行 -> 总结回复”的有向图节点拓扑。
        3. 采用 Conditional Edges 实现大模型决策工具分发；
        4. 全局配置 `MemorySaver` 进行 Checkpoint 保存，隔离不同的 Thread ID；
        5. 配置最大运行次数限制 `recursion_limit=6` 防范死循环，并使用自定义异常链优雅兜底。
    *   **🎯 交付件**：全套 LangGraph 客服机器人代码、持久化配置脚本、单元测试，以及模拟死循环触发熔断与 Thread ID 隔离的运行轨迹日志。\n