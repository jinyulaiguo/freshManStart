"""
Day 84 综合实战: Research Agent 评估与日志记录器 (Research Logger)

【设计说明】
负责捕获并物理记录整套 Research Agent 在运行期的多轮博弈与反思轨迹。
包含：Planner 规划图、ReWOO 变量表、Critic 审查得分、Reflexion 反思法则与 NLI 校对结论。
存储为 JSON Lines 结构化日志。
"""

import os
import json
import time
from typing import Dict, Any


class ResearchLogger:
    """结构化追踪日志记录器"""

    def __init__(self, log_path: str = "weekly/w12_planning_and_reflection/day84/research_agent_trace.jsonl"):
        self.log_path = log_path
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

    def log_event(self, event_type: str, payload: Dict[str, Any]):
        """
        写入事件日志
        """
        record = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event_type": event_type,
            "payload": payload
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
