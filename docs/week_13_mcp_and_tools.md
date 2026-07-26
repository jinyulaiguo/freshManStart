# 📅 Week 13: MCP 协议与标准化工具层

> **第十三周目标**：精通 Model Context Protocol (MCP, 模型上下文协议) 的 Client-Server 架构与通信规范，掌握基于 Python 官方 SDK (含 FastMCP) 的自定义资源（Resources）、提示词模板（Prompts）与可执行工具（Tools）暴露，熟练设计面向大模型优化的强类型 Tool Docstring 与 Schema 防错契约，掌握复用项目向量底座 Qdrant 的超大规模工具向量检索（Tool Retrieval）网关，并具备支持 Client 采样（Sampling）、异步进度（Progress）与多模态二进制字节流传输的工业级 Agent 系统架构能力。

---

## Day 85：Model Context Protocol (MCP) 客户端-服务器架构规范与协议原语
*   **核心知识点**：
    *   **MCP 协议全景规范**：由 Anthropic 开源的标准化模型上下文协议，用于规范 LLM 怎么与外部数据、本地文件、工具链建立安全的 HTTP/JSON-RPC 交互契约。
    *   **三大元实体与职责划分**：资源（Resources, URI寻址数据）、提示词模板（Prompts, 预定义上下文）与可执行工具（Tools, 带 Schema 的计算/动作函数）；Client 负责上下文组装与 LLM 调度，Server 负责暴露数据与能力。
    *   **通信传输层选择**：基于标准输入输出（Stdio）的本地进程双向通道与基于 HTTP SSE（Server-Sent Events）的网络分布式通信通道。
    *   **高级协议扩展原语**：反向采样（Sampling, Server 借用 Client LLM）与根目录限制（Roots, 文件系统安全边界）。
*   **Agent 核心关联**：传统的自定义工具编写方式无统一格式。掌握 MCP 协议，开发出的工具集不仅能在自定义 Agent 中跑，还能一键接入 Cursor、Claude Desktop 等主流 IDE 和 Agent 宿主中。
*   **🎯 过关验证标准**：手绘 MCP 协议的 JSON-RPC 消息请求/响应流向图，清晰标注 Resources、Prompts、Tools 三类请求交互细节，并能量化分析 Stdio 与 SSE 两种传输方式在本地执行与分布式网络环境下的选型差别与安全边界。

---

## Day 86：基于 Python FastMCP SDK 开发自定义资源、提示词与工具暴露服务器
*   **核心知识点**：
    *   **FastMCP 极速开发框架**：官方 `mcp.server.fastmcp` 的装饰器与轻量化架构。
    *   **Resource 注册与 URI 寻址**：利用 `@mcp.resource("file://...")` 将本地文件、系统指标与日志流抽象为 URI 寻址只读资源。
    *   **Prompt 模板导出**：利用 `@mcp.prompt()` 动态导出预定义 Prompt 模板与入参补全。
    *   **Tool 注册与异步逻辑**：利用 `@mcp.tool()` 将 Python 的计算、文件修改与外部 API 封装为带 Schema 的可执行工具。
*   **Agent 核心关联**：为 Agent 赋予读取本地资源（如“读取当前 git 提交记录”、“读取指定 log 日志”）和安全调用本地脚本的标准微服务封装。
*   **🎯 过关验证标准**：使用 Python FastMCP SDK 编写并运行一个本地 Stdio MCP Server，暴露 `get_memory_usage` 工具、`config://app.json` 资源及 `audit_prompt` 提示词模板，通过 MCP CLI 或调试脚本联调通过。

---

## Day 87：MCP 客户端接入、LangGraph 绑定与 Client Sampling 反向采样
*   **核心知识点**：
    *   **MCP 客户端构建**：使用 Python SDK 的 `mcp.client` 异步连接外部 Stdio / SSE 服务器。
    *   **工具反射包装 (Reflection Adapter)**：将 MCP 暴露出的 Tool 签名无缝翻译为 LangGraph Node 认可的 Runnable 签名。
    *   **Client Sampling 采样响应**：实现 Client 侧处理 Server 端发起的 `ctx.sample()` 采样请求，向本地 LLM 代理求值并安全返回结果。
    *   **生命周期注销与长连接回收**：连接中断后的自动重连与连接关闭后的进程优雅注销。
*   **Agent 核心关联**：LangGraph 主系统作为 MCP 客户端，可动态挂载多台机器的 MCP 数据库和文件处理服务器，并允许服务端反向借用客户端 LLM“大脑”完成中间辅助校验。
*   **🎯 过关验证标准**：编写一个 MCP 客户端，异步挂载 Day 86 的 MCP Server，转化为 LangGraph Node 成功执行反射调用，并成功响应由 MCP Server 工具内部触发的 Sampling 采样请求。

---

## Day 88：面向大模型优化的 Tool Docstring 与入参命名静态契约
*   **核心知识点**：
    *   **语义指引与命名精细化**：消除命名歧义（使用 `target_file_absolute_path` 代替 `path`），利用 Pydantic `Field(description="...")` 进行精确边界约束。
    *   ** Schema 格式防御 (Defensive Guard)**：在 description 中注入合法样例与边界约束（如“格式必须为 YYYY-MM-DD”），防范 LLM 传空或格式非法。
    *   **Prompt 模板与 Tool 双重校验**：结合 MCP Prompts 模板对 LLM 的注意力收敛作用。
*   **Agent 核心关联**：大模型调用工具完全依赖于它对工具 JSON Schema 的文字理解。含糊不清的 docstring 会直接导致大模型传入非法类型参数或在不该调用该工具时误调用。
*   **🎯 过关验证标准**：设计一个功能相同的工具（如查询用户账单），对比简略命名与强契约防御版本，在大模型上进行 30 次 Prompt 误调用拦截测试，证明强契约防错设计能将工具误调用率降低 90% 以上。

---

## Day 89：动态 Tool 检索（Tool Retrieval）与解耦网关架构
*   **核心知识点**：
    *   **项目 Schema 文件动态解析**：系统启动时直接扫描并读取项目本地 Tool 定义文件与 MCP Server 暴露的 Schema 字典。
    *   **复用 Week 6 Qdrant 向量底座**：利用 Week 6 已引入的 **Qdrant 向量数据库（含 Payload Pre-Filtering 元数据过滤与 HNSW 索引）** 或纯内存适配器，对全量 Tool Schema 进行向量化构建。
    *   **动态召回与参数组装**：通过用户 Query 语义召回最相关的 Top-K 工具定义，在运行时动态生成并注入大模型上下文。
    *   **工具热更新与降级保护**：当 Tool 召回异常时的兜底核心工具列表与动态加卸载机制。
*   **Agent 核心关联**：单次大模型 API 调用塞入超过 15 个以上的工具描述会导致上下文 Token 成本飙升与注意力严重稀释（产生乱调用幻觉）。Tool Retrieval 是多功能大 Agent 系统的核心网关。
*   **🎯 过关验证标准**：直接读取项目内部包含 50 个工具 Schema 的定义文件，利用项目统一的 Qdrant / 内存 Retriever 向量底座实现解耦的 `DynamicToolRouter`，在 10ms 内根据 Query 精确召回 Top-3 工具 Schema 并注入调用链，同时包含熔断降级兜底验证。

---

## Day 90：工具输出二进制流（多模态）与异步 Progress/Cancellation 规约
*   **核心知识点**：
    *   **多模态工具响应处理**：工具返回生成的统计图表（图像字节流）、语音播报（音频流）或本地二进制压缩包。
    *   **FastMCP Image / Content Block 包装**：使用 Base64 编码与 Mime-Type 标记封装为合规数据流对象。
    *   **异步 Progress 进度通知与 Cancellation 中断**：在长耗时工具中通过 `ctx.report_progress()` 实时回传进度，并处理客户端打断信号。
*   **Agent 核心关联**：为 Agent 赋予生成多模态资产（直方图/音频/报告）的标准返回规范，以及管理长耗时任务状态的能力。
*   **🎯 过关验证标准**：编写一个 FastMCP 本地画图与长耗时数据分析工具，执行过程中回传进度 notification，并将生成的 Matplotlib 直方图封装为 Base64 PNG 数据流送回 Client 保存渲染。

---

## Day 91：第十三周综合实战：通过 MCP 标准协议连接本地文件与远程数据库的强类型系统 Agent
*   **实战任务**：**利用 FastMCP 与 MCP 标准协议为“AI 研究助手 Agent”搭建标准化工具访问、向量路由与微服务解耦层。**
    *   **要求**：
        1. 编写基于 Stdio 的 FastMCP Server，暴露：① 具备 Roots 工作区限制的受限文件工具；② 执行标准 SQL 查询的数据库工具；③ 生成 Matplotlib 多模态图表并回传 Progress 的数据分析工具；
        2. 工具入参全面使用 Pydantic 并辅以极精细的 Field description 语义修饰与格式防御；
        3. 支持服务端 `ctx.sample()` 反向请求 Client LLM 进行数据二次提纯校验；
        4. 编写 LangGraph 客户端挂载 MCP Server，读取项目 Tool 文件与 Schema 字典，复用 Week 6 项目向量底座 Qdrant（或内存 Retriever），动态检索并按需注入工具集，完美处理多模态字节流响应。
    *   **🎯 交付件**：FastMCP Server 与 Client 源码、Tool 向量路由门面脚本、强类型 Schema 声明、单元测试，以及包含 Sampling 采样、Progress 进度推送、多模态二进制传输和动态工具匹配运行的跟踪 Trace 日志。


\n