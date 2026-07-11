"""
Day 62: 自适应检索路由与 RAG 多路协同决策 (Standard Answer)

设计方案说明：
1. **设计意图**：
   本模块提供了高精度的检索流向路由分类器与虚拟 Pipeline 协同组件。
   前置的意图判定过滤了日常问候等低价值数据库检索，从而优化了 TTFT 首字时延并降低了 API 资费。
2. **类与核心结构**：
   - `MemoryRouter`: 路由器类。
     - `route(query)`: 请求大模型进行 MEM/RAG/NONE 分类。为防范思维链 CoT 干扰，加入了 clean_decision 物理清洗。
     - `execute_pipeline(query, user_id)`: 模拟后端检索行为，量化 Rtt 节省指标。
3. **性能评估模型**：
   - 传统盲检模型：每次都需要执行 MEM (100ms) + RAG (250ms) = 350ms 的开销。
   - 路由分流模型：NONE 降为 0ms，MEM 降为 100ms，RAG 降为 250ms。
"""

import json
import time
import sys
from typing import Dict, Any, List, Optional
from weekly.w04_prompt_and_http.utils import LLMClient

class MemoryRouter:
    """自适应检索流量分配路由器"""

    def __init__(self, client: Optional[LLMClient] = None):
        """初始化路由器。

        Args:
            client: 真实大模型请求客户端。
        """
        self.client = client or LLMClient()

    async def route(self, query: str) -> str:
        """分析用户当前 Query 意图，返回路由决策：MEM, RAG 或 NONE。

        - MEM: 查询涉及个人人设、个人历史偏好或先前事实（如：“我喜欢什么语言？”）。
        - RAG: 查询涉及外部专业知识、Leiden算法、PDF文档细节等（如：“Leiden原理是什么？”）。
        - NONE: 日常寒暄、日常口语或通用常识（如：“你好”、“1+1等于几”）。

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

        # 步骤 2: 调用 LLM 执行意图提取
        response_text = await self.client.request_llm(messages, temperature=0.1)
        
        # 步骤 3: 物理清洗与过滤推理模型的思维链 <think>...</think> 块，仅保留最后真正的分类输出
        clean_decision = response_text.strip().upper()
        if "</THINK>" in clean_decision:
            clean_decision = clean_decision.split("</THINK>")[-1].strip()
            
        # 步骤 4: 移除非法多余字符，防止大模型抽风带上句号
        for char in ".\"'`[]：: \n\t":
            clean_decision = clean_decision.replace(char, "")
            
        # 步骤 5: 降级保护，若输出不符合契约，默认走最安全的 RAG 保证知识召回
        if clean_decision not in {"MEM", "RAG", "NONE"}:
            print(f"⚠️ [MemoryRouter] 大模型输出的路由格式异常: \"{response_text}\"。已降级归入 RAG 分支。", file=sys.stderr)
            return "RAG"
            
        return clean_decision

    async def execute_pipeline(self, query: str, user_id: str) -> Dict[str, Any]:
        """根据路由决策执行具体的虚拟检索流水线，并返回执行耗时（Rtt）。

        Args:
            query: 用户输入的请求提问。
            user_id: 租户标识符。

        Returns:
            包含路由决策 'route'、检索时延 'rtt_ms' 和数据包 'payload' 的结果字典。
        """
        start_time = time.time()
        
        # 调用大模型执行意图路由判定
        route_decision = await self.route(query)
        
        rtt_ms = 0
        payload = {}
        
        # 根据分流分支模拟底层的物理读取行为
        if route_decision == "NONE":
            # 短路路由，直接移交大模型回复，不执行任何 I/O 检索
            rtt_ms = 0
            payload = {"source": "direct_llm", "data": "未检索任何库"}
            
        elif route_decision == "MEM":
            # 模拟执行长期 Facts 语义召回与 I/O 等待
            rtt_ms = 100
            payload = {"source": "qdrant_facts", "user_id": user_id, "data": ["user_prefer_language: Python"]}
            
        elif route_decision == "RAG":
            # 模拟执行外部向量库的相似度召回与 Lost in the middle 重排拼接
            rtt_ms = 250
            payload = {"source": "chroma_pdf_docs", "data": ["GraphRAG uses Leiden community detection to map nodes."]}
            
        return {
            "route": route_decision,
            "rtt_ms": rtt_ms,
            "payload": payload,
            "pipeline_time_ms": int((time.time() - start_time) * 1000)
        }


# 调试主入口与性能评测
async def main() -> None:
    print("=== 运行 Day 62 自适应检索路由与 RAG 多路协同决策标准答案 ===")
    
    router = MemoryRouter()
    
    # 构造包含 20 条样本的黑盒测试集，覆盖三大分支维度
    test_samples = [
        # NONE 闲聊与口语 (6条)
        {"query": "你好呀！", "expected": "NONE"},
        {"query": "今天天气真是不错。", "expected": "NONE"},
        {"query": "哈哈，太搞笑了！", "expected": "NONE"},
        {"query": "一加一等于几？", "expected": "NONE"},
        {"query": "随便聊聊别的吧。", "expected": "NONE"},
        {"query": "再见，祝你有个愉快的一天！", "expected": "NONE"},

        # MEM 个人背景与偏好历史 (6条)
        {"query": "你还记得我常用的编程语言是什么吗？", "expected": "MEM"},
        {"query": "我叫什么名字来着？", "expected": "MEM"},
        {"query": "我刚才说我在哪家公司上班？", "expected": "MEM"},
        {"query": "推荐一个适合我口味的饮料吧，别推荐茶。", "expected": "MEM"},
        {"query": "我的技术级别目前达到哪个阶段了？", "expected": "MEM"},
        {"query": "我比较喜欢喝什么咖啡？", "expected": "MEM"},

        # RAG 专业技术与 PDF 文档情节 (8条)
        {"query": "微软 GraphRAG 框架的核心检索机制是什么？", "expected": "RAG"},
        {"query": "Leiden 社区 MapReduce 模拟算法在图谱中如何应用？", "expected": "RAG"},
        {"query": "知识图谱中实体消歧是如何实现的？", "expected": "RAG"},
        {"query": "小说中谁背叛了李四，并与赵六密谋？", "expected": "RAG"},
        {"query": "HyDE 假设性检索的流程是什么？", "expected": "RAG"},
        {"query": "简述 Rerank 精排对召回准确率的影响。", "expected": "RAG"},
        {"query": "Lost in the Middle 现象如何通过重排机制解决？", "expected": "RAG"},
        {"query": "Qdrant 向量数据库如何实现带有 Filter Payload 的检索？", "expected": "RAG"}
    ]

    correct_count = 0
    total_none_rtt = 0
    total_none_count = 0
    
    # 传统无路由时的盲检索开销 (每次都检索 MEM + RAG = 350ms)
    traditional_total_rtt = len(test_samples) * (100 + 250)
    optimized_total_rtt = 0

    print("\n开始自适应路由分类评测 (20条样本) ...")
    
    for idx, sample in enumerate(test_samples):
        query = sample["query"]
        expected = sample["expected"]
        
        # 运行路由 Pipeline
        result = await router.execute_pipeline(query, user_id="test_user_001")
        actual = result["route"]
        rtt = result["rtt_ms"]
        
        optimized_total_rtt += rtt
        is_correct = (actual == expected)
        
        if is_correct:
            correct_count += 1
            
        if expected == "NONE":
            total_none_rtt += rtt
            total_none_count += 1
            
        print(f"[{idx+1:02d}] Query: \"{query}\"")
        print(f"     -> 预测路由: {actual} | 期望路由: {expected} | 检索开销: {rtt}ms | 状态: {'✅ 正确' if is_correct else '❌ 偏离'}")

    # 计算评估指标
    accuracy = (correct_count / len(test_samples)) * 100
    
    # 时延收益：无路由时每次 350ms，路由后 NONE 分支为 0ms (相比 350ms 降幅 100%)
    none_traditional_rtt = total_none_count * 350
    none_latency_drop_pct = ((none_traditional_rtt - total_none_rtt) / none_traditional_rtt) * 100 if none_traditional_rtt > 0 else 100
    
    total_latency_drop_pct = ((traditional_total_rtt - optimized_total_rtt) / traditional_total_rtt) * 100

    print("\n================ 评测指标结果 ================")
    print(f"1. 路由意图分类准确率: {accuracy:.1f}% (验证通过标准: >= 90.0%)")
    print(f"2. NONE 分支检索耗时 (Rtt) 降幅: {none_latency_drop_pct:.1f}% (验证通过标准: >= 80.0%)")
    print(f"3. 全样本累计检索时延收益: 从 {traditional_total_rtt}ms 降至 {optimized_total_rtt}ms (节省 {total_latency_drop_pct:.1f}%)")
    print("==============================================")
    
    # 验证最终过关标准
    is_passed = (accuracy >= 90.0 and none_latency_drop_pct >= 80.0)
    print(f"🎯 最终过关验证结论: {'✅ 完美通过' if is_passed else '❌ 未达到过关要求'}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
