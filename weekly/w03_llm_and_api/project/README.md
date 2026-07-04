# OpsChat CLI — SRE 智能故障诊断助手终端 (Day 21 综合实战)

本项目是一个全异步、具备工业级容错与可观测性的 SRE 命令行流式交互终端系统。通过融合第三周每日所学的 LLM 原理、Token 裁剪、并发会话管理和流式引擎，支持在首选大模型网络抖动或服务崩溃时在 500ms 内静默切换至备用大模型，并提供高精度的 Token 账单审计。

---

## 🌟 核心功能亮点

1. **并发安全会话隔离 (`SessionManager`)**
   - 使用 `asyncio.Lock` 细粒度锁保证多会话状态的读写原子性。
   - 引入 `OrderedDict` 结合 LRU 淘汰机制自动剔除最久未使用的冷会话，防止内存泄露。
2. **高精度 3000 Token 滑动裁剪器 (`SmartContextCutter`)**
   - 在请求发出前，利用本地 `tiktoken` 离线分词精确预算 Token 消耗。
   - 滑动窗口截断老旧消息，无条件保留 System SRE 专家人设，绝不打碎单条消息实体（防止 JSON 损毁）。
3. **500ms 超时动态 Fallback 降级 (`FallbackController`)**
   - 首选高性价比大模型 (MiniMax)，备用高可用大模型 (DeepSeek/OpenAI)。
   - 使用 `asyncio.wait_for` 拦截首字延迟 (TTFT) 大于 500ms 的情况，并在捕获连接异常/50x 错误时进行**自动、静默、无感知**降级重新请求。
4. **实时打字机渲染与性能可观测性看板 (`AsyncStreamEngine`)**
   - 异步逐字节流式 SSE 渲染，终端“打字机式”输出。
   - 对话结束自动打印时延看板：展示模型名称、首字延迟 (TTFT)、吞吐速率 (TPS) 和本次对话产生的美元费用。
5. **CSV 结构化 Token 计费审计 (`TokenAuditor`)**
   - 自动按照输入/输出的美元费率计算每次交互产生的美元账单，持久化追加至本地 `audit_log.csv` 中。

---

## 📂 项目结构

```
weekly/w03_llm_and_api/project/
├── main.py                         # CLI 主入口（异步命令交互循环）
├── config.py                       # 全局参数与费率计费字典配置
├── models.py                       # 统一数据结构定义 (StreamChunk, StreamMetrics, AuditRecord)
├── exceptions.py                   # 统一自定义异常体系 (LLMAPIError, LLMConnectionError)
├── protocols.py                    # StreamingLLMClient Protocol 强契约声明
│
├── adapters/                       # 流式适配器层
│   ├── minimax_stream_adapter.py   # MiniMax 异步流式 SSE 适配器
│   └── openai_stream_adapter.py    # OpenAI/DeepSeek 异步流式 SDK 适配器
│
├── core/                           # 核心业务组件
│   ├── fallback_controller.py      # 500ms 超时动态降级控制器
│   ├── context_cutter.py           # 3000 Token 上下文裁剪器
│   ├── session_manager.py          # 并发安全与 LRU 淘汰会话管理器
│   └── token_auditor.py            # CSV Token 审计计费模块
│
├── tests/                          # 单元测试与集成测试
│   ├── test_fallback.py            # 500ms 超时与降级逻辑单元测试
│   └── test_integration.py         # 裁剪、并发会话与审计联合集成测试
│
└── README.md                       # 本说明文档
```

---

## 🚀 快速开始

### 1. 运行测试套件

在开始之前，强烈建议运行全量单元测试与集成测试，验证各个容错链路：

```bash
# 进入项目工作空间根目录
cd /Users/zhouyi/03.AI/03.freshManStart

# 使用 pytest 运行测试
python -m pytest weekly/w03_llm_and_api/project/tests -v
```

### 2. 启动 CLI 终端 (交互式 REPL)

运行 main.py 启动交互命令行：

```bash
python weekly/w03_llm_and_api/project/main.py
```

*如果在没有 API 密钥的环境下运行，系统将自动对未配置的适配器启用 Mock 模拟数据流进行离线演示。*

---

## 🛠️ CLI 特殊控制命令

在交互命令行终端中，除了直接输入 SRE 诊断问题外，还可使用以下控制指令：

* **`/help`** : 打印可用系统命令菜单。
* **`/switch <session_id>`** : 切换到指定会话（如果该会话不存在，则自动建立新会话，超出 LRU 限制将自动淘汰冷会话）。
* **`/clear`** : 清除当前会话的上下文消息历史。
* **`/audit`** : 审计并打印当前运行周期内所有会话累计的请求次数、Token 消耗以及美元费用账单。
* **`exit` 或 `quit`** : 结束会话并打印退出总账单总结，安全保存审计日志并退出程序。
