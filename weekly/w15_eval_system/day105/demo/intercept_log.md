# Day 105 演示：回归指标降级时拦截 PR

## 复现命令

```bash
# 1) 刷新完美 baseline
uv run python weekly/w15_eval_system/run_eval.py \
  --agent=mock --offline --metrics=gate --limit=20 \
  --scenario=default --save-as-baseline

# 2) 注入漏调 + 幻觉（应 exit 1）
uv run python weekly/w15_eval_system/run_eval.py \
  --agent=mock --offline --metrics=gate --limit=20 \
  --scenario=demo_fail --enforce-gate \
  --baseline weekly/w15_eval_system/reports/eval_baseline.json \
  --out weekly/w15_eval_system/reports/eval_result.json \
  --diff-out weekly/w15_eval_system/reports/regression_diff.md
```

或：`SCENARIO=demo_fail ./weekly/w15_eval_system/day105/start.sh`

## 期望结果

| 项 | 值 |
|----|-----|
| exit code | **1** |
| 降级 Case | `research_002`, `research_005`, `research_008`, `research_011` |
| tool_f1 | 0.80 &lt; 0.85 |
| faithfulness | 0.81 &lt; 0.90 |
| Gate 文案 | `门禁拦截 ... tool_f1=... faithfulness=...` |

## 日志摘录（本地 offline 跑通）

完整输出见同目录 [`intercept_raw.log`](intercept_raw.log)。关键片段：

```text
[FAIL] research_002  f1=0.000  faith=0.05
[FAIL] research_005  f1=0.000  faith=0.05
[FAIL] research_008  f1=0.000  faith=0.05
[FAIL] research_011  f1=0.000  faith=0.05

regressed_ids: ['research_002', 'research_005', 'research_008', 'research_011']

ThresholdGate 裁决  mode=pr  exit_code=1
tool_f1            0.8000       0.85  -0.0500      ❌
faithfulness       0.8100       0.90  -0.0900      ❌

🚫 门禁拦截 (mode=pr)：tool_f1=0.8000<0.85, faithfulness=0.8100<0.9
```

## GitHub Actions

1. Actions → **eval-gate** → **Run workflow**
2. `scenario=demo_fail`，`limit=20`
3. 主 Job 因 Gate 失败为红；`demo-fail-proof` Job 校验 exit 1 后自身标绿
4. Artifact `eval-reports-<run_id>` 含 `eval_result.json` 与 `regression_diff.md`

> 截图：在 Actions 运行页保存 Job 失败与 Artifact 下载界面即可附到作品集。
