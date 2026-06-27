# 📅 Week 3: LLM 原理与 API 交互

> **第三周目标**：深入理解大语言模型（LLM）的底层自回归生成与注意力分配机制，掌握 API 交互过程中的参数精细控制，具备处理多轮对话状态存储与高并发异步流式响应的系统设计能力。

---

## Day 15：Transformer 架构的自回归机制与 KV Cache 性能剖析
*   **核心知识点**：
    *   **自回归（Auto-regressive）生成机制**的数学定义：基于历史生成的序列条件概率预测下一个 Token，表达式为 $P(x_n | x_1, x_2, ..., x_{n-1})$。
    *   **自注意力（Self-Attention）机制**的底层原理：Query、Key、Value 矩阵的乘法运算与归一化注意力权重分配。
    *   **KV Cache（键值缓存）**的技术本质：避免对已生成历史 Token 重复进行 Query-Key 相似度与 Value 聚合的冗余矩阵乘法计算，从而将推理的时间复杂度从 $O(N^2)$ 降低到 $O(N)$（其中 $N$ 为序列长度）。
    *   **时延开销度量指标**：首字延迟（Time to First Token, TTFT，即 Prefill 阶段）与后续单字生成延迟（Time per Output Token, TPOT，即 Decode 阶段）的底层瓶颈差异。
*   **Agent 核心关联**：在 Agent 的长对话和多工具决策循环中，上下文长度（Context Length）会随迭代不断暴涨。如果大模型服务端或本地推理未开启 KV Cache，首字延迟（TTFT）和单字时延将呈指数级增加，直接拖垮 Agent 的实时交互响应速度。
*   **🎯 过关验证标准**：能够画出自回归模型的推理时序流向图，并能够推导出在上下文长度为 $L$、生成长度为 $M$ 的场景下，开启 KV Cache 与不开启 KV Cache 时所发生的浮点运算次数（FLOPs）的理论级比对。

---

## Day 16：概率采样控制与 Agent 确定性路由策略
*   **核心知识点**：
    *   **Softmax 函数**在输出层概率转换中的作用：将 logits 向量转化为总和为 1 的概率分布。
    *   **Temperature（温度参数）**的控制机理：通过调整公式中分母的参数 $T$（$e^{z_i/T}$），平滑或拉陡概率分布。$T \to 0$ 导致确定性输出（Argmax），$T \to \infty$ 导致概率趋于均匀分布。
    *   **Top-P（核采样）**与 **Top-K 采样**的筛选边界：Top-K 限制候选 token 的绝对数量，Top-P 动态控制概率累计和大于阈值 $p$ 的最小候选集。两者对采样搜索空间收缩的联动效应。
    *   **Frequency Penalty（频率惩罚）**与 **Presence Penalty（存在惩罚）**对输出 logits 的负反馈调整公式，用以控制词汇重复率。
*   **Agent 核心关联**：Agent 在执行自动化控制路径（如解析工具返回码、逻辑路由选择、JSON 结构体生成）时，需要高度的确定性，通常必须设置 `temperature = 0` 以确保代码的稳定复现；但在反思、纠错与创意生成路径下，需要适度调高 `temperature` 以产生变体方案。
*   **🎯 过关验证标准**：编写一段 Python 测试脚本，传入同一段 Prompt 50 次，在不同的 Temperature/Top-P 参数组合下统计输出文本的字符熵值（Entropy）以及格式损毁率，从而以数据支撑得出 Agent 在不同场景下的参数设置经验模型。

---

## Day 17：Tokenizer BPE 算法原理与带 System 优先权的离线上下文裁剪器
*   **核心知识点**：
    *   **BPE (Byte Pair Encoding, 字节对编码)** 的原理：从字节级别开始，通过迭代统计并合并最频繁出现的字符对构建词表。
    *   **Token 膨胀率**的产生：中文字符、特殊符号、多空格代码段在 BPE 切词后所占的 Token 数量往往是英文单词的 2-3 倍。
    *   **`tiktoken` 库的离线切词与编码**：加载模型专属分词器（如 `cl100k_base`），将原始字符串编码为 Token ID 整数数组，并获取其长度。
    *   **上下文边界溢出风险**：超出大模型最大上下文限制后，模型会直接抛出 400 异常或隐式发生前部信息丢失。
*   **Agent 核心关联**：在 Agent 的多轮循环中，如果无节制地把所有 Observation 和 Tool 返回值拼接进 Prompt，很快就会突破 Context Limit。我们需要在将 Payload 发送给 API 之前，利用本地 `tiktoken` 精确预算其大小，并进行截断或压缩。
*   **🎯 过关验证标准**：实现一个 `SmartContextCutter` 消息裁剪类。该类输入一个消息历史列表（格式符合 OpenAI 规范，包含 System、User、Assistant 等 role），在指定最大 Token 阈值下，按照以下规则自底向上裁剪：
    1. 必须无条件保留 System Prompt，即使它很长；
    2. 优先保留最近的多轮对话（按时序由新到旧保留）；
    3. 不能将一条消息从中间截断（以防破坏 JSON 结构），只能整条消息淘汰。
    通过单元测试验证在极限阈值下其剪裁逻辑完全符合预期。

---

## Day 18：统一 API 适配器设计与 System/User/Assistant 角色语义契约
*   **核心知识点**：
    *   **System Role** 的最高优先级执行指令性质（指令防御屏障，用以约束模型行为边界）。
    *   **User Role** 的任务负载性质，**Assistant Role** 的历史决策复现性质。
    *   **Python `Protocol` 静态类型契约**：设计接口契约，实现业务逻辑与模型客户端解耦。
    *   **模型参数映射**：OpenAI 的 `response_format` 与其他模型（如 DeepSeek、Qwen）在入参 and 返回 JSON 路径上的差异平滑适配。
*   **Agent 核心关联**：工业级 Agent 系统不能与具体的 LLM API SDK 耦合。需要通过抽象契约建立统一的大模型客户端，屏蔽模型差异，实现“首选 DeepSeek，降级到 OpenAI，备用 Qwen”的统一调用方式。
*   **🎯 过关验证标准**：使用 Python `typing.Protocol` 声明一个统一的 `BaseLLMClient` 接口。分别编写 `OpenAIClientAdapter` 与 `DeepSeekClientAdapter` 予以实现。两者的初始化需要通过读取 `.env` 配置文件载入凭证，并在调用同一接口方法时支持统一的参数结构输入。

---

## Day 19：异步非阻塞 API 并发调用与流式分块解析引擎
*   **核心知识点**：
    *   **异步上下文对象**（`async with`）与异步大模型客户端调用。
    *   **流式响应（Chunking）传输**：HTTP SSE (Server-Sent Events) 协议在模型输出中的应用。
    *   **异步迭代器与生成器**（`async for` 与 `async yield`）对 HTTP 响应流的逐块解析。
    *   **首字延迟（TTFT）** 与 **平均吞吐量（Tokens per Second）** 的秒表级实时量化监测。
*   **Agent 核心关联**：多 Agent 协同工作时，多个 Agent 需要并发调用 LLM API。如果使用同步阻塞 API，会产生灾难性的排队时延。同时，大模型输出可能长达数千 Token，流式解析能够让系统在模型第一个 Token 生成时就开始解析，以降低整体首字响应延迟（TTFT）。
*   **🎯 过关验证标准**：基于 `httpx.AsyncClient` 编写一个 `AsyncStreamEngine`，向 LLM API 发送流式请求，使用 `async for` 异步迭代流式解析，在终端以“打字机式”无延迟渲染输出。在生成结束后，输出本次生成的 TTFT（毫秒级）和 Token 吞吐速率（Tokens/sec）。

---

## Day 20：并发安全的 Session 会话管理器与 LRU 淘汰机制
*   **核心知识点**：
    *   **多协程并发安全（Concurrency Safety）**：利用 `asyncio.Lock` 保护 Session 状态的读写原子性。
    *   **LRU（Least Recently Used, 最近最少使用）** 缓存算法的基本数据结构：双向链表（Doubly Linked List）与哈希表（Hash Map）的结合，或者使用 Python 内置的 `collections.OrderedDict` 实现。
    *   **多用户/多会话隔离模式**：每一个 Session 独立维护专属的消息历史与元数据。
*   **Agent 核心关联**：多用户并发请求同一个 Agent 实例时，共享的状态字典极易产生协程竞态条件（Race Condition）导致上下文串线。因此，必须对 Session 实现线程/协程安全的完全隔离，并在内存受限的容器内配置 LRU 缓存以自动剔除冷数据，防止内存泄露。
*   **🎯 过关验证标准**：手写一个协程安全的 `SessionManager` 类，通过 `asyncio.gather` 模拟 20 个用户并发向不同 Session 中追加历史消息，验证读写不发生错乱。设置最大 Session 容量（如 5 个），验证超出时最早未使用的 Session 消息能被自动淘汰释放。

---

## Day 21：第三周综合实战：具有动态 Fallback 与 Token 审计的异步流式 CLI 聊天终端
*   **综合实战任务**：**从零构建一个具备工业级容错与可观测性的命令行流式交互终端系统。**
    *   **架构设计要求**：
        1. 必须是全异步设计，使用命令行界面接收用户连续输入。
        2. 底层采用 Day 18 的 Protocol 适配器，支持 OpenAI 与 DeepSeek 双重适配。
        3. 自带 Day 17 的 `SmartContextCutter`，限制对话历史在 3000 Token 内，超出时自动滑动剪裁，但保留 System 人设。
        4. 每次请求均通过 Day 19 的 `AsyncStreamEngine` 流式读取响应。
        5. **引入 Fallback 动态降级机制**：首选请求 DeepSeek 模型，如果捕获到网络异常、API 超时或 50x 服务错误，系统必须在 500ms 内**自动且静默地**降级切换调用 OpenAI 或本地 Qwen 接口重新请求，确保用户体验不中断。
        6. 会话结束时，将本次对话消耗的 Input Token、Output Token 以及累计所消耗的美元账单输出至结构化 CSV 审计日志中。
    *   **🎯 交付件**：全套异步适配器代码、会话管理与剪裁机制类、动态降级控制逻辑、CSV Token 审计模块，并附带针对 Fallback 与剪裁逻辑的单元测试。
