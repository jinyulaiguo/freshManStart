# 📅 Week 9: 多层级记忆系统 (Memory Engineering)

> **第九周目标**：精通多层级记忆系统的生命周期设计，掌握基于 Token 计量的非阻塞滑动摘要压缩，设计基于实体的长期事实提取与多租户隔离向量化存储机制，实现支持断电状态恢复与自适应路由的高可用记忆增强 Agent系统。
> 
> **✅ 里程碑二达成**：打通外部知识检索（RAG）与动态交互记忆（Memory）的状态流转，构建一个具备长时会话缓存、增量事实更新与时序一致性消解的生产级 AI 助手核心组件。

---

## 🛠 记忆工程知识演进路线 (Research Timeline)

```text
[2023.04] Generative Agents (记忆检索与反思)
       │
       ▼
[2023.10] MemGPT (虚拟内存管理 OS-style)
       │
       ▼
[2024.01] MemoryBank (遗忘曲线与时间衰减)
       │
       ▼
[2024.07] Mem0 (实体级别事实增量更新)
       │
       ▼
[2025.03] Letta (多进程高可用状态管理服务)
       │
       ▼
[2026.06] OpenAI & Anthropic (原生持久记忆与上下文缓存)
```

---

## Day 57：记忆系统分层架构：Working/Sensory/Long-term 契约设计

### 1. 痛点场景 (Problem)
无记忆分层的 Agent 无法区分交互周期中的**瞬时上下文**（如请求延迟、Token 开销等元数据）与**持久偏好**。每次会话冷启动，模型都会丢失全部历史偏好；而试图保留全量历史消息，又会导致会话 Context 物理窗口迅速溢出，且带来极高昂的 Token 费用。

### 2. 核心理论 (Theory)
将 Agent 记忆按生命周期划分为不同层次：
*   **感觉记忆 (Sensory Memory)**：瞬时请求响应中的临时特征数据，无存盘价值。
*   **工作记忆/短期记忆 (Working Memory)**：当前会话（Session）内流转的滑动消息列表。
*   **长期记忆 (Long-term Memory)**：跨越会话周期的结构化事实（Facts）与语义向量空间。
*   **语义缓存 (Semantic Cache)**：基于语义相似度判定拦截重复请求，提高系统的并发时延性能。

### 3. 经典论文 (Foundation Papers)
*   **MemGPT** (2023)：首次提出将操作系统虚拟内存机制（L1/L2 缓存与 Disk 映射）引入 LLM 状态管理。

### 4. 最新研究 (Latest Research)
*   **MemoryOS** / **LongMem** (2025-2026)：面向长文本交互的操作系统级持久化与高时效状态管理。

### 5. 工程实践 (Practice)
*   **类型契约定义**：在 Python 中使用 `typing.Protocol` 定义 `ShortTermMemory`、`LongTermMemory` 和 `SemanticCache` 的基类接口。
*   **🎯 过关验证标准**：通过编写接口定义类，规范各级记忆的读写操作（`read/write/clear`），要求完成无具体实现的代码框架设计，并通过静态类型检查（`mypy`）。

### 6. Pipeline 映射 (Pipeline Mapping)
```text
User Input ──> [Semantic Cache] ──> [Working Memory] ──> [Long-term Memory (Vector)]
```

---

## Day 58：短期记忆管理：滑动窗口、Token 监测与后台异步摘要压缩

### 1. 痛点场景 (Problem)
随着对话轮次增加，Working Memory 中的 Token 数量呈线性增长。若直接粗暴截断，会导致前期核心语义（如用户偏好、当前开发主语言）彻底丢失；若在主线程同步调用大模型进行总结，会造成显著的阻塞时延，降低首字延迟（TTFT）体验。

### 2. 核心理论 (Theory)
*   **会话滚动截断 (Sliding Window)**：基于 Token 计数动态截取最近 $N$ 轮消息。
*   **非阻塞异步摘要 (Asynchronous Summarization)**：在主流程响应的后台，通过异步任务（`asyncio.create_task`）触发大模型执行历史归约，生成轻量级上下文摘要（Summary），避免主交互阻塞。
*   **摘要漂移控制 (Summary Drift)**：设计递归总结的深度上限与高保真 Prompt，降低信息迭代过程中的信息损耗。

### 3. 经典论文 (Foundation Papers)
*   **MemGPT (Context Management)**：LLM 显式触发上下文交换与分页逻辑。

### 4. 最新研究 (Latest Research)
*   **Activation Beacon** & **StreamingLLM** (2024-2025)：利用 KV Cache 压缩与注意力滑窗实现无限流式输入。

### 5. 工程实践 (Practice)
*   **异步归约管道**：编写 `BufferMemoryManager` 类，检测消息 Token 超过 2000 时，在不阻塞主交互流的前提下异步启动 LLM 执行 Summary 归约，自动替换已截断的历史消息。
*   **🎯 过关验证标准**：设计一个模拟对话脚本。测试 20 次交互下，后台成功触发至少 2 次异步摘要压缩，主交互通道依然保持非阻塞流式输出。

### 6. Pipeline 映射 (Pipeline Mapping)
```text
[New Message] ──> (Token Check) ──> [Buffer Memory] ──> (Limit Exceeded) ──> [Async Summary Generator]
```

---

## Day 59：长期记忆系统：实体级别 Facts 实时抽取与多租户隔离存储

### 1. 痛点场景 (Problem)
大段的会话摘要（Summary）存在严重的信息稀释问题。如果要精确获取用户对某技术栈的偏好，让模型在数千字摘要中检索往往不够可靠。此外，多用户并发环境下，若没有进行严格的租户隔离（Tenant Isolation），极易引发越权读取与记忆数据交叉污染。

### 2. 核心理论 (Theory)
*   **事实提取 (Fact Extraction)**：使用结构化 JSON Schema 约束，从日常对话中抽取出独立的原子事实实体（例如：`likes python`，`hates java`）。
*   **多租户隔离 (Multi-Tenant Isolation)**：基于 `user_id` 和 `session_id` 对长期记忆数据库进行物理隔离。
*   **增量式 Facts 沉淀**：避免对全部对话进行重写，仅对新增的 Facts 进行分析并向量化沉淀。

### 3. 经典论文 (Foundation Papers)
*   **Generative Agents** (2023)：提出人物画像（Profile）与偏好的持久化管理机制。

### 4. 最新研究 (Latest Research)
*   **Mem0** (2024-2025)：摒弃 Summary 模式，开创了基于实体的增量 facts 提取与关系图记忆（Entity-centric Memory）。

### 5. 工程实践 (Practice)
*   **多路 Facts 写入器**：实现 `FactExtractor` 模块。大模型从对话历史中提取结构化事实，并将其写入支持 `user_id` 过滤的本地 Qdrant 数据库中。
*   **🎯 过关验证标准**：向 Facts 处理器输入 5 轮包含闲聊与技术偏好的对话，验证大模型提取出至少 3 条结构化事实，且 Qdrant 能够使用 `Filter` 基于 `user_id` 准确召回。

### 6. Pipeline 映射 (Pipeline Mapping)
```text
User Message ──> [Fact Extractor] ──> [JSON Filter] ──> [Qdrant DB (Partition by user_id)]
```

---

## Day 60：时序一致性：记忆去重、冲突判定与时间衰减消解机制

### 1. 痛点场景 (Problem)
长期记忆随时间推移必然会产生矛盾与过时。例如：用户前天声明“我常用 Java 开发项目”，今天却声明“我已完全转入 Python 且厌恶 Java”。若不解决此冲突，向量数据库同时召回这两条事实会导致大模型输入上下文前后矛盾，出现严重幻觉。

### 2. 核心理论 (Theory)
*   **记忆整合 (Memory Consolidation)**：后台进程定期合并高度相关的 Facts。
*   **冲突判定 (Conflict Detection)**：定义语义互斥逻辑，识别新旧事实的时序对立。
*   **时间衰减 (Time-decay Weighting)**：结合艾宾浩斯遗忘曲线，为记忆条目计算时间衰减系数，最新事实具备最高权重级别。

### 3. 经典论文 (Foundation Papers)
*   **Reflexion** (2023)：通过环境反馈进行反思（Self-Reflection）并修改长期规划记忆。

### 4. 最新研究 (Latest Research)
*   **Memory Editing** & **Knowledge Updating** (2024-2026)：关于大模型外挂知识库实时编辑与权重遗忘的论文。

### 5. 工程实践 (Practice)
*   **冲突消解算法**：编写 `MemoryConsolidator` 控制类。当提取出新的 Fact 时，比对已有 Fact 集合，计算相似度与对立度，使用 LLM 对冲突记录进行“原地更新”或“逻辑删除”。
*   **🎯 过关验证标准**：输入两条互斥的模拟事实（带有时戳），运行消解逻辑后，确保旧有互斥事实被物理覆盖或逻辑注销，只保留最新事实状态。

### 6. Pipeline 映射 (Pipeline Mapping)
```text
[New Fact] ──> [Conflict Detector] ──> (Semantic Similarity & Time Stamp) ──> [Consolidated Facts]
```

---

## Day 62：自适应决策：记忆路由（Memory Router）与 RAG 多路检索协同

### 1. 痛点场景 (Problem)
并非所有简单的交互请求（如“你好”、“今天天气怎么样”）都需要去扫描 Qdrant 的长期偏好数据库以及专业 RAG 知识库。无差别的全量向量检索会导致首字延迟（TTFT）增加、API 费用暴涨，同时检索回的无关文档会干扰大模型生成。

### 2. 核心理论 (Theory)
*   **检索分类决策 (Retrieval Routing)**：前置路由分类层，基于轻量分类 Prompt 对用户意图进行识别分类（分流至：`MEM` / `RAG` / `NONE`）。
*   **协同召回重排**：若判定为混合意图，执行多路检索（从 RAG 检索知识，从 Memory 检索偏好），并对召回条目进行归一化阈值过滤（Threshold Filtering）。

### 3. 经典论文 (Foundation Papers)
*   **Self-RAG** / **Corrective RAG (CRAG)** (2023-2024)：提出了自适应检索路由以及基于反思符（Critique Tokens）的信息修正思想。

### 4. 最新研究 (Latest Research)
*   **Adaptive Retrieval** (2024-2025)：基于 Query 复杂度和不确定性动态控制检索深度与路线的研究。

### 5. 工程实践 (Practice)
*   **多路决策路由**：实现 `MemoryRouter` 模块。对输入的 Query 进行特征识别，返回 `MEM`（仅读取个性化偏好）、`RAG`（检索外部知识）或 `NONE`（直接会话）。
*   **🎯 过关验证标准**：通过 20 条测试样本，覆盖闲聊、个人偏好、技术知识三大维度，验证路由准确率达 90% 以上，且在路由为 `NONE` 时，查询总耗时（Rtt）降低 80% 以上。

### 6. Pipeline 映射 (Pipeline Mapping)
```text
                   ┌──> [MEM Branch] ──> Qdrant (Facts)
User Query ──> [Memory Router] ──> [RAG Branch] ──> VectorDB (Docs)
                   └──> [NONE Branch] ──> Directly to LLM
```

---

## Day 61：底层持久化：关系型 Schema 建模与多 Session 状态重构

### 1. 痛点场景 (Problem)
若 Agent 的会话数据和 Facts 仅保留在内存（In-Memory）或单纯依赖外部 API 的 Session（如 OpenAI 云端云存储），当网络断连、容器重启或模型服务发生降级时，将导致历史交互上下文完全遗失。必须在本地实现可靠的数据持久化，提供断电恢复和多 Session 隔离的能力。

### 2. 核心理论 (Theory)
*   **异步关系型数据库操作**：利用 `aiosqlite` 异步连接并操作本地关系型数据库 SQLite。
*   **数据库 Schema 实体建模**：设计 `sessions`（会话元数据表）、`messages`（消息历史表）、`memories`（长期记忆/事实表）三张核心关系表。
*   **Session 重构与反序列化**：当用户传入特定的 `session_id` 时，系统自动从 SQLite 中读取并反序列化出该 Session 的历史上下文。
*   **存储与状态解耦**：将存储逻辑抽离为 `Repository` 适配层，解耦核心业务 Pipeline 与具体的数据库引擎细节。

### 3. 最新研究 (Latest Research)
*   **Letta (Agentic OS State Management)** (2025)：将 Agent 状态从应用层剥离为独立的、符合 ACID 特性的持久化数据库服务的工业级最佳工程实践。

### 4. 工程实践 (Practice)
*   **异步数据库适配器**：使用 `aiosqlite` 编写 `PersistenceStore` 辅助类，支持多 Session 的写入、读取与上下文反序列化重构。
*   **🎯 过关验证标准**：编写单元测试，模拟多 Session 写入并突发进程中断（主动退出事件循环）。进程重启后，传入相同 `session_id` 能 100% 重构恢复先前的短期上下文与 Facts 关联。

### 6. Pipeline 映射 (Pipeline Mapping)
```text
LLM State / Facts ──> [Repository Interface] ──> [aiosqlite Adapter] ──> SQLite DB
```

---

## Day 63：第九周综合实战（✅ 里程碑二）：多层级记忆工程 Pipeline 拼装实战

### 1. 实战目标 (Goal)
自底向上组装第九周开发的所有记忆引擎模块，构建一个支持断电无缝恢复、具备长时个性化偏好事实沉淀、并能根据问题自动路由 RAG 专业知识的**生产级 AI 研究助手引擎**。

### 2. 架构设计 (System Architecture)
```text
                         ┌────────────────────────────────────┐
                         │             User Input             │
                         └─────────────────┬──────────────────┘
                                           │
                                           ▼
                                ┌────────────────────┐
                                │   Memory Router    │
                                └──────┬──┬──┬───────┘
                                       │  │  │
                    ┌──────────────────┘  │  └──────────────────┐
                    ▼                     ▼                     ▼
             [ MEM Route ]          [ RAG Route ]         [ NONE Route ]
            Qdrant (Facts)         VectorDB (Docs)       (Skip Retrieval)
                    │                     │                     │
                    └──────────────┬──────┴─────────────────────┘
                                   │
                                   ▼
                         ┌────────────────────┐
                         │  Context Assembler │ <─── [ Working Memory ]
                         └─────────────────┬──┘      (From SQLite Store)
                                           │
                                           ▼
                         ┌────────────────────┐
                         │   LLM Inference    │
                         └─────────────────┬──┘
                                           │
                                           ▼
                      ┌────────────────────┴────────────────────┐
                      │    Background Async Tasks (Non-blocking)│
                      └────────────┬────────────────────────────┘
                                   │
                     ┌─────────────┴─────────────┐
                     ▼                           ▼
          [ Fact Extraction ]         [ Buffer Memory Manager ]
          (JSON Constraints)          (Token Metric > 2000)
                     │                           │
                     ▼                           ▼
          [ Memory Consolidation ]    [ Async Summary Generator ]
          (Conflict Resolution)                  │
                     │                           ▼
                     └─────────────┬─────────────┘
                                   │
                                   ▼
                         ┌────────────────────┐
                         │ SQLite Store       │ (Sessions, Messages, Facts)
                         └────────────────────┘
```

### 3. 🎯 交付件与验收标准 (Deliverables)
1. **完整 SQLite Schema 定义脚本**。
2. **微引擎物理隔离组件**：
   - 包含 `BufferMemoryManager`（异步摘要滑窗）、`FactExtractor` 与 `MemoryConsolidator`（事实冲突消解）、`MemoryRouter`（自适应三路路由）。
3. **主装配入口 `main.py`**：仅负责生命周期的事件流与各微引擎的装配（`Repository` 模式），不包含具体的路由或冲突处理逻辑。
4. **完整的单元测试套件**：覆盖记忆路由准确率、时序冲突消解正确性及 Session 断电恢复。
5. **模拟跨 Session 对话的详细审计日志（Stdout Log）**。
