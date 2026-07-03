# 📅 Week-by-Week 综合实战项目及交付件汇总

本文件提取自各周详细的 `docs/week_*.md` 计划，精简整理了 **Week 1 到 Week 26** 的所有周末综合实战项目及具体交付件要求。其中，带有 **“主线演进”** 标记的为贯穿性项目 **“AI 研究助手”** 的功能模块。

---

## 阶段一：Python + LLM 地基

### 📅 Week 1: Python 基础与面向对象
*   **综合实战项目**：**手写一个微型 Agent 执行框架原型（Chain-like）**
*   **🎯 交付件要求**：
    *   定义一个 `Tool` 基类，支持 `__call__` 魔法方法执行具体逻辑。
    *   使用单例类 `LLMClient` 模拟大模型调用（随机返回 Action 或文本）。
    *   编写一个装饰器，为 Tool 函数自动包裹输入输出日志、异常捕获与耗时统计。
    *   控制台可流畅运行的微型调用流代码。

### 📅 Week 2: 静态类型、Pydantic 与 异步并发
*   **综合实战项目**：**手写一个“异步工具调度器（Tool Runner）”**
*   **🎯 交付件要求**：
    *   支持用户使用 Pydantic 规范定义工具的入参 Schema。
    *   调度器支持异步注册工具函数。
    *   传入工具名与 JSON 字符串参数时，调度器自动进行 Pydantic 边界参数校验，并异步并发（`asyncio`）执行工具。
    *   类型安全、完全异步、具备入参拦截与格式校验的 Tool Runner 核心代码。

### 📅 Week 3: LLM 原理与 API 交互
*   **综合实战项目**：**具有动态 Fallback 与 Token 审计的异步流式 CLI 聊天终端**
*   **🎯 交付件要求**：
    *   基于 `httpx.AsyncClient` 编写异步非阻塞的适配器，实现打字机式流式分块解析。
    *   基于 LRU 淘汰机制实现并发安全的 Session 消息管理器，以及带 System 优先权的离线上下文裁剪器。
    *   实现动态 Fallback 降级（首选大模型调用超时或报错时，毫秒级切换到备用模型）。
    *   自动统计并输出 TTFT（首包延迟）、Token 吞吐率及 CSV Token 费用审计日志。

### 📅 Week 4: Prompt 工程与结构化输出
*   **综合实战项目**：**高并发、具备重试自愈与熔断机制的简历结构化提取流水线**
*   **🎯 交付件要求**：
    *   设计 Jinja2 模板防止 Prompt 恶意注入。
    *   使用 Pydantic 强类型模型约束大模型输出，结合 `robust_json_parser` 自动修复被故意破坏的脏 JSON 字符串。
    *   应用 `asyncio.Semaphore` 信号量控制高并发连接池，挂载指数退避重试装饰器与 `@circuit_breaker` 熔断器，防御 429 限流及网络波动。

### 📅 Week 5: 手写 ReAct 框架与 Function Calling
*   **综合实战项目【✅ 里程碑一：最小 Agent 引擎】**：**纯手写工业级 ReAct 搜索引擎 Agent**
*   **🎯 交付件要求**：
    *   不依赖任何第三方 Agent 框架，实现 `while max_steps` 主决策控制流循环与历史状态快照深拷贝回滚。
    *   手写动态 Tool 反射注册中心，支持大模型 Parallel Tool Calls（并行工具调用）。
    *   实现并行执行中的部分失败隔离，以及基于 Reflection 的工具层异常自愈与主控制流参数纠偏。
    *   配备 `StuckDetector` 避免 Action 参数哈希相同的死循环熔断。

---

## 阶段二：知识与记忆系统（主线项目启动）

> 💡 **贯穿项目说明**：从本阶段开始，每周的实战项目都将作为功能模块，不断集成到主线项目 **“AI 研究助手”** 中。

### 📅 Week 6: Embedding 与向量数据库
*   **综合实战项目【主线演进：检索基座】**：**具有元数据联合索引与限流防护的高吞吐知识检索引擎**
*   **🎯 交付件要求**：
    *   使用 Docker 部署本地 Qdrant 向量数据库。
    *   实现分批向量化、批量插入流水线，并接入并发 Semaphore 限制与 tenacity 限流指数退避重试。
    *   实现 Pre-Filtering 元数据联合过滤检索（过滤类别、读取级别、时间戳范围等）。
    *   实现 `CleanTextPipeline` 段落清洗去重与 SHA-256 哈希计算。

### 📅 Week 7: 经典 RAG 架构
*   **综合实战项目【主线演进：事实问答】**：**公司内部规章制度问答 Bot（带完美引用与语义切块）**
*   **🎯 交付件要求**：
    *   编写多格式文档解析器（PDF 表格高保真提取为 Markdown、HTML、Markdown 自动检测）。
    *   实现 `SemanticTextSplitter` 语义分块器，在相邻句子 Embedding 距离骤降的话题转换点进行动态切分。
    *   设计 `RAGPipeline`，当向量库召回分数低于 0.6 时自动降级，避免模型幻觉。
    *   通过 Prompt 和解析函数实现 Footnote 脚注，流式生成时实时捕捉 `[doc_id:page]` 并输出可溯源的对照表。
    *   接入 `ReorderContextHandler` 进行 U 型上下文重排，解决 Lost in the Middle 痛点。

### 📅 Week 8: 高级检索与 GraphRAG
*   **综合实战项目【主线演进：图谱推理】**：**跨小说章节的高级逻辑推理分析器（多路 Rerank + 知识三元组）**
*   **🎯 交付件要求**：
    *   实现 `QueryRewriter` 生成 3 句改写问题，并行检索并进行 hash 去重合并。
    *   本地挂载 Cross-Encoder 重排序模型进行二次打分重排，过滤低相关性 Chunks。
    *   实现 HyDE（假设性文档嵌入）检索管道。
    *   设计 Prompt 提取非结构化文本中的实体与关系，在 Python 侧解析为拓扑三元组（Nodes & Edges）。
    *   实现支持 50 个工具的工具智能检索（Tool Retrieval）。

### 📅 Week 9: 多层级记忆系统
*   **综合实战项目【主线演进【✅ 里程碑二】：知识记忆 Agent】**：**具备 RAG + 长期记忆持久化的跨会话 AI 心理慰藉 Agent**
*   **🎯 交付件要求**：
    *   实现短期记忆管理（滑动 Token 窗口自动异步摘要压缩）与长期记忆系统（基于 Qdrant 的用户实体偏好提取及写入）。
    *   编写 `MemoryConsolidator` 处理长期记忆的冗余合并与时序冲突。
    *   使用 `aiosqlite` 实现跨会话持久化 SQLite 消息存储，支持断电状态 100% 还原。
    *   实现 `MemoryRouter` 进行路由分发（MEM / RAG / NONE），路由准确率 >90%。

---

## 阶段三：框架与核心工程

### 📅 Week 10: LangGraph 核心
*   **综合实战项目【主线演进：框架迁移】**：**基于 LangGraph 的类型安全、环路熔断客服机器人**
*   **🎯 交付件要求**：
    *   将“AI 研究助手”的控制层重构迁移至 LangGraph 状态机架构。
    *   定义 StateGraph 拓扑、节点（Nodes）和有向边（Edges）。
    *   使用 `Annotated` 与 `add_messages` 状态归约器（Reducer）管理消息状态。
    *   编写条件边路由器进行分支分流，配置 `recursion_limit` 触发死循环熔断，并绑定 `MemorySaver` 实现基于 Thread ID 的会话持久化与隔离。

### 📅 Week 11: LangGraph 进阶
*   **综合实战项目【主线演进：人在回路】**：**带人工介入审批与时间旅行故障恢复的 SQL 执行 Agent**
*   **🎯 交付件要求**：
    *   配置运行时挂起断点（`interrupt_before`），实现敏感工具执行前的人工审批。
    *   使用 `graph.update_state()` 运行时拦截并重写大模型生成的错误参数。
    *   编写测试代码演示状态“时间旅行”（Time Travel），回退到特定历史 Checkpoint 快照并分叉运行。
    *   编写子图（Subgraph）状态隔离逻辑，并实现多线程并行节点的分支汇聚与消息合并。
    *   继承 `BaseCheckpointSaver` 手写扩展自定义 `RedisCheckpointer`。

### 📅 Week 12: Planning + Reflection 范式
*   **综合实战项目【主线演进：规划反射】**：**支持复杂多任务规划、自动纠错与反思重构的行业趋势分析 Agent**
*   **🎯 交付件要求**：
    *   实现 Plan-and-Execute 状态图，Planner 自动拆解复杂任务并循环分步执行。
    *   构建 ReWOO 图拓扑，将规划步骤与工具 Observation 执行解耦。
    *   构建 Generator 与 Critic 双节点博弈，引入 `AntiHallucinationVerifier` 校对逻辑蕴含关系，防范幻觉。
    *   实现 Reflexion 架构，在工具抛出运行时 Traceback 错误时送入 Reflector 节点反思，并在下一轮生成中纠偏。
    *   支持动态计划重构（Dynamic Re-planning），根据环境反馈重写 Plan 步骤。

### 📅 Week 13: MCP 协议与标准化工具层
*   **综合实战项目【主线演进：工具标准化】**：**通过 MCP 标准协议连接本地文件与远程数据库的强类型系统 Agent**
*   **🎯 交付件要求**：
    *   使用 Python MCP SDK 编写运行 Stdio MCP Server，安全暴露系统内存、文件 URI 资源及本地工具。
    *   编写 MCP Client 挂载服务器，将导出的工具与 LangGraph 进行无缝节点绑定。
    *   使用 Pydantic Field 精确指引优化 Tool Docstring，通过向量检索实现动态 Tool 检索。
    *   实现工具输出多模态二进制流（如图像直方图的 Base64 传递与本地保存）。

### 📅 Week 14: Context Engineering
*   **综合实战项目【主线演进：降本增效】**：**超低成本、毫秒级响应的模型路由与缓存优化 Agent 引擎**
*   **🎯 交付件要求**：
    *   设计分层 Context Jinja2 模板（System/Memory/Retrieval/Dialogue），并保证防注入安全。
    *   在图循环中引入 `BudgetGuard`（Token 预算熔断器），超过限额瞬间抛错中止。
    *   优化 Payload 结构顺序，完美适配 Prompt Cache 规范以提高缓存命中率。
    *   实现异步对话摘要压缩（`ContextCompressor`），以及动态模型路由（`ModelRouter`，复杂任务路由给大模型，简单任务用小模型），降低 Token 成本 30% 以上。
    *   编写高可用 `HAClient`，支持主接口超时（如 1s）时毫秒级自动 Fallback 重试备用 API。

### 📅 Week 15: 评测体系（Eval）
*   **综合实战项目【主线演进【✅ 里程碑三】：框架+规划+评测完整系统】**：**全自动化的 Agent 质量评测与 CI/CD 拦截发布流水线**
*   **🎯 交付件要求**：
    *   构建 50 条 JSONL 格式的 Golden Dataset（黄金评测集）。
    *   设计基于 LLM-as-Judge 的 G-Eval 评测指标打分模板，并控制重测标准差小于 0.2。
    *   实现 `ToolExecutionEvaluator` 计算 Precision、Recall 和 $F_1$ 值，并利用探针打分 Faithfulness（忠实度）和 Relevance（相关性）。
    *   手写 `.github/workflows/eval.yml`，在指标降级或报错时返回非 0 状态码拦截 GitHub PR。
    *   编写 `EvalReporter` 自动比对历史评测结果，输出 Markdown 格式的绝对值变动差异报告。

---

## 阶段四：生产工程化

### 📅 Week 16: 可观测性
*   **综合实战项目**：**接入全分布式链路追踪、指标监控看板的生产级 Agent 可观测性底座**
*   **🎯 交付件要求**：
    *   非侵入式配置并接入 LangSmith/Phoenix 可观测性平台，呈现树状 Trace。
    *   遵循 OpenTelemetry 规范，手写嵌套 Span 包装类对 Agent 内部调用链（加载/RAG/LLM/计算）进行链路嵌套展示。
    *   实时计费上报，监控 Trace 中每个 Span 的 Latency 运行时长、Input/Output Token 数及精细的美元费用。
    *   收集 Traceback 异常堆栈并在 Phoenix 界面上高亮标红展示。
    *   使用 `prometheus_client` 上报 QPS 计数、当前活跃协程、调用 API 时延分布直方图，在 `/metrics` 暴露。

### 📅 Week 17: 可靠性工程
*   **综合实战项目**：**具备网络波动雪崩防护、幂等性事务约束的极高可靠性 Agent 引擎**
*   **🎯 交付件要求**：
    *   手写带随机抖动的指数退避（Jittered Backoff）异步重试装饰器。
    *   实现异步协程安全的令牌桶限流器（`TokenBucketRateLimiter`），支持高频请求平滑放行。
    *   手写熔断器类，管理 Closed/Open/Half-Open 三态流转，实现网络波动自动隔离与探测自愈。
    *   为 RAG 检索 Node 提供异常 Fallback 降级（数据库死锁时切换本地 Mock 缓存）。
    *   结合 Redis 锁编写具有幂等性约束的工具函数，利用 `asyncio.wait_for` 提供连接超时保护与拦截。

### 📅 Week 18: 容器化与部署
*   **综合实战项目【✅ 里程碑四：云原生多租户系统】**：**容器化封装、支持一键 docker-compose 部署的云原生多租户 Agent 集群**
*   **🎯 交付件要求**：
    *   使用 FastAPI 封装 Agent 执行图接口，编写 SSE 协议 `/stream` 路由实现流式传输。
    *   编写多阶段构建的 Dockerfile（体积控制在 250MB 内，非 root 权限运行）。
    *   编写 `docker-compose.yml` 配置文件，编排 FastAPI 服务、Redis checkpointer 和 Qdrant。
    *   编写安全凭证解密挂载脚本，优化 Python 模块的 Lazy Import 以降低 Serverless 部署下的冷启动时延（时延降低 40%+）。
    *   配置 Nginx 反向代理，支持高并发负载均衡并平滑输出 SSE 流。

---

## 阶段五：多 Agent 系统与协议

### 📅 Week 19: 多 Agent 设计模式
*   **综合实战项目【主线演进：多 Agent 协作】**：**基于层级架构的多角色（研究员、文案写手、校对员）研报生成多 Agent 系统**
*   **🎯 交付件要求**：
    *   在 LangGraph 中设计多节点图，运行“规划-执行-审查”三角多 Agent 架构协同。
    *   实现上游节点到下游节点的强类型 Pydantic 管道，防止多步骤传输数据格式报错。
    *   设计层级（Hierarchical）模式下的中央协调器（Supervisor）与分权子图（Subgraphs）。
    *   设计多模型辩论与投票共识机制，并编写基于消息的 Handoff 动态状态传递算法。
    *   设计包含 Namespace 隔离的共享 State 状态字典，防御子 Agent 写入冲突。

### 📅 Week 20: A2A 协议与跨系统协作
*   **综合实战项目**：**跨越两个独立主机的分布式 Agent 协同处理复杂订单任务系统**
*   **🎯 交付件要求**：
    *   手写符合谷歌 Agent-to-Agent (A2A) 通信规范的 Payload。
    *   基于 JWT 签名与验签机制，在 `ClientAgent` 和 `ServerAgent` 间建立跨域身份验证。
    *   使用 Saga 模式设计分布式最终一致性事务，当酒店服务挂掉时自动异步回滚机票预订。
    *   使用 RabbitMQ 消息队列的 ACK 机制与死信队列（DLQ），解耦 Agent 间的并发通信。
    *   实现跨系统异常链传递序列化，并在 HTTP 请求中手动注入和传递 `traceparent` 以实现跨网络可观测性关联。

### 📅 Week 21: 指挥官架构与冲突解决
*   **综合实战项目【主线演进【✅ 里程碑五】：指挥官系统】**：**具有冲突仲裁、动态回溯纠偏机制的高自愈指挥官 Agent系统**
*   **🎯 交付件要求**：
    *   使用 LangGraph 编写中央调度器（Supervisor）分发任务。
    *   为子 Agent 的执行设置最大耗时（如 3s）和最大 Token（如 3000）物理限额隔离。
    *   编写意图检测器，在发生意图跑偏（Intent Drift）时触发警报，回滚至上一状态快照并修正 Prompt 引导。
    *   基于 SQLite 编写分布式互斥锁（Mutex），防止并发 Agent 抢占同一个资源锁产生死锁。
    *   引入 Arbitrator 仲裁节点裁决子 Agent 间的决策冲突，编写 `EarlyStopController` 根据版本编辑距离相似度提前终止会话以节省成本。

---

## 阶段六：Harness Engineering

### 📅 Week 22: Guides 执行前约束
*   **综合实战项目【主线演进：前置约束】**：**构建带 SPEC 校验与自动防越权硬性约束 of Guides 控制引擎**
*   **🎯 交付件要求**：
    *   设计 YAML 格式的 `AgentSPEC` 引导文档并由解析器转化为 System Prompt 注入。
    *   手写 `HardRuleFilter`，在 0.1ms 内预匹配拦截包含“删除系统文件”等恶意指令并抛出异常。
    *   封装可复用的 `WebTableExtractorSkill` 技能包并在 SPEC 中注册挂载。
    *   解析 `AGENTS.md` 行为规范文档并将“二次授权操作列表”动态渲染注入 System Prompt。
    *   设计 `RuleActivator` 动态规则过滤器，根据提问上下文按需激活对应规则，并对工具入参进行前置类型强转与越界安全检查。

### 📅 Week 23: Constraints 执行中控制
*   **综合实战项目【主线演进：隔离防逃逸】**：**在容器化隔离沙箱内安全执行未知代码并自动防御逃逸的 Constraints 系统**
*   **🎯 交付件要求**：
    *   使用 Docker SDK for Python 编写 `SandboxExecutor`，将未知代码送入隔离、无网络、无特权的临时沙箱容器运行。
    *   在 Python 运行时调用 `os.setuid` 和 `os.setgid` 降权运行，以触发系统 ACL 读写阻断。
    *   配置容器 iptables 策略，硬限外网请求防数据泄露。
    *   设计运行时二次授权（2FA）挂起断点，六位 Token 校验通过后继续执行，否则超时回滚。
    *   手写 `PromptInjectionDetector` 运行时拦截注入攻击，并使用 `PIIDataGuard` 双向敏感数据脱敏过滤器屏蔽手机号和密码。

### 📅 Week 24: Sensors / Feedback 执行后校验
*   **综合实战项目【主线演进【✅ 里程碑六】：安全合规封包】**：**完成具备 Guides 执行前规训、Sandbox 执行中隔离与 Sensors 执行后审计的完整 Harness 安全控制封包**
*   **🎯 交付件要求**：
    *   编写 `LinterFeedbackLoop`，调用 `ruff` 扫描大模型生成的文件并将静态扫描报错喂回大模型纠错。
    *   构建审计 Sensor 节点检验促销邮件是否包含“退订指引”等缺失项，不合规时反馈驳回。
    *   实现基于运行时错误的 Self-Correction 局部自动重试反思，捕获 Trace 报错引导大模型修正参数。
    *   手写 Redis `SemanticCacheManager`（语义缓存），在提问相似时直接从 Redis 读取返回（时延 < 8ms）。
    *   引入 `BudgetBreaker` 实时检测 Token 费用并在超限时强行熔断状态机。
    *   编写微调数据生成器，导出脱敏的多轮 SQLite 成功对话为 fine-tuning JSONL 训练集。

---

## 阶段七：毕业冲刺

### 📅 Week 25: 毕业项目打磨与作品集准备
*   **综合实战项目【最终里程碑：完整作品集】**：**打磨完毕、功能完备、生产就绪的“AI 研究助手”毕业级 GitHub 仓库交付**
*   **🎯 交付件要求**：
    *   重构底层架构，使三个子 Agent 完全适配 LangGraph 编排、多 Agent 层级协同和 Harness 三层控制环。
    *   注入恶意脚本进行 Sandbox 沙箱容器逃逸测试，验证 Linux 降权及 iptables 拦截对容器的保护。
    *   接入 Phoenix 和 Grafana 看板，抓取并呈现精细的端到端时延和 Token 费用图表。
    *   并发运行 100 个 Golden Dataset 测试用例，自动生成包含详尽指标和回归变化比对的 Markdown 评测白皮书 `eval_whitepaper.md`。
    *   整理 GitHub 仓库，提供包含 Mermaid 架构图、一键 `docker-compose` 启动指南和可观测性配置的顶级 README.md。
    *   录制 5 分钟交互式 UI 演示视频，展现沙箱防御、LangGraph 回滚、Grafana 看板等核心功能。

### 📅 Week 26: 简历梳理与面试冲刺
*   **综合实战项目【求职就绪】**：**全真模拟面试与简历完成封包**
*   **🎯 交付件要求**：
    *   按照 STAR 原则整理 5 个核心面试故事（手写 ReAct 循环、高级 RAG 优化、自动化评测、Harness 防失控安全沙箱等）。
    *   绘制出支持百万日活多租户的 Agent System Design 平台架构拓扑图。
    *   推导自注意力公式、KV Cache 显存公式及 3 种并发协议优雅降级设计方案。
    *   优化完毕的“Agent 开发专家”高含金量简历 PDF，正式向求职市场投递并记录首批面试进度。
