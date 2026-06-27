# 📅 Week 4: Prompt 工程进阶与结构化输出

> **第四周目标**：精通基于少样本与自一致性的提示词优化架构，攻克大模型结构化输出的边界解析障碍，掌握防御性 JSON 清洗技术，并建立网络层高性能连接池与熔断器机制。

---

## Day 22：CoT 思维链、Few-shot 样本库与 Self-Consistency 异步并行投票机制
*   **核心知识点**：
    *   **CoT（Chain-of-Thought）思维链**的注意力分配：通过在输出中强制增加推理推理路径 Token，使得后续 Token 生成获得更高的语义条件约束。
    *   **动态 Few-shot 检索**：利用向量数据库对当前 Task 进行语义 Search，提取与 Task 最相似的 top-K 示例（Example）动态拼接至 Prompt。
    *   **Self-Consistency（自一致性）**的数学原理：利用多样本路径采样（Marginalizing out reasoning paths），通过对生成的多条推理路径进行投票（Majority Vote），提高复杂推理的输出稳定性。
*   **Agent 核心关联**：Agent 在执行多步规划（Planning）与任务分配（Routing）时，单一的 CoT 推理仍有较大概率发生逻辑崩溃。通过在 Python 侧以并发方式实现 Self-Consistency，能够显著压低 Agent 第一步决策失误的概率。
*   **🎯 过关验证标准**：实现一个 `SelfConsistencyEvaluator` 类，以异步并发（`asyncio.gather`）请求 5 次包含 CoT 推理的 Prompt，提取生成的选项或核心数值，在 Python 中实现高效率多数票选择机制，并过滤非法无效响应。

---

## Day 23：大模型原生结构化输出（Structured Outputs）与 Pydantic 边界类型契约
*   **核心知识点**：
    *   **JSON Mode**（提示词声明 JSON）与 **Structured Outputs**（严格模式）的底层实现差异：严格模式下，大模型提供商在解码（Decoding）阶段利用 JSON Schema 对词表（Vocabulary）的 logits 进行掩码（Masking）干预，强制仅生成符合约束的 token。
    *   **Pydantic 运行时类型契约**：使用 `pydantic.BaseModel` 导出强约束的 JSON Schema（通过 `model_json_schema()`），定义嵌套结构与字段级校验规则。
    *   **异常拦截机制**：捕获并提取 `pydantic.ValidationError` 中的字段路径（loc）、错误原因（msg）与输入值。
*   **Agent 核心关联**：大模型需要执行的 Action 及其参数，必须以 100% 格式无误的结构化对象传递给外部系统。了解严格模式的原理，能够确保 Agent 调用外部系统工具时参数彻底符合预期的静态类型。
*   **🎯 过关验证标准**：使用 Pydantic 声明一个包含嵌套结构和字段自定义校验的 `UserInfo` 模型（包含姓名、多技能熟练度字典、邮箱地址格式校验）。编写代码强制大模型输出该结构，并故意构造非法输入触发 `ValidationError`，验证并格式化输出其捕获的越界报错信息。

---

## Day 24：防御性 JSON 解析器与脏 JSON 格式化语法纠错引擎
*   **核心知识点**：
    *   **正则表达式提取边界**：利用非贪婪匹配等正则算法，在杂乱无章的返回文本中精准提取出最外层的 `{ ... }` 或 `[ ... ]` 结构。
    *   **脏 JSON 容错纠正技术**：在不支持严格模式的轻量级端侧模型中，处理以下输出缺陷：
        1. 带有 markdown 语法包裹符 ` ```json ` ；
        2. 遗漏了结束标记（未闭合的大括号）；
        3. 键值对末尾多余的逗号（尾部逗号在 Python json 中是非法的）；
        4. 缺少双引号或使用单引号包裹键值。
    *   **解析栈（Parsing Stack）自愈算法**：通过模拟括号匹配压栈出栈过程，寻找截断 JSON 的最佳闭合点。
*   **Agent 核心关联**：在面对开源端侧大模型或老旧 API 时，大模型常常因上下文过载或本身能力不足输出格式受损的 JSON。Agent 必须具备解析边界防护能力，防止系统因解析器抛错导致决策流中断。
*   **🎯 过关验证标准**：手写一个 `robust_json_parser` 解析引擎。输入各种被故意破坏的字符串（例如：包含 Markdown 干扰文字、首尾带有脏字符、末尾缺失大括号、包含非法单引号及多余尾逗号的 JSON 串），引擎必须能全部自动修复并成功转换为合法的 Python 字典。

---

## Day 25：生产级 Prompt Jinja2 模版解耦与动态上下文防注入架构
*   **核心知识点**：
    *   **Jinja2 模版引擎**在 Prompt 管理中的核心用法：支持条件判断（`if`）、循环（`for`）、宏（`macro`）与变量过滤器。
    *   **Prompt 与代码逻辑解耦**：将所有 System/User 提示词集中在外部资源文件（如 `.jinja` 或 `.txt`）中，避免硬编码拼接。
    *   **提示词注入（Prompt Injection）攻击机理**：恶意输入通过拼接逃逸原本的 Prompt 指令界限，劫持模型执行未授权任务。
    *   **护栏设计（Guardrails）**：对注入的动态变量执行类型约束、敏感词检测与转义处理。
*   **Agent 核心关联**：Agent 在执行过程中需要将 Tool 返回的 Observation 和用户的输入动态渲染进 Prompt。如果不做模版解耦与安全性处理，极易被恶意构造的工具返回值（如外部抓取到的网页攻击代码）直接篡改 Agent 的决策流。
*   **🎯 过关验证标准**：设计一个包含 `tools_definition`、`conversation_history` 和 `current_task` 的 Jinja2 提示词模版。使用 Python 脚本读取并动态渲染它。编写测试用例输入恶意的逃逸注入字符串，验证过滤器能成功识别并进行安全拦截或语义中和。

---

## Day 26：网络请求库 HTTPX 连接池（Connection Pool）优化与 HTTP 异常工程
*   **核心知识点**：
    *   **HTTP/1.1 Keep-Alive 与 TCP 连接复用**：避免高频创建/销毁 TCP 套接字所产生的时延（TCP 三次握手与 TLS 握手开销）。
    *   **HTTPX 异步 `AsyncClient` 连接池参数调优**：`limits=httpx.Limits(max_connections=..., max_keepalive_connections=...)` 性能影响。
    *   **HTTP 异常等级划分**：区分传输层异常（ConnectionTimeout, ReadTimeout）、协议层异常（TooManyRedirects）、服务端异常（500, 502, 504）与客户端鉴权/限流异常（401, 403, 429）。
*   **Agent 核心关联**：Agent 本质上是基于网络 IO 驱动的系统，其大量时间消耗在请求 LLM API 和第三方 HTTP 工具接口上。优化 HTTP 客户端的连接复用能够直接缩短 Agent 决策链的端到端耗时，而规范的 HTTP 异常工程是设计容错重试的前提。
*   **🎯 过关验证标准**：配置一个具备 Keep-Alive 参数调优的全局异步 HTTPX 客户端，封装统一的 API 请求函数。模拟对慢速网络及异常 HTTP 状态码的请求，确保在发生网络波动时，抛出体系明确的自定义异常（如 `ToolNetworkException`），而不会泄漏 HTTPX 底层库的原始报错。

---

## Day 27：面向 Agent 工具的安全护栏：熔断器（Circuit Breaker）与并发速率限制（Rate Limiter）
*   **核心知识点**：
    *   **熔断器模式（Circuit Breaker）的状态转移**：
        1. **Closed**：请求正常通过，统计失败率；
        2. **Open**：当报错率达到阀值，直接拦截后续所有请求，直接返回降级数据，保护脆弱的下游接口；
        3. **Half-Open**：冷却时间过后，放行极少量测试请求，若成功则恢复 Closed，若失败则退回 Open。
    *   **速率限制器（Rate Limiter）的令牌桶（Token Bucket）算法**：以固定速率向桶内填充令牌，请求只有拿到令牌才能执行，限制瞬时并发突发流量。
    *   **Python 异步装饰器设计**：用装饰器优雅注入异常计数与状态转移逻辑。
*   **Agent 核心关联**：Agent 在自动执行 ReAct 循环时，对于不稳定的外部工具（如第三方搜索 API 或本地计算脚本），一旦连续请求超时或报错，如果没有任何保护，Agent 可能会陷入死循环疯狂请求，导致高昂的账单开销及自身系统的假死。
*   **🎯 过关验证标准**：手写一个异步装饰器 `@circuit_breaker`。修饰一个模拟的网络请求工具，当该函数在 10 秒内连续抛错 3 次，熔断器进入 Open 状态，在接下来的 30 秒内，任何对此函数的调用都必须直接抛出自定义的 `CircuitOpenException`，直到冷却期过进入 Half-Open 进行探测恢复。

---

## Day 28：第四周综合实战：高并发、具备重试自愈与熔断机制的简历结构化提取流水线
*   **综合实战任务**：**实现一个能够稳定运行在高吞吐量场景下的结构化简历抽取与转换引擎。**
    *   **架构设计要求**：
        1. 使用 `asyncio.Semaphore` 强制控制最大并发请求数（如限制最多 3 个协程同时请求模型），防止 API key 触发厂商 QPS 限制。
        2. 底层包含 Day 26 的 HTTPX 调优连接池，所有提取逻辑均通过 Pydantic 定义模型并使用严格的 JSON Schema 进行强约束约束。
        3. **实现基于反思的格式纠错自愈回路**：如果 LLM 输出的 JSON 无法通过 Pydantic 校验或由 Day 24 的防脏 JSON 解析器报错，系统**不能直接中断**，而是自动组装包含 `pydantic.ValidationError` 具体报错定位的提示词，发回给 LLM 启动第二轮“自愈纠错（Self-Correction）”，要求其修正参数并重新输出，统计最终自愈成功率。
        4. 整个流水线被 Day 27 设计的 `@circuit_breaker` 进行全面包裹，在外部 API 频繁崩溃时自动熔断降级。
        5. 对提取流水线的每一步（读取、渲染、并发提取、校验报错、反思纠错、熔断）进行标准的结构化日志输出，保存带有调用栈的 Traceback。
    *   **🎯 交付件**：包含信号量并发控制的流水线主代码、脏 JSON 纠错自愈逻辑类、熔断器装饰器应用、单元测试以及完整的模拟提取运行日志。
