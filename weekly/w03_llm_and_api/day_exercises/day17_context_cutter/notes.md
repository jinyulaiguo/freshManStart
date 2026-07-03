# Day 17：Tokenizer BPE 原理与带 System 优先权的离线上下文裁剪器

本节重点介绍分词器（Tokenizer）的工作原理（重点是字节对编码 BPE 算法及 Token 膨胀率），并掌握如何使用 `tiktoken` 库在本地精确计算 Token 量，进而设计具备 System 优先权的滑动窗口裁剪器来控制 API 的上下文边界。

---

## 📖 核心概念讲解

### 1. Tokenizer 与 BPE（Byte Pair Encoding，字节对编码）原理
大模型不直接处理字符，而是处理 **Token**。**BPE** 是一种主流的子词分词（Subword Tokenization）算法，其构建和切词的核心逻辑为：
1.  **初始化**：将词表初始化为包含所有的单字节字符（共 256 个）。
2.  **迭代合并**：统计训练语料中相邻字符对的共现频次，将最频繁出现的字节对合并成一个新的子词（Subword），并加入词表。
3.  **循环终止**：重复合并步骤，直至达到预设的词表大小（如 `gpt-4` 分词器 `cl100k_base` 词表约为 10 万个词）。

### 2. Token 膨胀率现象
由于大模型的训练语料库以英文为主，BPE 词表中绝大多数合并词都是英文词汇（一个英文单词通常只需 1 个 Token）。而中文字符或少见的特殊字符、多空格缩进代码段，在 BPE 分词时无法高效匹配，会被切碎成单字、单偏旁甚至单字节，从而造成 **Token 膨胀率**：
*   **英文**：1 个单词 $\approx$ 1.3 个字符 $\approx$ 1 个 Token。
*   **中文**：1 个汉字 $\approx$ 2 至 3 个 Token（膨胀率为英文的 2-3 倍）。
*   **代码**：4 个连续空格的缩进在某些分词器中可能被切为 2-3 个 Token。

### 3. 使用 `tiktoken` 离线切词与计数
在本地发送网络请求前，我们可以利用 OpenAI 开源的 `tiktoken` 库进行零成本、极速的离线编码以获取 Token 长度：
```python
import tiktoken

# 1. 获取对应的分词编码器
encoding = tiktoken.encoding_for_model("gpt-4o")

# 2. 编码得到 Token ID 数组
token_ids = encoding.encode("你好，世界！")
print(len(token_ids))  # 输出 Token 数量
```

---

## 💡 补充总结与问答

### 1. 为什么上下文裁剪不能“野蛮切除”？
在 Agent 多轮对话迭代中，最简单粗暴的裁剪方法是直接截取文本字符串的前 $N$ 个字符抛弃，或者直接裁剪掉对话列表的前面几条消息。这会带来严重后果：
*   **丢失 System 设定**：在多轮对话消息列表中，`system` 消息（定义 Agent 身份、行动规范、安全限制）往往位于第一条。如果粗暴地从头部截断，`system` 消息会首先被删掉，导致 Agent 彻底“失忆”并失控。
*   **破坏消息的物理完整性**：如果只截断单条消息的部分内容（例如半截 JSON），会导致底层的反序列化结构破损（如少了一个 `}`），从而引发 downstream 代码抛出异常。

### 2. `SmartContextCutter` 的设计准则
为了解决上述痛点，我们设计的 [SmartContextCutter](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w03_llm_and_api/day_exercises/day17_context_cutter/context_cutter.py#L19) 遵循以下核心规则：

> [!IMPORTANT]
> **裁剪三法则**：
> 1.  **System 无条件留存**：将所有 `system` 消息提取并置顶保留，计算其所占用的 Token 额度，仅对非 System 消息进行滑动淘汰。
> 2.  **倒序累加评估**：非 System 消息代表对话历史。应当从最新（列表末尾）向最旧（列表头部）累加 Token。一旦累加值超过可用配额（$max\_tokens - system\_tokens$），则停止吸纳，将更旧的消息直接整条抛弃。
> 3.  **消息级（Message-level）淘汰**：不打碎单条消息的内容。要么整条消息保留，要么整条消息丢弃。
> 4.  **顺序恢复**：最后输出时，必须恢复保留消息的原有时序，确保 System 在前，其余历史时序从小到大排列。
