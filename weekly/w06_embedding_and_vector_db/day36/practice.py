"""
Day 36 练习模版 — 文本向量化（Embedding）数学直觉与表征限制

设计方案：
==========
1. 设计意图：
   本文件是 Day 36 的练习骨架，学员需要手动实现以下核心功能：
   - 余弦相似度计算（纯 numpy，不使用 sklearn 等高层封装）
   - 欧氏距离计算（纯 numpy）
   - Matryoshka 维度裁剪
   - 文本对距离分析的完整工作流

2. 练习任务清单（共 5 项 TODO）：
   TODO-1: 实现 cosine_similarity() — 手动余弦相似度计算
   TODO-2: 实现 l2_distance() — 手动欧氏距离计算
   TODO-3: 实现 truncate_vector() — Matryoshka 维度裁剪
   TODO-4: 实现 analyze_pair() — 文本对向量化 + 距离计算完整流程
   TODO-5: 实现 run_benchmark() — 批量测试并输出对比表格

3. 核心公式提示：
   - 余弦相似度: cos(θ) = (a·b) / (||a|| × ||b||)
   - 欧氏距离:   d = sqrt(Σ(a_i - b_i)²)
   - 维度裁剪:   truncated = full_vector[:target_dim]

4. 关键依赖：
   - numpy: 向量计算
   - weekly.w06_embedding_and_vector_db.utils.EmbeddingClient: API 客户端

使用方式（在项目根目录）：
    python -m weekly.w06_embedding_and_vector_db.day36.practice

⚠ 所有 TODO 完成前运行会抛出 NotImplementedError 提示。
"""
from __future__ import annotations

import asyncio
import numpy as np

from weekly.w06_embedding_and_vector_db.utils import EmbeddingClient


# ══════════════════════════════════════════════════════════════════════════════
# 板块一：EmbeddingAnalyzer 练习骨架
# ══════════════════════════════════════════════════════════════════════════════

class EmbeddingAnalyzer:
    """Embedding 向量距离分析引擎（练习版）

    学员需要实现以下方法：
    1. cosine_similarity(vec_a, vec_b) → float
    2. l2_distance(vec_a, vec_b) → float
    3. truncate_vector(vec, target_dim) → np.ndarray
    4. analyze_pair(text_a, text_b) → dict
    5. run_benchmark(test_cases) → None

    Attributes:
        client: MiniMax Embedding API 客户端实例
        _vector_cache: 文本→向量的本地缓存字典
    """

    def __init__(self) -> None:
        """初始化分析引擎。"""
        self.client = EmbeddingClient()
        self._vector_cache: dict[str, np.ndarray] = {}

    # ── TODO-1: 手动实现余弦相似度 ──

    @staticmethod
    def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        """计算两个向量的余弦相似度

        数学公式: cos(θ) = (a·b) / (||a|| × ||b||)

        实现步骤提示：
        1. 校验 vec_a 和 vec_b 的 shape 是否一致（不一致则 raise ValueError）
        2. 用 np.dot() 计算点积
        3. 用 np.linalg.norm() 计算各自的 L2 范数
        4. 处理零向量边界（任一范数为 0 时返回 0.0）
        5. 返回 dot / (norm_a * norm_b)

        Args:
            vec_a: 向量 A（一维 numpy 数组）
            vec_b: 向量 B（一维 numpy 数组）

        Returns:
            余弦相似度值，范围 [-1, 1]

        Raises:
            ValueError: 维度不匹配时抛出
        """
        # TODO: 在此实现余弦相似度计算
        raise NotImplementedError("TODO-1: 请实现 cosine_similarity()")

    # ── TODO-2: 手动实现欧氏距离 ──

    @staticmethod
    def l2_distance(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        """计算两个向量的欧氏距离（L2 Distance）

        数学公式: d = sqrt(Σ(a_i - b_i)²)

        实现步骤提示：
        1. 校验 vec_a 和 vec_b 的 shape 是否一致
        2. 计算差向量 diff = vec_a - vec_b
        3. 用 np.sum(diff ** 2) 计算平方和
        4. 用 np.sqrt() 开方得到欧氏距离

        Args:
            vec_a: 向量 A（一维 numpy 数组）
            vec_b: 向量 B（一维 numpy 数组）

        Returns:
            欧氏距离值，范围 [0, +∞)

        Raises:
            ValueError: 维度不匹配时抛出
        """
        # TODO: 在此实现欧氏距离计算
        raise NotImplementedError("TODO-2: 请实现 l2_distance()")

    # ── TODO-3: 实现维度裁剪 ──

    @staticmethod
    def truncate_vector(vec: np.ndarray, target_dim: int) -> np.ndarray:
        """维度裁剪（Matryoshka Representation Learning）

        实现步骤提示：
        1. 校验 target_dim > 0 且 <= len(vec)
        2. 返回 vec[:target_dim]（数组切片）

        Args:
            vec: 原始高维向量
            target_dim: 目标维度

        Returns:
            截断后的低维向量

        Raises:
            ValueError: 目标维度非法时抛出
        """
        # TODO: 在此实现维度裁剪
        raise NotImplementedError("TODO-3: 请实现 truncate_vector()")

    # ── 向量化辅助方法（已实现，无需修改）──

    async def _get_vectors(self, texts: list[str]) -> list[np.ndarray]:
        """获取文本向量（带缓存）— 此方法已实现，无需修改。"""
        uncached_texts = [t for t in texts if t not in self._vector_cache]
        if uncached_texts:
            raw_vectors = await self.client.embed_texts(uncached_texts)
            for text, vec in zip(uncached_texts, raw_vectors):
                self._vector_cache[text] = np.array(vec, dtype=np.float64)
        return [self._vector_cache[t] for t in texts]

    # ── TODO-4: 实现文本对距离分析 ──

    async def analyze_pair(self, text_a: str, text_b: str) -> dict:
        """对比分析两段文本的距离指标

        实现步骤提示：
        1. 调用 self._get_vectors([text_a, text_b]) 获取向量
        2. 调用 self.cosine_similarity() 计算余弦相似度
        3. 调用 self.l2_distance() 计算欧氏距离
        4. 用 np.linalg.norm() 计算各向量的模长
        5. 返回包含所有指标的字典

        Args:
            text_a: 文本 A
            text_b: 文本 B

        Returns:
            dict: {
                "text_a": str (截断到 30 字符),
                "text_b": str (截断到 30 字符),
                "cosine": float,
                "l2": float,
                "dim": int,
                "norm_a": float,
                "norm_b": float,
            }
        """
        # TODO: 在此实现文本对距离分析
        raise NotImplementedError("TODO-4: 请实现 analyze_pair()")

    # ── TODO-5: 实现批量测试对比表格 ──

    async def run_benchmark(self, test_cases: list[dict]) -> None:
        """批量运行测试并输出对比表格

        每个 test_case 的结构: {
            "group": str,      # 测试组名
            "text_a": str,     # 文本 A
            "text_b": str,     # 文本 B
            "expected": str,   # 预期说明
        }

        输出格式要求：
        - 打印表头：测试组 | 余弦相似度 | L2 距离 | ||a|| | ||b||
        - 对每个 test_case 调用 analyze_pair() 并打印一行

        Args:
            test_cases: 测试用例列表
        """
        # TODO: 在此实现批量测试
        raise NotImplementedError("TODO-5: 请实现 run_benchmark()")


# ══════════════════════════════════════════════════════════════════════════════
# 板块二：测试样本集
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
        "expected": "余弦 < 0.80：相同词汇但语义完全不同",
    },
    {
        "group": "完全无关（基线）",
        "text_a": "量子力学中薛定谔方程的波函数坍缩现象",
        "text_b": "今天晚餐我想吃麻辣火锅配冰啤酒",
        "expected": "余弦最低，L2 为所有测试组中最大值",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# 板块三：调试主入口（带 NotImplementedError 友好拦截）
# ══════════════════════════════════════════════════════════════════════════════

async def main() -> None:
    """练习入口 — 逐步验证各 TODO 实现。

    运行时会自动检测哪些 TODO 尚未完成并给出提示。
    """
    print("\n" + "█" * 68)
    print("  Day 36 练习 — 文本向量化数学直觉与表征限制")
    print("  请逐一完成上方的 5 个 TODO")
    print("█" * 68)

    analyzer = EmbeddingAnalyzer()

    # ── 测试 TODO-1: cosine_similarity ──
    print("\n── 检查 TODO-1: cosine_similarity ──")
    try:
        vec_test_a = np.array([1.0, 2.0, 3.0])
        vec_test_b = np.array([4.0, 5.0, 6.0])
        result = analyzer.cosine_similarity(vec_test_a, vec_test_b)
        expected = 0.9746  # 预计算值
        print(f"  ✅ cosine_similarity 已实现！结果: {result:.4f} (参考值: {expected})")
    except NotImplementedError as e:
        print(f"  ⏳ {e}")
    except Exception as e:
        print(f"  ❌ 运行出错: {type(e).__name__}: {e}")

    # ── 测试 TODO-2: l2_distance ──
    print("\n── 检查 TODO-2: l2_distance ──")
    try:
        result = analyzer.l2_distance(vec_test_a, vec_test_b)
        expected = 5.1962  # sqrt(9+9+9) = sqrt(27)
        print(f"  ✅ l2_distance 已实现！结果: {result:.4f} (参考值: {expected})")
    except NotImplementedError as e:
        print(f"  ⏳ {e}")
    except Exception as e:
        print(f"  ❌ 运行出错: {type(e).__name__}: {e}")

    # ── 测试 TODO-3: truncate_vector ──
    print("\n── 检查 TODO-3: truncate_vector ──")
    try:
        vec_long = np.arange(100, dtype=np.float64)
        truncated = analyzer.truncate_vector(vec_long, 10)
        print(f"  ✅ truncate_vector 已实现！100 维 → {len(truncated)} 维")
    except NotImplementedError as e:
        print(f"  ⏳ {e}")
    except Exception as e:
        print(f"  ❌ 运行出错: {type(e).__name__}: {e}")

    # ── 测试 TODO-4: analyze_pair ──
    print("\n── 检查 TODO-4: analyze_pair（需要有效 API Key）──")
    try:
        result = await analyzer.analyze_pair(
            "今天天气很好", "今天天气不错"
        )
        print(f"  ✅ analyze_pair 已实现！")
        print(f"     cosine={result['cosine']:.4f}, L2={result['l2']:.4f}")
        print(f"     向量维度: {result['dim']}")
    except NotImplementedError as e:
        print(f"  ⏳ {e}")
    except Exception as e:
        print(f"  ❌ 运行出错: {type(e).__name__}: {e}")

    # ── 测试 TODO-5: run_benchmark ──
    print("\n── 检查 TODO-5: run_benchmark ──")
    try:
        await analyzer.run_benchmark(TEST_CASES[:2])  # 先用前 2 组测试
        print(f"  ✅ run_benchmark 已实现！")
    except NotImplementedError as e:
        print(f"  ⏳ {e}")
    except Exception as e:
        print(f"  ❌ 运行出错: {type(e).__name__}: {e}")

    # ── 总结 ──
    print("\n" + "─" * 68)
    print("  所有 TODO 完成后，运行标准答案对比验证：")
    print("  python -m weekly.w06_embedding_and_vector_db.day36.demo")
    print("─" * 68)


if __name__ == "__main__":
    asyncio.run(main())
