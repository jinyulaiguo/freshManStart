# Day 108 课堂笔记：Trace / Span / Event 嵌套拓扑（真实 OTel → Phoenix）

> **材料约定**：只维护 `notes.md`；无 `practice.py`；模块自带 `__main__`。  
> **硬约束**：真实语料、真实 MiniMax、Trace 推到真实 Phoenix。  
> 总纲：[`../overview.html`](../overview.html)

## 运行

```bash
# Phoenix 需已启动
cd weekly/w16_observability/infra && ./start.sh

cd weekly/w16_observability/day108
python research_pipeline.py
pytest tests/ -q
```

验收：Phoenix（`http://0.0.0.0:6006`）中出现  
`pipeline → load / rag(rerank) / llm / local_compute`，且 `llm` Span 含真实 input/output 文本。

---

## 一、概念

| 概念 | 含义 | 本课落点 |
| :--- | :--- | :--- |
| Trace | 一次端到端请求 | `research_pipeline.run_pipeline` 整次运行 |
| Span | 可嵌套计时单元 | `otel_nesting.span` / `aspan` / `@traced` |
| Event | Span 内瞬时标记 | `add_event("corpus_loaded")` 等 |

嵌套的意义：用各 Span 的 `duration_ms` 看出 RAG vs LLM 谁更慢，而不是只看总耗时。

---

## 二、为何不用平行 SpanTracer 运行时

课纲要求「手写装饰器/上下文管理器」。正确做法是：**手写薄包装，底下仍是 OTel**（`otel_nesting.py`），这样：

1. 满足手写 API 教学  
2. 数据进入真实 Phoenix（Day 107 已绑定）  
3. 避免 Day 112 双栈

已删除 sleep 假流水线与 `practice.py`。

---

## 三、真实四阶段

1. **load**：读取 `corpus/papers.json`  
2. **rag**：词项重叠检索 + `rerank` 子 Span（真实文本，非随机 mock sleep）  
3. **llm**：MiniMax 真实调用，写入 `llm.input_messages` / `llm.output_messages`  
4. **local_compute**：本地结构化报告  

---

## 四、与 Day 112

包装类即 `otel_nesting.py`；流水线形状对齐研究助手 Node。Day 109 起在同一套 OTel Span 上叠加 Token/美分。
