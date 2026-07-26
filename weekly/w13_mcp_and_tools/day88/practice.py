"""
Day 88 练习模版: 基于真实 LLM 的 5 段式 Docstring 契约 5 阶段 1 对 1 递进实战

设计意图:
    本练习引导学员通过【5 阶段 1 对 1 递进演进实验】，完全理解 5 段式 Docstring 中每一段的作用:
    1. Stage 1 (适用/禁用场景): 验证【禁用场景】拦截模糊 Query 的误触发；
    2. Stage 2 (入参范例): 验证【入参范例】如何引导真实 LLM 纠正非法格式参数；
    3. Stage 3 (返回值契约): 验证【返回值契约】帮助 LLM 提前感知返回结构；
    4. Stage 4 (侧效应 Warning): 验证【侧效应 Warning】触发 LLM 风险提示与二次确认；
    5. Stage 5 (Pydantic 防范): 验证后端正则强行闭环拦截。

主入口测试用例设计意图 (Test Case Design Intent):
    引导学员分 5 个阶段使用 LLMClient 向真实 LLM 发起递进测试并观察拦截日志。
"""

import sys
import json
import asyncio
from pathlib import Path
from typing import Dict, Any

from pydantic import BaseModel, Field, ValidationError

# 确保项目根目录在 PYTHONPATH 中
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# 🔑 复用项目公共基础设施
from weekly.w04_prompt_and_http.utils import LLMClient


# Stage 3/4 完整契约工具
class SpecOptimizedInput(BaseModel):
    cluster_id: str = Field(
        pattern=r"^cls-[a-z0-9\-]+$",
        description="目标 Kubernetes 集群的物理 ID (合法示例: cls-prod-01)"
    )


def stage3_full_spec_tool(cluster_id: str) -> Dict[str, Any]:
    """【适用场景】仅在用户明确下达危险擦除指令，要求清理指定 K8s 集群缓存时调用。
    【禁用场景】若用户仅要求读取配置或未授权，绝对禁止调用！
    【入参范例】合法示例: 'cls-prod-01'。非法示例: 'production'。
    【返回值契约】返回包含 clean_status 和 purged_bytes_gb 的 JSON 结果对象。
    【侧效应 Warning】⚠️ 高危操作：包含物理不可逆的磁盘擦除操作！调用前必须警示风险！"""
    
    try:
        validated = SpecOptimizedInput(cluster_id=cluster_id)
    except ValidationError as err:
        return {"status": "REJECTED_BY_PYDANTIC_DEFENSE", "error": str(err)}

    return {"clean_status": "PURGED_SUCCESS", "target": validated.cluster_id, "purged_bytes_gb": 128.5}


async def run_5stage_progressive_experiment():
    """5 阶段 1 对 1 递进测试主流程"""
    client = LLMClient()
    
    # TODO: 学员需在此实现 5 阶段递进测试:
    # 1. 验证 Stage 1 对模糊 Query 的误调用拦截；
    # 2. 验证 Stage 2 对非规范入参的格式纠正；
    # 3. 验证 Stage 3 对返回值契约的精准解析；
    # 4. 验证 Stage 4 对 Warning 侧效应的二次风险警示；
    # 5. 验证 Stage 5 后端 Pydantic 正则强防御。
    raise NotImplementedError("TODO: 请使用 client.request_llm_with_tools 完成 5 阶段 1对1 演进逻辑")


if __name__ == "__main__":
    try:
        asyncio.run(run_5stage_progressive_experiment())
    except (NotImplementedError, BaseExceptionGroup) as e:
        print("⚠️ 拦截到未实现提示:", e)
        print("请打开 practice.py 完成 TODO 部分的代码实现。")
