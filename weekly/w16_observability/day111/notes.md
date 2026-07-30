# Day 111 课堂笔记：Prometheus 指标上报（QPS / 活跃并发 / 延迟分布）

> **材料约定**：无 `practice.py`；`python metrics_graph.py` 自可执行。  
> **硬约束**：真实链路 + 真实 `/metrics` 抓取验证。

## 运行

```bash
cd weekly/w16_observability/infra && ./start.sh   # 若未启动
cd weekly/w16_observability/day111
python metrics_graph.py --serve-seconds 180
# 或长期观察：python metrics_graph.py --serve-forever
pytest tests/ -q
```

验收：
1. 本机开放 `/metrics`（默认 `0.0.0.0:9108`）
2. 1 次真实链路 + 100 次高频模拟后，指标有非零分布
3. 终端能抓到并打印 `agent_requests_total` / `agent_active_coroutines` / `agent_request_latency_seconds_bucket`

---

## 一、三类指标与职责

| 指标 | 类型 | 作用 |
| :--- | :--- | :--- |
| `agent_requests_total` | Counter | 总请求量（含 success/error 标签） |
| `agent_active_coroutines` | Gauge | 当前活跃协程数（瞬时并发） |
| `agent_request_latency_seconds` | Histogram | 请求时延分布（供 p95/p99 与告警） |

---

## 二、实现要点

1. `prometheus_client.start_http_server(port)` 暴露 `/metrics`  
2. 每次请求：
   - 进入时 `Gauge.inc()`
   - 结束时 `Gauge.dec()`
   - `Histogram.observe(duration)`
   - `Counter.labels(status=...).inc()`
3. 先跑 1 次真实链路，再用 `asyncio.Semaphore` + 100 次轻量并发任务做高频模拟（控制成本）
4. 运行后主动 `GET /metrics` 打印关键行，确认 Prometheus 能抓到

---

## 三、与 Day 112

Day 112 直接复用这套 `MetricsTracker`：把请求入口替换为研究助手真实图即可。


> 提示：Prometheus 抓取是周期性的（默认 5s），脚本若立即退出会导致 target=DOWN。
> 因此 Day111 默认会在模拟后继续暴露 /metrics 一段时间。
