# Redis Checkpointer 数据结构与 Key 设计规则

为了在生产环境下支持高性能存盘与无损时间旅行（Time Travel），`ProductionRedisCheckpointer` 采用 **Hash + Sorted Set (ZSet)** 组合存储方案。

---

## 一、Key 命名规范

所有存储的 key 均带有统一前缀 `lg` (LangGraph)：

| 存储类型 | Key 物理格式 | Redis 数据结构 | 说明 |
|---|---|---|---|
| 快照详情 | `lg:cp:{thread_id}:{ns}:{checkpoint_id}` | Hash | 存储具体快照序列化字节流与元数据 |
| 最新快照引用 | `lg:cp:{thread_id}:{ns}:latest` | Hash | 指向该 thread 的最新快照快速索引 |
| 时间线索引 | `lg:idx:{thread_id}:{ns}` | Sorted Set (ZSet) | Score 为毫秒时间戳，Member 为 `checkpoint_id` |
| 挂起写操作 | `lg:writes:{thread_id}:{ns}:{cp_id}:{task_id}` | Hash | 存储节点的中间挂起写入对象 |

---

## 二、Redis 数据结构物理解构

### 1. 快照 Hash (`lg:cp:{thread_id}:{ns}:{checkpoint_id}`)

包含字段：
- `checkpoint_type`: str（如 `"json"` 或二进制类型签名）
- `checkpoint_bytes`: bytes（序列化后的 `Checkpoint` 对象）
- `metadata_type`: str
- `metadata_bytes`: bytes（序列化后的 `CheckpointMetadata` 对象）
- `parent_checkpoint_id`: str（父 Checkpoint ID，用于构造 DAG 关系树）
- `timestamp`: float/str（存盘时刻时间戳）

### 2. 时间线 ZSet (`lg:idx:{thread_id}:{ns}`)

- **Score**: Unix timestamp in milliseconds (e.g. `1774258900.123`)
- **Member**: `{checkpoint_id}`

**为什么引入 ZSet？**
LangGraph 底层在调取 `get_state_history` 时，依赖 `list()` 契约按创建时间**倒序**检索历史版本。使用裸 `KEYS *` 无法保证时间顺序且在大数据量下有性能危机；使用 Redis Sorted Set 通过 `ZREVRANGEBYSCORE` 指令，能够实现 $O(\log N + M)$ 的高性能时间倒序检索与高效分页。
