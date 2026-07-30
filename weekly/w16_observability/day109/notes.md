# Day 109 课堂笔记：Latency · Token · 美分成本上卷

> **材料约定**：无 `practice.py`；`python costed_graph.py` 自可执行。  
> **硬约束**：真实 MiniMax + Trace 进真实 Phoenix。  
> **收敛**：成本写在 **OTel Span Attribute**，不扩展平行追踪框架。  
> 总纲：[`../overview.html`](../overview.html)

## 运行

```bash
cd weekly/w16_observability/infra && ./start.sh   # 若未启动
cd weekly/w16_observability/day109
python costed_graph.py
pytest tests/ -q
```

验收：
1. 终端打印根 Trace 汇总：`total_latency_ms`、`input_tokens`、`output_tokens`、`cost_usd`、`cost_cents`
2. Phoenix 根 Span / 各 Node Span 可见上述属性；LLM Span 含 `ttft_ms`（流式首字）

---

## 一、为何要上卷

并发图里每个 Node 各自烧 Token。若只在子 Span 记一笔，根 Trace 看不到「这一单总价」，无法做秒级扣费与预算熔断。

| 字段 | 含义 | 写在哪 |
| :--- | :--- | :--- |
| `duration_ms` | 单调时钟耗时 | 每个 Node Span（Day108 已有） |
| `llm.token_count.prompt/completion` | 单次 LLM 账单 | LLM Span |
| `ttft_ms` | 首字延迟 | LLM Span（流式） |
| `cost.input_tokens` / `cost.output_tokens` | 子账单累加 | 根 Trace（上卷） |
| `cost.usd` / `cost.cents` | 估价 | 根 Trace |

价目来自 `.env`：`LLM_PRICE_INPUT_USD_PER_1M` / `LLM_PRICE_OUTPUT_USD_PER_1M`。

\[
\text{cost\_usd} = \frac{in}{10^6}\cdot P_{in} + \frac{out}{10^6}\cdot P_{out}
\]

美分：`cost_cents = round(cost_usd * 100, 4)`（保留小数美分便于小流量演示）。

---

## 二、CostLedger（可观测性追踪类）

`CostLedger`：
- 用 `contextvars` 挂在当前请求
- `threading.Lock` 保证并发 Node 上报不丢账
- `record_node(name, latency_ms, in_tok, out_tok, ttft_ms?)`
- `apply_to_span(root_span)` 写入根 Attribute 并返回汇总 dict

子 Span 仍写自己的 token；**根**写总和——对应课纲「层层上报到主 Trace」。

---

## 三、并发图形态（研究助手形）

```text
pipeline (root)
├── load                 # 真实语料
├── asyncio.gather
│   ├── rag              # 检索
│   └── outline_llm      # 并行真实 LLM（流式 + TTFT）
└── synthesize_llm       # 再一次真实 LLM，综合 outline+chunks
```

两路 LLM 的 Token 都会打进同一 `CostLedger`，根上看到总和。

---

## 四、与 Day 112

Day 112 把 `CostLedger` 挂到研究助手每个 LangGraph Node；价目表与 Attribute 名保持不变即可。
