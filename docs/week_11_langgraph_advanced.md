# 📅 Week 11: LangGraph 进阶

> **第十一周目标**：精通人在回路（HITL）交互机制与运行时中断（interrupt）控制，掌握“时间旅行”状态回滚，熟练设计多线程并行节点的分支汇聚，具备在生产环境下编写自定义 Redis/Postgres Checkpointer 持久化插件的能力。

---

## Day 71：人在回路（HITL）中断（interrupt）机制与断点控制
*   **核心知识点**：
    *   **双范式中断控制**：静态拓扑断点 `compile(interrupt_before=[...], interrupt_after=[...])` 与动态节点内中断 `interrupt()` 的设计含义与适用场景。
    *   **中断运行时与状态快照**：图挂起冻结机制，调取 `StateSnapshot` 读取 `snapshot.next` 待执行队列与 `snapshot.tasks` 中解构的 Interrupt Payload。
    *   **双路径解冻恢复（Resume）**：调用 `update_state` 原位修正状态并搭配 `invoke(None)` 恢复运行；或通过 `Command(resume=...)` 注入人工审核响应数据原位解冻。
*   **Agent 核心关联**：对于高风险的 Agent 决策（如发送商业邮件、删除数据库记录、大额资金支付），绝不能交由 LLM 盲盒全自动执行。必须通过物理阻断屏障挂起图状态落盘，等待人工安全审计与修正后缝合控制流。
*   **🎯 过关验证标准**：构建带双范式 HITL 机制的状态图。1) 验证静态断点 `interrupt_before` 在节点前挂起，调取快照，利用 `update_state` 修正参数后解冻；2) 验证动态 `interrupt()` 在大额场景触发挂起并暴露告警 Payload，通过 `Command(resume=...)` 注入响应恢复图运行。

---

## Day 72：工具调用人工审批与运行时拦截重写
*   **核心知识点**：
    *   **LLM tool_calls 原位覆写**：解析挂起快照中的 `AIMessage.tool_calls`，在 `update_state` 中修正工具入参 arguments，防止重新生成产生的 Token 浪费与随机抖动。
    *   **`as_node` 挂载点控制**：使用 `graph.update_state(config, patch, as_node="agent")` 明确状态覆写的节点锚点，确保控制流无缝推进至 `ToolNode`。
    *   **工具安全审批与风控拦截**：组合静态/动态中断，实现高危 SQL/API 调用的“审核-修正-放行-审计”全链路防护。
*   **Agent 核心关联**：当大模型生成的工具参数有误（如 SQL ID 拼错、转账金额多打零）时，人类安全员可直接在 Checkpoint 原位纠偏 `tool_calls` 参数并无缝放行，大幅提升人机协作效率与执行确定性。
*   **🎯 过关验证标准**：构建带工具调用的客服 DB 查询状态图。当 LLM 决策生成错误的查询参数 `{"user_id": "ERR_999"}` 并触发表单挂起时，通过 `update_state(config, {"messages": [...]}, as_node="agent")` 将 `tool_calls` 的参数修改为正确的 `{"user_id": "USR_1001"}` 并解冻运行，验证 `ToolNode` 执行了正确的数据库查询并返回预期结果。

---

## Day 73：状态“时间旅行”（Time Travel）与回滚分叉重试
*   **核心知识点**：
    *   **Checkpoint 链式历史回溯**：使用 `graph.get_state_history(config)` 遍历该 thread 历史中带有唯一 `checkpoint_id` 与 `parent_checkpoint_id` 的状态快照链。
    *   **分叉执行（Forking）机制**：在特定历史 `checkpoint_id` 节点上，构造带 `checkpoint_id` 的 RunnableConfig 发起二次 `invoke` 派生新分支。
    *   **快照修补分叉（Snapshot Patch & Fork）**：结合 `update_state` 在历史快照点注入修正数据并分叉流动，确保原历史路径不被破坏的同时实现“故障自愈式重做”。
*   **Agent 核心关联**：在多步循环推演（如代码重构、复杂推理）中，若第 5 步发生逻辑崩溃，最省算力与确定的恢复方式是回滚到第 3 步（大模型决策偏离点），修改状态并分叉推演一条新路径。
*   **🎯 过关验证标准**：构建一个多步骤 Agent 运行图，产生至少 4 个 Checkpoint 节点。通过 `get_state_history` 读取历史快照，选取中间步骤的 `checkpoint_id`，利用 `update_state` 修正 Context 参数并发起 `invoke` 分叉运行，验证生成了包含新 `checkpoint_id` 的分支历史，且旧分支与新分支的 Checkpoint 链均完整可读取。

---

## Day 74：子图（Subgraph）状态隔离与并发子流程设计
*   **核心知识点**：
    *   **子图模式（Subgraph）架构**：主图节点绑定已编译的 `StateGraph` 实例，实现模块化嵌套编排。
    *   **状态隔离与 Schema 映射（State Mapping）**：通过独立定义 `ChildInputState` / `ChildOutputState` 物理隔离子图高频消息与局部细节，防止污染 `ParentState` 历史链。
    *   **Nested `checkpoint_ns` 命名空间**：理解底座持久化引擎如何通过命名空间分隔（如 `thread_id:subgraph_node`）维护主子图独立且连贯的 Checkpoint 结构。
*   **Agent 核心关联**：在大型企业级多 Agent 架构（如退款处理子系统、代码审计子系统）中，各个专业模块逻辑复杂。利用子图模式能实现高内聚低耦合，保持主控制流清爽优雅。
*   **🎯 过关验证标准**：构建主图 `ParentGraph` 与子图 `RefundChildGraph`。子图使用独立简化的 `ChildState` 执行多步退款校验。主图将 `RefundChildGraph` 作为 Node 嵌套调用，验证子图内部高频状态不写入主图 State，且最终只有 `RefundResult` 被正确归约合入主图状态。

---

## Day 75：多线程并行节点（Parallel Nodes）的并发执行与分支汇聚
*   **核心知识点**：
    *   **拓扑扇出与扇入（Fan-out / Fan-in）**：通过 `builder.add_edge("start", ["node_a", "node_b"])` 触发非阻塞并发分支，并在汇聚节点安全归约。
    *   **Pregel 超步（Superstep）同步屏障 Barrier 机制**：理解引擎如何在当前 Superstep 冻结等待所有并行 Worker 执行完毕后，统一推进至下一 Superstep 汇聚节点。
    *   **并发安全 Reducer 竞态防护**：使用 `Annotated[list, operator.add]` 强类型归约器解决多路 Node 状态并发写入冲突，实现数据无损强一致合并。
*   **Agent 核心关联**：在多源并行检索（如同时调用学术库、搜索 API、本地 DB 进行信息交叉核验）或多 Agent 审查（代码审计 + 性能审计）时，利用并行节点能降低 60%+ 的总响应延迟。
*   **🎯 过关验证标准**：设计多源核验 Agent 图。从起始节点同时 Fan-out 分流给 `BaiduSearchNode` 与 `GoogleSearchNode` 并发执行；两个 Worker 各自模拟延迟；在汇聚节点 `ConsolidateNode` 上使用 `Annotated` 列表 Reducer 成功将两路并发返回的数据安全归约合并，且验证总耗时接近最大单节点耗时（而非两者叠加）。

---

## Day 76：持久化存储接口与自定义 Redis/Postgres Checkpointer 扩展
*   **核心知识点**：
    *   **BaseCheckpointSaver 接口契约**：理解 LangGraph 读写 Checkpoint 的核心抽象方法（`put` 与 `get`）。
    *   **Redis / PostgreSQL 连接池与序列化**：将图状态（State）序列化为二进制字节流（使用 pickle 或 json），存储并建立快速索引。
    *   **分布式锁与一致性**：在高并发场景下防止同一 thread_id 被多个请求并发写入。
*   **Agent 核心关联**：默认的 `MemorySaver` 是内存级别的，进程重启状态就归零。在真正的线上高并发生产环境中，必须自己基于 Redis 或 Postgres 数据库重写持久化存储插件，以支持百万级多租户状态存盘。
*   **🎯 过关验证标准**：继承 `BaseCheckpointSaver` 抽象类，手写一个 Redis 校验器 `RedisCheckpointer`（或 Postgres 版本），并在编译图时予以绑定，验证数据落库的序列化正确度及重启恢复功能。

---

## Day 77：第十一周综合实战：带人工介入审批与时间旅行故障恢复的 SQL 执行 Agent
*   **实战任务**：**开发一个企业级的高安全性数据库交互图状态机系统。**
    *   **要求**：
        1. Agent 能够根据用户问题动态构建 SQL 语句（Node-1）。
        2. 构建 Node-2（SQL 执行）前配置 `interrupt_before` 断点挂起，并将当前生成的 SQL 输出到终端等待确认。
        3. 支持外部人工 update_state：人工可以修改 SQL 参数，也可以直接点击“确认”通过。
        4. 写入 SQLite 数据库，并捕获运行异常；一旦执行崩溃，支持技术人员调取 Checkpoint History，一键回溯到“生成 SQL”阶段进行“时间旅行式”的参数修改分叉运行。
        5. 基于 Redis 自定义 Checkpointer 读写全图状态。
    *   **🎯 交付件**：完整的 SQL 执行 Agent 图拓扑代码、RedisCheckpointer 扩展插件、异常回滚测试脚本、单元测试，以及全套运行时中断、数据修改和回滚恢复的日志。\n