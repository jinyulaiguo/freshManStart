"""R1：安全过滤路由函数"""
from typing import Literal
from cve_pipeline.state import CVETriageState


def route_after_sanitizer(state: CVETriageState) -> Literal["block_response", "severity_triage"]:
    """R1 安全过滤路由：根据输入净化结果决定下一跳。

    路由逻辑：
      is_input_safe == False  →  "block_response"（安全违规终止）
      is_input_safe == True   →  "severity_triage"（流转分诊）

    Args:
        state: 当前全局 CVETriageState 快照。

    Returns:
        下一跳节点名称字符串，作为 path_map 的查找键。
    """
    return "severity_triage" if state.get("is_input_safe", True) else "block_response"
