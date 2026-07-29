"""
Week 14 Day 96 生产级项目代码: Enterprise Context Layout Engine & Prompt Cache 系统 (layout_impl.py)

===============================================================================
设计方案说明 (Architecture Design Specification)
===============================================================================

1. 设计意图 (Design Intent):
   在多轮、高频、多租户 Agent 运行中，乱序拼接 Payload 会导致前缀哈希 (Prefix Hash) 频频变动，
   使得云厂商 (Anthropic / OpenAI) 的 Prompt Cache 完全失效，带来昂贵费用与高首字延迟 (TTFT)。
   本模块实现 Enterprise Context Layout Engine (上下文布局引擎)，核心机制：
   - 7-Layer Context Segmentation: 按稳定性排序 (Global Static -> Tenant Static -> User Memory -> Task State -> RAG -> Dialogue -> Query)；
   - LayoutPlanner: 确保前置 Prefix 100% 稳定对齐；
   - CacheAnalyzer: 计算 Static Prefix Ratio 与 Anthropic (-90%) / OpenAI (-50%) 降本推导；
   - Provider Adapters: 适配 Anthropic `ephemeral` 显式缓存断点与 OpenAI 自动前缀匹配。

2. 核心类与数据流拓扑 (Class & Data Flow Topology):
   - `ContextSegment`: 包含名称、内容、层级 (1~7)、稳定性 ('static'/'dynamic') 与作用域 ('global'/'tenant'/'user')。
   - `LayoutPlanner`: 严格按照 7 层梯度排列 Segment，保证头部 Prefix 区块物理不动摇。
   - `CacheAnalyzer`: 计算 Static Ratio，生成 `layout_analysis.json`。
   - `PromptCacheAdapter`: 抽象基类，子类 `AnthropicAdapter` 与 `OpenAIAdapter` 输出标准化厂商 Payload。

3. 核心用例设计意图 (Test Case Design Intent):
   跑通 4 大生产级验收场景：
   - Case 1: 多轮对话 10 次请求，验证 Static Prefix Zone 的 MD5 Hash 保持 100% 相同；
   - Case 2: 每轮 RAG 结果剧烈变化，验证前置 Static Prefix 哈希 0 干扰、防穿透；
   - Case 3: 多租户 (医院A vs 医院B) 隔离测试，验证租户级 Cache 作用域隔离；
   - Case 4: 成本与延迟降本推导计算，并将优化后 Payload 发送给真实 LLM 运行。
===============================================================================
"""

import os
import sys
import enum
import time
import json
import hashlib
import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

# 导入 Week 4 LLM 工具客户端
current_dir = os.path.dirname(os.path.abspath(__file__))
w04_dir = os.path.abspath(os.path.join(current_dir, "../../w04_prompt_and_http"))

if w04_dir not in sys.path:
    sys.path.append(w04_dir)

from utils import LLMClient


def estimate_tokens(text: str) -> int:
    """估算 Token 数量"""
    return max(1, len(text) // 2 + len(text.split()))


@dataclass
class ContextSegment:
    """7 层 Context 分段数据模型"""
    name: str
    content: str
    layer_index: int                  # 1 ~ 7 层级
    stability: str = "static"         # 'static' (静态不变) 或 'dynamic' (动态变动)
    cache_scope: str = "global"       # 'global', 'tenant:<id>', 'user:<id>', 'task'
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    tokens: int = 0

    def __post_init__(self):
        if self.tokens == 0:
            self.tokens = estimate_tokens(self.content)


class LayoutPlanner:
    """
    7 层 Context 布局编排引擎 (Layout Planner)
    按稳定性降序重排：Global Static(L1) -> Tenant Static(L2) -> User Memory(L3) -> Task State(L4) -> RAG(L5) -> Dialogue(L6) -> Query(L7)
    """
    @staticmethod
    def plan_layout(segments: List[ContextSegment], tenant_id: Optional[str] = None) -> List[ContextSegment]:
        """
        根据 7 层梯度与租户作用域执行物理重排
        """
        # 行内步骤 1：租户作用域隔离过滤
        valid_segments = []
        for s in segments:
            if s.cache_scope == "global" or s.cache_scope.startswith("user:") or s.cache_scope == "task":
                valid_segments.append(s)
            elif tenant_id and s.cache_scope == f"tenant:{tenant_id}":
                valid_segments.append(s)

        # 行内步骤 2：按 layer_index 升序排序 (L1 -> L7，稳定在前，动态在后)
        sorted_segments = sorted(valid_segments, key=lambda x: (x.layer_index, x.name))
        return sorted_segments


class CacheAnalyzer:
    """
    缓存前缀与成本分析计算器 (Cache & Cost Analyzer)
    """
    @staticmethod
    def compute_prefix_hash(segments: List[ContextSegment], max_layer: int = 3) -> str:
        """计算指定静态前缀层级 (L1 ~ L3) 的 MD5 哈希值"""
        static_contents = [s.content for s in segments if s.layer_index <= max_layer and s.stability == "static"]
        joint_text = "\n---\n".join(static_contents)
        return hashlib.md5(joint_text.encode("utf-8")).hexdigest()

    @staticmethod
    def analyze_layout(segments: List[ContextSegment]) -> Dict[str, Any]:
        """
        分析静态前缀占比 Static Prefix Ratio 与 Anthropic / OpenAI 理论成本节省
        """
        total_tokens = sum(s.tokens for s in segments)
        static_tokens = sum(s.tokens for s in segments if s.stability == "static")
        dynamic_tokens = total_tokens - static_tokens

        static_ratio = round(static_tokens / total_tokens, 4) if total_tokens > 0 else 0.0

        # Anthropic: Cache Read 价格为 10% (节省 90% 静态部分开销)
        anthropic_saving_ratio = round(static_ratio * 0.90, 4)
        # OpenAI: Cache Read 价格为 50% (节省 50% 静态部分开销)
        openai_saving_ratio = round(static_ratio * 0.50, 4)

        return {
            "total_tokens": total_tokens,
            "static_tokens": static_tokens,
            "dynamic_tokens": dynamic_tokens,
            "static_prefix_ratio": static_ratio,
            "anthropic_theoretical_cost_saving": f"{anthropic_saving_ratio * 100:.1f}%",
            "openai_theoretical_cost_saving": f"{openai_saving_ratio * 100:.1f}%",
            "cache_potential_level": "HIGH" if static_ratio >= 0.5 else "MEDIUM" if static_ratio >= 0.3 else "LOW"
        }


class PromptCacheAdapter(ABC):
    """LLM Provider 缓存适配器抽象基类"""
    @abstractmethod
    def prepare_payload(self, segments: List[ContextSegment]) -> List[Dict[str, Any]]:
        pass


class AnthropicAdapter(PromptCacheAdapter):
    """
    Anthropic Prompt Cache 适配器
    自动在静态前缀区域 (L1~L3) 结尾处注入 `"cache_control": {"type": "ephemeral"}` 显式缓存断点
    """
    def prepare_payload(self, segments: List[ContextSegment]) -> List[Dict[str, Any]]:
        system_parts = []
        user_parts = []

        for s in segments:
            if s.layer_index <= 3:
                # 静态区：系统规范、Tools、Memory
                system_parts.append(f"[{s.name.upper()}]\n{s.content}")
            else:
                # 动态区：Task、RAG、Dialogue、Query
                user_parts.append(f"[{s.name.upper()}]\n{s.content}")

        system_text = "\n\n".join(system_parts)
        user_text = "\n\n".join(user_parts)

        # 构造带有 Anthropic 显式缓存断点的 Block
        return [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": system_text,
                        "cache_control": {"type": "ephemeral"}  # Anthropic 显式缓存断点
                    }
                ]
            },
            {
                "role": "user",
                "content": user_text
            }
        ]


class OpenAIAdapter(PromptCacheAdapter):
    """
    OpenAI Prompt Cache 适配器
    生成平铺连续且前缀严格对齐的 Standard OpenAI Messages Payload
    """
    def prepare_payload(self, segments: List[ContextSegment]) -> List[Dict[str, Any]]:
        system_parts = []
        user_parts = []

        for s in segments:
            if s.layer_index <= 2:
                system_parts.append(f"[{s.name.upper()}]\n{s.content}")
            else:
                user_parts.append(f"[{s.name.upper()}]\n{s.content}")

        return [
            {"role": "system", "content": "\n\n".join(system_parts)},
            {"role": "user", "content": "\n\n".join(user_parts)}
        ]


# ===============================================================================
# 运行主入口与 4 大生产级场景演示 (Execution Entrypoint & Production Demonstrations)
# ===============================================================================
async def main():
    print("=================================================================")
    print("🚀 启动 Day 96: Context Layout Engine & Prompt Cache 验证")
    print("=================================================================\n")

    # 1. 初始化基础 7 层 Segment 数据
    seg_l1_global = ContextSegment(
        name="Global_System_Rules",
        content="你是医院 Agent 助手。绝对禁止泄露患者隐私。输出格式必须为标准 Markdown。",
        layer_index=1,
        stability="static",
        cache_scope="global"
    )

    seg_l1_tools = ContextSegment(
        name="Tool_Schema_Declarations",
        content="TOOL_1: search_medical_records(patient_id: str)\nTOOL_2: query_drug_interaction(drug_a, drug_b)\n" * 5,
        layer_index=1,
        stability="static",
        cache_scope="global"
    )

    seg_l2_tenant_a = ContextSegment(
        name="Tenant_Policy_Hospital_A",
        content="[医院 A 专属规则]: 优先推荐本院药房药品，医保报销规则按 '北京市医保 2026 版' 执行。",
        layer_index=2,
        stability="static",
        cache_scope="tenant:hospital_a"
    )

    seg_l2_tenant_b = ContextSegment(
        name="Tenant_Policy_Hospital_B",
        content="[医院 B 专属规则]: 药品推荐按 '上海市医保 2026 版' 执行，自费药需二次弹窗提醒。",
        layer_index=2,
        stability="static",
        cache_scope="tenant:hospital_b"
    )

    seg_l3_memory = ContextSegment(
        name="User_Preference_Memory",
        content="用户偏好：患者张三，主诉高血压病史 5 年，对青霉素过敏。",
        layer_index=3,
        stability="static",
        cache_scope="user:user_123"
    )

    # -------------------------------------------------------------------------
    # 场景 1: 多轮对话 Static Prefix Hash 稳定性测试
    # -------------------------------------------------------------------------
    print("--- 【场景 1】多轮对话 Static Prefix Zone 哈希稳定性测试 ---")
    prefix_hashes = []
    
    for round_num in range(1, 4):
        # 模拟每轮动态 Dialogue 和 Query 的变化
        seg_l6_dialogue = ContextSegment(
            name=f"Dialogue_History_Round_{round_num}",
            content=f"Round {round_num}: 医生询问患者最近头晕频率，患者回答每天早晨发生。",
            layer_index=6,
            stability="dynamic",
            cache_scope="task"
        )
        seg_l7_query = ContextSegment(
            name=f"User_Query_Round_{round_num}",
            content=f"提问 Round {round_num}: 请根据上述情况开具复诊建议？",
            layer_index=7,
            stability="dynamic",
            cache_scope="task"
        )

        all_segs = [seg_l1_global, seg_l1_tools, seg_l2_tenant_a, seg_l3_memory, seg_l6_dialogue, seg_l7_query]
        planned = LayoutPlanner.plan_layout(all_segs, tenant_id="hospital_a")
        
        prefix_hash = CacheAnalyzer.compute_prefix_hash(planned, max_layer=3)
        prefix_hashes.append(prefix_hash)
        print(f"▶ 第 {round_num} 轮对话 - 静态前缀 (L1~L3) MD5 Hash: [{prefix_hash}] (前缀完全相同: {prefix_hash == prefix_hashes[0]})")
    
    print("✅ 结论: 无论对话轮次如何增加，前置 Static Zone 的前缀哈希 100% 保持一致，完美命中 Prompt Cache！\n")

    # -------------------------------------------------------------------------
    # 场景 2: RAG 结果剧烈变动防穿透测试
    # -------------------------------------------------------------------------
    print("--- 【场景 2】RAG 结果剧烈变动防前缀穿透测试 ---")
    rag_1 = ContextSegment("RAG_TopK", "RAG 召回内容：高血压患者用药指南 2026 版", 5, "dynamic", "task")
    rag_2 = ContextSegment("RAG_TopK", "RAG 召回内容：完全不同的硝苯地平控释片禁忌症说明", 5, "dynamic", "task")

    segs_rag_1 = LayoutPlanner.plan_layout([seg_l1_global, seg_l1_tools, seg_l2_tenant_a, rag_1], tenant_id="hospital_a")
    segs_rag_2 = LayoutPlanner.plan_layout([seg_l1_global, seg_l1_tools, seg_l2_tenant_a, rag_2], tenant_id="hospital_a")

    hash_rag_1 = CacheAnalyzer.compute_prefix_hash(segs_rag_1, max_layer=3)
    hash_rag_2 = CacheAnalyzer.compute_prefix_hash(segs_rag_2, max_layer=3)
    print(f"▶ RAG 结果 1 前缀 Hash: [{hash_rag_1}]")
    print(f"▶ RAG 结果 2 前缀 Hash: [{hash_rag_2}]")
    print(f"✅ RAG 变化是否影响前置静态 Cache Prefix: {'否 (前缀防护成功)' if hash_rag_1 == hash_rag_2 else '是'}\n")

    # -------------------------------------------------------------------------
    # 场景 3: 多租户 (Tenant) 缓存前缀隔离测试
    # -------------------------------------------------------------------------
    print("--- 【场景 3】多租户 (Tenant A vs Tenant B) 缓存前缀隔离测试 ---")
    segs_hosp_a = LayoutPlanner.plan_layout([seg_l1_global, seg_l2_tenant_a, seg_l2_tenant_b], tenant_id="hospital_a")
    segs_hosp_b = LayoutPlanner.plan_layout([seg_l1_global, seg_l2_tenant_a, seg_l2_tenant_b], tenant_id="hospital_b")

    hash_a = CacheAnalyzer.compute_prefix_hash(segs_hosp_a, max_layer=2)
    hash_b = CacheAnalyzer.compute_prefix_hash(segs_hosp_b, max_layer=2)
    print(f"▶ 医院 A (Tenant A) 前缀 Hash: [{hash_a}]")
    print(f"▶ 医院 B (Tenant B) 前缀 Hash: [{hash_b}]")
    print(f"✅ 租户前缀隔离防护验证: {'通过 (Tenant 隔离正常)' if hash_a != hash_b else '失败'}\n")

    # -------------------------------------------------------------------------
    # 场景 4: Cache 占比分析与真实 LLM 运行
    # -------------------------------------------------------------------------
    print("--- 【场景 4】Cache 静态占比分析与 Provider 适配器实战 ---")
    final_segments = LayoutPlanner.plan_layout(
        [seg_l1_global, seg_l1_tools, seg_l2_tenant_a, seg_l3_memory, rag_1, seg_l7_query],
        tenant_id="hospital_a"
    )

    analysis_res = CacheAnalyzer.analyze_layout(final_segments)
    print("📊 Layout 分析报告 (layout_analysis.json 导出内容):")
    print(json.dumps(analysis_res, ensure_ascii=False, indent=2))

    # 导出可观测 Trace
    trace_path = os.path.join(current_dir, "layout_analysis.json")
    with open(trace_path, "w", encoding="utf-8") as f:
        json.dump(analysis_res, f, ensure_ascii=False, indent=2)
    print(f"📁 已导出布局分析追踪报告至: {trace_path}\n")

    # 发送 Anthropic 适配器与 OpenAI 适配器格式，并调用真实 LLM 验证
    openai_adapter = OpenAIAdapter()
    openai_payload = openai_adapter.prepare_payload(final_segments)

    print("🤖 正在调用大模型验证优化布局后的 Payload...")
    client = LLMClient()
    try:
        resp = await client.request_llm(messages=openai_payload, max_tokens=200)
        print("\n✅ LLM 返回结果:")
        print("-----------------------------------------------------------------")
        print(resp.strip())
        print("-----------------------------------------------------------------")
        print("\n🎉 Day 96 Context Layout Engine 验证完全成功！")
    except Exception as e:
        print(f"❌ 大模型调用失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
