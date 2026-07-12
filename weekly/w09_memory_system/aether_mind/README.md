# 📅 Week 9 综合实战：AetherMind 多层级记忆工程 Agent 系统

AetherMind 是一个自底向上构建的、支持断电无缝恢复、多租户物理隔离的 **生产级 AI 记忆与 RAG 检索双驱动引擎**。项目融合了短期工作记忆（滑窗摘要）、长期事实记忆（艾宾浩斯衰减与消歧冲突解决）以及先进的 GraphRAG（局部/全局图检索与社区预筛选）系统。

为了便于调试与观测多层级记忆在后台的流转状态，项目配备了一个精致的 **Web 调试 Dashboard**（遵循温润知性极简主义配色风格），并提供了一键启动与自动化测试脚本。

---

## 🏗️ 积木式微引擎物理结构

系统各核心组件物理隔离，以确保低耦合度与高可维护性：

```text
weekly/w09_memory_system/aether_mind/
├── aether_mind/                   # 高内聚、职责单一的微引擎组件
│   ├── core/                      # 核心调度与编排层
│   │   ├── context.py             # 动态上下文组装器
│   │   ├── engine.py              # 引擎装配主干（MemoryAgentEngine）
│   │   ├── planner.py             # 规划生成引擎
│   │   └── router.py              # 自适应意图分流路由器 (MemoryRouter)
│   ├── memory/                    # 多层级自主记忆管理
│   │   ├── buffer.py              # 短期消息管理与会话生命周期
│   │   ├── consolidator.py        # 长期记忆事实整合消歧与衰减器
│   │   ├── extractor.py           # 原子事实三元组提取器
│   │   └── long.py                # 长期记忆检索适配器
│   ├── rag/                       # 混合检索工程 (GraphRAG + VectorRAG)
│   │   ├── engine.py              # 检索引擎主控 (RAGEngine)
│   │   ├── graph_search.py        # 知识图谱抽取与全局/局部图搜索 (GraphRAGEngine)
│   │   └── vector_search.py       # 多路语义混合向量搜索 (VectorSearcher)
│   ├── storage/                   # 持久化存储驱动层
│   │   ├── base.py                # 存储驱动抽象协议
│   │   ├── postgres.py            # PostgreSQL 物理存储适配器
│   │   ├── qdrant.py              # Qdrant 向量数据库适配器
│   │   └── sql.py                 # SQLite/关系数据库通用存储适配器
│   ├── tools/                     # 内置 Agent 外部调用工具集
│   └── utils/                     # 基础工具组件 (真实 LLM 请求客户端等)
├── tests/                         # 自动化测试用例集
├── server.py                      # FastAPI Web 后端服务
├── dashboard.html                 # 调试与交互 Web 看板（前端单页面）
├── start.sh                       # 物理拉起 Web 后端服务的一键脚本
├── run_tests.py                   # pytest 自动化测试运行器
└── README.md                      # 本项目文档说明
```

---

## 💾 底层 SQLite 持久化 Schema 建模

通过 `aether_mind/storage/sql.py` 中定义的三个核心物理关系表，解耦了内存状态变量，为断电无缝恢复与多租户物理隔离打下底层架构基础：

```sql
-- 1. 会话元数据表（存储各会话的当前累积摘要，用于热重构）
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);

-- 2. 短期消息历史表（在滑窗摘要后，旧消息将被物理清理）
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

-- 3. 长期事实记忆表（支持权重 weight 与写入时戳）
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    timestamp REAL NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0
);
```

---

## ⚡ 快速启动与访问

### 1. 运行自动化测试验证过关指标
项目配备了完整的测试用例，您可以通过以下命令运行它们：
```bash
python3 run_tests.py
```
该脚本将执行全部测试，并确保以下指标通过验证：
*   **路由分流准确率 >= 80%** (NONE, MEM, RAG, PLAN 等多路正确导流)。
*   **长期记忆时序冲突消歧正确性** (CONFLICT 物理覆盖、REDUNDANT 权重重置)。
*   **冷记忆遗忘衰减淘汰正确性** (衰减后低于 0.2 被自动淘汰)。
*   **物理断电状态 100% 还原** (崩溃重启后 Session 消息与摘要 100% 复原)。
*   **多租户安全隔离性** (不同 user_id 下 Facts 绝不交叉泄露)。

### 2. 启动 Web Dashboard 看板
执行以下一键启动脚本：
```bash
./start.sh
```
服务成功拉起后，请在浏览器中打开：
👉 [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

---

## 🚀 GraphRAG 检索瓶颈与性能优化

在 GraphRAG 的全局检索（Global Search）中，用户的宏观提问（如 *“AI Agent 的论文中，相关文献有哪些”*）需要对全局知识图谱中的 **131 个 Louvain 社区** 进行评估。在 Map 阶段中，系统需要对每个社区的报告独立调用一次 LLM API。

### 1. 性能瓶颈分析
* **无并发限制**：若瞬间发送 131 个请求，会直接触发 MiniMax API 的 `HTTP 429` 速率限制拦截。
* **5 并发限制下**：`131 个社区 / 5 并发 = 27 批`。在 API 响应均值为 4~5 秒时，完成全部 Map 评估需执行 $27 \times 5 = 135$ 秒左右，检索极其缓慢。

### 2. 我们实现的 KNN 社区预筛选优化方案（已落地）
* **原理**：
  1. 在社区报告生成完毕后，自动在 `build_communities` 方法中将每份社区报告的 `summary` 向量化，并与社区 ID 一起写入 Qdrant 的专用集合 `community_collection`。
  2. 在全局检索时，先将用户的 query 向量化，并在 Qdrant 中执行相似度检索，召回 Top 10 的相关社区。
  3. Map 评估阶段**仅传入这 10 个被筛选出的相关社区**，其余无关社区直接裁剪舍弃。
* **效果**：
  * 大模型 Map 阶段的请求次数由 **131 次直接降为 10 次**。
  * 全局检索时间由 **135 秒缩短为 8 ~ 10 秒**（耗时缩短约 13 倍），同时 Token 消耗降低 90% 以上。

### 3. 我们实现的其他鲁棒性防御设计
* **信号量并发限流 (`asyncio.Semaphore(5)`)**：保证高频请求下 API 不会触发 429 崩溃。
* **JSON 多候选提取与自愈机制**：
  * 正则剥离 `<think>...</think>` 块，替换中英文混用符号。
  * **多候选提取算法**：同时提取所有 `{` 和 `[` 起始位置，并提取出“切片至文本末尾”的截断候选子串。对于每个候选子串，使用解析栈补齐缺失的闭合括号（`}`、`]`）并尝试 `json.loads` 反序列化。这完美解决了由于 API 超时物理截断（没有尾部括号）或 LLM 在响应中复述 Prompt 文字导致常规正则失准的痛点。

---

## 🎨 看板设计风格：温润知性极简主义

调试看板严格遵循 **Warm Intellectual Minimalism** 设计规范：
*   **色彩体系**：主背景为骨白色 (`#faf9f4`)，卡片容器为纯白色 (`#ffffff`)，文字主色为深炭黑 (`#141413`)，功能强调与高亮使用杏粘土色 (`#D97757`)。摒弃强阴影，采用 1px 低对比度细线边框（`#e9e8e3`）。
*   **上帝视角调试面板**：
    *   **短期工作记忆**：实时显示内存活跃滑动窗口的消息数量和当前的滚动摘要内容。
    *   **长期事实库**：列表可视化展示 Facts 属性、记录时间及当前根据艾宾浩斯遗忘曲线折算出的权重，并支持手动衰减淘汰。
    *   **意图分流路由器**：直观展示上轮提问的预测意图（NONE/MEM/RAG/PLAN/TOOL），量化检索时延并展示召回的 Payload。
    *   **后台任务审计日志**：展示后台非阻塞异步线程执行的原子事实提取与时序消歧日志流。

---

## 🧠 生产级三层语义缓存（Semantic Cache）设计

### 1. 原有设计的工程缺陷

原始实现以 SQL 精确字符串匹配代替"语义缓存"，是一个严重的名实不符的伪缓存方案：

```sql
-- ❌ 原方案：= 号精确匹配，任何标点/空格差异即 miss
WHERE session_id = ? AND step_name = 'final_answer' AND input_data = ?
```

**三大硬伤：**

| 缺陷 | 影响 |
|---|---|
| `input_data = query` 字节级精确匹配 | `"什么是RAG"` vs `"RAG是什么"` 永远 miss，实际命中率 ≈ 0 |
| `session_id` 强绑定 | 同用户跨 Session 提相同问题，永远 miss |
| 无 TTL 设计 | 缓存永不过期，知识更新后用户拿到过时答案 |

### 2. 生产级三层缓存架构（Industry Standard）

参考 Redis GPTCache / RedisVL 生产实践，系统现采用三层瀑布式缓存架构：

```
用户 Query
    │
    ▼
┌──────────────────────────────────┐
│  L1：精确哈希缓存（Python in-memory） │  < 1ms   命中率约 15%
│  key = f"{user_id}:{SHA256(normalize(q))}"  │
└──────────────────────────────────┘
              │ miss
              ▼
┌──────────────────────────────────┐
│  L2：向量语义缓存（Qdrant ANN 检索）   │  < 50ms  命中率约 60%
│  cosine_similarity > 0.92         │
└──────────────────────────────────┘
              │ miss
              ▼
┌──────────────────────────────────┐
│  L3：LLM 兜底推理                   │  ~3000ms
│  → 异步后台双写回 L1 + L2           │
└──────────────────────────────────┘
```

### 3. 各层核心设计细节

#### L1：精确哈希缓存（Python `dict` + LRU）

对 Query 做**规范化**（小写 + 折叠空白）后取 SHA-256 哈希，以 `user_id:hash` 为键做内存字典查找。

```python
def _normalize(q: str) -> str:
    """折叠空白 + 小写，消除无意义的字符差异"""
    return re.sub(r'\s+', ' ', q.strip().lower())

# 缓存 key 格式（多租户物理隔离）
key = f"{user_id}:{sha256(normalize(query))}"
```

- **TTL**：写入时记录 UNIX 时间戳，读取时判断 `now - written_at > TTL_SECONDS`，超期自动 miss
- **LRU 驱逐**：上限 `L1_MAX_SIZE = 500` 条，超出时驱逐最久未访问的 entry
- **多租户隔离**：key 前缀包含 `user_id`，不同用户缓存物理隔离

#### L2：向量语义缓存（Qdrant `semantic_cache_collection`）

对 Query Embedding 向量执行 Qdrant ANN 检索，相似度超过阈值则命中缓存：

**Payload 结构（写入 Qdrant 时）：**
```json
{
    "user_id": "usr_123",
    "original_query": "RAG是什么",
    "cached_response": "RAG（检索增强生成）是...",
    "created_at": 1720000000,
    "hit_count": 12
}
```

- **相似度阈值**：`SIM_THRESHOLD = 0.92`（余弦相似度，可在 `.env` 调整）
- **TTL 实现**：命中条目若 `now - created_at > TTL_SECONDS` 则忽略并异步删除该过期点
- **多租户过滤**：`filter_dict={"user_id": user_id}` 保证不同租户缓存物理隔离
- **独立 Collection**：`semantic_cache_collection`（与 `knowledge_collection` 物理隔离，防止 RAG 检索污染）

#### L3：LLM 兜底推理 + 异步双写回

LLM 正常推理完成后，通过 `asyncio.create_task` **非阻塞**地将结果双写回 L1 和 L2，不增加用户响应延迟。

### 4. 实现架构：`SemanticCacheEngine` 微引擎

遵循项目"积木式自底向上拼装"规范，缓存逻辑被封装为独立微引擎 `aether_mind/core/semantic_cache.py`，与 `engine.py` 完全解耦：

```text
aether_mind/core/
├── semantic_cache.py    # 新增：独立语义缓存微引擎
├── engine.py            # 修改：替换 Step 2 伪缓存，接入 SemanticCacheEngine
└── ...
```

**对外公开接口：**
- `SemanticCacheEngine.get(user_id, query)` → `Optional[Tuple[str, str]]` 返回 `(cached_text, hit_level)`
- `SemanticCacheEngine.put(user_id, query, response)` → 双写 L1 + L2

### 5. 可观测性：Trace 命中分级

每次请求 Trace 日志中可见命中层级，便于调优阈值与监控命中率：

```json
{"type": "trace", "step": "cache", "content": "L1_HIT | 精确哈希命中，< 1ms 直接返回"}
{"type": "trace", "step": "cache", "content": "L2_HIT | 语义相似度 0.947，命中向量缓存"}
{"type": "trace", "step": "cache", "content": "MISS   | 未命中任何缓存层，进入正常推理流程"}
```

### 6. 核心配置项（`.env`）

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `SEMANTIC_CACHE_ENABLED` | `true` | 总开关，可紧急关闭 |
| `SEMANTIC_CACHE_THRESHOLD` | `0.92` | L2 余弦相似度命中阈值 |
| `SEMANTIC_CACHE_TTL_SECONDS` | `3600` | 缓存 TTL（秒），过期自动失效 |
| `SEMANTIC_CACHE_L1_MAX_SIZE` | `500` | L1 内存字典最大条目数（LRU） |

### 7. 与旧方案的关键差异对比

| 维度 | 旧方案（精确匹配） | 新方案（三层语义缓存） |
|---|---|---|
| 匹配逻辑 | SQL `=` 字节级精确 | L1 哈希 + L2 余弦相似度 ANN |
| 缓存范围 | 绑定单个 Session | 绑定 `user_id`，跨 Session 复用 |
| TTL | 无，永不过期 | 支持，默认 3600s |
| 容量控制 | 无限增长（DB 撑死） | L1 LRU 500 条上限 |
| 语义等价 | ❌ 不支持 | ✅ `"RAG是什么"` ≈ `"什么是RAG"` |
| 写回时机 | 阻塞主流程末尾 | 非阻塞 `create_task` 异步双写 |
| 实际命中率 | ≈ 0（生产几乎无用） | 预估 L1+L2 综合 ≈ 75% |
