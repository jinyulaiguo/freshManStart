"""
微引擎 8：检索质量评估引擎 (RetrievalEvaluator)

设计方案：
==========
1. 设计意图：
   原设计只关注检索速度（15ms），但检索"快而不准"等于无效。
   生产级 RAG 系统必须能量化"找到的答案到底对不对"。
   本引擎实现四个核心信息检索质量指标：
   - Recall@K: Top-K 中命中了多少正确答案（最重要的 RAG 指标）
   - Precision@K: Top-K 中有多少是真相关的
   - MRR: 第一个正确答案出现得多靠前
   - NDCG@K: 带位置衰减的累积增益归一化（区分排名质量）

2. 关键组件结构：
   - RetrievalEvaluator: 检索质量评估引擎
     - recall_at_k(): 单样本 Recall@K 计算
     - precision_at_k(): 单样本 Precision@K 计算
     - reciprocal_rank(): 单样本 MRR 的分子部分
     - ndcg_at_k(): 单样本 NDCG@K 计算
     - evaluate_single(): 单样本全指标评估
     - evaluate_batch(): 批量评估并汇总平均值
     - format_report(): 格式化输出评估报告

3. 关键数据流：
   EvalSample[] + RetrievalResponse[]
     → evaluate_batch()
     → 逐样本计算 Recall/Precision/MRR/NDCG
     → 求均值输出 EvalMetrics

使用方式（在项目根目录）：
    python -m weekly.w06_embedding_and_vector_db.project.evaluator
"""
from __future__ import annotations

import math

from weekly.w06_embedding_and_vector_db.project.models import (
    EvalSample,
    EvalMetrics,
    SearchResult,
    RetrievalStrategy,
)


# ══════════════════════════════════════════════════════════════════════════════
# 板块一：RetrievalEvaluator — 检索质量评估引擎
# ══════════════════════════════════════════════════════════════════════════════

class RetrievalEvaluator:
    """检索质量评估引擎。

    基于"黄金标准"标注数据集（EvalSample），对检索系统返回的结果
    进行四维度量化评估。所有指标计算均为纯离线数值运算，不依赖任何
    外部服务。

    指标说明：
    - Recall@K: |retrieved ∩ relevant| / |relevant|
      衡量"找全了多少"，是 RAG 系统最核心的指标
    - Precision@K: |retrieved ∩ relevant| / K
      衡量"找的有多准"，K 固定所以分母是 K 而非 |retrieved|
    - MRR (Mean Reciprocal Rank): 1 / rank_of_first_relevant
      衡量"第一个正确答案排多高"
    - NDCG@K (Normalized Discounted Cumulative Gain):
      衡量"排名质量"，越靠前的相关结果贡献越大

    Attributes:
        default_k: 默认的 K 值
    """

    def __init__(self, default_k: int = 5) -> None:
        """初始化评估器。

        Args:
            default_k: 默认的 K 值（用于 @K 系列指标）
        """
        self.default_k = default_k

    def recall_at_k(
        self,
        retrieved_ids: list[str],
        relevant_ids: list[str],
        k: int | None = None,
    ) -> float:
        """计算单样本的 Recall@K。

        Recall@K = |retrieved_top_k ∩ relevant| / |relevant|

        如果 relevant 集合为空，返回 0.0（避免除零）。

        Args:
            retrieved_ids: 检索返回的 Chunk ID 列表（已按排名排序）
            relevant_ids: 人工标注的正确答案 Chunk ID 列表
            k: K 值（默认使用 self.default_k）

        Returns:
            float: Recall@K 值，范围 [0.0, 1.0]
        """
        k = k or self.default_k
        if not relevant_ids:
            return 0.0

        top_k_set = set(retrieved_ids[:k])
        relevant_set = set(relevant_ids)
        hits = len(top_k_set & relevant_set)

        return hits / len(relevant_set)

    def precision_at_k(
        self,
        retrieved_ids: list[str],
        relevant_ids: list[str],
        k: int | None = None,
    ) -> float:
        """计算单样本的 Precision@K。

        Precision@K = |retrieved_top_k ∩ relevant| / K

        Args:
            retrieved_ids: 检索返回的 Chunk ID 列表
            relevant_ids: 正确答案 Chunk ID 列表
            k: K 值

        Returns:
            float: Precision@K 值，范围 [0.0, 1.0]
        """
        k = k or self.default_k
        if k <= 0:
            return 0.0

        top_k_set = set(retrieved_ids[:k])
        relevant_set = set(relevant_ids)
        hits = len(top_k_set & relevant_set)

        return hits / k

    def reciprocal_rank(
        self,
        retrieved_ids: list[str],
        relevant_ids: list[str],
    ) -> float:
        """计算单样本的 Reciprocal Rank（MRR 的分子部分）。

        RR = 1 / rank_of_first_relevant_result

        如果检索结果中没有任何正确答案，返回 0.0。

        Args:
            retrieved_ids: 检索返回的 Chunk ID 列表
            relevant_ids: 正确答案 Chunk ID 列表

        Returns:
            float: Reciprocal Rank 值，范围 [0.0, 1.0]
        """
        relevant_set = set(relevant_ids)

        for rank, chunk_id in enumerate(retrieved_ids, start=1):
            if chunk_id in relevant_set:
                return 1.0 / rank

        return 0.0

    def ndcg_at_k(
        self,
        retrieved_ids: list[str],
        relevant_ids: list[str],
        k: int | None = None,
    ) -> float:
        """计算单样本的 NDCG@K (Normalized Discounted Cumulative Gain)。

        NDCG@K = DCG@K / IDCG@K

        DCG@K = Σ(i=1 to K) rel_i / log2(i + 1)
        IDCG@K = 理想排序下的 DCG@K

        其中 rel_i = 1（如果第 i 位是正确答案），否则为 0（二元相关性）。

        Args:
            retrieved_ids: 检索返回的 Chunk ID 列表
            relevant_ids: 正确答案 Chunk ID 列表
            k: K 值

        Returns:
            float: NDCG@K 值，范围 [0.0, 1.0]
        """
        k = k or self.default_k
        relevant_set = set(relevant_ids)

        # 计算 DCG@K（实际排序）
        dcg = 0.0
        for i in range(min(k, len(retrieved_ids))):
            if retrieved_ids[i] in relevant_set:
                # 位置从 1 开始计数，所以 log2(i + 2)
                dcg += 1.0 / math.log2(i + 2)

        # 计算 IDCG@K（理想排序：所有正确答案排在最前面）
        num_relevant = min(len(relevant_ids), k)
        idcg = 0.0
        for i in range(num_relevant):
            idcg += 1.0 / math.log2(i + 2)

        if idcg == 0.0:
            return 0.0

        return dcg / idcg

    def evaluate_single(
        self,
        retrieved_ids: list[str],
        relevant_ids: list[str],
        k: int | None = None,
    ) -> dict[str, float]:
        """对单个样本计算全部四个指标。

        Args:
            retrieved_ids: 检索返回的 Chunk ID 列表
            relevant_ids: 正确答案 Chunk ID 列表
            k: K 值

        Returns:
            dict: 包含 recall, precision, rr, ndcg 四个指标值
        """
        k = k or self.default_k
        return {
            "recall": self.recall_at_k(retrieved_ids, relevant_ids, k),
            "precision": self.precision_at_k(retrieved_ids, relevant_ids, k),
            "rr": self.reciprocal_rank(retrieved_ids, relevant_ids),
            "ndcg": self.ndcg_at_k(retrieved_ids, relevant_ids, k),
        }

    def evaluate_batch(
        self,
        eval_samples: list[EvalSample],
        retrieved_results: list[list[SearchResult]],
        k: int | None = None,
        strategy: RetrievalStrategy = RetrievalStrategy.HYBRID,
    ) -> EvalMetrics:
        """批量评估多个样本并汇总平均值。

        Args:
            eval_samples: 评估样本列表（含黄金标准答案）
            retrieved_results: 每个样本对应的检索结果列表
            k: K 值
            strategy: 评估使用的检索策略标识

        Returns:
            EvalMetrics: 汇总后的平均评估指标

        Raises:
            ValueError: eval_samples 和 retrieved_results 长度不一致
        """
        k = k or self.default_k

        if len(eval_samples) != len(retrieved_results):
            raise ValueError(
                f"样本数 ({len(eval_samples)}) 与结果数 ({len(retrieved_results)}) 不一致"
            )

        if not eval_samples:
            return EvalMetrics(k=k, num_samples=0, strategy=strategy)

        # 逐样本计算指标
        total_recall = 0.0
        total_precision = 0.0
        total_rr = 0.0
        total_ndcg = 0.0

        for sample, results in zip(eval_samples, retrieved_results):
            retrieved_ids = [r.chunk_id for r in results]
            metrics = self.evaluate_single(
                retrieved_ids=retrieved_ids,
                relevant_ids=sample.expected_chunk_ids,
                k=k,
            )
            total_recall += metrics["recall"]
            total_precision += metrics["precision"]
            total_rr += metrics["rr"]
            total_ndcg += metrics["ndcg"]

        n = len(eval_samples)

        return EvalMetrics(
            recall_at_k=round(total_recall / n, 4),
            precision_at_k=round(total_precision / n, 4),
            mrr=round(total_rr / n, 4),
            ndcg_at_k=round(total_ndcg / n, 4),
            k=k,
            num_samples=n,
            strategy=strategy,
        )

    def format_report(self, metrics: EvalMetrics) -> str:
        """格式化输出评估报告。

        Args:
            metrics: 评估指标结果

        Returns:
            str: 格式化的报告文本
        """
        lines = [
            "┌─────────────────────────────────────────┐",
            "│      Retrieval Quality Evaluation        │",
            "├─────────────────────────────────────────┤",
            f"│  Strategy:       {metrics.strategy.value:<22} │",
            f"│  Samples:        {metrics.num_samples:<22} │",
            f"│  K:              {metrics.k:<22} │",
            "├─────────────────────────────────────────┤",
            f"│  Recall@{metrics.k}:       {metrics.recall_at_k:<22.4f} │",
            f"│  Precision@{metrics.k}:    {metrics.precision_at_k:<22.4f} │",
            f"│  MRR:            {metrics.mrr:<22.4f} │",
            f"│  NDCG@{metrics.k}:        {metrics.ndcg_at_k:<22.4f} │",
            "└─────────────────────────────────────────┘",
        ]
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 主入口：评估引擎功能演示
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  微引擎 8：检索质量评估引擎 — 功能演示")
    print("=" * 70)

    evaluator = RetrievalEvaluator(default_k=5)

    # --- 演示 1：理想场景（全部命中，排名靠前） ---
    print("\n  📊 场景 1：理想检索（正确答案排在 #1 和 #2）")
    m1 = evaluator.evaluate_single(
        retrieved_ids=["c1", "c2", "c3", "c4", "c5"],
        relevant_ids=["c1", "c2"],
    )
    print(f"    Recall@5={m1['recall']:.4f}, Precision@5={m1['precision']:.4f}, "
          f"RR={m1['rr']:.4f}, NDCG@5={m1['ndcg']:.4f}")

    # --- 演示 2：部分命中（正确答案在 #3 和 #5） ---
    print("\n  📊 场景 2：部分命中（正确答案在 #3 和 #5）")
    m2 = evaluator.evaluate_single(
        retrieved_ids=["x1", "x2", "c1", "x3", "c2"],
        relevant_ids=["c1", "c2"],
    )
    print(f"    Recall@5={m2['recall']:.4f}, Precision@5={m2['precision']:.4f}, "
          f"RR={m2['rr']:.4f}, NDCG@5={m2['ndcg']:.4f}")

    # --- 演示 3：完全未命中 ---
    print("\n  📊 场景 3：完全未命中")
    m3 = evaluator.evaluate_single(
        retrieved_ids=["x1", "x2", "x3", "x4", "x5"],
        relevant_ids=["c1", "c2"],
    )
    print(f"    Recall@5={m3['recall']:.4f}, Precision@5={m3['precision']:.4f}, "
          f"RR={m3['rr']:.4f}, NDCG@5={m3['ndcg']:.4f}")

    # --- 演示 4：批量评估 ---
    print("\n  📊 场景 4：批量评估（3 个样本）")
    samples = [
        EvalSample(question="Q1", expected_chunk_ids=["c1", "c2"], category="test"),
        EvalSample(question="Q2", expected_chunk_ids=["c3"], category="test"),
        EvalSample(question="Q3", expected_chunk_ids=["c4", "c5"], category="test"),
    ]
    results = [
        [SearchResult(chunk_id="c1", content="", score=0.9, rank=1),
         SearchResult(chunk_id="c2", content="", score=0.8, rank=2),
         SearchResult(chunk_id="x1", content="", score=0.7, rank=3)],
        [SearchResult(chunk_id="x2", content="", score=0.9, rank=1),
         SearchResult(chunk_id="c3", content="", score=0.8, rank=2),
         SearchResult(chunk_id="x3", content="", score=0.7, rank=3)],
        [SearchResult(chunk_id="x4", content="", score=0.9, rank=1),
         SearchResult(chunk_id="x5", content="", score=0.8, rank=2),
         SearchResult(chunk_id="x6", content="", score=0.7, rank=3)],
    ]
    batch_metrics = evaluator.evaluate_batch(samples, results, k=5)
    report = evaluator.format_report(batch_metrics)
    print(report)

    # --- 验证指标正确性 ---
    print("\n  🔬 指标正确性验证:")
    # 场景 1 的理论值
    assert m1["recall"] == 1.0, f"Recall 应为 1.0, 实际 {m1['recall']}"
    assert m1["precision"] == 0.4, f"Precision 应为 0.4, 实际 {m1['precision']}"
    assert m1["rr"] == 1.0, f"RR 应为 1.0, 实际 {m1['rr']}"
    print("    ✅ 场景 1 指标计算正确")

    # 场景 3 应全部为 0
    assert m3["recall"] == 0.0
    assert m3["precision"] == 0.0
    assert m3["rr"] == 0.0
    assert m3["ndcg"] == 0.0
    print("    ✅ 场景 3 指标计算正确")

    print(f"\n{'=' * 70}")
    print("  检索质量评估引擎功能演示完成 ✅")
    print("=" * 70)
