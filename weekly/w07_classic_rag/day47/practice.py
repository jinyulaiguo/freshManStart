"""
Day 47 练习：长上下文填充位置对召回率的影响 (Lost in the Middle) 与重排 (Reranking)

设计方案：
本模块演示“迷失中段”现象并实现一个基于 LLM 的相关性打分重排器（LLMReranker），包含：
1. 噪声数据生成：构造 10 个文献片段，将唯一的答案片段埋藏在第 5 位（中段），两端铺满高相似度但无答案的噪声。
2. 迷失中段复现：在未执行重排时，将原始顺序的 Context 直接灌入 LLM，观察其是否发生中段信息遗忘。
3. 动态打分重排：调用 LLMReranker，对每个分块计算与提问的相关性得分，进行降序重排，将答案块推至黄金头部（第 1 位）。
4. 重排生成对比：将重排后的 Context 灌入 LLM，验证其是否能准确提取出答案，对比前后效果。
"""

import asyncio
from typing import List, Dict

# 导入 w04 中的真实大模型客户端
from weekly.w04_prompt_and_http.utils import LLMClient

# 构造 10 个测试片段。只有 doc_005 包含了真正核心的机密研发代号及预算答案。
# 其余片段均大谈特谈公司的研发环境、研发流程，与提问“研发代号与预算”高度语义雷同但无答案。
# 构造 5 个测试片段。只有 doc_003 包含了真正核心的机密研发代号及预算答案。
# 其余片段均大谈特谈公司的研发环境、研发流程，与提问“研发代号与预算”高度语义雷同但无答案。
TEST_CHUNKS = [
    {"doc_id": "doc_001", "content": "公司研发大楼位于科技园 A 栋，配备了先进 of 硬件测试实验室与全天候的中央服务器机房。"},
    {"doc_id": "doc_002", "content": "研发部门的日常运作遵循敏捷开发流程，每周进行迭代规划，每双周向业务端输出可交付的版本更新包。"},
    # 核心答案块：故意埋藏在中段（第 3 位）
    {"doc_id": "doc_003", "content": "【核心机密】公司本年度的核心科研项目的研发代号正式确定为“Project Vulcan”，项目研发预算总额为 5000 万人民币。"},
    {"doc_id": "doc_004", "content": "研发大楼一楼大厅配备了专职安保人员，员工必须刷工作证卡片方可进入电梯，访客必须提前在系统报备审批。"},
    {"doc_id": "doc_005", "content": "研发部门定期在每季度末举行全员技术沙龙分享会，邀请业内顶尖技术专家来公司分享前沿分布式系统架构。"}
]


class LLMReranker:
    """基于大模型语义相关性打分机制的重排器"""
    
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def _score_chunk(self, query: str, chunk_content: str) -> float:
        """
        对单条文献块计算与用户提问的语义相关性分数 (0.0 - 100.0)
        
        Args:
            query (str): 用户查询
            chunk_content (str): 文献片段内容
            
        Returns:
            float: 相关性打分
        """
        # TODO: 步骤 1：设计打分 Prompt，强迫大模型只输出一个 0 到 100 之间的纯数字，
        #       评估 chunk_content 与 query 的直接相关度。
        # TODO: 步骤 2：调用 LLM 获取响应，使用 try-except 和正则强制转换为 float 格式，
        #       若发生格式异常则兜底返回 0.0。
        raise NotImplementedError("TODO: 请在此处实现单 Chunk 相关性打分逻辑")

    async def rerank(self, query: str, chunks: List[Dict]) -> List[Dict]:
        """
        对文献列表执行并发相关性打分并降序重排
        
        Args:
            query (str): 用户查询
            chunks (List[Dict]): 原始文献列表
            
        Returns:
            List[Dict]: 重排后的文献列表（按得分从大到小排序，且附带得分字段）
        """
        # TODO: 步骤 3：利用 asyncio.gather 并发计算所有 chunk 的得分
        # TODO: 步骤 4：将得分绑定在 chunk 上，并执行 sorted 降序排列返回
        raise NotImplementedError("TODO: 请在此处实现并发打分与重排排序")


class RAGPipeline:
    """对比演示“迷失中段”与“Rerank 优化”的 RAG 管道"""
    
    def __init__(self):
        self.llm_client = LLMClient()
        self.reranker = LLMReranker(self.llm_client)

    async def answer_without_rerank(self, query: str, chunks: List[Dict]) -> str:
        """
        不进行重排，直接以原始顺序（答案埋在中段）拼接 Context 驱动 LLM 问答
        """
        # 拼装上下文
        context = "\n".join([f"【文献-{idx+1}】: {c['content']}" for idx, c in enumerate(chunks)])
        
        system_prompt = (
            "你是一个合规问答助手。你的任务是根据提供的背景文献回答问题。无法推导时请直接说不知道。\n"
            f"背景文献事实:\n{context}"
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
        # 调用大模型 (低温度)
        return await self.llm_client.request_llm(messages, temperature=0.01)

    async def answer_with_rerank(self, query: str, chunks: List[Dict]) -> Tuple[str, List[Dict]]:
        """
        先调用 Reranker 对 Context 重新排序，将最相关的块置于头部再调用 LLM 问答
        """
        # TODO: 步骤 5：调用 self.reranker.rerank 对原始 chunks 执行排序
        # TODO: 步骤 6：利用重排后的列表拼装 Context 发送给大模型进行可信解答
        # TODO: 步骤 7：返回一个元组：(大模型答案, 重排后的 Chunks 列表)
        raise NotImplementedError("TODO: 请在此处实现重排问答编排")


if __name__ == "__main__":
    from typing import Tuple
    
    async def main():
        print("=== Day 47 迷失中段 (Lost in the Middle) 与重排演示 调试入口 ===")
        pipeline = RAGPipeline()
        query = "请问公司本年度的核心科研项目研发代号是什么？研发预算是多少？"
        
        try:
            # 1. 模拟未重排生成（答案在第 5 位中段，容易遗忘）
            print("\n❌ [执行未重排 RAG 测试] ...")
            ans_raw = await pipeline.answer_without_rerank(query, TEST_CHUNKS)
            print(f"未重排时 LLM 输出结果：\n{ans_raw}")
            
            # 2. 模拟重排后生成（相关块被推至第 1 位）
            print("\n🚀 [执行重排后 RAG 测试] ...")
            ans_rerank, reranked_chunks = await pipeline.answer_with_rerank(query, TEST_CHUNKS)
            print(f"重排后 LLM 输出结果：\n{ans_rerank}")
            
            print("\n[重排后前 3 位文献分布]：")
            for idx, c in enumerate(reranked_chunks[:3]):
                print(f"  排名 [{idx+1}] [{c['doc_id']}] 得分: {c.get('score', 0.0)}")
                print(f"    内容: {c['content']}")
                
        except NotImplementedError as e:
            print(f"\n[提示] 核心逻辑未实现: {e}")

    asyncio.run(main())
