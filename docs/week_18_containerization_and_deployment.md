# 📅 Week 18: 容器化与部署

> **第十八周目标**：精通基于 FastAPI 构建高性能 Agent 异步接口服务，掌握 Dockerfile 轻量级容器封装，熟练编写 docker-compose 进行多容器集群联调部署，了解多租户环境变量隔离配置，具备生产环境高并发反向代理与 Serverless 部署能力。
> 
> **🔴 面试准备启动**：本周学习结束后，你已具备了：ReAct 控制流、RAG 向量检索、LangGraph 持久化编排、Eval 质量评测、可靠性工程、可观测性监控以及容器化部署的完整链条。必须立即开始完善个人简历，并在市场上投递简历，开始接受首轮面试以校准技术盲点。

---

## Day 120：使用 FastAPI 构建高性能 Agent 异步接口服务
*   **核心知识点**：
    *   **FastAPI 异步非阻塞处理**：使用 `async def` 定义高并发路由；
    *   **Pydantic 接收 Payload 校验**：设计规范的 `AgentRequest` 与 `AgentResponse` API 数据模型。
    *   **流式接口设计**：利用 FastAPI 的 `StreamingResponse` 将大模型的 Chunk 逐字推送至前端网页（支持 Event Stream SSE 协议）。
*   **Agent 核心关联**：大模型响应时间通常以秒计。如果不使用流式 SSE 协议而是在后台等待生成完毕一次性返回，前端用户会有严重的“系统卡死”感。FastAPI 的 StreamingResponse 是线上 Agent 服务交付的唯一标准。
*   **🎯 过关验证标准**：使用 FastAPI 编写一个运行 Agent 状态图的 API 服务，支持传递 Thread ID 恢复历史。实现一个 `/stream` 路由，在浏览器中请求时，能够通过 SSE 协议实时、逐块输出大模型生成的内容。

---

## Day 121：编写 Dockerfile 实现轻量级 Agent 隔离运行镜像
*   **核心知识点**：
    *   **多阶段构建（Multi-stage Build）**：分离编译依赖与运行时依赖，缩减镜像体积。
    *   **基础镜像选择**：采用 Python Alpine 或 Slim 镜像以防镜像冗余。
    *   **安全加固配置**：配置非 root 用户运行容器以提升运行时系统安全性。
    *   **依赖项精简**：配置 pip 缓存清理与无必要扩展排除。
*   **Agent 核心关联**：线上环境的部署要求秒级弹性伸缩。臃肿的 Docker 镜像会导致冷启动时间漫长，多阶段精简镜像是实现 Kubernetes 自动弹性伸缩的工程红线。
*   **🎯 过关验证标准**：为你的 Agent 系统编写一份精细的多阶段构建 Dockerfile。构建镜像并验证其总体体积控制在 250MB 以内，且容器内无法通过 shell 获取宿主机的 root 权限。

---

## Day 122：使用 Docker Compose 编排 Agent + Redis + Qdrant 容器化集群
*   **核心知识点**：
    *   **docker-compose 语法规范**：服务定义（services）、数据卷持久化挂载（volumes）、内部局域网隔离配置（networks）。
    *   **依赖等待机制**：使用 `depends_on` 结合 `healthcheck` 确保向量数据库和 Redis 启动就绪后，再拉起 Agent 业务服务。
    *   **数据卷隔离持久化**：保证重启后 SQLite/Redis 数据不丢失。
*   **Agent 核心关联**：Agent 需要与向量库、Checkpoint 缓存库（Redis）频繁通信。通过 docker-compose 进行一键本地编排，能够屏蔽环境差异，实现“开发环境与生产环境配置完全对齐”。
*   **🎯 过关验证标准**：编写一个 `docker-compose.yml` 配置文件，包含 Agent 服务、Redis、Qdrant。执行 `docker-compose up -d` 能够一键无错拉起全套集群服务，并能通过 FastAPI 成功读写 Qdrant 及 Redis checkpointer。

---

## Day 123：云原生多租户环境变量与安全凭证隔离
*   **核心知识点**：
    *   **多租户隔离模式（Multi-tenant Isolation）**：使用云平台秘钥管理服务（如 AWS Secrets Manager、阿里云 KMS）动态挂载凭证。
    *   **安全载入机制**：运行期禁止在代码中打印或泄露环境变量。
    *   **本地 `.env` 文件的动态排除规则**（防止意外提交 git 泄露凭证）。
*   **Agent 核心关联**：Agent 系统往往掌握了用户的高价值 API Keys、商业数据库密码。如果环境变量泄漏，会导致难以估量的安全和资金灾难。
*   **🎯 过关验证标准**：实现一个 `SecretsLoader`，通过解密挂载方式导入密钥。编写静态检查脚本，验证项目代码中 100% 不存在硬编码的凭证字符，且 `.gitignore` 规则对 `.env` 形成了严密防护。

---

## Day 124：Serverless 函数计算（Function Compute）冷启动性能优化
*   **核心知识点**：
    *   **Serverless 架构适用性**：Agent 的事件驱动和非高频常驻特性与 Serverless 完美契合（按运行秒数计费，大幅节省闲置成本）。
    *   **冷启动优化（Cold Start Optimization）**：精简导入包（不要在头部导入大型不常用包，采用局部延迟导入 Lazy Import）；优化基础容器体积；利用预留实例减少初始化耗时。
*   **Agent 核心关联**：如果将 Agent 部署在 Serverless 平台，如果冷启动需要 8 秒，用户体验会极差。掌握 Lazy Import 和容器轻量化能将冷启动时延压低在毫秒级。
*   **🎯 过关验证标准**：重构 Agent 的主入口文件，对部分重量级工具库（如 matplotlib、numpy）改为在具体工具 Node 执行时才执行 `import`，运行性能测试工具计算重构前后模块初次 import 的耗时差，实现冷启动时延降低 40% 以上。

---

## Day 125：基于 Nginx / Traefik 的反向代理与高并发负载均衡
*   **核心知识点**：
    *   **Nginx 负载均衡配置**：`upstream` 模块负载均衡轮询（Round Robin）与 IP Hash 算法配置。
    *   **WebSocket 与 Server-Sent Events (SSE) 代理透传设置**：配置 `proxy_set_header Connection ""`、`proxy_buffering off` 避免缓冲流式阻塞。
    *   **TLS/SSL 证书自动挂载（Let's Encrypt）**。
*   **Agent 核心关联**：大模型生成流式数据（SSE）要求连接保持且不被网关缓存缓冲。如果 Nginx 配置不当开启了 `proxy_buffering`，会导致流式打字机效果失效，表现为卡顿 10 秒后一次性吐出所有文字。
*   **🎯 过关验证标准**：编写并测试一个 Nginx 配置文件。将其配置为 FastAPI 流式服务的反向代理，验证通过 Nginx 转发的 SSE 请求能够平滑输出，且无任何前置延迟和缓冲积压。

---

## Day 126：第十八周综合实战：容器化封装、支持一键 docker-compose 部署的云原生多租户 Agent 集群
*   **实战任务**：**将“AI 研究助手”打包封装为高性能的云原生发布包并交付部署。**
    *   **要求**：
        1. 使用 FastAPI 提供标准的 REST API，包含线程 ID 隔离，提供 SSE 流式问答接口 `/api/v1/agent/chat`；
        2. 编写多阶段 Dockerfile 构建轻量级安全镜像，剔除无用依赖，体积控制在规范内；
        3. 采用 docker-compose 编排 FastAPI 服务、Redis（Checkpoint 存储）和 Qdrant（向量数据卷挂载），配置健康检查以防顺序启动报错；
        4. 环境变量与凭证动态注入，防范泄露；
        5. 配置 Nginx 代理，关闭 proxy_buffering 保证 SSE 完美透传，实现负载均衡轮询。
    *   **🎯 交付件**：FastAPI 接口脚本、多阶段 Dockerfile、docker-compose.yml 配置文件、Nginx 配置文件、一键部署启动脚本，以及在本地测试高并发流式 SSE 访问成功的监控截图与日志。\n