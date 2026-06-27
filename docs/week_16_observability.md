# 📅 Week 16: 可观测性

> **第十六周目标**：理解可观测性与传统日志的本质区别，掌握 OpenTelemetry 与 OpenInference 追踪规范，精通 Trace/Span/Event 的层级嵌套设计，实现运行时长与 Token 美分费用的精确实时上报，具备搭建 Prometheus + Grafana 告警看板的能力。

---

## Day 106：可观测性与 LangSmith 平台追踪机制剖析
*   **核心知识点**：
    *   **可观测性（Observability）**的定义：监控不仅是收集日志，更要能观察内部状态流动。
    *   **LangSmith 核心组件与原理**：如何通过上下文管理器（Context Manager）或装饰器劫持 Runnable API 调用，自动收集输入输出、参数与执行轨迹。
    *   **API 密钥配置与环境变量解耦**。
*   **Agent 核心关联**：Agent 的决策执行像个黑盒。通过 LangSmith 等追踪系统，开发人员能一眼看出大模型在第 3 步生成了什么 Thought，调用了什么 Tool，为何在第 4 步陷入了死循环。
*   **🎯 过关验证标准**：在 Python 脚本中配置 LangSmith 环境变量。在不修改核心业务代码的前提下，绑定追踪代理，运行一个 ReAct Agent 实例，在 LangSmith 后台能够清晰看到包含“Thought -> Action -> Observation”的完整交互树状 Trace。

---

## Day 107：OpenInference 标准与 OpenTelemetry 分布式追踪系统
*   **核心知识点**：
    *   **OpenTelemetry 标准**：云原生分布式追踪的事实标准（Tracer, Meter, Provider 概念）。
    *   **OpenInference 协议规范**：专为生成式 AI 和大模型设计的追踪拓展契约，定义了统一的大模型属性（如 `llm.input_messages`、`llm.output_messages`、`tool.name`）。
    *   **Phoenix / Arize 追踪服务器的本地部署与对接**。
*   **Agent 核心关联**：企业内网环境通常由于网络安全和敏感数据限制无法使用外网的 LangSmith。掌握基于 OpenTelemetry/OpenInference 的 Phoenix 本地化开源追踪方案，是私有化企业级 Agent 的必备能力。
*   **🎯 过关验证标准**：通过 Docker 部署本地 Phoenix 可观测性服务器。在 Python 侧配置 OTEL Exporter 导出器，向本地服务器发送 Trace 消息流，并在本地管理界面成功还原大模型调用的输入输出。

---

## Day 108：Trace / Span / Event 的结构化设计与嵌套拓扑
*   **核心知识点**：
    *   **Trace**：一次端到端 Agent 请求的完整生存周期；
    *   **Span**：Trace 下的具体执行单元（如 RAG 检索是一个 Span，大模型调用是子 Span，本地代码处理是另一个 Span），具有父子依赖的树状嵌套拓扑结构。
    *   **Event**：Span 内发生的瞬时时间标记（如抛出异常的瞬间、缓存命中的瞬间）。
*   **Agent 核心关联**：合理的嵌套 Span 设计能让我们直观量化耗时占比：例如一眼看出“端到端耗时 5 秒中，有 4.2 秒耗在 RAG 粗筛向量检索的 Span 内”，从而精确定位性能瓶颈。
*   **🎯 过关验证标准**：手写一段基于 Python 装饰器和上下文管理器的 Span 嵌套包装类。修饰一个包含了“加载 -> RAG -> 大模型 -> 本地计算”的四阶段异步流程，运行后输出 JSON 结构的 Trace 嵌套链路日志。

---

## Day 109：运行时长（Latency）与 Token 成本实时计费上报
*   **核心知识点**：
    *   **时延开销监控**：在 Span 启动时记录单调时钟（`time.monotonic()`），结束时计算精确时延。
    *   **Token 消费的分布式累加**：在并发多 Agent 系统中，如何将子节点产生的 Token 账单层层上报，累加到主 Trace 节点的 Attribute 属性中。
    *   **计费数据规约**。
*   **Agent 核心关联**：在高并发大流量的线上环境中，需要对用户的消费额度进行秒级监控和实时扣费。没有精确的时延与美分成本统计上报，系统无法进行合理的商业化计费。
*   **🎯 过关验证标准**：实现一个可观测性追踪类。在图状态机并发运行时，自动记录每个 Node 的 Latency，并在最后的主 Trace 属性中打印出本次端到端运行的总耗时、总 Input/Output Token、以及预计消耗的美元精确数值。

---

## Day 110：异常堆栈 Traceback 收集与结构化 JSON 日志归档
*   **核心知识点**：
    *   **异常元数据富集**：在 OTEL Span 中，当捕获到异常时，利用 `span.record_exception(e)` 记录，并设置状态为 ERROR。
    *   **traceback 模块深度解析**：提取报错的文件名、行号、调用栈树并转化为 JSON 结构。
    *   **基于标准输出的结构化日志（Structured Logging）**。
*   **Agent 核心关联**：生产环境中的崩溃发生在一瞬间。如果只记录一个“Error”字符串，运维根本无从排查。将带有完整 traceback 的结构化异常作为 Event 绑定在特定的 Span 上，是快速定位线上 Bug 的关键。
*   **🎯 过关验证标准**：编写一个异常捕获可观测性包装器。故意触发一个工具执行异常（如 ZeroDivisionError），捕获后将包含 Traceback 堆栈、局部变量状态的 JSON 日志输出，且当前 Span 状态在 Phoenix/LangSmith 面板上被自动高亮标红并展示异常细节。

---

## Day 111：自定义 Prometheus 监控指标（Meter）上报
*   **核心知识点**：
    *   **Prometheus 指标类型**：Counter（计数器，如请求总数）、Gauge（仪表盘，如当前并发数）、Histogram（直方图，如响应时间分布）。
    *   **Prometheus Python Client 使用**：定义 Metrics 并注册。
    *   **Grafana 看板绑定**：通过 Prometheus 暴露的 `/metrics` 接口拉取数据并在 Grafana 渲染可视化看板。
*   **Agent 核心关联**：运维团队（SRE）需要实时掌握系统的健康状态。Prometheus 指标监控能够让我们在系统遭遇流量洪峰、或 API 整体超时飙升时，第一时间触发系统告警。
*   **🎯 过关验证标准**：编写脚本使用 `prometheus_client` 声明并上报 Agent 的三个指标（QPS 计数、当前活跃协程、调用 API 时延分布直方图）。本地运行测试客户端模拟 100 次高频访问，并在暴露的 `/metrics` 端口成功抓取到这些数据的统计分布。

---

## Day 112：第十六周综合实战：接入全分布式链路追踪、指标监控看板的生产级 Agent 可观测性底座
*   **实战任务**：**为“AI 研究助手”开发并集成完备的、符合 OpenInference 规范的本地化可观测性底层系统。**
    *   **要求**：
        1. 采用 Docker 本地化部署 Phoenix 追踪服务与 Prometheus 监控；
        2. 原生手写或绑定 OpenInference Tracing，为 LangGraph 的 Node、RAG 阶段、工具反射调度阶段注入规范的嵌套 Span 追踪；
        3. Span 中必须携带当前 Token 计费、首字延迟（TTFT）以及大模型的输入输出消息；
        4. 异常发生时，利用 traceback 精确提取并以结构化日志落盘，在 Span 上记录异常元数据；
        5. 导出标准的 Prometheus metrics，提供 QPS、Error Rate 与 Latency 指标，准备接入 Grafana。
    *   **🎯 交付件**：Phoenix 绑定配置代码、嵌套 Span 包装类、Prometheus 接口导出模块、单元测试、docker-compose 可观测性集群配置文件，以及运行后的 Trace 树状图截图和日志。\n