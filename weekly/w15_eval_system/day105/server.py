"""
Week 15 Day 105: Eval Dashboard FastAPI + WebSocket 服务

页面交互触发真实评测流水线（默认走真实 LLM Judge；可选 live ResearchAgent）。
默认全量 50 Case + 并发 8；后台对每次 LLM/Trace/Gate 打 INFO 日志。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
W15_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
REPO_ROOT = os.path.abspath(os.path.join(W15_ROOT, "../.."))
W04_PATH = os.path.abspath(os.path.join(W15_ROOT, "../w04_prompt_and_http"))
EVALUATORS_DIR = os.path.join(W15_ROOT, "evaluators")
GATE_DIR = os.path.join(W15_ROOT, "gate")
REPORTER_DIR = os.path.join(W15_ROOT, "reporter")

for p in (REPO_ROOT, W04_PATH, W15_ROOT, EVALUATORS_DIR, GATE_DIR, REPORTER_DIR, CURRENT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from contracts.schemas import EvalRunReport, load_golden_dataset  # noqa: E402
from run_eval import (  # noqa: E402
    DEFAULT_BASELINE,
    DEFAULT_DATASET,
    DEFAULT_DIFF,
    DEFAULT_OUT,
    EvalPipeline,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)
logger = logging.getLogger("day105.eval")

DASHBOARD_DIR = Path(CURRENT_DIR) / "dashboard"
REPORTS_DIR = Path(W15_ROOT) / "reports"

DEFAULT_LIMIT = 0  # 0 = 全量
DEFAULT_CONCURRENCY = 8

app = FastAPI(
    title="Day 105 Eval Dashboard",
    description="AI 研究助手 QA 自动化评测流水线 · 交互触发真实 LLM Judge",
)

app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")

_run_lock = asyncio.Lock()
_latest_report: dict[str, Any] | None = None
_latest_diff_md: str | None = None
_latest_gate: dict[str, Any] | None = None


@app.on_event("startup")
async def _on_startup() -> None:
    logger.info(
        "Eval Dashboard 就绪 | dataset=%s | has_api_key=%s | model=%s | "
        "default_limit=%s(0=全量) concurrency=%s",
        DEFAULT_DATASET,
        bool(os.getenv("MINIMAX_API_KEY")),
        os.getenv("MINIMAX_MODEL"),
        DEFAULT_LIMIT,
        DEFAULT_CONCURRENCY,
    )


@app.get("/")
async def index():
    return FileResponse(DASHBOARD_DIR / "index.html")


@app.get("/api/health")
async def health():
    has_key = bool(os.getenv("MINIMAX_API_KEY"))
    dataset_ok = DEFAULT_DATASET.exists()
    n_cases = 0
    if dataset_ok:
        try:
            n_cases = len(load_golden_dataset(DEFAULT_DATASET))
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {"ok": False, "error": str(exc), "has_api_key": has_key},
                status_code=500,
            )
    return {
        "ok": True,
        "has_api_key": has_key,
        "dataset_path": str(DEFAULT_DATASET),
        "dataset_cases": n_cases,
        "default_limit": DEFAULT_LIMIT,
        "default_concurrency": DEFAULT_CONCURRENCY,
        "judge_model": os.getenv("MINIMAX_MODEL"),
        "baseline_exists": DEFAULT_BASELINE.exists(),
    }


@app.get("/api/report/latest")
async def latest_report():
    if _latest_report is None and DEFAULT_OUT.exists():
        report = EvalRunReport.load_json(DEFAULT_OUT)
        return JSONResponse(json.loads(report.model_dump_json()))
    if _latest_report is None:
        return JSONResponse({"error": "尚无评测报告"}, status_code=404)
    return JSONResponse(_latest_report)


@app.get("/api/diff/latest")
async def latest_diff():
    global _latest_diff_md
    if _latest_diff_md:
        return JSONResponse({"markdown": _latest_diff_md})
    if DEFAULT_DIFF.exists():
        return JSONResponse({"markdown": DEFAULT_DIFF.read_text(encoding="utf-8")})
    return JSONResponse({"error": "尚无回归 Diff"}, status_code=404)


def _log_event(event_type: str, data: dict) -> None:
    compact = {
        k: data[k]
        for k in (
            "phase",
            "message",
            "test_case_id",
            "index",
            "total",
            "metric",
            "agent",
            "passed",
            "tool_f1",
            "faithfulness",
            "score",
            "exit_code",
            "tool_count",
        )
        if k in data
    }
    logger.info("[event:%s] %s", event_type, compact or data)


async def _ws_send(ws: WebSocket, event_type: str, data: dict) -> None:
    _log_event(event_type, data)
    try:
        await ws.send_json({"type": event_type, "data": data})
    except Exception as exc:  # noqa: BLE001
        logger.warning("WebSocket 发送失败 type=%s err=%s", event_type, exc)


@app.websocket("/ws/eval")
async def ws_eval(websocket: WebSocket):
    """
    客户端发送 run_eval；limit=0 表示全量 50 Case；concurrency 默认 8。
    """
    await websocket.accept()
    logger.info("WebSocket 已连接 /ws/eval")
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await _ws_send(websocket, "error", {"message": "无效 JSON"})
                continue

            action = payload.get("action")
            if action != "run_eval":
                await _ws_send(
                    websocket,
                    "error",
                    {"message": f"未知 action: {action}"},
                )
                continue

            if _run_lock.locked():
                await _ws_send(
                    websocket,
                    "error",
                    {"message": "已有评测在运行，请等待完成"},
                )
                continue

            async with _run_lock:
                await _run_eval_session(websocket, payload)

    except WebSocketDisconnect:
        logger.info("WebSocket 断开 /ws/eval")
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("WebSocket 异常")
        await _ws_send(websocket, "error", {"message": f"WebSocket 异常: {exc}"})


async def _run_eval_session(websocket: WebSocket, payload: dict) -> None:
    global _latest_report, _latest_diff_md, _latest_gate

    agent = payload.get("agent", "live")
    metrics = payload.get("metrics", "gate")
    raw_limit = payload.get("limit", DEFAULT_LIMIT)
    limit = int(raw_limit) if raw_limit is not None else DEFAULT_LIMIT
    scenario = payload.get("scenario", "default")
    offline = bool(payload.get("offline", False))
    concurrency = int(payload.get("concurrency") or DEFAULT_CONCURRENCY)
    concurrency = max(1, min(concurrency, 32))
    enforce_gate = bool(payload.get("enforce_gate", True))
    compare_baseline = bool(payload.get("compare_baseline", True))
    save_as_baseline = bool(payload.get("save_as_baseline", False))
    geval_samples = int(payload.get("geval_samples") or 1)

    logger.info(
        "收到 run_eval | agent=%s metrics=%s limit=%s(0=全量) concurrency=%s "
        "scenario=%s offline=%s enforce_gate=%s",
        agent,
        metrics,
        limit,
        concurrency,
        scenario,
        offline,
        enforce_gate,
    )

    if agent not in ("live", "mock"):
        await _ws_send(websocket, "error", {"message": "agent 必须是 live|mock"})
        return
    if metrics not in ("gate", "full", "tool"):
        await _ws_send(websocket, "error", {"message": "metrics 无效"})
        return
    if scenario not in ("default", "demo_fail"):
        await _ws_send(websocket, "error", {"message": "scenario 无效"})
        return

    if not offline and not os.getenv("MINIMAX_API_KEY"):
        await _ws_send(
            websocket,
            "error",
            {
                "message": (
                    "未检测到 MINIMAX_API_KEY。请在环境中配置后重启 start.sh；"
                    "或勾选 Offline（仅调试，不会调用真实 LLM）。"
                ),
            },
        )
        return

    if not DEFAULT_DATASET.exists():
        await _ws_send(
            websocket,
            "error",
            {"message": f"Golden Dataset 不存在: {DEFAULT_DATASET}"},
        )
        return

    cases = load_golden_dataset(DEFAULT_DATASET)
    total_available = len(cases)
    if limit > 0:
        cases = cases[:limit]
    logger.info(
        "加载 Golden | available=%s | running=%s | concurrency=%s",
        total_available,
        len(cases),
        concurrency,
    )

    await _ws_send(
        websocket,
        "status",
        {
            "phase": "start",
            "message": (
                f"开始评测：agent={agent}, metrics={metrics}, offline={offline}, "
                f"cases={len(cases)}/{total_available}, concurrency={concurrency}, "
                f"scenario={scenario}"
            ),
            "config": {
                "agent": agent,
                "metrics": metrics,
                "offline": offline,
                "limit": len(cases),
                "dataset_total": total_available,
                "scenario": scenario,
                "concurrency": concurrency,
            },
        },
    )

    async def on_event(event_type: str, data: dict) -> None:
        await _ws_send(websocket, event_type, data)

    pipeline = EvalPipeline(
        agent_mode=agent,  # type: ignore[arg-type]
        scenario=scenario,  # type: ignore[arg-type]
        metrics=metrics,  # type: ignore[arg-type]
        concurrency=concurrency,
        offline=offline,
        geval_samples=geval_samples,
        on_event=on_event,
    )

    try:
        report = await pipeline.run(
            cases,
            run_id=(
                f"ui-{agent}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            ),
            dataset_path=str(DEFAULT_DATASET),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("评测执行失败")
        await _ws_send(
            websocket,
            "error",
            {"message": f"评测执行失败: {exc}"},
        )
        await _ws_send(websocket, "complete", {"exit_code": 2})
        return

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report.save_json(DEFAULT_OUT)
    _latest_report = json.loads(report.model_dump_json())
    logger.info(
        "评测完成 | run_id=%s | aggregate=%s | out=%s",
        report.run_id,
        report.aggregate,
        DEFAULT_OUT,
    )

    if save_as_baseline:
        report.save_json(DEFAULT_BASELINE)
        await _ws_send(
            websocket,
            "status",
            {"phase": "baseline", "message": f"已写入 baseline: {DEFAULT_BASELINE}"},
        )

    if compare_baseline and DEFAULT_BASELINE.exists():
        await _ws_send(
            websocket,
            "status",
            {"phase": "diff", "message": "生成回归 Diff…"},
        )
        baseline = EvalRunReport.load_json(DEFAULT_BASELINE)
        reg = pipeline.reporter.compare(baseline, report)
        diff_md = pipeline.reporter.render_markdown(reg)
        DEFAULT_DIFF.write_text(diff_md, encoding="utf-8")
        _latest_diff_md = diff_md
        logger.info("回归 Diff | regressed=%s", reg.regressed_ids)
        await _ws_send(
            websocket,
            "diff",
            {
                "markdown": diff_md,
                "regressed_ids": reg.regressed_ids,
                "improved_ids": reg.improved_ids,
            },
        )
    elif compare_baseline:
        await _ws_send(
            websocket,
            "status",
            {
                "phase": "diff",
                "message": "无 baseline，跳过 Diff（可勾选「保存为 Baseline」后再跑）",
            },
        )

    gate_payload: dict[str, Any]
    exit_code = 0
    if enforce_gate:
        await _ws_send(
            websocket,
            "status",
            {"phase": "gating", "message": "ThresholdGate 裁决中…"},
        )
        verdict = pipeline.gate.check(
            report,
            mode="full" if len(cases) >= total_available else "pr",
        )
        gate_payload = json.loads(verdict.model_dump_json())
        exit_code = 0 if verdict.passed else 1
        _latest_gate = gate_payload
        logger.info("Gate | passed=%s | %s", verdict.passed, verdict.message)
        await _ws_send(websocket, "gate", gate_payload)
    else:
        gate_payload = {"passed": True, "message": "未启用门禁", "checks": []}
        await _ws_send(websocket, "gate", gate_payload)

    await _ws_send(
        websocket,
        "report",
        {
            "report": _latest_report,
            "aggregate": report.aggregate,
            "out_path": str(DEFAULT_OUT),
        },
    )
    await _ws_send(
        websocket,
        "complete",
        {
            "exit_code": exit_code,
            "message": "评测完成",
            "gate_passed": gate_payload.get("passed"),
        },
    )
