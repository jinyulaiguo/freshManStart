# 📅 Week 9 综合实战：多层级记忆工程 Agent 系统

本项目为第九周的综合实战成果交付，自底向上构建了一个支持断电无缝恢复、多租户物理隔离、并能根据用户 Query 自动分流路由 RAG 专业客观知识的 **生产级 AI 记忆增强助手引擎**。

为了便于调试与观测多层级记忆在后台的流转状态，项目配备了一个精致的 **Web 调试 Dashboard**（遵循温润知性极简主义配色风格），并提供了一键启动与自动化测试脚本。

---

## 🏗️ 积木式微引擎物理结构

系统各核心组件物理隔离，以确保低耦合度与高可维护性：

```text
weekly/w09_memory_system/project/
├── app/                           # 高内聚、职责单一的微引擎组件
│   ├── config.py                  # 环境参数加载（sys.path 动态物理补全）
│   ├── db.py                      # SQLite 关系建模与断电状态反序列化接口
│   ├── memory_router.py           # 意图分流路由器（MEM / RAG / NONE）
│   ├── buffer_memory_manager.py   # 短期工作记忆（非阻塞后台摘要滑窗与时序保护）
│   ├── fact_extractor.py          # 长期记忆 Facts 实体级增量提取器
│   ├── memory_consolidator.py     # 长期记忆去重、时序冲突判定消歧与遗忘衰减器
│   ├── rag_engine.py              # 专业客观文档库检索（轻量级离线 rank-bm25）
│   └── main_engine.py             # 引擎主装配层（串联生命周期，不承担算法实现）
├── tests/                         # 自动化测试用例
│   ├── test_router.py             # 自适应路由准确率评测
│   ├── test_consolidation.py      # 时序一致性消歧与艾宾浩斯衰减测试
│   ├── test_recovery.py           # Session 断电恢复一致性测试
│   └── test_integration.py        # 多租户物理隔离及全链路集成测试
├── server.py                      # FastAPI Web 后端服务
├── dashboard.html                 # 调试与交互 Web 看板（前端单页面）
├── start.sh                       # 物理拉起 Web 后端服务的一键脚本
├── run_tests.py                   # pytest 自动化测试运行器
└── README.md                      # 本项目文档说明
```

---

## 💾 底层 SQLite 持久化 Schema 建模

通过 `app/db.py` 中定义的三个核心物理关系表，解耦了内存状态变量，为断电无缝恢复与多租户物理隔离打下底层架构基础：

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
python run_tests.py
```
该脚本将使用当前工作区虚拟环境的 pytest 执行测试，并确保以下指标通过验证：
*   **路由分流准确率 >= 80%** (NONE, MEM, RAG 三路正确导流)。
*   **长期记忆时序冲突消歧正确性** (CONFLICT 物理覆盖、REDUNDANT 权重重置)。
*   **冷记忆遗忘衰减淘汰正确性** (衰减后低于 0.2 被自动淘汰)。
*   **物理断电状态 100% 还原** (崩溃重启后 Session 消息与摘要 100% 复原)。
*   **多租户安全隔离性** (不同 user_id 下 Facts 绝不交叉泄露)。

### 2. 启动 Web Dashboard 看板
执行以下一键启动脚本：
```bash
./start.sh
```
服务成功拉起后，会在终端打印本地访问链接。请在浏览器中打开：
👉 [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

---

## 🎨 看板设计风格：温润知性极简主义

调试看板严格遵循 **Warm Intellectual Minimalism** 设计规范：
*   **色彩体系**：主背景为骨白色 (`#faf9f4`)，卡片容器为纯白色 (`#ffffff`)，文字主色为深炭黑 (`#141413`)，功能强调与高亮使用杏粘土色 (`#D97757`)。摒弃炫酷黑与强阴影，采用 1px 低对比度细线边框。
*   **上帝视角调试面板**：
    *   **短期工作记忆**：实时显示内存活跃滑动窗口的消息数量和当前的滚动摘要内容。
    *   **长期事实库**：列表可视化展示 Facts 属性、记录时间及当前根据艾宾浩斯遗忘曲线折算出的权重，并支持手动衰减淘汰。
    *   **意图分流路由器**：直观展示上轮提问的预测意图（NONE/MEM/RAG），量化检索时延并展示召回的 Payload。
    *   **后台任务审计日志**：展示后台非阻塞异步线程执行的原子事实提取与时序消歧日志流。
