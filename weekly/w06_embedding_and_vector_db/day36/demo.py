"""
Day 36 参考标准答案 — 文本向量化（Embedding）数学直觉与表征限制

设计方案：
==========
1. 设计意图：
   通过真实 MiniMax Embedding API (embo-01) 调用获取文本向量，使用 numpy
   手动实现余弦相似度（Cosine Similarity）与欧氏距离（L2 Distance）的计算，
   对多组精心构造的测试样本进行定量分析，揭示不同距离度量的几何物理意义差异，
   以及反讽、转折等复杂语义在高维空间中的表征退化（Representation Degradation）
   现象。

2. 核心类与函数结构：
   - EmbeddingAnalyzer 类：
     ├── cosine_similarity(vec_a, vec_b) → float   # 手动余弦相似度
     ├── l2_distance(vec_a, vec_b) → float          # 手动欧氏距离
     ├── truncate_vector(vec, dim) → ndarray         # Matryoshka 维度裁剪
     ├── analyze_pair(text_a, text_b) → dict         # 单对文本距离分析
     └── truncation_comparison(text_a, text_b, dims) # 裁剪对比分析

3. 关键数据流：
   TEST_CASES 测试样本集
   → EmbeddingClient.embed_texts() 获取高维向量
   → numpy 手动计算 cosine_similarity() / l2_distance()
   → 格式化为对比表格输出到 stdout

4. 演示场景（三组实验）：
   - 演示一：六组文本对的 余弦 vs L2 对比表格
   - 演示二：Matryoshka 维度裁剪的余弦保留率
   - 演示三：反讽/转折/否定的表征退化量化

使用方式（在项目根目录）：
    python -m weekly.w06_embedding_and_vector_db.day36.demo

需要有效的 MINIMAX_API_KEY 环境变量（通过 .env 文件配置）。
"""
from __future__ import annotations

import asyncio
import numpy as np

from weekly.w06_embedding_and_vector_db.utils import EmbeddingClient


# ══════════════════════════════════════════════════════════════════════════════
# 板块一：EmbeddingAnalyzer — 向量距离分析引擎
# ══════════════════════════════════════════════════════════════════════════════

class EmbeddingAnalyzer:
    """Embedding 向量距离分析引擎

    设计意图：
        封装余弦相似度和欧氏距离的手动 numpy 实现，并提供
        "文本对向量化 → 距离计算 → 对比分析" 的完整工作流。

    核心方法：
        - cosine_similarity: 余弦相似度（方向偏差度量）
        - l2_distance: 欧氏距离（空间位移度量）
        - truncate_vector: Matryoshka 维度裁剪
        - analyze_pair: 文本对距离分析（含向量缓存）
        - truncation_comparison: 多维度裁剪对比

    Attributes:
        client: MiniMax Embedding API 客户端实例
        _vector_cache: 文本→向量的本地缓存字典，避免重复 API 调用
    """

    def __init__(self) -> None:
        """初始化分析引擎，创建 API 客户端并初始化向量缓存。"""
        self.client = EmbeddingClient()
        self._vector_cache: dict[str, np.ndarray] = {}

    # ── 核心距离计算（纯 numpy 手动实现，不使用 sklearn 等高层封装）──

    @staticmethod
    def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        """计算两个向量的余弦相似度

        数学定义：cos(θ) = (a · b) / (||a|| × ||b||)
        物理意义：衡量两个向量在高维空间中的方向偏差，值越接近 1 方向越一致。

        Args:
            vec_a: 向量 A（一维 numpy 数组）
            vec_b: 向量 B（一维 numpy 数组）

        Returns:
            余弦相似度值，范围 [-1, 1]

        Raises:
            ValueError: 当两个向量维度不匹配时抛出
        """
        # Step 1: 维度一致性校验
        if vec_a.shape != vec_b.shape:
            raise ValueError(
                f"向量维度不匹配: vec_a.shape={vec_a.shape}, "
                f"vec_b.shape={vec_b.shape}"
            )

        # Step 2: 计算点积（分子）—— 各维度对应元素乘积之和
        dot_product = np.dot(vec_a, vec_b)

        # Step 3: 计算各自的 L2 范数（分母）
        norm_a = np.linalg.norm(vec_a)
        norm_b = np.linalg.norm(vec_b)

        # Step 4: 零向量防御 —— 避免除零异常
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        # Step 5: 返回余弦相似度
        return float(dot_product / (norm_a * norm_b))

    @staticmethod
    def l2_distance(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        """计算两个向量的欧氏距离（L2 Distance）

        数学定义：d = sqrt(Σ(a_i - b_i)²)
        物理意义：衡量两个点在高维空间中的直线位移距离。

        Args:
            vec_a: 向量 A（一维 numpy 数组）
            vec_b: 向量 B（一维 numpy 数组）

        Returns:
            欧氏距离值，范围 [0, +∞)

        Raises:
            ValueError: 当两个向量维度不匹配时抛出
        """
        # Step 1: 维度一致性校验
        if vec_a.shape != vec_b.shape:
            raise ValueError(
                f"向量维度不匹配: vec_a.shape={vec_a.shape}, "
                f"vec_b.shape={vec_b.shape}"
            )

        # Step 2: 计算差向量（逐维度相减）
        diff = vec_a - vec_b

        # Step 3: 计算差向量各维度的平方和
        squared_sum = np.sum(diff ** 2)

        # Step 4: 开平方根得到欧氏距离
        return float(np.sqrt(squared_sum))

    @staticmethod
    def truncate_vector(vec: np.ndarray, target_dim: int) -> np.ndarray:
        """维度裁剪（Matryoshka Representation Learning）

        将高维向量截断到指定维度。Matryoshka 训练策略要求模型将关键语义
        信息编码在前几个维度中，因此截断操作可在不显著损害表征质量的
        前提下大幅减少存储开销。

        裁剪操作本身是零计算开销的数组切片。

        Args:
            vec: 原始高维向量
            target_dim: 目标维度（必须 > 0 且 <= 原始维度）

        Returns:
            截断后的低维向量

        Raises:
            ValueError: 目标维度非法时抛出
        """
        if target_dim <= 0:
            raise ValueError(f"目标维度必须 > 0，当前为 {target_dim}")
        if target_dim > len(vec):
            raise ValueError(
                f"目标维度 {target_dim} 超过原始维度 {len(vec)}"
            )
        return vec[:target_dim]

    # ── 向量化与缓存 ──

    async def _get_vectors(self, texts: list[str]) -> list[np.ndarray]:
        """获取文本向量（带本地缓存，避免重复 API 调用）

        缓存策略：以文本字符串为 key，向量为 value。
        仅对未命中缓存的文本发起 API 请求。

        Args:
            texts: 待向量化的文本列表

        Returns:
            与 texts 顺序一致的 numpy 向量列表
        """
        # Step 1: 筛选出未缓存的文本
        uncached_texts = [t for t in texts if t not in self._vector_cache]

        # Step 2: 仅对未缓存文本发起 API 请求
        if uncached_texts:
            raw_vectors = await self.client.embed_texts(uncached_texts)
            for text, vec in zip(uncached_texts, raw_vectors):
                self._vector_cache[text] = np.array(vec, dtype=np.float64)

        # Step 3: 按原始顺序返回（全部来自缓存）
        return [self._vector_cache[t] for t in texts]

    # ── 分析功能 ──

    async def analyze_pair(self, text_a: str, text_b: str) -> dict:
        """对比分析两段文本的完整距离指标

        Args:
            text_a: 文本 A
            text_b: 文本 B

        Returns:
            包含 cosine, l2, dim, norm_a, norm_b 的分析结果字典
        """
        vecs = await self._get_vectors([text_a, text_b])
        vec_a, vec_b = vecs[0], vecs[1]

        return {
            "text_a": text_a[:30] + ("..." if len(text_a) > 30 else ""),
            "text_b": text_b[:30] + ("..." if len(text_b) > 30 else ""),
            "cosine": self.cosine_similarity(vec_a, vec_b),
            "l2": self.l2_distance(vec_a, vec_b),
            "dim": len(vecs[0]),
            "norm_a": float(np.linalg.norm(vec_a)),
            "norm_b": float(np.linalg.norm(vec_b)),
        }

    async def truncation_comparison(
        self,
        text_a: str,
        text_b: str,
        dims: list[int],
    ) -> list[dict]:
        """维度裁剪对比：在多个维度下计算同一对文本的距离指标

        Args:
            text_a: 文本 A
            text_b: 文本 B
            dims: 要测试的维度列表（如 [64, 128, 256, 512]）

        Returns:
            每个维度对应的 {dim, cosine, l2, cosine_retention} 字典列表
        """
        vecs = await self._get_vectors([text_a, text_b])
        vec_a, vec_b = vecs[0], vecs[1]

        # 计算全维度基准余弦
        full_cosine = self.cosine_similarity(vec_a, vec_b)

        results = []
        for dim in dims:
            trunc_a = self.truncate_vector(vec_a, dim)
            trunc_b = self.truncate_vector(vec_b, dim)
            cos_val = self.cosine_similarity(trunc_a, trunc_b)
            results.append({
                "dim": dim,
                "cosine": cos_val,
                "l2": self.l2_distance(trunc_a, trunc_b),
                "cosine_retention": (
                    cos_val / full_cosine * 100 if full_cosine != 0 else 0.0
                ),
            })

        return results


# ══════════════════════════════════════════════════════════════════════════════
# 板块二：测试样本集 — 六组精心构造的文本对
# ══════════════════════════════════════════════════════════════════════════════

TEST_CASES: list[dict] = [
    {
        "group": "语义等价（同义改写）",
        "text_a": "这款手机的拍照效果非常出色，画面清晰细腻",
        "text_b": "这部手机的摄影功能很优秀，成像清楚且精致",
        "expected": "余弦 > 0.85：同义改写应保持高语义相似度",
    },
    {
        "group": "反讽表征退化",
        "text_a": "这个产品的质量真好",
        "text_b": "这个产品的质量真好，好到让我用了三天就坏了",
        "expected": "余弦仍然偏高（> 0.80）：反讽语义被前半段肯定词汇稀释",
    },
    {
        "group": "转折语义偏移",
        "text_a": "今天的天气非常好，阳光明媚",
        "text_b": "今天的天气非常好，但是我的心情糟透了",
        "expected": "余弦仍然偏高：转折后的否定语义权重被前半段覆盖",
    },
    {
        "group": "长短文本模长",
        "text_a": "机器学习",
        "text_b": (
            "机器学习是人工智能的一个重要分支领域，它利用统计学方法"
            "让计算机系统能够从历史数据中自动发现规律和模式，"
            "从而在没有显式编程指令的情况下完成预测和决策任务"
        ),
        "expected": "余弦不受模长影响保持合理值，L2 因长文本模长更大而显著增大",
    },
    {
        "group": "多义词歧义",
        "text_a": "苹果公司今天发布了新款智能手机",
        "text_b": "我今天在超市买了两斤新鲜的苹果",
        "expected": "余弦 < 0.80：相同词汇但语义完全不同，向量方向应有明显偏差",
    },
    {
        "group": "完全无关（基线）",
        "text_a": "量子力学中薛定谔方程的波函数坍缩现象",
        "text_b": "今天晚餐我想吃麻辣火锅配冰啤酒",
        "expected": "余弦最低，L2 为所有测试组中最大值",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# 板块三：演示主入口 — 三组对比实验
# ══════════════════════════════════════════════════════════════════════════════

def print_separator(title: str) -> None:
    """打印带标题的分隔线"""
    print(f"\n{'═' * 68}")
    print(f"  {title}")
    print(f"{'═' * 68}")


async def demo_distance_comparison() -> None:
    """演示一：六组文本对的余弦相似度 vs 欧氏距离对比分析

    验证要点：
    1. 同义改写的余弦相似度应 > 0.85
    2. 反讽/转折的余弦相似度仍然偏高（表征退化）
    3. 长短文本的余弦不受模长影响，但 L2 显著增大
    4. 完全无关文本的余弦最低
    """
    print_separator("演示一：余弦相似度 vs 欧氏距离 · 六组对比测试")

    analyzer = EmbeddingAnalyzer()

    # ── 打印对比表格 ──
    col_w = [22, 12, 12, 10, 10]
    header = (
        f"{'测试组':<{col_w[0]}}"
        f"{'余弦相似度':>{col_w[1]}}"
        f"{'L2 距离':>{col_w[2]}}"
        f"{'||a||':>{col_w[3]}}"
        f"{'||b||':>{col_w[4]}}"
    )
    sep_line = "─" * sum(col_w)

    print(f"\n{sep_line}")
    print(header)
    print(sep_line)

    for case in TEST_CASES:
        result = await analyzer.analyze_pair(case["text_a"], case["text_b"])
        print(
            f"{case['group']:<{col_w[0]}}"
            f"{result['cosine']:>{col_w[1]}.4f}"
            f"{result['l2']:>{col_w[2]}.4f}"
            f"{result['norm_a']:>{col_w[3]}.4f}"
            f"{result['norm_b']:>{col_w[4]}.4f}"
        )

    print(sep_line)

    # ── 逐组打印预期 vs 实测分析 ──
    print("\n── 逐组定量分析 ──")
    for case in TEST_CASES:
        result = await analyzer.analyze_pair(case["text_a"], case["text_b"])
        print(f"\n  [{case['group']}]")
        print(f"    文本 A: {case['text_a'][:50]}")
        print(f"    文本 B: {case['text_b'][:50]}")
        print(f"    预期: {case['expected']}")
        print(f"    实测: cosine={result['cosine']:.4f}, L2={result['l2']:.4f}")

    # 输出向量维度
    sample = await analyzer.analyze_pair(
        TEST_CASES[0]["text_a"], TEST_CASES[0]["text_b"]
    )
    print(f"\n  向量维度: {sample['dim']}")


async def demo_matryoshka_truncation() -> None:
    """演示二：维度裁剪（Matryoshka）余弦保留率对比

    验证要点：
    1. 从全维度逐步裁剪到低维度，余弦保留率应逐步下降
    2. 前 256 维通常能保留 > 90% 的余弦相似度
    """
    print_separator("演示二：维度裁剪（Matryoshka）· 余弦保留率")

    analyzer = EmbeddingAnalyzer()

    text_a = "深度学习通过多层神经网络自动提取数据的层次化特征表示"
    text_b = "神经网络模型利用反向传播算法逐层优化参数以学习数据表征"

    # 获取原始向量维度
    vecs = await analyzer._get_vectors([text_a])
    full_dim = len(vecs[0])

    # 构建测试维度列表（过滤掉超过原始维度的值）
    candidate_dims = [32, 64, 128, 256, 512, 768, 1024]
    test_dims = [d for d in candidate_dims if d < full_dim]
    test_dims.append(full_dim)  # 加入全维度作为基准

    results = await analyzer.truncation_comparison(text_a, text_b, test_dims)

    print(f"\n  文本 A: {text_a}")
    print(f"  文本 B: {text_b}")
    print(f"  原始维度: {full_dim}")

    sep_line = "─" * 64
    print(f"\n{sep_line}")
    print(f"{'维度':>8} {'余弦相似度':>14} {'L2 距离':>14} {'余弦保留率':>14}")
    print(sep_line)

    for r in results:
        retention_str = (
            f"{r['cosine_retention']:.1f}%"
            if r["dim"] < full_dim
            else "100.0% (基准)"
        )
        print(
            f"{r['dim']:>8}"
            f"{r['cosine']:>14.4f}"
            f"{r['l2']:>14.4f}"
            f"{retention_str:>14}"
        )

    print(sep_line)

    # 输出结论
    if len(results) >= 2:
        dim_256 = next((r for r in results if r["dim"] == 256), None)
        if dim_256:
            print(
                f"\n  结论: 裁剪到 256 维后，余弦保留率约 "
                f"{dim_256['cosine_retention']:.1f}%，"
                f"存储节省 {(1 - 256/full_dim) * 100:.0f}%"
            )


async def demo_irony_degradation() -> None:
    """演示三：反讽与转折的表征退化量化

    验证要点：
    1. 肯定文本 vs 简单否定：余弦应有明显下降
    2. 肯定文本 vs 反讽文本：余弦仍然偏高（退化）
    3. 反讽的严重程度增加时，余弦下降幅度微小
    """
    print_separator("演示三：表征退化量化 · 反讽/转折/否定")

    analyzer = EmbeddingAnalyzer()

    # 构造渐进式反讽测试样本
    base_text = "这家餐厅的服务态度非常好"
    variants: list[tuple[str, str]] = [
        ("原始肯定", "这家餐厅的服务态度非常好"),
        ("简单否定", "这家餐厅的服务态度非常差"),
        ("轻微反讽", "这家餐厅的服务态度非常好，等了一个小时才上菜"),
        ("强烈反讽", "这家餐厅的服务态度非常好，好到我再也不想去了"),
        ("完全无关", "今天股市大盘指数上涨了百分之三"),
    ]

    print(f"\n  基准文本: 「{base_text}」")

    sep_line = "─" * 76
    print(f"\n{sep_line}")
    print(
        f"{'变体类型':<16}"
        f"{'余弦相似度':>12}"
        f"{'L2 距离':>12}"
        f"{'语义偏离判定':<24}"
    )
    print(sep_line)

    for label, variant_text in variants:
        result = await analyzer.analyze_pair(base_text, variant_text)

        # 基于余弦相似度做定性偏离判定
        cos = result["cosine"]
        if cos > 0.95:
            deviation = "极低 (近似等价)"
        elif cos > 0.85:
            deviation = "低 (高度相似)"
        elif cos > 0.70:
            deviation = "中等"
        elif cos > 0.50:
            deviation = "较高"
        else:
            deviation = "极高 (语义完全不同)"

        print(
            f"{label:<16}"
            f"{cos:>12.4f}"
            f"{result['l2']:>12.4f}"
            f"{deviation:<24}"
        )

    print(sep_line)

    # 输出关键观察
    print("\n  ── 关键观察 ──")
    print("  1. '简单否定' 仅替换了一个词（好→差），余弦下降最明显")
    print("  2. '轻微反讽' 和 '强烈反讽' 的余弦仍然偏高（与原始肯定高度相似）")
    print("     → 这是 Embedding 单向量表征的固有限制：反讽语义被肯定词汇稀释")
    print("  3. 工程防御策略：在向量检索后加入 LLM Reranker 二次精排")


async def main() -> None:
    """Day 36 演示主入口 — 三组对比实验

    运行顺序：
    1. 六组文本对的余弦 vs L2 对比
    2. Matryoshka 维度裁剪保留率
    3. 反讽/转折表征退化量化
    """
    print("\n" + "█" * 68)
    print("  Day 36 — 文本向量化数学直觉与表征限制")
    print("  使用真实 MiniMax Embedding API (embo-01)")
    print("█" * 68)

    # 演示一：距离度量对比
    await demo_distance_comparison()

    # 演示二：维度裁剪
    await demo_matryoshka_truncation()

    # 演示三：表征退化
    await demo_irony_degradation()

    print("\n" + "█" * 68)
    print("  所有演示完成！")
    print("█" * 68)


if __name__ == "__main__":
    asyncio.run(main())
