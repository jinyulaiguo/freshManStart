"""R3：验证结果路由函数（含反馈环路控制）"""
from typing import Literal
from cve_pipeline.state import CVETriageState

# 环路最大重试次数阈值（patch_retry_count >= 此值时触发升舱）
MAX_PATCH_RETRIES: int = 2


def route_after_validation(
    state: CVETriageState,
) -> Literal["compliance_reporter", "code_patch_generator", "human_escalation"]:
    """R3 验证结果路由：控制补丁重试反馈环路与升舱决策。

    路由逻辑（三路决策）：
      PASS                              →  "compliance_reporter"（质量门控通过，签发报告）
      FAIL + patch_retry_count < 2      →  "code_patch_generator"（反馈问题，重试修正）
      FAIL + patch_retry_count >= 2     →  "human_escalation"（重试耗尽，人工介入）

    设计要点：
      patch_retry_count 在 patch_generator_node 中每次调用时递增（调用前为 N，
      调用后为 N+1）。因此当 validator 执行时读到的 patch_retry_count 即为
      "已完成的补丁生成轮次"，用于判断是否达到重试上限。

      recursion_limit=15 作为全局保底机制，防止任何意外情况下的无限环路。
      在正常业务逻辑中，patch_retry_count 的判断已足够阻止超过 2 次的重试。

    Args:
        state: 当前全局 CVETriageState 快照。

    Returns:
        下一跳节点名称字符串，作为 path_map 的查找键。
    """
    verdict = state.get("validation_verdict", "FAIL").upper()
    retry_count = state.get("patch_retry_count", 0)

    if verdict == "PASS":
        return "compliance_reporter"
    elif retry_count < MAX_PATCH_RETRIES:
        # 将 validation_findings 注入 State，patch_generator 下一轮读取后定向修正
        return "code_patch_generator"
    else:
        # 重试次数达到上限，升舱人工处置
        return "human_escalation"
