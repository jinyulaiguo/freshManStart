# Day 106 课堂笔记：可观测性与 LangSmith 平台追踪机制

> **材料约定**：本周日常只维护 `notes.md`；运行与终局规划见 [`../overview.html`](../overview.html)。README 仅出现在 Day 112 综合项目。

## 运行（本课）

```bash
cd weekly/w16_observability/day106
python practice.py
pytest tests/ -q
```

LangSmith UI：项目名见根 `.env` 的 `LANGSMITH_PROJECT`。

---

## 一、为什么 Agent 特别需要「可观测性」

传统后端靠日志（log）排查：打印一行 `"error: timeout"` 往往够用。  
Agent 却是一个**会自己选下一步的黑盒**：Thought → Action → Observation 可能循环多轮，任何一步选错工具、参数漏传或陷入死循环，都很难从几行字符串日志还原因果链。

### 1. Observability ≠ Monitoring ≠ Logging

| 概念 | 回答的问题 | Agent 场景例子 |
| :--- | :--- | :--- |
| **Logging** | 发生了什么事件？ | `"tool_call: search_inventory"` |
| **Monitoring** | 指标是否越线？ | QPS、错误率、P95 延迟 |
| **Observability** | 系统**内部状态如何流动**？为何在第 4 步死循环？ | 完整 Trace 树：每轮 LLM 输入/输出、工具参数与返回值、父子耗时 |

可观测性的工业三角是 **Logs / Metrics / Traces**。Day 106 聚焦 **Traces（链路追踪）**；Metrics 留给 Day 111，结构化异常日志留给 Day 110。

### 2. 没有 Trace 时的典型灾难

| 现象 | 根因可能 | 无 Trace 时的代价 |
| :--- | :--- | :--- |
| 回复胡编库存 | 第 2 步工具参数传错 SKU | 只能猜 Prompt，反复盲改 |
| 费用暴涨 | Agent 在工具环里空转 20 轮 | 账单先到，原因后查 |
| 偶发超时 | 某次 Observation 过长塞爆上下文 | 无法对比「好 run / 坏 run」 |

---

## 二、LangSmith 在做什么（原理级）

LangChain / LangGraph 的 Runnable（`invoke` / `ainvoke` / 图节点 / 工具）执行时，会经过统一的回调与上下文传播链路。  
当进程环境满足条件时，LangSmith SDK 作为 **tracing callback** 挂载上去：

1. 每个 Runnable 调用开启一个 **Run（类似 Span）**
2. 父子调用自动嵌套（Agent → LLM → Tool → LLM …）
3. 输入、输出、耗时、token、错误状态异步上报到 LangSmith 后端
4. UI 把这些 Run 渲染成**树状 Trace**

因此过关标准强调：**不修改核心业务代码，只靠环境变量绑定追踪代理**。

```text
业务代码: agent.invoke(...)     ← 零 LangSmith import
     │
     ▼
LangChain Callback / Context
     │
     ▼
LangSmith Exporter  ──HTTP──▶  smith.langchain.com UI
```

### 环境变量解耦（配置与代码分离）

| 变量 | 作用 |
| :--- | :--- |
| `LANGSMITH_TRACING=true` | 总开关：是否启用追踪 |
| `LANGSMITH_API_KEY` | 鉴权 |
| `LANGSMITH_PROJECT` | 项目名，便于在 UI 筛选今日练习 |

业务模块只关心「查库存、算价格」；是否上报 Trace 由运维/本地 `.env` 决定，这就是**环境变量解耦**。

### 进阶手段（今日了解即可）

- `langsmith.tracing_context(enabled=True)`：局部开关，适合「只追某一次 invoke」
- `@traceable`：给**非** LangChain 原生函数手工包一层（例如纯 Python 计费函数）

Day 106 主路径仍是纯环境变量，对应过关原文「不修改核心业务代码」。

---

## 三、在 LangSmith UI 里怎么读 ReAct Trace

跑完 `practice.py` 后打开项目页，点进最新 Run，你应能看到类似结构：

```text
Trace (根)
├── agent / LangGraph          ← 整次请求
│   ├── model (LLM)            ← Thought：决定调用哪个工具
│   ├── tools / lookup_stock   ← Action + Observation
│   ├── model (LLM)            ← 再思考
│   ├── tools / calc_quote     ← 又一轮 Action + Observation
│   └── model (LLM)            ← 最终自然语言答复
```

对照 ReAct 术语：

| ReAct | Trace 里看什么 |
| :--- | :--- |
| Thought | LLM Run 的输出（常含 tool_calls 意图） |
| Action | Tool Run 的 name + input |
| Observation | Tool Run 的 output |

若只看到一次 LLM、没有 Tool 子节点：说明 Query 没有逼出工具调用——换一条「必须查库存再算价」的问题重跑。

---

## 四、与本周后续的衔接

| 天 | 相对 Day 106 的升级 |
| :--- | :--- |
| Day 107 | 同样的 Trace 语义，换成本地 Phoenix + OpenTelemetry/OpenInference（数据不出网） |
| Day 108 | 手写 Span 嵌套，理解自动埋点背后的拓扑 |
| Day 109+ | 在 Span 上挂 Latency / Token / 美分成本；异常进 Span；Prometheus 指标 |

今日先把「黑盒变白盒」跑通；私有化与指标是后面的课。

---

## 五、权威参考

- [LangGraph Observability](https://docs.langchain.com/oss/python/langgraph/observability)
- [Trace with LangGraph](https://docs.langchain.com/langsmith/trace-with-langgraph)
- [LangSmith 环境变量](https://docs.smith.langchain.com/)
