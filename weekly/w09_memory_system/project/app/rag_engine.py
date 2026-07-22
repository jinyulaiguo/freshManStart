"""
RAG Engine Module.

设计方案说明：
1. **设计意图**：
   本模块提供专业外部知识库检索器（RAG Engine）。
   当自适应路由器（Memory Router）判定用户的提问属于“客观大文档专业知识（RAG Branch）”时，
   系统将在本模块中执行文本相似度召回。
2. **核心机制与依赖**：
   - 依赖 `jieba` 分词器和 `rank_bm25` (BM25Okapi) 算法，实现完全本地化的高精准文本检索，摆脱远程 Embedding 网络的超时重试依赖，极其健壮稳定。
   - 知识库中预置了有关第九周记忆工程的核心技术文档（如 MemGPT, Mem0, Letta, Sliding Window 等的核心设计理念）。
3. **类与函数结构**：
   - `RAGEngine`: 本地客观文档检索器类。
     - `retrieve(query, limit)`: 输入 Query，对其进行 jieba 分词后，通过 BM25 计算最相关的知识条目并返回。
"""

import sys
import os
from typing import List, Dict, Any

# 确保导入 config
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    import jieba
    from rank_bm25 import BM25Okapi
    # 禁用 jieba 的默认 stdout 调试日志，以保持审计日志纯净
    jieba.setLogLevel(20)
except ImportError as e:
    raise RuntimeError(f"RAG 引擎依赖缺包 (jieba / rank-bm25)，请先确认安装。错误: {e}")

class RAGEngine:
    """基于本地 BM25Okapi 与结巴分词的外部专业知识 RAG 检索微引擎。"""

    def __init__(self):
        """初始化 RAG 引擎，加载预置的技术知识库文档并构建 BM25 倒排索引。"""
        # 预设的第九周记忆工程与状态管理客观技术库
        self.documents = [
            "MemGPT (2023): 首次提出将操作系统的虚拟内存管理机制（L1/L2 缓存与 Disk 映射）引入大语言模型（LLM）的状态管理，主要通过主动的 Memory Swap (I/O 交换) 解决 Context 窗口暴涨的问题。",
            "Letta (2025): 前身为 MemGPT，是一种面向生产级多进程高可用 Agent 的持久化状态管理服务框架，解耦了 Agent 核心逻辑与底层的 ACID 持久化数据库。",
            "Mem0 (2024-2025): 摒弃了大段的全局 Summary 摘要归约模式，开创了基于实体与关系图谱的增量 facts 提取与写入机制，大幅度降低了信息稀释与漂移问题。",
            "StreamingLLM: 利用 KV Cache 缓存压缩机制和 Attention 滑动窗口（保持 Attention Sink 头部），实现无限长文本流的流式对话输入，且不引起时延爆炸。",
            "Ebbinghaus Forgetting Curve (艾宾浩斯遗忘曲线): 在长期事实记忆的持久化管理中，引入指数衰减模型 W = exp(-decay_rate * delta_t)，重算 Facts 的权重以剔除低值冷事实，解决大模型输入矛盾与幻觉。",
            "HyDE (假设性文档检索): 一种 RAG 检索增强技术，LLM 先生成一个符合 Query 的假想回答（Hypothetical Document），然后再用这个假想回答去向量库检索相似文档，有效解决 Query 和 Doc 的语义空间不重叠问题。",
            "Lost in the Middle (迷失在中间): LLM 易在长上下文的中段丢失核心信息，Rerank (重排) 技术通过将最相关的 Top 召回文档重组至上下文的最前和最尾两端来克服该硬件级局限。"
        ]
        
        # 步骤 1: 对预存库文档进行中文分词预处理
        self.tokenized_docs = [list(jieba.cut(doc)) for doc in self.documents]
        
        # 步骤 2: 构建 BM25 检索实例
        self.bm25 = BM25Okapi(self.tokenized_docs)

    def retrieve(self, query: str, limit: int = 2) -> List[str]:
        """执行外部知识检索。

        Args:
            query: 用户输入的客观提问。
            limit: 最大返回的文档条数。

        Returns:
            最相关的文档字符串列表。若没有检索到高度相关内容，则返回空列表。
        """
        # 步骤 1: 判定输入合法性
        if not query or not query.strip():
            return []
            
        # 步骤 2: 对 Query 进行与文档库一致的分词处理
        query_tokens = list(jieba.cut(query))
        
        # 步骤 3: 运行 BM25 算法计算得分并提取 Top-N 文档
        scores = self.bm25.get_scores(query_tokens)
        
        # 步骤 4: 结合得分进行过滤。为防止强召回无关文档，若 BM25 分数极低（接近 0），我们防御性过滤掉它们
        # 这里进行快速关联性排序
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:limit]
        
        results: List[str] = []
        for idx in top_indices:
            # BM25 大于 0.1 代表具有一定关联词重合度
            if scores[idx] > 0.1:
                results.append(self.documents[idx])
                
        print(f"[RAGEngine] 检索完成。Query: \"{query}\"，召回文档数: {len(results)}")
        return results
