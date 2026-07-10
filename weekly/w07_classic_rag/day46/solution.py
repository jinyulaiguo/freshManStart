"""
Day 46 参考标准答案：基于 Context 来源的可信引用 (Source Citation) 与脚注机制

设计方案：
本模块提供带脚注引用的 RAG 可信问答与解析器（CitationRAGPipeline）的具体实现方案。
通过将元数据（文献ID、来源文件、页码）与检索片段一同灌入 Context，利用 System Prompt 
的强规则契约迫使 LLM 产出 `[doc_id:page_number]` 的精准标引；随后在 Python 侧利用正则表达式
对生成的文本流进行提取、去重，并反向映射出对应的源文本库条目，为 RAG 答案提供坚实的可信审计背书。

类与函数结构：
- CitationRAGPipeline: 可信引用控制器类。
  - parse_citations(): 使用正则扫描大模型输出文本，抓取 `\\[(doc_\\d+):(\\d+)\\]` 结构的脚注元组并去重。
  - answer_with_citation(): 控制器主运行程序，处理拼装、LLM请求、正则解析以及原始文献映射。

关键数据流：
1. 拼装 Context：为每个背景文献加装 `doc_id`、`source_file` 和 `page` 前缀。
2. 约束请求：在 System 契约限制下，调用大模型（温度设为 0.01）。
3. 文本正则过滤：Python 侧扫描文本提取 `(doc_id, page)` 列表。
4. 文献映射映射：循环在 facts_db 寻址，构建溯源文献对照表。
"""

import re
import asyncio
from typing import List, Dict, Tuple

# 导入 w04 中的真实大模型客户端，严禁使用 Mock
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
    
    def __init__(self) -> None:
        """初始化可信引用管道"""
        self.llm_client = LLMClient()
        # 将测试事实库缓存为以 doc_id 为键的映射，便于高效 O(1) 检索
        self.facts_db: Dict[str, dict] = {f["doc_id"]: f for f in TEST_FACTS}

    def parse_citations(self, response_text: str) -> List[Tuple[str, int]]:
        """
        利用正则表达式从文本中提取出所有形如 [doc_xxx:page_num] 的脚注对并执行去重
        
        Args:
            response_text (str): 大模型生成的包含引用标记的响应文本
            
        Returns:
            List[Tuple[str, int]]: 提取出去重后的 (doc_id, page_number) 元组列表
        """
        if not response_text:
            return []
            
        # 1. 编写正则表达式。\\s* 用以容忍部分模型在冒号前后产生的多余空格
        pattern = r"\[(doc_\d+)\s*:\s*(\d+)\]"
        matches = re.findall(pattern, response_text)
        
        unique_citations = []
        seen = set()
        
        # 2. 遍历匹配项并执行去重，保持第一次在文本中被引用的顺序不变
        for doc_id, page_str in matches:
            pair = (doc_id, int(page_str))
            if pair not in seen:
                seen.add(pair)
                unique_citations.append(pair)
                
        return unique_citations

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
        # 1. 拼装 Context 段落，将元数据显式标注于每段文本头部以供大模型感知
        context_parts = []
        for fid, f in self.facts_db.items():
            context_parts.append(
                f"【ID: {f['doc_id']}, 来源文件: {f['source_file']}, 页码: {f['page']}】: {f['content']}"
            )
        context_str = "\n".join(context_parts)
        
        # 2. 构造标引 System Prompt 契约指令，对其施加最高级别的格式限制
        system_prompt = (
            "你是一个极其诚实、严肃的企业内部合规审查助手。\n"
            "你的任务是根据给出的【参考背景文献】回答用户的问题。\n"
            "为了保障回答的可信度与溯源审计，你必须在回答的任何事实或陈述所在的句子句尾（标点符号之前），"
            "紧跟并标注其直接引用的文献脚注。格式必须严格为：`[doc_id:page_number]`。\n\n"
            "例如：“公司员工每年享有 15 天年假`[doc_001:5]`，出差费用每天报销上限为 500 元`[doc_002:8]`。”\n\n"
            "【强制规则契约】：\n"
            "1. 必须严格执行 `[doc_id:page_number]` 格式标引。绝对不允许错标或遗漏，绝对不能标注为 `[doc_001]` 或 `[Page 5]`。\n"
            "2. 只能针对陈述句中直接依赖的事实标注脚注，严禁凭空生硬捏造或批量堆砌。\n"
            "3. 如果问题无法从【参考背景文献】中完全推导出来，请如实声明无法回答，且不能附带任何脚注。\n\n"
            "【参考背景文献】:\n"
            f"{context_str}"
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
        
        # 3. 调用大模型，将温度控制为 0.01（极度保守），强固其格式生成的准确性
        print(f"[CitationRAG] 正在向 LLM 发送提问，要求执行强引用标引...")
        response_text = await self.llm_client.request_llm(
            messages=messages,
            temperature=0.01,
            max_tokens=800
        )
        
        # 4. 正则解析提取所有引用 (doc_id, page) 对
        citation_pairs = self.parse_citations(response_text)
        
        # 5. 反向映射，根据提取出的 (doc_id, page) 富集原始文献记录
        citations = []
        for doc_id, page in citation_pairs:
            # 如果大模型引用的 doc_id 确实存在于我们背景事实库中，则提取富集
            if doc_id in self.facts_db:
                fact = self.facts_db[doc_id]
                # 注意：这里只采信页码能够完美吻合的原始数据，防范模型张冠李戴
                if fact["page"] == page:
                    citations.append({
                        "doc_id": doc_id,
                        "page": page,
                        "source_file": fact["source_file"],
                        "content": fact["content"]
                    })
                else:
                    # 页码不匹配，记录潜在的幻觉越界
                    print(f"⚠️ [Warning] 检测到模型生成了错误的页码映射：{doc_id} 对应的真实页码是 {fact['page']}，但模型标引了 {page}")
                    
        return response_text, citations


if __name__ == "__main__":
    async def main():
        print("=== Day 46 基于 Context 来源的可信引用 运行演示 ===")
        pipeline = CitationRAGPipeline()
        
        query = "请问公司正式员工年假怎么规定？周末加班又有什么补偿？"
        print(f"\n🙋 用户查询：'{query}'")
        
        ans, citations = await pipeline.answer_with_citation(query)
        
        print(f"\n[大模型流式响应最终文本]：\n{ans}")
        
        print("\n================== 原始文献溯源审计表 ==================")
        for idx, cite in enumerate(citations, start=1):
            print(f" 引用 [{idx}] [{cite['doc_id']}:{cite['page']}]")
            print(f"   - 来源文献: {cite['source_file']}")
            print(f"   - 原始段落: {cite['content']}")
        print("======================================================")
        
        # 静态验证断言：应提取出 doc_001 和 doc_003 两个引用
        doc_ids = [c["doc_id"] for c in citations]
        assert "doc_001" in doc_ids, "未成功提取出年假的引用来源 doc_001"
        assert "doc_003" in doc_ids, "未成功提取出加班补偿的引用来源 doc_003"
        print("\n✅ 物理过关验证成功！正则流提取无误，原始文献高保真对照表映射成功！")

    asyncio.run(main())
