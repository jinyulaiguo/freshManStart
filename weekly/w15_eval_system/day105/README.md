# Day 105：AI 研究助手 QA 自动化评测流水线

为 W14 Research Agent 拼装 Week 15 全链路评测，并通过 **Dashboard 交互触发真实 LLM Judge**。

## 启动（推荐）

```bash
./weekly/w15_eval_system/day105/start.sh
# → http://localhost:8105
```

1. 浏览器打开 Dashboard  
2. 确认右上角 `API Key OK`  
3. 默认 **全量 50 Case + 并发 8**（limit=0）；可在页面改 concurrency  
4. **不要勾 Offline**（默认走真实 MiniMax Judge）  
5. 点击「运行评测」—— WebSocket 推送 Trace / Judge / Gate / Diff；**终端同步打印调用日志**  

`demo_fail` 场景可演示阈值拦截（exit 语义在 Gate 面板显示 FAIL）。

## CLI（CI / 脚本）

```bash
# 真实 Judge（需 MINIMAX_*）
uv run python weekly/w15_eval_system/run_eval.py \
  --agent=mock --metrics=gate --limit=3 --enforce-gate

# live ResearchAgent + 真实 Judge
uv run python weekly/w15_eval_system/run_eval.py \
  --agent=live --metrics=gate --limit=2 --concurrency=1

# 仅单测用离线启发式
uv run python weekly/w15_eval_system/run_eval.py \
  --agent=mock --offline --metrics=gate --limit=5 --enforce-gate
```

## 交付件

| 路径 | 说明 |
|------|------|
| [`server.py`](server.py) | FastAPI + `/ws/eval` |
| [`dashboard/index.html`](dashboard/index.html) | 交互控制台 |
| [`start.sh`](start.sh) | uvicorn 启动 |
| [`../run_eval.py`](../run_eval.py) | 主编排（支持 `on_event` 进度回调） |
| [`golden_dataset.jsonl`](golden_dataset.jsonl) | 50 条黄金集 |
| [`.github/workflows/eval.yml`](../../../.github/workflows/eval.yml) | CI 门禁 |

## 门禁阈值

| 指标 | 阈值 |
|------|------|
| `tool_f1` | ≥ 0.85 |
| `faithfulness` | ≥ 0.90 |

## 单元测试

```bash
uv run pytest weekly/w15_eval_system/day105/tests -q
```
