# Day 110 课堂笔记：异常 Traceback 与结构化日志（Span ERROR）

> **材料约定**：无 `practice.py`；`python fault_tolerant_graph.py` 自可执行。  
> **硬约束**：真实 MiniMax + Trace 进 Phoenix；故意触发真实工具异常并在 Span 标红。

## 运行

```bash
cd weekly/w16_observability/infra && ./start.sh   # 若未启动
cd weekly/w16_observability/day110
python fault_tolerant_graph.py
pytest tests/ -q
```

验收：
1. 终端输出一条结构化 JSON 错误日志（含 traceback、文件/行号、脱敏 locals）
2. `day110/logs/error_latest.json` 落盘
3. Phoenix 中 `tool_divide` Span 为 ERROR（红色）

---

## 一、为什么异常可观测要单独做

只打印 `Error` 字符串，线上几乎无法复盘：
- 不知道在哪个节点崩
- 不知道调用栈路径
- 不知道关键上下文变量（但全量 locals 又有泄密风险）

Day 110 的目标就是：

- `span.record_exception(e)` + `Status(ERROR)`
- traceback 结构化 JSON
- **白名单脱敏**局部变量

---

## 二、实现要点

1. `ExceptionObserver.capture(...)`：
   - 抽取异常类型、消息
   - 遍历 traceback 帧：文件、函数、行号
   - 仅保留白名单 locals（并长度截断）
2. `ExceptionObserver.record_to_span(...)`：
   - 写 `error.type`、`error.message` Attribute
   - 加 `exception.structured` Event
3. `ExceptionObserver.emit_json(...)`：
   - 标准输出打印 JSON
   - 落盘 `logs/error_latest.json`

---

## 三、与 OTel 规范对齐

- 失败时 Span 状态应设为 `ERROR`
- 异常应记录为 span event（`record_exception`）
- 异常描述不应携带敏感信息

本课 `tool_divide` 用 `ZeroDivisionError` 触发真实失败，演示完整闭环。

---

## 四、与 Day 112

Day 112 将 `ExceptionObserver` 复用到研究助手真实 Tool 节点，统一错误 JSON 契约与脱敏策略。
