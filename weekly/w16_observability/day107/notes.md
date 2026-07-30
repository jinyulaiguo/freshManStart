# Day 107 课堂笔记：OpenInference 与 OpenTelemetry 本地追踪

> **材料约定**：本周日常只维护 `notes.md`；知识总纲与 Day 112 终局映射见 [`../overview.html`](../overview.html)。README 仅出现在 Day 112。

## 运行（本课）

```bash
# 基建（若未启动）
cd weekly/w16_observability/infra && ./start.sh

cd weekly/w16_observability/day107
# 仅冒烟 OTEL 绑定
python phoenix_otel.py
# 真实 MiniMax ReAct → Phoenix
python traced_agent.py
pytest tests/ -q
```

Phoenix UI：`http://0.0.0.0:6006`（勿用 `localhost`）。项目名见 `PHOENIX_PROJECT_NAME`。  
（无 `practice.py`。）

---

## 一、为什么不能只靠 LangSmith

Day 106 用托管 LangSmith 把黑盒 Agent 变成白盒 Trace，开发体验极好。  
但企业内网常见约束是：

| 约束 | 后果 |
| :--- | :--- |
| 数据不出网 | Prompt / 工具返回值含客户机密，禁止上传 SaaS |
| 供应商锁定 | 换云或换观测平台时，埋点代码要重写 |
| 审计合规 | 需要自建存储与保留策略 |

因此需要一套 **厂商中立** 的遥测标准：数据在你自己的 Phoenix（或任意 OTLP 后端）里。

---

## 二、OpenTelemetry：怎么发 Trace

OpenTelemetry（OTel）是云原生分布式追踪的事实标准。核心对象：

| 概念 | 职责 |
| :--- | :--- |
| **TracerProvider** | 全局工厂：持有 Processor / Exporter |
| **Tracer** | 按 instrumentation 名称创建 Span |
| **Span** | 一次操作的计时单元（有父子关系） |
| **Exporter** | 把 Span 序列化后发到后端（OTLP HTTP/gRPC） |
| **Meter** | 指标侧（Counter/Histogram），本周 Day 111 再用 |

数据通路（本课）：

```text
Agent (LangGraph / LangChain)
        │  OpenInference 自动埋点
        ▼
TracerProvider + OTLP Exporter
        │  HTTP POST /v1/traces
        ▼
本地 Phoenix :6006  →  UI 还原 LLM 输入输出
```

Day 107 推荐用 `phoenix.otel.register(endpoint=..., project_name=...)` 一次完成 Provider + Exporter 绑定。

> **坑**：当前学习环境使用的 `arize-phoenix-otel` 在 HTTP 模式下，`endpoint` 需要写成  
> `http://localhost:6006/v1/traces`。若只写 `http://localhost:6006`，Exporter 会 `POST /` 并返回 **405**，Span 永远进不了 UI。  
> 本课 `phoenix_otel.resolve_phoenix_endpoint()` 已自动补全该后缀。

---

## 三、OpenInference：AI 语义约定

OTel 只定义「Span 长什么样、怎么传」；**不定义**「大模型调用该写哪些属性」。  
[OpenInference](https://github.com/Arize-ai/openinference) 是叠在 OTel 之上的 **GenAI 语义约定**，让 Phoenix 能画出 LLM / Tool / Agent / Retriever 专用视图。

常见属性（示意）：

| 属性 | 含义 |
| :--- | :--- |
| `openinference.span.kind` | `LLM` / `TOOL` / `AGENT` / `CHAIN` / `RETRIEVER` |
| `llm.input_messages` | 发给模型的消息列表 |
| `llm.output_messages` | 模型输出消息 |
| `llm.model_name` | 模型名 |
| `tool.name` / `tool.parameters` | 工具名与参数 |

本课用 `openinference.instrumentation.langchain.LangChainInstrumentor`：  
**自动**给 LangChain/LangGraph 的 Runnable 打上上述属性，业务代码（`agent_core`）仍然零改动。

业界另有 OTel 官方推进的 `gen_ai.*` 语义；与 OpenInference 可并存。本周以 OpenInference + Phoenix 为准。

---

## 四、LangSmith vs Phoenix（选型心智）

| 维度 | LangSmith (Day 106) | Phoenix + OTel (Day 107) |
| :--- | :--- | :--- |
| 部署 | SaaS | Docker 本地 / 私有化 |
| 埋点 | 环境变量即可 | `register` + Instrumentor |
| 数据驻留 | 云端 | 本机 volume |
| 可移植性 | 偏 LangChain 生态 | 任意 OTLP 后端可接 |
| 学习价值 | 最快看见 Trace | 企业私有化必备 |

今日练习会 **显式关闭** `LANGSMITH_TRACING`，避免同一进程双写干扰观察。

---

## 五、过关时你在 Phoenix UI 看什么

1. 打开 http://0.0.0.0:6006 （或 http://127.0.0.1:6006；勿用 localhost）  
2. 进入项目（默认 `freshman-w16-observability`，见 `.env` 的 `PHOENIX_PROJECT_NAME`）  
3. 最新 Trace 应能展开：
   - Agent / Chain 根 Span
   - 子 Span：LLM（含 input/output messages）
   - 子 Span：`lookup_stock` / `calc_quote`（tool 属性）

若只有空项目：检查 compose 是否在跑；确认 `.env` 使用 `0.0.0.0` 而非 `localhost`（后者在 macOS 上常解析到 IPv6 导致 Connection reset）。

---

## 六、参考

- [OpenTelemetry + OpenInference Overview (Phoenix)](https://arize.com/docs/phoenix/tracing/concepts-tracing/otel-openinference/overview)
- [OpenInference Best Practices](https://arize.com/docs/phoenix/cookbook/tracing/openinference-best-practices)
- [Phoenix Docker 端口：6006 HTTP / 4317 gRPC](https://arize.com/docs/phoenix/self-hosting/configuration)
