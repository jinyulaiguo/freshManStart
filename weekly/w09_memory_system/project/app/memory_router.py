"""
Memory Router Module.

设计方案说明：
1. **设计意图**：
   本模块实现了一个自适应检索意图路由（Memory Router），对进入 Agent 系统的每个 Query 进行前置分析。
   将流量分流至：`MEM`（长期个性化偏好）、`RAG`（大文档客观知识）或 `NONE`（直接大模型回复，不执行任何检索）。
   这种自适应路由设计避免了全局无差别向量检索对系统时延（TTFT）造成的累加开销，并有效降低了 API 消耗。
2. **类与核心结构**：
   - `MemoryRouter`: 流量分配路由器。
     - `route(query)`: 请求大模型进行三分类，并应用 clean_decision 物理清洗。
3. **安全防错设计**：
   - 内置 clean_decision 推理过程清洗，能物理截断各种新模型生成的 `<think>...</think>` 思维链。
   - 过滤任何中文或英文标点符号。
   - 降级保护：大模型格式失控时默认归为 "RAG" 分支以确保召回安全性。
"""

import sys
import os
from typing import Optional

# 动态确保 sys.path 正确导入 config
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from config import get_llm_client
from weekly.w04_prompt_and_http.utils import LLMClient

class MemoryRouter:
    """自适应检索流量分配路由器"""

    def __init__(self, client: Optional[LLMClient] = None):
        """初始化路由器。

        Args:
            client: 真实大模型请求客户端，若未传入则默认使用全局 Client 单例。
        """
        # 使用传入的 client，或者通过 config 获取全局统一的客户端
        self.client = client or get_llm_client()

    async def route(self, query: str) -> str:
        """分析用户当前 Query 意图，返回路由决策：MEM, RAG 或 NONE。

        - MEM: 查询涉及个人人设、个人历史偏好或先前事实（如：“我常用什么编程语言？”）。
        - RAG: 查询涉及外部客观专业知识、特定算法原理、大作业文档细节等（如：“微软GraphRAG框架原理是什么？”）。
        - NONE: 日常寒暄问候、通用的常识数学问答、或不需要任何检索上下文就能直接回复的问题（如：“你好”、“1+1等于几”）。

        Args:
            query: 用户输入的请求提问。

        Returns:
            决策路由值：'MEM' | 'RAG' | 'NONE' 之一。
        """
        # 步骤 1: 构造强约束的分类系统 Prompt，规范大模型直接输出单一的决策关键字
        system_prompt = (
            "你是一个高精度的检索路由分类器。\n"
            "分析用户提问，判定其是否需要访问【长期记忆库（MEM）】或【外部专业知识库（RAG）】。\n\n"
            "分类规范：\n"
            "1. MEM : 如果提问涉及用户的个人背景、姓名、职业、个人技术偏好、历史提及的设定等（例如：“我常用什么语言？”、“我是做什么的？”）。\n"
            "2. RAG : 如果提问涉及客观的专业技术概念、特定算法原理、PDF大文档细节、小说剧情事实推理等（例如：“微软GraphRAG框架原理是什么？”、“谁背叛了李四并与赵六密谋？”）。\n"
            "3. NONE : 如果提问属于日常寒暄问候、通用的常识数学问答、或不需要任何上下文就能直接回答的问题（例如：“你好”、“今天天气真好”、“1+1等于几”）。\n\n"
            "必须输出且仅输出 'MEM', 'RAG' 或 'NONE' 之一，禁止包含任何标点符号或Markdown解释。"
        )
        
        user_prompt = f"请对以下 Query 进行路由分类：\nQuery: {query}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            # 步骤 2: 调用 LLM 执行意图提取，使用较低温度以确保分类稳定性
            response_text = await self.client.request_llm(messages, temperature=0.1)
            
            # 步骤 3: 物理清洗与过滤推理模型的思维链 <think>...</think> 块，仅保留最后真正的分类输出
            clean_decision = response_text.strip().upper()
            if "</THINK>" in clean_decision:
                clean_decision = clean_decision.split("</THINK>")[-1].strip()
                
            # 步骤 4: 移除非法多余字符，防止大模型抽风带上标点
            for char in ".\"'`[]：: \n\t。，":
                clean_decision = clean_decision.replace(char, "")
                
            # 步骤 5: 降级保护，若输出不符合契约，默认走最安全的 RAG 保证知识召回
            if clean_decision not in {"MEM", "RAG", "NONE"}:
                print(f"⚠️ [MemoryRouter] 大模型输出的路由格式异常: \"{response_text}\"。已降级归入 RAG 分支。", file=sys.stderr)
                return "RAG"
                
            return clean_decision
        except Exception as e:
            print(f"⚠️ [MemoryRouter] 调用大模型分流异常: {e}。已降级归入 RAG 分支。", file=sys.stderr)
            return "RAG"
