# Day 91: 工业级 AI 研究助手 (Enterprise MCP Orchestration)

本项目基于 **Model Context Protocol (MCP)** 和 **LangGraph**，构建了一个完全符合架构师级别规范（Enterprise Architect Standard）的生产级 AI 研究助手 Agent 系统。

## 🎯 业务场景痛点与解法

在真实的科研或金融投研场景中，数据孤岛严重（文献在特定网盘，实验数据在独立 DB），核心分析任务耗时极长，且越权操作代价极大。

本项目通过以下解法直击痛点：
1. **单一职责微服务隔离**：将文件读取、数据库查询、图表渲染拆分为三个独立的 FastMCP Server，物理隔离。
2. **海量工具网关**：利用 **Qdrant** 建立统一的语义检索路由（Semantic Tool Router），Agent 根据当前意图毫秒级召回最合适的工具，防止“工具爆炸”引发的大模型幻觉。
3. **进度与多模态**：在执行动辄几十秒的长耗时分析任务时，系统通过 WebSocket 实时向前端回传 Progress（进度），并最终以 Base64 无损渲染 Matplotlib 高清图表。
4. **AST 逆向安全审计**：仅仅依靠大模型的 Prompt 防御是不够的。本系统的 Database MCP 强制引入了 `sqlglot` 进行 SQL 抽象语法树（AST）解析。一旦出现非 `SELECT` 的越权操作，物理层直接斩断，并通过 `ctx.sample()` 挂起执行流，逆向呼叫大脑进行二次审计。

## 🏗️ 领域驱动架构 (DDD)

系统代码结构严格遵循洋葱架构分层，抛弃了“玩具级”的脚本堆叠：

```text
src/
├── config/                # 强类型配置 (pydantic-settings)
├── infrastructure/        # 防腐层 (PG Checkpointer, Qdrant, Structlog)
├── mcp_servers/           # 单一职责微服务集群 (File, DB, Analysis)
├── agent_domain/          # LangGraph 确定性状态机与 Qdrant 路由
└── presentation/          # 统一接入层 (FastAPI + WebSocket)
```

## 🚀 一键启动与观测

### 启动前提
系统高度解耦，默认 Qdrant (6333) 与 PostgreSQL (5432) 已通过项目的公共基础设施稳定运行。

### 启动服务
```bash
chmod +x start.sh
./start.sh
```
该脚本采用严格的**进程组守护模式**。启动前会自动进行 LSOF 业务端口冲突检测并强制 `kill -9`，确保沙箱环境绝对纯净。

### 观测控制台
系统启动后，访问 `http://localhost:8000` 进入极简科研工作台。
- 左侧为 **聊天记录与多模态图表渲染区**
- 右侧为 **Execution Trace (执行轨迹监控区)**，实时打印大模型的思维节点、MCP 工具切换流和耗时计算进度。

## 🛡️ 工业级规范落地亮点
*   **分布式状态保险箱**：摒弃 `MemorySaver`，采用 `AsyncPostgresSaver` 支持真正的断点挂起与恢复。
*   **多维韧性控制**：引入 `tenacity` 实现带抖动的指数退避重试（LLM、Qdrant），保护下游基建。
*   **结构化可观测性**：全链路采用 `structlog` 输出 JSON 标准日志，并打通 `X-Correlation-ID`。
