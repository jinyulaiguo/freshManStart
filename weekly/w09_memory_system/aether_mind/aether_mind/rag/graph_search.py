"""
AetherMind GraphRAG Engine
==========================

设计方案:
---------
本模块实现了基于知识图谱的高级检索（GraphRAG）。
相较于传统向量检索（Dense RAG）仅关注局部文本的语义相似度，GraphRAG
通过抽取文本实体与关系，在全局关系拓扑上实现关联多步推理与宏观概念总结。

核心原理:
---------
1. **实体关系抽取 (Extraction)**：使用大模型结构化提取文档切片中的实体节点（`GraphEntity`）
   和关系边（`GraphRelation`），写入 NetworkX 内存有向图结构。
2. **社区发现 (Community Detection)**：使用 NetworkX 内置的 Louvain 算法对全局图谱进行分群，
   并利用 LLM 针对每个群落生成技术社区报告（`CommunityReport`）。
3. **局部检索 (Local Search)**：针对包含特定实体的 Query，沿图拓扑进行 1-2 跳邻域遍历，
   返回该实体最直接的外向/内向关联链条。
4. **全局检索 (Global Search)**：针对全局性/比对性 Query，执行 Map-Reduce 聚合：
   - Map: 各个社区独立分析该 Query 并产生打分答案。
   - Reduce: 筛选得分合格的回答并融合为宏观综述。

结构说明:
---------
- Pydantic models (EntityExtractionItem, RelationExtractionItem, ExtractionResult): 抽取契约。
- Pydantic models (GraphEntity, GraphRelation, CommunityReport): 存储结构。
- GraphRAGEngine: GraphRAG 执行与图谱库维护主类。
"""

import json
import asyncio
from typing import List, Dict, Any, Tuple, Set, Optional
import networkx as nx
from pydantic import BaseModel, Field
from aether_mind.utils.client import AetherMindLLMClient
from aether_mind.utils.logging import logger
from aether_mind.storage.base import VectorStore


# === 1. Pydantic 抽取契约 ===

class EntityExtractionItem(BaseModel):
    """单条实体节点提取格式。"""
    name: str = Field(..., description="实体名称，使用统一简称。例如: 'smolagents'、'Letta'")
    type: str = Field(..., description="类别。可选值: framework (框架), paper (论文), component (核心组件), concept (概念), author (作者/组织)")
    description: str = Field(..., description="针对当前上下文关于该实体的描述摘要")


class RelationExtractionItem(BaseModel):
    """单条实体关系提取格式。"""
    source: str = Field(..., description="源实体名称")
    target: str = Field(..., description="目标实体名称")
    relation: str = Field(..., description="关系说明，如 depends_on, improves, competes_with, inherits")
    evidence: str = Field(..., description="得出该关系判断的原文核心单句")


class ExtractionResult(BaseModel):
    """图谱抽取输出包装。"""
    entities: List[EntityExtractionItem] = Field(default_factory=list, description="实体节点列表")
    relations: List[RelationExtractionItem] = Field(default_factory=list, description="关系连接边列表")


# === 2. Pydantic 社区 Map-Reduce 模型 ===

class CommunityReportModel(BaseModel):
    """网络社区报告的主题总结数据契约。"""
    title: str = Field(..., description="社区标题，例如 '状态流与持久化记忆框架群'")
    summary: str = Field(..., description="社区的深度技术解析与设计意图总结")
    importance: float = Field(..., ge=0.0, le=1.0, description="社区在整个大图谱下的重要性权重打分")


class CommunityMapAnswer(BaseModel):
    """Map 阶段单个社区的初步回答结果。"""
    score: int = Field(..., ge=0, le=10, description="该社区报告对 Query 的相关度打分 (0-10)")
    answer: str = Field(..., description="基于社区报告得出的解答文本。如不相关则输出为空。")



# === 3. GraphRAG 主引擎 ===

class GraphRAGEngine:
    """
    GraphRAG 检索引擎，负责维护 NetworkX 内存图及执行 Local/Global 图检索。
    """

    def __init__(self, client: AetherMindLLMClient):
        """
        初始化 GraphRAG 引擎。

        Args:
            client (AetherMindLLMClient): 大模型客户端。
        """
        self.client = client
        # NetworkX 内存有向图结构
        self.graph = nx.DiGraph()
        # 社区发现生成的报告列表
        self.community_reports: List[Dict[str, Any]] = []

    async def extract_and_build_graph(self, chunk_id: int, text: str) -> bool:
        """
        解析单条文档 Chunk，提取实体和关系并织入内存图。

        Args:
            chunk_id (int): 来源 Chunks ID。
            text (str): 文本内容。

        Returns:
            bool: 提取并织入图谱成功返回 True，发生异常失败返回 False。
        """
        prompt = [
            {
                "role": "system",
                "content": (
                    "你是一个资深的图谱实体关系抽取器。\n"
                    "你需要分析给定的文档切片，识别其中的技术框架、学术论文、核心组件与技术概念实体，"
                    "并建立它们之间的逻辑连接（关系）。\n\n"
                    "关系分类规范（必须是以下之一）：\n"
                    "- depends_on：A 依赖或需要 B 才能运行。\n"
                    "- improves：A 在 B 的基础上进行了优化、增强或替代。\n"
                    "- competes_with：A 与 B 是竞争/对比关系。\n"
                    "- inherits：A 继承或借鉴了 B 的设计设计哲学。\n"
                    "- cited_by：A 被 B 引用或参考。\n\n"
                    "请以严格的 JSON Schema 格式输出，除 JSON 内容外不要包含任何其他文字。"
                )
            },
            {"role": "user", "content": f"【切片内容 (Chunk ID: {chunk_id})】:\n{text}\n\n请进行图谱提取："}
        ]

        try:
            res = await self.client.request_llm_json(prompt, ExtractionResult, temperature=0.01, max_tokens=3000)
            
            # 1. 织入节点
            for ent in res.entities:
                name = ent.name.strip()
                if not name:
                    continue
                # 若节点不存在则创建，若存在则合并 description
                if self.graph.has_node(name):
                    old_desc = self.graph.nodes[name].get("description", "")
                    # 避免重复合并相同描述
                    if ent.description not in old_desc:
                        self.graph.nodes[name]["description"] = f"{old_desc} | {ent.description}"
                    self.graph.nodes[name]["source_chunks"].add(chunk_id)
                else:
                    self.graph.add_node(
                        name,
                        type=ent.type,
                        description=ent.description,
                        source_chunks={chunk_id}
                    )

            # 2. 织入关系边
            for rel in res.relations:
                src = rel.source.strip()
                tgt = rel.target.strip()
                if not src or not tgt:
                    continue
                
                # 确保两端节点存在（防悬挂边）
                if not self.graph.has_node(src):
                    self.graph.add_node(src, type="concept", description="自动创建的临时节点", source_chunks={chunk_id})
                if not self.graph.has_node(tgt):
                    self.graph.add_node(tgt, type="concept", description="自动创建的临时节点", source_chunks={chunk_id})

                # 若边已存在，则追加 evidence 证据链
                if self.graph.has_edge(src, tgt):
                    old_evidence = self.graph.edges[src, tgt].get("evidence", "")
                    if rel.evidence not in old_evidence:
                        self.graph.edges[src, tgt]["evidence"] = f"{old_evidence} | {rel.evidence}"
                else:
                    self.graph.add_edge(
                        src,
                        tgt,
                        relation=rel.relation,
                        evidence=rel.evidence,
                        weight=1.0
                    )
            logger.info(f"[图构建] Chunk {chunk_id} 成功织入图谱。当前图节点数: {self.graph.number_of_nodes()}，边数: {self.graph.number_of_edges()}")
            return True
        except Exception as e:
            logger.error(f"[图构建异常] Chunk {chunk_id} 提取失败: {str(e)}")
            return False

    async def build_communities(self, vector_store: Optional[VectorStore] = None) -> None:
        """
        使用 Louvain 社区发现算法对内存图进行分群，并调用大模型生成各个社区的技术总结报告。
        """
        if self.graph.number_of_nodes() < 2:
            logger.info("[社区生成] 图中节点过少，跳过社区分群。")
            return

        # 1. 转换为无向图执行 Louvain 算法
        undirected_g = self.graph.to_undirected()
        try:
            communities = nx.community.louvain_communities(undirected_g)
        except Exception as e:
            logger.error(f"[社区发现算法失败] {str(e)}，降级使用 Modularity-Greedy")
            communities = nx.community.greedy_modularity_communities(undirected_g)

        self.community_reports = []
        logger.info(f"[社区生成] 成功将图划分出 {len(communities)} 个网络社区")

        # 2. 为每个社区并发生成报告，引入并发控制防止 429
        semaphore = asyncio.Semaphore(5)

        async def _generate_report(comm_idx: int, nodes_set: Set[str]) -> Dict[str, Any]:
            async with semaphore:
                # 汇总当前社区内的全部节点属性
                nodes_info = []
                for node in nodes_set:
                    attrs = self.graph.nodes[node]
                    nodes_info.append(f"实体: {node} (类型: {attrs.get('type')}) -> 描述: {attrs.get('description')}")
                
                # 汇总当前社区内包含的关系边
                edges_info = []
                for u, v in self.graph.edges:
                    if u in nodes_set and v in nodes_set:
                        attrs = self.graph.edges[u, v]
                        edges_info.append(f"关系: {u} --[{attrs.get('relation')}]--> {v} (证据: {attrs.get('evidence')})")

                nodes_str = "\n".join(nodes_info)
                edges_str = "\n".join(edges_info)

                prompt = [
                    {
                        "role": "system",
                        "content": (
                            "你是一个高级学术与技术主题总结专家。\n"
                            "你需要针对一组互相关联的网络实体和关系信息（属于同一个网络社区），"
                            "撰写一份客观、凝炼的社区技术主题报告。\n"
                            "报告内容必须包括：\n"
                            "1. 一个概括性的标题（如 '状态流与持久化记忆框架群'）。\n"
                            "2. 社区整体的技术意图总结、各实体之间的架构演进或对比规律。\n"
                            "3. 给出一个重要度评估评分 (0.0 - 1.0)。\n"
                            "请以严格的 JSON 格式输出，字段为: title (标题), summary (技术总结), importance (打分)。\n"
                            "【注意】：为防止 JSON 语法错误，输出的所有字符串字段值内部严禁包含未转义的双引号。如果需要使用引用或双引号，请改用单引号（例如使用 'smolagents' 代替 \"smolagents\"）。"
                        )
                    },
                    {
                        "role": "user",
                        "content": (
                            f"【网络社区 ID: {comm_idx}】\n\n"
                            f"【包含实体节点】:\n{nodes_str}\n\n"
                            f"【包含关系链条】:\n{edges_str}\n\n"
                            "请输出社区主题报告："
                        )
                    }
                ]
                
                try:
                    # 使用结构化 API 强校验生成，包含纠错重试机制
                    report_data = await self.client.request_llm_json(
                        messages=prompt,
                        response_model=CommunityReportModel,
                        temperature=0.1,
                        max_tokens=1500
                    )
                    return {
                        "community_id": comm_idx,
                        "title": report_data.title,
                        "summary": report_data.summary,
                        "importance": report_data.importance,
                        "entities": list(nodes_set)
                    }
                except Exception as ex:
                    logger.error(f"[社区报告生成异常] 社区 {comm_idx} 生成失败: {str(ex)}")
                    return {
                        "community_id": comm_idx,
                        "title": f"社区 {comm_idx} 兜底报告",
                        "summary": "未能成功生成技术总结报告",
                        "importance": 0.5,
                        "entities": list(nodes_set)
                    }


        # 3. 并发执行报告生成
        tasks = [_generate_report(idx, comm) for idx, comm in enumerate(communities)]
        self.community_reports = await asyncio.gather(*tasks)
        logger.info(f"[社区生成完成] 成功构建 {len(self.community_reports)} 份社区宏观报告。")

        # 4. 如果提供了 vector_store，将社区总结 Summary 向量化并写入 Qdrant
        if vector_store and self.community_reports:
            logger.info(f"[社区向量化] 开始为 {len(self.community_reports)} 个社区报告计算 Summary 向量并存入 Qdrant...")
            try:
                valid_reports = [r for r in self.community_reports if r.get("summary") and r["summary"].strip()]
                if valid_reports:
                    summaries = [r["summary"] for r in valid_reports]
                    embeddings = await self.client.get_embeddings(summaries, embed_type="db")
                    
                    points = []
                    for report, vector in zip(valid_reports, embeddings):
                        points.append({
                            "id": report["community_id"],  # 使用社区 ID 作为 Qdrant Point 整数 ID
                            "vector": vector,
                            "payload": {
                                "community_id": report["community_id"],
                                "title": report["title"],
                                "summary": report["summary"],
                                "importance": report["importance"]
                            }
                        })
                    
                    await vector_store.upsert_points("community_collection", points)
                    logger.info(f"[社区向量化成功] 已向 community_collection 写入 {len(points)} 个社区摘要向量。")
            except Exception as e:
                logger.error(f"[社区向量化异常] 将社区报告写入向量库失败: {str(e)}", exc_info=True)

    async def local_search(self, query: str, top_k: int = 3) -> str:
        """
        局部检索：针对 Query 中提及的特定实体，沿图谱拓扑结构搜索其 1-2 跳的局域关联链。

        Args:
            query (str): 用户查询。
            top_k (int): 检索词抽取上限。

        Returns:
            str: 格式化的局部实体图上下文文本。
        """
        if self.graph.number_of_nodes() == 0:
            return "知识图谱为空，无法进行局部检索。"

        # 1. 抽取 Query 中含有的网络实体
        all_nodes = list(self.graph.nodes)
        matched_nodes = []
        for node in all_nodes:
            # 简单模糊匹配（生产环境中可使用 LLM 实体识别，这里做轻量化文本扫描）
            if node.lower() in query.lower():
                matched_nodes.append(node)

        # 如果没有直接匹配的节点，检索结束
        if not matched_nodes:
            return ""

        logger.info(f"[GraphRAG 局部检索] 匹配到 Query 关联实体: {matched_nodes}")

        # 2. 对匹配实体进行邻域 1 跳子图扩展
        subgraph_nodes = set(matched_nodes)
        for node in matched_nodes:
            # 扩展出前驱与后继节点
            subgraph_nodes.update(self.graph.predecessors(node))
            subgraph_nodes.update(self.graph.successors(node))

        # 3. 汇总子图中的节点信息与关系边证据
        sub_nodes_info = []
        for n in subgraph_nodes:
            attrs = self.graph.nodes[n]
            sub_nodes_info.append(f"- 实体: {n} ({attrs.get('type')}) -> 描述: {attrs.get('description')}")
            
        sub_edges_info = []
        for u, v in self.graph.edges:
            if u in subgraph_nodes and v in subgraph_nodes:
                attrs = self.graph.edges[u, v]
                sub_edges_info.append(f"  关系边: {u} --[{attrs.get('relation')}]--> {v}. 证据原文: '{attrs.get('evidence')}'")

        context_lines = [
            "【知识图谱局部实体关系关联检索】:",
            "\n".join(sub_nodes_info),
            "\n".join(sub_edges_info)
        ]
        return "\n".join(context_lines)

    async def global_search(self, query: str, vector_store: Optional[VectorStore] = None) -> str:
        """
        全局检索：利用 Map-Reduce 对所有的网络社区总结报告执行宏观聚合推理。

        Args:
            query (str): 用户全局性/比对性查询。
            vector_store (Optional[VectorStore]): 向量数据库（用于 KNN 社区预筛选）。

        Returns:
            str: 汇总答复文本。
        """
        if not self.community_reports:
            return ""

        # 0. 如果提供了 vector_store，在 Map 阶段前进行 KNN 社区预初筛 (Top 10)
        reports_to_assess = self.community_reports
        if vector_store:
            try:
                query_vector = await self.client.get_embedding(query, embed_type="query")
                hits = await vector_store.search_points("community_collection", query_vector, top_k=10)
                if hits:
                    matched_ids = {hit["payload"]["community_id"] for hit in hits}
                    reports_to_assess = [r for r in self.community_reports if r["community_id"] in matched_ids]
                    logger.info(
                        f"[GraphRAG 全局检索优化] 通过 Qdrant KNN 粗筛出 {len(reports_to_assess)}/{len(self.community_reports)} 个相关社区进行大模型 Map 评估。"
                    )
                else:
                    logger.info("[GraphRAG 全局检索优化] Qdrant 中未搜到相似社区，降级扫描全量社区。")
            except Exception as e:
                logger.error(f"[GraphRAG 检索筛选异常] KNN 社区初筛失败，降级扫描全量社区。错误: {str(e)}", exc_info=True)

        if not reports_to_assess:
            return ""

        logger.info(f"[GraphRAG 全局检索] 开始对 {len(reports_to_assess)} 个社区报告执行 Map-Reduce 分析...")

        # 1. Map 阶段：针对每个社区报告并行求解，引入并发控制防止 429
        semaphore = asyncio.Semaphore(5)

        async def _map_community(report: Dict[str, Any]) -> Tuple[int, str]:
            async with semaphore:
                prompt = [
                    {
                        "role": "system",
                        "content": (
                            "你是一个技术架构分析器。\n"
                            "你需要基于下面给定的网络社区报告内容，回答用户的全局查询问题。\n"
                            "打分要求：如果社区报告内容与用户问题高度相关，并能提供深入的论据，给该社区打高分 (7-10)；"
                            "如果关联不大，打低分 (0-3)；若完全不相关，分数必须填 0。\n"
                            "必须严格以 JSON 格式输出，字段为: score (打分，必须是 0-10 之间的数字整数，如 5。若不相关请直接填 0，严禁使用 null、'N/A' 或留空), answer (回答内容，纯文本描述，不可嵌套 JSON 或额外括号)。\n"
                            "【重要】：直接输出标准 JSON 对象，以 { 开始以 } 结束，不要包含任何 Markdown 代码围栏或其他前缀文字。"
                        )
                    },
                    {
                        "role": "user",
                        "content": (
                            f"【网络社区报告 - 标题: {report['title']}】\n"
                            f"摘要: {report['summary']}\n"
                            f"包含实体: {', '.join(report['entities'])}\n\n"
                            f"【用户问题】: {query}\n\n"
                            "请输出回答："
                        )
                    }
                ]
                try:
                    res = await self.client.request_llm_json(prompt, CommunityMapAnswer, temperature=0.01)
                    return res.score, res.answer
                except Exception as ex:
                    logger.error(f"[Map 异常] 社区 {report['community_id']} 计算失败: {str(ex)}")
                    return 0, ""

        map_tasks = [_map_community(r) for r in reports_to_assess]
        map_results = await asyncio.gather(*map_tasks)

        # 2. Filter 过滤：筛选得分大于等于 3 的有效社区回答
        valid_answers = []
        for idx, (score, answer) in enumerate(map_results):
            if score >= 3 and answer.strip():
                valid_answers.append(
                    f"【社区主题: {reports_to_assess[idx]['title']} (相关得分: {score})】\n解答线索: {answer}"
                )

        # 2.1 降级过滤：如果没有得分 >= 3 的社区，降级过滤得分 >= 1 的有效回答
        if not valid_answers:
            for idx, (score, answer) in enumerate(map_results):
                if score >= 1 and answer.strip():
                    valid_answers.append(
                        f"【社区主题: {reports_to_assess[idx]['title']} (相关得分: {score})】\n解答线索: {answer}"
                    )

        # 2.2 兜底保护：若得分全部为 0，将所有要评估社区的 summary 拼接作为输入，强制进行全局融合
        if not valid_answers:
            logger.info("[GraphRAG] 未筛选到高分相关社区线索，自动提取相关社区技术报告进行兜底融合回答...")
            for r in reports_to_assess:
                if r["summary"].strip():
                    valid_answers.append(
                        f"【社区主题: {r['title']}】\n技术总结线索: {r['summary']}"
                    )

        if not valid_answers:
            return ""

        # 3. Reduce 阶段：将多个社区的线索合并融合成最终综述
        logger.info(f"[GraphRAG 全局检索] Map 阶段过滤出 {len(valid_answers)} 条有效社区线索，进入 Reduce 融合...")
        valid_answers_str = "\n\n".join(valid_answers)
        
        reduce_prompt = [
            {
                "role": "system",
                "content": (
                    "你是一个资深的开源框架研究助理。\n"
                    "你需要将多路独立网络社区报告得出的解答线索，融合成一段系统、客观、逻辑清晰的技术综述，"
                    "以完美回答用户提出的全局性比对或设计理念分析问题。\n"
                    "注意：融合时要保持客观中立，指出不同社区线索反映的异同。仅输出综述内容，不要包含任何自然语言回复前缀。"
                )
            },
            {
                "role": "user",
                "content": (
                    f"【用户查询问题】: {query}\n\n"
                    f"【收集到的多路社区解答线索】:\n{valid_answers_str}\n\n"
                    "请输出最终融合成的系统综述回答："
                )
            }
        ]

        try:
            final_report = await self.client.request_llm(reduce_prompt, temperature=0.2, max_tokens=1000)
            return f"【知识图谱社区全局多重推理综述】:\n{final_report.strip()}"
        except Exception as e:
            logger.error(f"[Reduce 融合异常] {str(e)}")
            return "\n\n".join(valid_answers)
