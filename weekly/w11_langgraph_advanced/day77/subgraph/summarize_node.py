"""子图真实 LLM 摘要生成节点 (含 2s 延时验证 Barrier 屏障)

设计方案与架构说明：
----------------------------------------------------------------
本节点负责调用真实大模型 (MiniMax LLM Client) 对数据库返回的结果进行自然语言洞察提炼。
1. 真实 API 调用：使用 `weekly/w04_prompt_and_http/utils.py` 中的 `LLMClient`。
2. 同步屏障验证 (Barrier Verification)：
   - 人为嵌入 `await asyncio.sleep(2.0)` 模拟耗时任务。
   - 证明三路 Fan-out 并行节点中，最快完成的节点会等待此 2s 节点完成后，控制流才解冻走向 merge 节点。

数据流：
--------
Input (execution_result, generated_sql) -> 2s 延时 -> 真实 LLM 摘要 -> 写入 state.summary_text
"""

import os
import sys
import asyncio
from typing import Dict, Any

# 动态将工作区根目录添加到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from weekly.w04_prompt_and_http.utils import LLMClient
from weekly.w11_langgraph_advanced.day77.state.analysis_state import AnalysisSubState

llm_client = LLMClient()


async def summarize_node(state: AnalysisSubState) -> Dict[str, Any]:
    """子图节点：调用真实 LLM 生成数据摘要 (带 2s 延时验证 Barrier)。"""
    sql = state.get("generated_sql", "")
    res = state.get("execution_result", [])

    print(f"\n  [Subgraph Worker: Summarize] 发起真实 LLM API 请求 (人为加 2.0s 延迟以验证 Barrier)...")
    await asyncio.sleep(2.0)  # 人为延迟

    messages = [
        {"role": "system", "content": "你是一位敏锐的数据分析师。请用 1-2 句话对输入的 SQL 查询及其数据结果进行精准提炼。"},
        {"role": "user", "content": f"执行 SQL: `{sql}`\n数据记录: {res[:5]}"}
    ]

    try:
        llm_res = await llm_client.request_llm(messages, temperature=0.3, max_tokens=150)
        summary = llm_res.strip()
        print(f"  [Subgraph Worker: Summarize] 真实 LLM 摘要生成成功: '{summary}'")
    except Exception as e:
        summary = f"执行 SQL ({sql}) 成功返回 {len(res) if res else 0} 条记录。"

    return {
        "summary_text": summary,
        "internal_trace": ["LLM Summarizer completed with 2s intentional latency."]
    }
