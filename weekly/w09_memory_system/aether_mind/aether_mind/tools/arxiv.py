"""
AetherMind ArXiv Paper Fetcher Tool
===================================

设计方案:
---------
本模块实现了检索 ArXiv 学术论文的工具 `arxiv_paper_fetcher`。
本工具支持双通道保障设计：
1. **实时网络检索**：使用 `httpx` 调用 ArXiv 官方开放的 XML-RPC 查询接口，
   自动通过 `xml.etree.ElementTree` 解析召回前 2 篇最相关的论文。
2. **本地静态兜底**：当因断网、超时或接口封禁导致 HTTP 请求失败时，
   自动切入本地预置的顶级 Agent 论文库（包含 MemGPT, Reflexion, Self-RAG 等），
   根据关键字进行模糊匹配，确保大模型始终能够得到非空 Observation。

结构说明:
---------
- ArxivFetcherInput: 工具入参 Pydantic 模型。
- arxiv_paper_fetcher: 执行 ArXiv 查询与解析的主入口函数。
"""

import httpx
import xml.etree.ElementTree as ET
from pydantic import BaseModel, Field
from aether_mind.tools.base import register_tool
from aether_mind.utils.logging import logger


class ArxivFetcherInput(BaseModel):
    """arxiv_paper_fetcher 的输入参数契约。"""
    query: str = Field(
        ...,
        description="用于在 ArXiv 检索的关键词，如 'MemGPT'、'Agentic OS' 或 'Self-RAG'"
    )


# 本地兜底论文库
LOCAL_PAPERS = [
    {
        "title": "MemGPT: Towards LLMs as Operating Systems",
        "authors": "Packer et al.",
        "summary": "MemGPT introduces virtual memory management techniques (paging, swap) to extend LLM context windows, allowing agents to manage long-term state independently."
    },
    {
        "title": "Reflexion: Language Agents with Active Learning Improved by Iterative Feedback",
        "authors": "Shinn et al.",
        "summary": "Reflexion introduces a self-reflective loop where agents evaluate their task completion, generate critique on errors, and store it in long-term memory to avoid repeating mistakes."
    },
    {
        "title": "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection",
        "authors": "Asai et al.",
        "summary": "Self-RAG trains LLMs to generate self-reflection tokens ('critique tokens') to adaptively retrieve documents, assess relevance, and check factuality during generation."
    }
]


@register_tool(
    name="arxiv_paper_fetcher",
    description="拉取 ArXiv 上的 Agent 相关最新学术文献，返回 Top-2 论文的标题、作者与摘要。",
    args_schema=ArxivFetcherInput
)
async def arxiv_paper_fetcher(query: str) -> str:
    """
    检索并返回 ArXiv 上的学术文献信息。

    Args:
        query (str): 查询关键词。

    Returns:
        str: 格式化的学术论文摘要汇总。
    """
    url = f"http://export.arxiv.org/api/query?search_query=all:{query}&max_results=2"
    timeout_policy = httpx.Timeout(timeout=10.0)

    try:
        logger.info(f"[ArXiv 检索] 正在发起学术请求 -> {url}")
        async with httpx.AsyncClient(timeout=timeout_policy) as client:
            response = await client.get(url)
            
            if response.status_code != 200:
                raise RuntimeError(f"HTTP Status {response.status_code}")
                
            # 1. 使用 ElementTree 解析 Atom 命名空间 XML
            root = ET.fromstring(response.text)
            
            # Atom 命名空间
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entries = root.findall("atom:entry", ns)
            
            if not entries:
                return f"[ArXiv 检索结果]: 未能检索到关于关键词 '{query}' 的学术文献。"

            paper_list = []
            for idx, entry in enumerate(entries):
                title = entry.find("atom:title", ns)
                summary = entry.find("atom:summary", ns)
                
                # 获取作者列表
                authors_elements = entry.findall("atom:author/atom:name", ns)
                authors_str = ", ".join([auth.text.strip() for auth in authors_elements if auth.text])
                
                title_text = title.text.replace("\n", " ").strip() if title is not None else "Unknown"
                summary_text = summary.text.replace("\n", " ").strip() if summary is not None else "No summary available"
                
                paper_list.append(
                    f"论文 {idx + 1}:\n"
                    f"  - 标题: {title_text}\n"
                    f"  - 作者: {authors_str}\n"
                    f"  - 摘要: {summary_text[:400]}..."
                )
                
            return "\n\n".join(paper_list)

    except Exception as e:
        logger.warning(f"[ArXiv 检索失败] {str(e)}，自动切入本地兜底库...")
        
        # 2. 离线模糊匹配
        query_lower = query.lower()
        matched = []
        for paper in LOCAL_PAPERS:
            if (query_lower in paper["title"].lower()) or (query_lower in paper["summary"].lower()):
                matched.append(paper)
                
        # 若没有搜到，默认返回前两篇
        if not matched:
            matched = LOCAL_PAPERS[:2]

        paper_list = []
        for idx, paper in enumerate(matched):
            paper_list.append(
                f"论文 {idx + 1} (本地备用文献):\n"
                f"  - 标题: {paper['title']}\n"
                f"  - 作者: {paper['authors']}\n"
                f"  - 摘要: {paper['summary']}"
            )
        return "\n\n".join(paper_list)
