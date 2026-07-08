"""
Day 41 参考答案 — 跨语言检索与 Embedding 表征漂移检测

设计方案：
==========
1. 设计意图：
   本文件是 Day 41 的标准参考答案实现。多语言 Embedding 模型（如 MiniMax `embo-01`）为跨语言检索提供了空间对齐能力。
   然而，在面对高难度、专业性强的计算机垂直领域词汇时，由于多语言预训练语料分布稀疏、Tokenizer 退化等原因，
   语义对齐精度会发生系统性下滑，即“表征漂移 (Representation Drift)”。
   为了定量测算这一现象，本类使用 numpy 离线手写了余弦相似度度量，并对 10 组日常通用句对和 10 组专业技术句对进行并发向量化与距离分析，
   为生产级 RAG 系统跨语种卡控相似度阈值提供量化指标和架构决策。

2. 关键组件结构：
   - CrossLingualDriftDetector: 核心漂移测算类
     - calculate_cosine_similarity(): numpy 离线计算余弦值，包含零模长安全边界控制。
     - detect_cross_lingual_similarity(): 异步并发向量化中英文本并成对匹配相似度。
     - measure_representation_drift(): 计算两类对齐语料的平均对齐度，差值量化漂移指标。

3. 关键数据流向与 Benchmark 验证：
   - 实例化 `CrossLingualDriftDetector` 探测本地 `.env` 配置并初始化 API 请求端。
   - 配置日常标准对与垂直技术对（中英对齐）。
   - 异步并发拉取 40 个句子的 Embedding 向量。
   - 离线计算每对的余弦相似度并打印成对比 Markdown 表格形式。
   - 测算 Drift 值，自动为 Agent RAG 提供设防阈值的工程建议。

使用方式（在项目根目录）：
    python -m weekly.w06_embedding_and_vector_db.day41.drift_detector
"""
from __future__ import annotations

import asyncio
import numpy as np
import sys
from weekly.w06_embedding_and_vector_db.utils import EmbeddingClient


# ══════════════════════════════════════════════════════════════════════════════
# 板块一：CrossLingualDriftDetector 完整实现
# ══════════════════════════════════════════════════════════════════════════════

class CrossLingualDriftDetector:
    """跨语言对齐度量与表征漂移量化分析类"""

    def __init__(self) -> None:
        """初始化多语言 Embedding 异步请求客户端。"""
        # 初始化大模型 API 客户端（将自动读取本地 .env 环境变量配置）
        self.embedding_client = EmbeddingClient()

    def calculate_cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """计算两个高维空间向量之间的余弦相似度。

        Args:
            vec1: 一维浮点数向量 1
            vec2: 一维浮点数向量 2

        Returns:
            float: 范围在 [-1.0, 1.0] 的余弦夹角值
        """
        # Step 1: 输入防御校验
        if len(vec1) != len(vec2):
            raise ValueError(f"向量 vec1 维度 ({len(vec1)}) 与 vec2 维度 ({len(vec2)}) 不一致，无法计算！")

        # Step 2: 转化为 numpy 浮点数组，以便使用矢量化乘法加速
        v1 = np.array(vec1, dtype=np.float32)
        v2 = np.array(vec2, dtype=np.float32)

        # Step 3: 计算点积与 L2 范数（模长）
        dot_product = np.dot(v1, v2)
        norm_v1 = np.linalg.norm(v1)
        norm_v2 = np.linalg.norm(v2)

        # Step 4: 零模长防崩溃保护
        if norm_v1 == 0.0 or norm_v2 == 0.0:
            return 0.0

        # Step 5: 余弦相似度计算并转换为原生 float
        cosine_sim = dot_product / (norm_v1 * norm_v2)
        return float(cosine_sim)

    async def detect_cross_lingual_similarity(
        self,
        zh_texts: list[str],
        en_texts: list[str]
    ) -> list[float]:
        """批量将中文与英文对齐句子向量化，并按对计算它们在空间中的余弦对齐相似度。

        Args:
            zh_texts: 中文文本列表
            en_texts: 对应对齐的英文文本列表

        Returns:
            list[float]: 按位置对应的一组余弦相似度列表
        """
        # Step 1: 输入防御校验
        if len(zh_texts) != len(en_texts):
            raise ValueError(f"中文文本数 ({len(zh_texts)}) 与英文文本数 ({len(en_texts)}) 不匹配！")

        # Step 2: 异步并发向 API 发起中英文向量化请求
        # 中文通常是用户 Query，因此推荐使用 embed_type="query"；
        # 英文通常是知识库文档，因此推荐使用 embed_type="db"
        tasks = [
            self.embedding_client.embed_texts(zh_texts, embed_type="query"),
            self.embedding_client.embed_texts(en_texts, embed_type="db")
        ]
        
        # 阻塞等待中英两个批次并发请求返回
        zh_vectors, en_vectors = await asyncio.gather(*tasks)

        # Step 3: 循环按对计算余弦相似度
        similarities = []
        for zh_vec, en_vec in zip(zh_vectors, en_vectors):
            sim = self.calculate_cosine_similarity(zh_vec, en_vec)
            similarities.append(sim)

        return similarities

    async def measure_representation_drift(
        self,
        standard_pairs: list[tuple[str, str]],
        domain_pairs: list[tuple[str, str]]
    ) -> dict:
        """测算通用场景与垂直专业场景的对齐相似度，并量化评估表征漂移度。

        Args:
            standard_pairs: 日常通用语境下的中英对照句对列表
            domain_pairs: 垂直专业（如计算机/大模型工程）语境下的中英对照句对列表

        Returns:
            dict: 包含各项平均对齐度指标与漂移差值的字典
        """
        # Step 1: 解包并计算通用领域余弦对齐均值
        zh_std = [p[0] for p in standard_pairs]
        en_std = [p[1] for p in standard_pairs]
        
        print(f"⏳ 正在拉取通用领域 ({len(standard_pairs)} 组) 对齐文本向量...")
        std_sims = await self.detect_cross_lingual_similarity(zh_std, en_std)
        std_avg = float(np.mean(std_sims))
        
        # Step 2: 解包并计算专业领域余弦对齐均值
        zh_dom = [p[0] for p in domain_pairs]
        en_dom = [p[1] for p in domain_pairs]
        
        print(f"⏳ 正在拉取专业领域 ({len(domain_pairs)} 组) 对齐文本向量...")
        dom_sims = await self.detect_cross_lingual_similarity(zh_dom, en_dom)
        dom_avg = float(np.mean(dom_sims))

        # Step 3: 计算空间表征漂移量 (Drift Value)
        # 漂移值正向越大，表示模型在专业垂直领域对齐能力退化越严重
        drift = std_avg - dom_avg

        return {
            "standard_sims": std_sims,
            "domain_sims": dom_sims,
            "standard_avg": std_avg,
            "domain_avg": dom_avg,
            "representation_drift": drift
        }


# ══════════════════════════════════════════════════════════════════════════════
# 板块二：日常与专业垂直对照组 Benchmark 分析入口
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("======================================================================")
    print("🏆 Day 41 过关验证：中英文跨语言检索与 Embedding 空间表征漂移检测量化")
    print("======================================================================")

    # 1. 构造 10 组日常通用情境句对（Standard Domain）
    std_test_pairs = [
        ("你好，很高兴认识你。", "Hello, nice to meet you."),
        ("今天天气晴朗，阳光充足。", "Today the weather is clear and sunny."),
        ("你喜欢看什么类型的电影？", "What kind of movies do you like to watch?"),
        ("请问最近的地铁站在哪里？", "Excuse me, where is the nearest subway station?"),
        ("这是一篇关于旅行的日常博客。", "This is a daily blog about traveling."),
        ("我预订了一家靠近市中心的酒店。", "I booked a hotel close to the city center."),
        ("运动有助于保持身体健康。", "Exercise helps to keep the body healthy."),
        ("晚饭你想吃些什么？", "What would you like to eat for dinner?"),
        ("请帮我买一张去北京的火车票。", "Please help me buy a train ticket to Beijing."),
        ("在这个周末，我们打算去公园野餐。", "This weekend, we plan to have a picnic in the park.")
    ]

    # 2. 构造 10 组深水垂直专业开发情境句对（Technical Domain）
    # 词汇涉及 HNSW 图索引、并发控制、指数退避、SQLite 死锁、元数据前过滤等硬核概念
    dom_test_pairs = [
        ("使用自适应指数退避与随机抖动重试来防止网络限流引发的崩溃。", "Use adaptive exponential backoff and random jitter retry to prevent crashes caused by network rate limiting."),
        ("为了提高向量检索的效率，我们在Qdrant中为元数据构建了Payload属性索引。", "To improve vector retrieval efficiency, we constructed Payload attribute indexes for metadata in Qdrant."),
        ("利用跳表的多层有向图结构实现了近似最近邻搜索的HNSW索引算法。", "Using the multi-layer directed graph structure of skip lists, the HNSW index algorithm for approximate nearest neighbor search is implemented."),
        ("在多线程并发写入时，必须防止SQLite数据库发生死锁或者锁竞争异常。", "During multi-threaded concurrent writes, deadlocks or lock contention exceptions in the SQLite database must be prevented."),
        ("向量维度裁剪通过损失少许边缘维度，将1536维压缩为256维以节省存储。", "Vector dimension truncation compresses 1536 dimensions to 256 dimensions to save storage by losing a few edge dimensions."),
        ("利用余弦相似度度量来评估两个经过L2归一化的向量方向夹角偏差。", "Using cosine similarity metric to evaluate the angular deviation of two L2-normalized vectors."),
        ("先向量检索再Python属性过滤的后过滤模式容易造成检索空置现象。", "The post-filtering mode, which performs vector retrieval followed by Python attribute filtering, is prone to recall drop."),
        ("大语言模型和向量模型对原始HTML中的转义符以及多余空行非常敏感。", "Large language models and embedding models are highly sensitive to escape characters and redundant blank lines in raw HTML."),
        ("我们通过在底层对分类字段和可读权限实施前过滤以杜绝越权检索。", "We implement pre-filtering on classification fields and readable permissions at the bottom to eliminate unauthorized retrieval."),
        ("在多租户Agent框架中，每个会话应当具备独立的上下文裁剪和故障降级机制。", "In a multi-tenant Agent framework, each session should possess an independent context pruning and failover fallback mechanism.")
    ]

    async def main():
        try:
            # 初始化检测类
            detector = CrossLingualDriftDetector()
            
            # 执行量化度量
            report = await detector.measure_representation_drift(std_test_pairs, dom_test_pairs)
            
            # 3. 打印中英双语对齐相似度详情表格
            print("\n" + "="*80)
            print("📊 中英句对空间余弦相似度对比表格")
            print("="*80)
            print("| 序号 | 通用对话句对余弦值 | 专业技术句对余弦值 | 对齐度偏差 (通用 - 专业) |")
            print("|---|---|---|---|")
            for idx in range(10):
                std_val = report["standard_sims"][idx]
                dom_val = report["domain_sims"][idx]
                diff_val = std_val - dom_val
                print(f"|  {idx+1:02d}  |      {std_val:.4f}        |      {dom_val:.4f}        |        {diff_val:+.4f}         |")
            print("="*80)
            
            # 4. 打印均值与漂移分析结果
            print("\n📈 空间表征漂移量化分析结果：")
            print(f"   - 通用领域（Standard Domain）中英平均对齐度: {report['standard_avg']:.4f}")
            print(f"   - 专业技术（Technical Domain）中英平均对齐度: {report['domain_avg']:.4f}")
            print(f"   - 表征漂移偏差 (Representation Drift Value): {report['representation_drift']:.4f}")
            
            print("\n💡 生产环境 RAG 相似度卡控阈值 (Threshold) 工程决策指南：")
            # 依据科学漂移度推荐阈值设防
            base_threshold = 0.85
            recommended_threshold = base_threshold - report["representation_drift"]
            print(f"1. **单阈值弊端**：若系统统一硬性设置 RAG 过滤阈值为 `{base_threshold:.2f}`，")
            print(f"   所有平均对齐度仅有 `{report['domain_avg']:.4f}` 的高相关专业英文文档块将被系统在底层全部误杀丢弃！")
            print(f"2. **自适应阈值设防**：对于专业硬核知识库的跨语言检索，推荐将过滤阈值自适应卡控线下调至 `{recommended_threshold:.2f}`，")
            print("   从而在规避噪声的同时，确保核心关键技术语料能够被成功召回并喂给大模型。")
            print("="*80)
            print("🏁 Day 41 过关压测测试结束！")

        except Exception as e:
            print("\n💥 运行过程中抛出意外异常:")
            import traceback
            traceback.print_exc()

    # 运行异步事件循环
    asyncio.run(main())
