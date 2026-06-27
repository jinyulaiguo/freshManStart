# 📅 Week 13: MCP 协议与标准化工具层

> **第十三周目标**：精通 Model Context Protocol (MCP, 模型上下文协议) 的 Client-Server 架构，掌握基于 Python MCP SDK 的自定义资源与工具暴露，熟练设计面向大模型优化的强类型 Tool Docstring 契约，具备在大规模工具库中进行 Tool Retrieval (工具检索) 的系统架构能力。

---

## Day 85：Model Context Protocol (MCP) 客户端-服务器架构规范
*   **核心知识点**：
    *   **MCP 协议规范**：由 Anthropic 开源的标准化模型上下文协议，用于规范 LLM 怎么与外部数据、本地文件、工具链建立安全的 HTTP/JSON-RPC 交互契约。
    *   **Client 与 Server 的职责划分**：Server 负责暴露特定的资源（Resources）、提示词模板（Prompts）和可执行工具（Tools）；Client 负责封装大模型请求并进行指令分发。
    *   **通信传输层选择**：基于标准输入输出（Stdio）的传输通道与基于服务端推送（SSE）的 HTTP 通信通道。
*   **Agent 核心关联**：传统的自定义工具编写方式没有统一格式，不同平台各自为政。掌握 MCP 协议，能让你开发出的工具集不仅能在自己的 Agent 中跑，还能一键接入 Cursor、Claude Desktop 等所有支持 MCP 协议的主流 IDE 和 Agent 宿主中。
*   **🎯 过关验证标准**：手绘 MCP 协议的 JSON-RPC 消息请求/响应流向图，并能够解释 Stdio 与 SSE 两种传输方式在本地执行与分布式网络环境下的选型差别。

---

## Day 86：基于 Python MCP SDK 开发自定义本地资源暴露服务器
*   **核心知识点**：
    *   **Python `mcp` 官方 SDK 的加载与初始化**。
    *   **Resource 注册**：利用 `@server.list_resources()` 和 `@server.read_resource()` 将本地的文件、日志流或系统状态抽象为 URI 寻址资源（如 `file://` 或 `postgres://`）。
    *   **Tool 注册**：利用 `@server.call_tool()` 将 Python 的计算和文件修改函数暴露给客户端。
*   **Agent 核心关联**：为 Agent 赋予读取本地资源（如“读取当前 git 提交记录”、“读取指定 log 日志”）和安全调用本地脚本的底层标准服务器封装。
*   **🎯 过关验证标准**：使用 Python MCP SDK 编写并运行一个本地 Stdio MCP Server，该服务器暴露出一个可供大模型调用的读取系统内存占用的 Tool（`get_memory_usage`）和一个特定配置文件的 URI 资源，通过 Python SDK CLI 工具进行联调通过。

---

## Day 87：MCP 客户端接入与 LangGraph 多工具无缝绑定
*   **核心知识点**：
    *   **MCP 客户端构建**：使用 Python SDK 的 `mcp.client` 异步连接外部暴露的 Stdio / SSE 服务器。
    *   **工具反射包装**：将 MCP 暴露出的 Tool 签名无缝翻译为 LangGraph Node 认可的 Runnable 签名。
    *   **生命周期注销与垃圾回收**：连接中断后的自动重连与连接关闭后的进程优雅注销。
*   **Agent 核心关联**：LangGraph 主系统可以作为 MCP 客户端，通过网络动态挂载来自多台机器的 MCP 数据库和文件处理服务器，实现分布式 Agent 协同。
*   **🎯 过关验证标准**：编写一个 MCP 客户端，异步挂载 Day 86 编写的 MCP Server。将其导出的工具转化为标准的 LangGraph 工具格式，并注入到 StateGraph 的 Node 中成功执行大模型的反射调用。

---

## Day 88：面向大模型优化的 Tool Docstring 与入参命名静态契约
*   **核心知识点**：
    *   **语义指引优化**：Docstring 中各参数描述（`param_name`）的精准修饰以及大模型对其解析的注意力差异；
    *   **入参命名规范**：使用完全不带歧义的静态命名（如使用 `target_file_absolute_path` 而不是 `path`），以及在 Pydantic 中使用 `Field(description="...")` 进行边界描述。
    *   **格式防御**：通过 Schema 的 description 注入示例格式（如“格式必须为 YYYY-MM-DD”）。
*   **Agent 核心关联**：大模型调用工具完全依赖于它对工具描述 JSON Schema 的文字理解。含糊不清的 docstring 会直接导致大模型传入非法类型参数或在不该调用该工具时误调用该工具。
*   **🎯 过关验证标准**：设计一个功能相同的工具（如查询用户账单），编写两个版本的 docstring：一个极为简略且命名含糊，另一个包含 Pydantic Field 精确指引与格式描述。在大模型上进行 30 次 Prompt 命中评测，用数据证明高清晰度契约能将工具误调用率降低 90% 以上。

---

## Day 89：动态 Tool 检索（Tool Retrieval）架构
*   **核心知识点**：
    *   **超大规模工具池的检索方案**：当系统拥有 200+ 个 API 时，利用向量化手段将所有 Tool 描述存入向量库。
    *   **动态召回与参数组装**：通过用户 Query 向量匹配出最相关的 Top-5 工具定义，在运行时动态生成并注入大模型参数中。
    *   **检索降级保护**：当 Tool 召回异常时的兜底核心工具列表。
*   **Agent 核心关联**：单次大模型 API 调用如果塞入超过 15 个以上的工具描述，不仅会导致上下文成本飙升，还会让模型的注意力严重稀释，产生可怕的工具乱调用幻觉。Tool Retrieval 是搭建多功能大 Agent 系统的核心网关。
*   **🎯 过关验证标准**：构建一个包含 50 个模拟工具描述的 Chroma 向量集合。实现一个 `DynamicToolRouter`，输入用户问题（如“帮我查一下上个月底的交易，并生成一份 PDF 发到小明的邮箱”），系统能在 10ms 内精确召回 3 个对应工具的 JSON Schema，并组装进调用链中。

---

## Day 90：工具输出二进制流（如图像、音频）的包装传输规约
*   **核心知识点**：
    *   **多模态工具响应处理**：工具不仅仅返回纯文本，还需要返回生成的统计图表（图像字节流）、语音播报（音频流）或本地二进制压缩包。
    *   **Base64 编码包装与 Mime-Type 标记**：按照协议标准将二进制包装为数据流对象。
    *   **客户端动态提取渲染**。
*   **Agent 核心关联**：为 Agent 赋予生成多模态资产（如数据分析 Agent 生成直方图、绘图 Agent 生成图片、录音 Agent 生成音频）的标准返回规范。
*   **🎯 过关验证标准**：编写一个 MCP 本地画图工具（使用 matplotlib 绘图），执行后将生成的直方图转化为 Base64 编码的 PNG 数据，封装为合规的多模态内容块（Content Block）通过 Stdio 通道成功送回给 MCP Client 并保存为本地文件。

---

## Day 91：第十三周综合实战：通过 MCP 标准协议连接本地文件与远程数据库的强类型系统 Agent
*   **实战任务**：**利用 MCP 协议为“AI 研究助手”搭建标准化的工具访问与微服务解耦层。**
    *   **要求**：
        1. 编写一个基于 Stdio 的 MCP Server，暴露出：① 读写特定系统目录的受限文件工具；② 执行标准数据库查询的工具；
        2. 工具入参全面使用 Pydantic 并辅以极精细的 Field description 语义修饰以防大模型误调；
        3. 工具返回值支持文本与二进制流（如导出数据库查询的 PDF 报表）；
        4. 编写 LangGraph 客户端，挂载该 MCP Server；使用 Day 89 的 Tool Retrieval 技术，根据用户意图，从服务器上动态匹配并按需注入工具集合。
    *   **🎯 交付件**：MCP Server 与 Client 源码、Tool 向量库配置脚本、强类型 Schema 声明、单元测试，以及包含多模态二进制传输和动态工具匹配运行的跟踪 Trace 日志。\n