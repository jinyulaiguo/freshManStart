"""
Day 46 练习：基于 Context 来源的可信引用 (Source Citation) 与脚注机制

设计方案：
本模块实现一个带脚注引用的 RAG 可信问答与解析器（CitationRAGPipeline），包括：
1. 可信标引指令：设计严密的 Prompt，强制要求 LLM 在结论句末尾以 [doc_id:page] 格式标引。
2. 脚注正则抓取：使用 Python 正则表达式从 LLM 的响应文本中提取出所有声明的脚注对，并执行去重。
3. 原始文献对照映射：在终端高亮还原每个脚注背后的原始文件名称、页码及段落内容。

数据流向：
用户提问 -> 拼装背景文献与 doc_id 元数据 -> LLM 基于约束生成包含 [doc_id:page] 标记的答案 ->
  - Python 侧正则过滤提取元数据键对
  - 对比事实库，抽取原始文献关联信息
  - 输出美化的解答文本与底层可溯源文献对照表。
"""

import re
from typing import List, Dict, Tuple

# 导入 w04 中的真实大模型客户端
from weekly.w04_prompt_and_http.utils import LLMClient

# 模拟背景文献事实库，每个事实附带唯一的 doc_id、源文件名及页码
TEST_FACTS = [
    {
        "doc_id": "doc_001",
        "source_file": "employee_handbook.pdf",
        "page": 5,
        "content": "公司正式员工享有每年 15 天的带薪年假，且年假不接受跨年累积，当年未休完即自动作废。"
    },
    {
        "doc_id": "doc_002",
        "source_file": "travel_policy.pdf",
        "page": 8,
        "content": "差旅报销规定：单次出差的住宿费上限为每天 500 元人民币，超出部分需由员工个人自理。"
    },
    {
        "doc_id": "doc_003",
        "source_file": "overtime_rules.pdf",
        "page": 14,
        "content": "加班补偿规定：周末加班可选择 2 倍工资补偿，或申请 1:1 的等时长调休假，调休需在 3 个月内休完。"
    }
]


class CitationRAGPipeline:
    """具备可信引用脚注生成与解析的 RAG 控制管道"""
    
    def __init__(self):
        self.llm_client = LLMClient()
        # 将测试事实库缓存为以 doc_id 为键的映射，便于高效 O(1) 检索映射
        self.facts_db: Dict[str, dict] = {f["doc_id"]: f for f in TEST_FACTS}

    def parse_citations(self, response_text: str) -> List[Tuple[str, int]]:
        """
        利用正则表达式从文本中提取出所有形如 [doc_xxx:page_num] 的脚注对并执行去重
        
        Args:
            response_text (str): 大模型生成的包含引用标记的响应文本
            
        Returns:
            List[Tuple[str, int]]: 提取出去重后的 (doc_id, page_number) 元组列表
        """
        # TODO: 步骤 1：手写正则表达式匹配 [doc_xxx:page]（注意方括号需要转义）
        # TODO: 步骤 2：使用 re.findall 扫描 response_text 获得所有匹配对
        # TODO: 步骤 3：进行去重（保留首次出现的顺序），并转换 page 为 int 类型返回
        raise NotImplementedError("TODO: 请在此处实现脚注正则过滤提取逻辑")

    async def answer_with_citation(self, query: str) -> Tuple[str, List[dict]]:
        """
        强制标引生成与引用对照解析的主逻辑
        
        Args:
            query (str): 用户查询提问
            
        Returns:
            Tuple[str, List[dict]]: 返回一个元组，包括：
              - 原始生成的答案文本
              - 被引用的原始文献结构体列表（富集了文件名、页码、文献内容等元数据）
        """
        # 1. 拼装 Context 段落，将 doc_id 和 page 显式绑定在文本首部
        context_parts = []
        for fid, f in self.facts_db.items():
            context_parts.append(
                f"【ID: {f['doc_id']}, 来源: {f['source_file']}, 页码: {f['page']}】: {f['content']}"
            )
        context_str = "\n".join(context_parts)
        
        # 2. 构造标引 System Prompt 契约指令
        # TODO: 步骤 4：设计 System 提示词，严厉约束 LLM 在回答中针对每一个所参考的事实，
        #       必须且只能在结论句末尾紧跟标记：`[doc_id:page_number]` (例如: `[doc_001:5]`)。
        system_prompt = (
            "你是一个严谨的合规审查助手。\n"
            "TODO: 请在此处编写强约束提示词，指引 LLM 输出标准标引标记\n"
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
        
        # 3. 调用大模型（设定低温度确保稳定输出标引）
        # response_text = await self.llm_client.request_llm(messages, temperature=0.01)
        
        # 4. 正则解析提取所有引用对
        # citation_pairs = self.parse_citations(response_text)
        
        # 5. 根据提取到的 (doc_id, page) 从 self.facts_db 中抓取对应的原始数据富集返回
        # TODO: 步骤 5：构建被引用原始文献的对照列表返回
        
        raise NotImplementedError("TODO: 请在此处实现引用标引问答与文献对照映射")


if __name__ == "__main__":
    import asyncio
    
    async def main():
        print("=== Day 46 基于 Context 来源的可信引用调试入口 ===")
        pipeline = CitationRAGPipeline()
        
        query = "请问公司年假有多少天？周末加班有什么补偿？"
        try:
            ans, citations = await pipeline.answer_with_citation(query)
            print(f"\n[大模型输出答案]：\n{ans}")
            
            print("\n[文献来源溯源对照表]：")
            for idx, cite in enumerate(citations, start=1):
                print(f" 引用 [{idx}] [{cite['doc_id']}:{cite['page']}]")
                print(f"   - 来源文件: {cite['source_file']}")
                print(f"   - 原始事实: {cite['content']}")
        except NotImplementedError as e:
            print(f"\n[提示] 核心逻辑未实现: {e}")

    asyncio.run(main())
