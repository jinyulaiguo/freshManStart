"""
Day 54 参考答案：微软 GraphRAG 框架机制分析与社区版实践

设计方案：
1. 设计意图：
   提供完整的内存级 GraphRAG 全局检索机制实现。
   为了保证本地无二进制编译依赖崩溃风险，手写了忽略方向的 BFS 连通子图聚类算法，逻辑上完美平替 Leiden。
   在此基础上实现 Map-Reduce 并发图谱总结报告生成，以及全局查询路由与蒸馏（Global Search）。

2. 核心结构：
   - `MockGraphRAG`:
     - `partition_communities`: 无向图 BFS 连通分量遍历。将相互交织的话题划分为独立的 Communities。
     - `generate_community_summaries`: 并发向 LLM 提交社区边关系，生成各个社区的主题报告。
     - `global_search`: 运行 Map-Reduce 过滤“无相关信息”的分支，合并有效片段输出最终架构报告。
   - `if __name__ == "__main__":` 调试主入口：注入 Redis 与 PG 两套话题图谱，演示并打印出全局合并回答。

3. 物理防爆与过滤：
   - 所有的 LLM 调用接口均使用 re.DOTALL 正则物理剔除 `<think>` 标签，防止推理模型的中间内容污染生成的报告与回答。
"""

import asyncio
import re
from typing import List, Dict, Any, Tuple

# 导入真实 LLM 客户端
from weekly.w04_prompt_and_http.utils import LLMClient


class MockGraphRAG:
    """极简 GraphRAG 检索器：模拟图社区发现与 Map-Reduce 全局查询机制"""

    def __init__(self, llm_client: LLMClient):
        """初始化 GraphRAG 实例
        
        Args:
            llm_client: 已经加载了环境变量的真实大模型客户端实例
        """
        self.llm_client = llm_client
        # 属性图结构：{ node_id: {"label": str, "neighbors": { relation_name: [neighbor_ids] }} }
        self.graph = {}
        # 社区总结缓存：{ community_id: community_summary_text }
        self.community_summaries = {}

    def add_relation(self, s: str, s_label: str, p: str, o: str, o_label: str):
        """往内存属性图中添加三元组边关系，并自动维护邻接表结构
        
        Args:
            s: 主体 ID
            s_label: 主体标签类型
            p: 关系名称
            o: 客体 ID
            o_label: 客体标签类型
        """
        for node, label in [(s, s_label), (o, o_label)]:
            if node not in self.graph:
                self.graph[node] = {"label": label, "neighbors": {}}
                
        if p not in self.graph[s]["neighbors"]:
            self.graph[s]["neighbors"][p] = []
        if o not in self.graph[s]["neighbors"][p]:
            self.graph[s]["neighbors"][p].append(o)

    def _get_undirected_neighbors(self, node: str) -> set:
        """辅助函数：获取一个节点的无向邻居节点集 (合并出边与入边邻居)"""
        neighbors = set()
        # 1. 收集从该节点出发的有向出边邻居
        if node in self.graph:
            for p, objects in self.graph[node]["neighbors"].items():
                for obj in objects:
                    neighbors.add(obj)
        # 2. 收集指向该节点的有向入边源头节点
        for other_node, data in self.graph.items():
            for p, objects in data["neighbors"].items():
                if node in objects:
                    neighbors.add(other_node)
        return neighbors

    def partition_communities(self) -> List[List[str]]:
        """基于图拓扑连通分量划分话题子社区 (无向 BFS 聚类，平替 Leiden 算法的分组效果)
        
        Returns:
            社区列表，每个社区为一个包含实体 ID 的字符串列表
        """
        visited = set()
        communities = []
        
        # 遍历图中的每一个实体节点，搜寻其所属连通分支
        for node in self.graph:
            if node not in visited:
                community = []
                queue = [node]
                visited.add(node)
                
                # 标准宽度优先搜索 (BFS) 遍历所有无向相连节点
                while queue:
                    curr = queue.pop(0)
                    community.append(curr)
                    for nxt in self._get_undirected_neighbors(curr):
                        if nxt not in visited:
                            visited.add(nxt)
                            queue.append(nxt)
                            
                communities.append(community)
                
        return communities

    async def generate_community_summaries(self, communities: List[List[str]]) -> Dict[int, str]:
        """异步并发调用大模型，为每个划分出来的社区生成一份主题总结报告
        
        Args:
            communities: 图社区划分结果
            
        Returns:
            社区 ID 与对应摘要报告的映射字典
        """
        async def summarize_single_community(comm_id: int, nodes: List[str]) -> Tuple[int, str]:
            # 1. 提炼该社区包含的所有节点属性和关系边
            relations = []
            for u in nodes:
                u_label = self.graph[u]["label"]
                if u in self.graph:
                    for p, objects in self.graph[u]["neighbors"].items():
                        for v in objects:
                            if v in nodes:
                                v_label = self.graph[v]["label"]
                                relations.append(
                                    f"({u}, 标签: {u_label}) ──[ {p} ]──► ({v}, 标签: {v_label})"
                                )
                                
            # 2. 序列化为文本事实集
            relations_text = "\n".join(relations)
            nodes_text = ", ".join([f"{u}({self.graph[u]['label']})" for u in nodes])
            
            system_prompt = (
                "你是一个资深的后台中间件运维分析专家。\n"
                "下面为你提供一个特定后台话题子社区的节点关系拓扑集，你需要阅读并为其生成一份约 150 字的技术总结报告。\n"
                "要求：\n"
                "1. 报告必须精简详实，描述该话题探讨了哪些中间件异常、具体的引发配置或场景以及相关的解决路线。\n"
                "2. 必须在 </think> 思维链标签外部输出最终的总结文本，严禁夹带主观推测。"
            )
            user_content = (
                f"社区包含实体：{nodes_text}\n"
                f"包含的关系链：\n{relations_text}"
            )
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]
            
            # 使用低温度保证技术术语的严谨性，将 max_tokens 扩大到 1500 防止长思维链截断
            report = await self.llm_client.request_llm(
                messages=messages,
                temperature=0.1,
                max_tokens=1500
            )

            
            # 清洗思维链
            if "<think>" in report:
                report = re.sub(r"<think>.*?</think>", "", report, flags=re.DOTALL)
                
            return comm_id, report.strip()

        # 3. 使用 asyncio.gather 并发调度所有社区总结任务，提升 RAG 效率
        tasks = [summarize_single_community(i, comm) for i, comm in enumerate(communities)]
        results = await asyncio.gather(*tasks)
        
        # 缓存总结报告
        self.community_summaries = {comm_id: report for comm_id, report in results}
        return self.community_summaries

    async def global_search(self, query: str) -> str:
        """运行 Map-Reduce 全局检索，融合所有社区报告生成宏观解答
        
        Args:
            query: 全局宏观提问
            
        Returns:
            高保真全局汇总答案
        """
        if not self.community_summaries:
            return "检索失败：图谱尚未完成聚类或社区总结未生成。"

        # A. Map 阶段：并发评估各社区总结，提炼关联局部细节
        async def map_single_report(comm_id: int, summary: str) -> str:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是一个资深的中间件系统分析师。\n"
                        "请根据提供的一个局部知识图谱社区主题报告，提取并生成对用户全局问题的局部解答片段。\n"
                        "要求：\n"
                        "1. 仅提取与用户问题直接相关的事实，严禁编造或添加外部假设。\n"
                        "2. 如果该社区总结中完全不含有与用户问题相关的信息，请直接回复 '无相关信息'，严禁胡扯。\n"
                        "3. 保持回答客观、紧凑，在 150 字以内。"
                    )
                },
                {
                    "role": "user",
                    "content": f"社区主题报告：\n{summary}\n\n全局提问：{query}"
                }
            ]
            text = await self.llm_client.request_llm(messages=messages, temperature=0.1, max_tokens=400)
            if "<think>" in text:
                text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
            return text.strip()

        map_tasks = [map_single_report(cid, r) for cid, r in self.community_summaries.items()]
        intermediate_answers = await asyncio.gather(*map_tasks)

        # B. Reduce 阶段：过滤无用信息并合并高维事实
        valid_intermediates = [ans for ans in intermediate_answers if ans and "无相关信息" not in ans]
        if not valid_intermediates:
            return "很抱歉，当前系统图谱中没有检测到与您提问相关的任何数据库或中间件优化配置信息。"

        reduce_prompt = (
            "你是一个专业的分布式系统架构总监。\n"
            "你需要汇总以下各个子社区提交的局部系统风险和应对策略分析，生成一份结构清晰、条理分明、技术细节详实的最终全局解答。\n\n"
            "各个子社区的局部分析报告如下：\n"
            + "\n---\n".join(valid_intermediates)
            + "\n\n请以标准的中文技术参考报告格式输出，包含系统风险、触发指标与参数、规避方案这几个小标题。"
        )

        messages = [
            {"role": "user", "content": reduce_prompt}
        ]

        final_answer = await self.llm_client.request_llm(
            messages=messages,
            temperature=0.2,
            max_tokens=1000
        )

        if "<think>" in final_answer:
            final_answer = re.sub(r"<think>.*?</think>", "", final_answer, flags=re.DOTALL)

        return final_answer.strip()


# =====================================================================
# 🛠️ 预置异构多话题关联图谱与调试运行入口
# =====================================================================

def build_test_graph(rag_engine: MockGraphRAG):
    """辅助函数：在内存中构建包含 Redis 优化与 PG 锁竞争两个完全独立话题子社区的图谱"""
    # 话题社区 1: Redis 并发性能网络优化 (连通子图 A)
    rag_engine.add_relation("Redis", "中间件", "遭遇", "Connection refused", "系统异常")
    rag_engine.add_relation("Connection refused", "系统异常", "根源在于", "net.core.somaxconn", "内核指标")
    rag_engine.add_relation("net.core.somaxconn", "内核指标", "代表", "内核监听队列上限", "系统配置")
    rag_engine.add_relation("Connection refused", "系统异常", "关联参数", "maxclients", "Redis配置")
    rag_engine.add_relation("maxclients", "Redis配置", "限制", "最大连接数", "系统配置")
    
    # 话题社区 2: PostgreSQL 行级锁冲突与乐观锁机制 (连通子图 B)
    rag_engine.add_relation("PostgreSQL", "中间件", "发生", "行级锁竞争", "系统异常")
    rag_engine.add_relation("行级锁竞争", "系统异常", "触发", "锁冲突与阻塞", "并发瓶颈")
    rag_engine.add_relation("行级锁竞争", "系统异常", "解决方案A", "SELECT FOR UPDATE NOWAIT", "SQL控制")
    rag_engine.add_relation("行级锁竞争", "系统异常", "解决方案B", "乐观锁", "应用控制")
    rag_engine.add_relation("乐观锁", "应用控制", "使用", "版本号对比", "设计范式")
    
    print(f"-> 内存属性图初始化成功，共包含 {len(rag_engine.graph)} 个实体节点。\n")


async def main():
    """本地手动调试主入口"""
    print("=== 开始 Day 54 Mock GraphRAG 全局检索本地调试 (标准答案) ===\n")
    
    try:
        llm = LLMClient()
    except Exception as e:
        print(f"大模型客户端初始化失败 (检查 .env 配置文件): {e}")
        return

    rag = MockGraphRAG(llm)
    build_test_graph(rag)

    # 1. 尝试执行社区发现与总结
    try:
        print("--- [步骤 1] 正在进行连通社区检测 (模拟 Leiden) ---")
        communities = rag.partition_communities()
        for idx, comm in enumerate(communities):
            print(f"  社区 {idx+1} 包含实体: {comm}")
            
        print("\n--- [步骤 2] 正在并发生成各社区的主题总结报告 (Map 阶段) ---")
        summaries = await rag.generate_community_summaries(communities)
        for idx, report in summaries.items():
            print(f"\n[社区 {idx} 报告摘要]:\n{report}\n" + "-"*40)
            
        # 全局问题：提问包含 Redis 网络故障和 PG 锁竞争两个完全隔离的话题
        query = "高并发下中间件数据库层面有哪些常见的系统异常风险？具体的参数或策略规避方案是什么？"
        print(f"\n--- [步骤 3] 执行 Global Search (Reduce 阶段) ---\n提问: '{query}'\n")
        
        final_answer = await rag.global_search(query)
        print(f"【GraphRAG 全局检索回答】:\n{final_answer}\n")

    except Exception as e:
        print(f"\n❌ 运行发生未预期错误: {e}")


if __name__ == "__main__":
    asyncio.run(main())
