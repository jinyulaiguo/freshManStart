# 📅 Week 20: A2A 协议与跨系统协作

> **第二十周目标**：精通谷歌 Agent-to-Agent (A2A) 通信协议规范，掌握跨域名跨系统调用的 JWT 身份验证，实现跨系统 Agent 状态强一致性数据同步，具备利用异步消息队列进行高并发 A2A 解耦的架构设计能力。

---

## Day 134：谷歌 A2A (Agent-to-Agent) 通信协议规范解析
*   **核心知识点**：
    *   **A2A 协议框架**：解决不同公司的 Agent 之间如何互相发现、互相调用、安全传递输入输出的协议规范。
    *   **语义握手（Semantic Handshake）**：Agent 向另一个 Agent 声明自己的功能能力与通信协议版本。
    *   **调用标准 Payload 结构**。
*   **Agent 核心关联**：未来 Agent 是网状互联的。你公司的“旅游规划 Agent”需要去调度另一家公司的“机票预订 Agent”。掌握标准 A2A 协议，是让你的 Agent 能够融入分布式 Agent 互联网（Agent Web）的唯一技术门票。
*   **🎯 过关验证标准**：手写符合谷歌 A2A 标准的通信 Payload 结构体（包含 `agent_identity`、`session_context`、`intent_action` 等关键字段描述），并说明其与普通 API RPC 调用在语义协商上的本质差别。

---

## Day 135：跨域 Agent 调用的身份验证与 JWT 令牌交换
*   **核心知识点**：
    *   **OAuth2 / JWT 令牌机制在 A2A 中的应用**：主调方 Agent 使用公私钥签名（RSA/ECDSA）生成 JWT，被调方 Agent 使用公钥验签并进行授权。
    *   **会话级安全会话秘钥（Session Key）交换**。
    *   **防御重放攻击**：在 Payload 中注入 Nonce 和时间戳校验。
*   **Agent 核心关联**：当你的 Agent 调用其他系统的 Agent 去扣款或读写敏感资产时，必须进行严密的身份鉴权。没有 A2A 鉴权保护，Agent 系统极易被伪造的黑客指令攻破，产生重大经济损失。
*   **🎯 过关验证标准**：使用 Python 编写两个独立的 A2A 服务：`ClientAgent` 和 `ServerAgent`。ClientAgent 使用 RSA 私钥对请求体签名生成 JWT 发起请求，ServerAgent 验签成功后才放行接口并返回数据，并在篡改签名或 Nonce 超时时抛出 401 报错。

---

## Day 136：跨系统 Agent 状态同步机制与最终一致性设计
*   **核心知识点**：
    *   **分布式事务在 A2A 中的挑战**：两阶段提交（2PC）的阻塞痛点；
    *   **TCC（Try-Confirm-Cancel）模式**在 Agent 状态同步中的应用：
        - Try：预留资源（如冻结库存）；
        - Confirm：确认执行（完成交易）；
        - Cancel：回滚释放（释放冻结）。
    *   **Saga 模式**：长事务补偿机制。
*   **Agent 核心关联**：当你的 Agent 调度了外部 3 个独立的 Agent（机票、酒店、租车），如果机票订成功了但酒店订失败了，必须触发回滚（退机票）。这需要依靠 TCC 或 Saga 模式来维持跨系统状态的最终一致性。
*   **🎯 过关验证标准**：实现一个 Saga 补偿状态管理器。模拟机票和酒店预订场景。当酒店预订节点发生崩溃时，管理器能自动、异步拉起机票预订 Agent 的补偿回滚 Node，撤销机票订单，确保跨系统数据一致性。

---

## Day 137：异步消息队列（RabbitMQ/Kafka）解耦 Agent 间高并发调用
*   **核心知识点**：
    *   **消息驱动架构（EDA）**：使用 RabbitMQ 或 Kafka 进行 A2A 的发布-订阅（Pub/Sub）解耦。
    *   **异步确认机制（ACK）**：防范由于网络中断导致的任务丢失。
    *   **死信队列（Dead Letter Queue）**：存放格式错误或多次重试依然失败的任务，等待人工排查。
*   **Agent 核心关联**：如果跨系统 A2A 采用直接同步 HTTP 阻塞请求，一旦对方 Agent 响应慢（大模型生成可能需要 15 秒），本地连接池会迅速耗尽，直接引起全站雪崩。消息队列解耦能将高并发请求安全削峰。
*   **🎯 过关验证标准**：配置本地 RabbitMQ，编写 Client 协程和 Worker 协程，使 A2A 任务消息在队列中平稳传输，支持 ACK 确认机制，在 Worker 异常退出时任务能重回队列重新消费，且多次失败能自动隔离进入死信队列。

---

## Day 138：跨系统异常链传递与状态追踪
*   **核心知识点**：
    *   **跨域异常序列化**：如何将 B 系统的 Python CustomException 转化为标准的 JSON 错误 payload（包含标准错误码、错误描述、以及 sanitized traceback），回传给 A 系统。
    *   **异常链传递**：A 系统接收到 B 系统的 JSON 错误后，在本地使用 `raise RemoteAgentException(...) from ...` 进行重建抛出，保证调用链追踪不中断。
*   **Agent 核心关联**：分布式 Agent 协作时，如果 B 系统报错了，A 系统只拿到一个“500 Internal Error”，开发人员将根本无法定位故障在哪个系统的哪一步。透明的跨系统异常链是排障的刚需。
*   **🎯 过关验证标准**：实现跨系统异常序列化模块。当被调方 `Agent-B` 执行工具崩溃时，生成标准错误 Payload 传回；主调方 `Agent-A` 接收后，在本地控制台重新抛出，并打印出带“Remote System Boundary”的链式报错堆栈。

---

## Day 139：面向分布式协作的跨域可观测性追踪 ID 链条注入
*   **核心知识点**：
    *   **W3C Trace Context 规范**：分布式追踪的核心请求头——`traceparent`（包含版本号、Trace ID、Parent Span ID、Trace Flags）。
    *   **Trace Context 注入与提取（Inject & Extract）**：在发送 A2A HTTP 请求时将本地 Trace ID 注入 Header；在被调方提取并继承为父 Trace。
*   **Agent 核心关联**：实现“一次请求，全站追踪”。当用户的指令跨越了 3 个不同服务器的 Agent 系统时，依靠 traceparent 头，可观测性看板（Phoenix/Jaeger）能把所有机器上的执行 Span 自动整合成一棵完整的树状调用链路。
*   **🎯 过关验证标准**：使用 HTTPX 和 FastAPI 构建两个跨网络 Agent 节点，手动在请求头中注入并解析 `traceparent` 头。在 Phoenix 界面上验证两个不同主机的 API 调用被完美识别为同一个分布式 Trace，展现父子嵌套关系。

---

## Day 140：第二十周综合实战：跨越两个独立主机的分布式 Agent 协同处理复杂订单任务系统
*   **实战任务**：**实现两个解耦部署在不同主机上的 Agent 系统的分布式 A2A 强一致性协作。**
    *   **要求**：
        1. 包含主调方 `OrderAgent`（主机A）和被调方 `InventoryAgent`（主机B）；
        2. 两者之间通过 Day 135 的 JWT 身份验证进行接口鉴权；
        3. A2A 通信协议符合标准，请求头注入 W3C Trace Context，在可观测性面板实现分布式 Trace 汇聚；
        4. 采用 Saga 补偿机制，当 `OrderAgent` 发现后续支付失败时，自动异步呼叫 `InventoryAgent` 释放预留库存，实现最终一致性；
        5. 跨系统异常链完美传递，主调方能清晰解析被调方的 Traceback。
    *   **🎯 交付件**：OrderAgent 代码、InventoryAgent 代码、Saga 状态机实现、JWT 鉴权脚本、分布式链路追踪配置文件、单元测试，以及演示跨系统状态一致性流转及异常链传递的终端日志。\n