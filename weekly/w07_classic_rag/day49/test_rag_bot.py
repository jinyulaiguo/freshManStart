"""
Day 49 单元测试：对索引构建去重、大模型相关性重排和可信脚注解析进行全面验证
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from weekly.w07_classic_rag.day49.solution import ChunkIndexer, LLMReranker, CitationRAGBot


def test_chunk_indexer_hash_dedup():
    """验证哈希内容指纹计算的确定性，相同的文本/ID/页码应当生成完全相同的哈希"""
    indexer = ChunkIndexer()
    h1 = indexer._compute_content_hash("公司年假 15 天", "doc_abc", 1)
    h2 = indexer._compute_content_hash("公司年假 15 天", "doc_abc", 1)
    h3 = indexer._compute_content_hash("公司年假 16 天", "doc_abc", 1)
    
    assert h1 == h2, "哈希计算不具备确定性，相同输入产生了不同哈希"
    assert h1 != h3, "哈希计算碰撞，不同输入产生了相同哈希"


def test_citation_parse_basic():
    """验证从文本中正确提取标准格式的 [doc_id:page] 脚注"""
    bot = CitationRAGBot(MagicMock())
    text = "公司员工每年享有 15 天年假[doc_001:5]，週末加班可选择 2 倍工资补偿[doc_002:12]。"
    citations = bot.parse_citations(text)
    
    assert len(citations) == 2
    assert citations[0] == ("doc_001", 5)
    assert citations[1] == ("doc_002", 12)


def test_citation_parse_dedup():
    """验证重复出现的脚注能够被自动去重，并且保留首次出现的顺序"""
    bot = CitationRAGBot(MagicMock())
    text = "公司年假规定[doc_001:5]，超出上限个人自理[doc_002:8]，年假失效说明[doc_001:5]。"
    citations = bot.parse_citations(text)
    
    assert len(citations) == 2
    assert citations[0] == ("doc_001", 5)
    assert citations[1] == ("doc_002", 8)


def test_citation_parse_tolerant():
    """验证正则提取能容忍冒号前后的空格"""
    bot = CitationRAGBot(MagicMock())
    text = "差旅费报销上限 500 元[doc_001 : 8]，市内交通 80 元[doc_002: 12 ]。"
    citations = bot.parse_citations(text)
    
    assert len(citations) == 2
    assert citations[0] == ("doc_001", 8)
    assert citations[1] == ("doc_002", 12)


@pytest.mark.asyncio
async def test_reranker_ordering():
    """测试重排器打分与降序排列逻辑"""
    mock_llm = MagicMock()
    # 模拟三次打分，分别返回 85, 45, 95
    mock_llm.request_llm = AsyncMock(side_effect=["85.0", "45", "95"])
    
    reranker = LLMReranker(mock_llm)
    
    chunks = [
        {"doc_id": "doc_1", "content": "年假 15 天"},
        {"doc_id": "doc_2", "content": "差旅报销 500 元"},
        {"doc_id": "doc_3", "content": "加班 2 倍工资"}
    ]
    
    reranked = await reranker.rerank("公司福利年假与加班规定", chunks)
    
    assert len(reranked) == 3
    # 预期打分顺序：doc_3 (95) -> doc_1 (85) -> doc_2 (45)
    assert reranked[0]["doc_id"] == "doc_3"
    assert reranked[0]["rerank_score"] == 95.0
    assert reranked[1]["doc_id"] == "doc_1"
    assert reranked[1]["rerank_score"] == 85.0
    assert reranked[2]["doc_id"] == "doc_2"
    assert reranked[2]["rerank_score"] == 45.0
