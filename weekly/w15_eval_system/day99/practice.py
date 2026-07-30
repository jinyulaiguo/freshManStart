"""
Week 15 Day 99 学员练习模版: Golden Dataset 合成生成引擎 (practice.py)

===============================================================================
练习说明 (Exercise Specification)
===============================================================================
本练习目标是实现生产级 Golden Dataset 合成生成器 (SyntheticGenerator)，从 W14
Research Agent 的 RAG 论文语料与用户 Memory 偏好中，利用大模型 Few-shot 提示词
批量合成 50 条具有挑战性的评测用例，并持久化为标准 JSONL 文件。

学员需要补充 SyntheticGenerator 中以下关键方法：
1. `_load_source_corpus()`: 加载 W14 rag_simulator 与 memory_store 语料。
2. `_build_few_shot_prompt()`: 构造含种子样本与分层采样配额的合成提示词。
3. `_parse_llm_batch()`: 解析 LLM 返回的 JSON 数组并校验为 GoldenCase 列表。
4. `generate_category_batch()`: 调用 LLM API 合成指定类别的测试用例批次。
5. `generate_and_save()`: 编排全类别合成、去重校验并写入 golden_dataset_v1.jsonl。

请根据提示完成 TODO 部分的代码实现！
完成后可对照参考标准答案 `golden/synthetic_generator_impl.py`。
===============================================================================
"""

import os
import sys
import asyncio
from pathlib import Path
from typing import Any

# 导入 Week 4 LLM 客户端与 Week 15 共享契约
current_dir = os.path.dirname(os.path.abspath(__file__))
w04_path = os.path.abspath(os.path.join(current_dir, "../../w04_prompt_and_http"))
w15_root = os.path.abspath(os.path.join(current_dir, ".."))
w14_research = os.path.abspath(
    os.path.join(current_dir, "../../w14_context_engineering/day98/scenario_research")
)

for p in (w04_path, w15_root):
    if p not in sys.path:
        sys.path.append(p)

from utils import LLMClient
from contracts.schemas import (
    GoldenCase,
    GoldenCategory,
    save_golden_dataset,
    validate_dataset_uniqueness,
)


# 分层采样配额 (与 overview.html 对齐)
CATEGORY_QUOTAS: dict[GoldenCategory, int] = {
    GoldenCategory.NORMAL_RETRIEVAL: 15,
    GoldenCategory.MULTI_PAPER_COMPARISON: 10,
    GoldenCategory.PROMPT_INJECTION: 8,
    GoldenCategory.MEMORY_DEPENDENT: 8,
    GoldenCategory.TOOL_PARAM_EDGE: 5,
    GoldenCategory.ROUTING_FALLBACK: 2,
    GoldenCategory.CROSS_DOCUMENT: 2,
}


class SyntheticGenerator:
    """
    Golden Dataset 合成生成引擎

    从 W14 本地语料读取业务文档，通过 LLM Few-shot 提示词动态合成
    覆盖极端边界的 JSONL 测试用例，并执行 Pydantic 契约校验与去重。
    """

    def __init__(
        self,
        output_path: Path,
        llm_client: LLMClient | None = None,
    ):
        self.output_path = output_path
        self.llm = llm_client or LLMClient()
        self._corpus_cache: dict[str, Any] | None = None
        self._next_id: int = 1

    def _load_source_corpus(self) -> dict[str, Any]:
        """
        TODO 1: 加载 W14 Research Agent 本地语料

        要求：
        1. 动态 import rag_simulator 的 RAG_PAPER_CORPUS 与 INJECTION_PAYLOADS；
        2. 动态 import memory_store 的 USER_PREFERENCES；
        3. 返回 {"papers": [...], "injections": [...], "memories": [...]} 字典；
        4. 结果缓存到 self._corpus_cache 避免重复加载。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现语料加载逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 1: 请实现 _load_source_corpus 语料加载！")

    def _build_few_shot_prompt(
        self,
        category: GoldenCategory,
        batch_size: int,
        seed_examples: list[dict[str, Any]],
        corpus_excerpt: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        """
        TODO 2: 构造 Few-shot 合成提示词 Messages

        要求：
        1. System 消息定义 JSON 输出 Schema 与 GoldenCase 字段约束；
        2. User 消息包含：目标 category、batch_size、2-3 条 seed_examples、
           corpus_excerpt 语料片段；
        3. 强调 ground_truth 必须基于语料事实，expected_tools 必须含 rag_search；
        4. 返回 OpenAI 格式的 messages 列表。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现 Few-shot Prompt 构造逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 2: 请实现 _build_few_shot_prompt 提示词构造！")

    def _parse_llm_batch(
        self,
        raw_response: str,
        category: GoldenCategory,
    ) -> list[GoldenCase]:
        """
        TODO 3: 使用 llm_reliability_adapter.parse_structured 解析 LLM 批次响应

        要求：
        1. 导入 middlewares.llm_reliability_adapter.parse_structured 与 GoldenBatchResponse；
        2. 调用 parse_structured(raw_response, GoldenBatchResponse) 一键提纯解析；
        3. 为每条 draft 分配唯一 test_case_id 并升级为 GoldenCase；
        4. 校验失败时抛出 ValueError 并附带原始响应片段。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现 LLM 响应解析与校验逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 3: 请实现 _parse_llm_batch 响应解析！")

    async def generate_category_batch(
        self,
        category: GoldenCategory,
        count: int,
    ) -> list[GoldenCase]:
        """
        TODO 4: 调用 LLM API 合成指定类别的测试用例

        要求：
        1. 加载语料并选取与 category 相关的 excerpt；
        2. 构造 Few-shot prompt 并调用 self.llm.request_llm (temperature=0.3)；
        3. 解析响应为 GoldenCase 列表；
        4. 若单次返回不足 count 条，可递归补生成 (最多重试 2 次)。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现单类别批次合成逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 4: 请实现 generate_category_batch 批次合成！")

    async def generate_and_save(self) -> list[GoldenCase]:
        """
        TODO 5: 编排全类别合成、去重校验并持久化 JSONL

        要求：
        1. 按 CATEGORY_QUOTAS 逐类别调用 generate_category_batch；
        2. 合并所有用例并执行 validate_dataset_uniqueness；
        3. 调用 save_golden_dataset 写入 self.output_path；
        4. 返回完整 GoldenCase 列表。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现全量合成与持久化逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 5: 请实现 generate_and_save 全量编排！")


# ===============================================================================
# 调试主入口 (Debug Main Entrypoint)
# ===============================================================================
async def main() -> None:
    print("=" * 70)
    print("📝 运行 Day 99 学员练习调试入口 (practice.py)")
    print("   Golden Dataset 合成生成引擎 · SyntheticGenerator")
    print("=" * 70)

    output = Path(__file__).resolve().parent.parent / "golden" / "golden_dataset_v1.jsonl"
    generator = SyntheticGenerator(output_path=output)

    try:
        cases = await generator.generate_and_save()
        print(f"\n✅ 合成完成！共生成 {len(cases)} 条 Golden Case")
        print(f"📁 输出路径: {output}")

        # 分类统计
        from collections import Counter
        cat_counts = Counter(c.category.value for c in cases)
        print("\n📊 分类分布:")
        for cat, cnt in sorted(cat_counts.items()):
            print(f"   {cat}: {cnt}")

    except NotImplementedError as e:
        print(f"\n📌 [TODO 拦截提示]: {e}")
        print("💡 提示: 请打开 `weekly/w15_eval_system/day99/practice.py` 完成 TODO。")
        print("💡 参考: 完成后对照 `golden/synthetic_generator_impl.py`。")


if __name__ == "__main__":
    asyncio.run(main())
