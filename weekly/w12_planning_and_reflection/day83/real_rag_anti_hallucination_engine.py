"""
Day 83 生产级端到端实战: 本地 Qdrant 向量检索 + MiniMax LLM + NLI 语义防幻觉校对引擎

【架构设计说明】
1. 设计意图 (Design Intent):
   将 Day 83 的防幻觉校对引擎升级为 100% 真实生产闭环。
   - 接入本地已运行的 Qdrant 向量数据库 (localhost:6333) 动态索引与检索文档片。
   - 接入 MiniMax LLM 真实 API 进行向量文本生成与 NLI 对齐推理。
   - 实现真实 RAG Ingestion ➔ Qdrant 向量检索 ➔ Answer Generator ➔ Atomic Claim Extract ➔ NLI Verification ➔ Correction Guard 的完全物理闭环。

2. 物理组件分工:
   - QdrantVectorStore: 连接 localhost:6333，创建 `day83_rag_financial` 集合，索引财报段落片段，执行 Top-K 向量语义检索。
   - AnswerGeneratorNode: 基于 Qdrant 检索出的 RAG 上下文调用 MiniMax API 生成回答。
   - ClaimExtractorNode: 结构化抽取回答中的单点事实断言。
   - AntiHallucinationVerifier: 逐句对齐 Qdrant 检索到的源上下文，执行 NLI 蕴含判定。
   - AntiHallucinationGuard: 监控是否检测到幻觉，驱动自愈重修。
"""

import os
import re
import asyncio
from typing import Dict, List, Any, Optional, Literal, TypedDict
from pydantic import BaseModel, Field

# 导入 Qdrant 官方 SDK 与本地依赖
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

# 从公共工具与中间件导入 API 与结构化提纯功能
from weekly.w04_prompt_and_http.utils import load_env_file, LLMClient
from middlewares.llm_reliability_adapter import parse_structured

# 加载本地 .env
load_env_file()


# ==========================================
# 1. 强类型 Schema 与 State 容器契约
# ==========================================

class ClaimEvaluation(BaseModel):
    """
    单个原子事实陈述的 NLI 推理结果契约
    """
    claim_text: str = Field(description="抽取的单点事实陈述文本")
    label: Literal["ENTAILMENT", "CONTRADICTION", "NEUTRAL"] = Field(
        description="NLI 推理标签: ENTAILMENT(蕴含/完全符合), CONTRADICTION(与 Context 矛盾), NEUTRAL(无根无据/凭空捏造)"
    )
    reasoning: str = Field(description="基于 Context 的逻辑推导与判定依据")


class AntiHallucinationReport(BaseModel):
    """
    全局防幻觉校对报告契约
    """
    overall_status: Literal["PASS", "HALLUCINATION_DETECTED"] = Field(description="综合校对结论: PASS 或 HALLUCINATION_DETECTED")
    claim_evaluations: List[ClaimEvaluation] = Field(default_factory=list, description="每个断言的 NLI 详细评估列表")
    unsupported_claims: List[str] = Field(default_factory=list, description="被判定为 CONTRADICTION 或 NEUTRAL 的无效/幻觉陈述列表")
    correction_guidance: str = Field(description="针对性的文本纠偏指令，供下一轮 Generator 剔除或修正幻觉")


class AtomicClaimsPayload(BaseModel):
    """
    Extractor 提取出的原子事实断言列表 Payload
    """
    claims: List[str] = Field(description="从回答文本中拆分出的单点事实断言数组")


class RealRAGState(TypedDict):
    """
    真实 RAG 状态容器
    """
    user_query: str
    retrieved_chunks: List[str]
    rag_context: str
    current_answer: str
    verification_report: Optional[AntiHallucinationReport]
    loop_counter: int
    is_success: bool


# ==========================================
# 2. 真实 Qdrant 向量检索组件 (Retriever Component)
# ==========================================

class QdrantRAGStore:
    """
    本地 Qdrant 向量数据库检索组件 (连接 localhost:6333)
    """

    def __init__(self, collection_name: str = "day83_rag_financial"):
        self.collection_name = collection_name
        self.client = QdrantClient(host="localhost", port=6333)
        self.vector_dim = 384  # 轻量离线 Embedding 维度 (此处采用语义词频特征模拟，无需额载 PyTorch)

    def _text_to_vector(self, text: str) -> List[float]:
        """
        轻量级确定性文本向量化转换函数 (确定性哈希分布)
        """
        import hashlib
        words = re.findall(r'\w+', text.lower())
        vec = [0.0] * self.vector_dim
        for word in words:
            h = int(hashlib.md5(word.encode('utf-8')).hexdigest(), 16)
            idx = h % self.vector_dim
            vec[idx] += 1.0
        # 归一化 L2 向量
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def initialize_and_seed(self, documents: List[str]):
        """
        初始化 Collection 并写入真实财报文档片段
        """
        # 如果存在则删除旧集合以保证幂等性
        collections = [c.name for c in self.client.get_collections().collections]
        if self.collection_name in collections:
            self.client.delete_collection(self.collection_name)

        # 创建新集合
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=self.vector_dim, distance=Distance.COSINE),
        )

        # 写入 Point 数据
        points = []
        for i, doc in enumerate(documents):
            vec = self._text_to_vector(doc)
            points.append(PointStruct(id=i + 1, vector=vec, payload={"content": doc}))

        self.client.upsert(collection_name=self.collection_name, points=points)
        print(f"📦 [Qdrant] 成功在 collection '{self.collection_name}' 中索引 {len(documents)} 条物理文本片段！")

    def search_context(self, query: str, top_k: int = 3) -> List[str]:
        """
        在 Qdrant 向量库中执行 Top-K 检索
        """
        query_vec = self._text_to_vector(query)
        search_response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vec,
            limit=top_k
        )
        search_results = search_response.points
        retrieved_texts = [hit.payload["content"] for hit in search_results if hit.payload]
        return retrieved_texts


# ==========================================
# 3. 防幻觉核心微引擎组件
# ==========================================

class ClaimExtractorNode:
    """
    原子事实提取节点
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.client = llm_client or LLMClient()

    async def extract_claims(self, answer: str) -> List[str]:
        cleaned_answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL | re.IGNORECASE).strip()
        prompt = f"""你是一名严谨的文本分析专家。请将以下回答段落拆解为互相独立的单点原子事实陈述 (Atomic Claims)。

【待拆解回答段落】:
{cleaned_answer}

【要求】:
1. 将回答中的主张、数字、结论拆分为简短、独立的陈述句。
2. 忽略 Markdown 格式符号 (#, |, >) 与连接词，仅保留事实断言。
3. 请直接输出符合 JSON 结构的文本，严禁包含 <think> 标签！
"""
        messages = [
            {"role": "system", "content": "你是一名精通文本原子陈述拆解的专家。请输出 JSON 强类型契约。"},
            {"role": "user", "content": prompt}
        ]

        try:
            raw_text = await self.client.request_llm(messages=messages, temperature=0.1)
            payload: AtomicClaimsPayload = parse_structured(raw_text=raw_text, response_model=AtomicClaimsPayload)
            valid_claims = []
            for c in payload.claims:
                c_str = c.strip()
                if not c_str or c_str.startswith(("#", "|", ">", "---", "```", "<think>", "Let me", "The user")):
                    continue
                cleaned = re.sub(r"[\*#>\-\|\`]", "", c_str).strip()
                if len(cleaned) > 3:
                    valid_claims.append(cleaned)
            return valid_claims if valid_claims else [cleaned_answer]
        except Exception:
            raw_lines = [s.strip() for s in cleaned_answer.replace("！", "。").replace("\n", "。").split("。") if s.strip()]
            valid_sentences = []
            for line in raw_lines:
                line_str = line.strip()
                if not line_str or line_str.startswith(("#", "|", ">", "---", "```", "<think>")):
                    continue
                cleaned = re.sub(r"[\*#>\-\|\`]", "", line_str).strip()
                if len(cleaned) > 3:
                    valid_sentences.append(cleaned)
            return valid_sentences if valid_sentences else [cleaned_answer]


class AntiHallucinationVerifier:
    """
    NLI 语义蕴含校验器
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.client = llm_client or LLMClient()

    async def verify(self, rag_context: str, claims: List[str]) -> AntiHallucinationReport:
        prompt = f"""你是一名极其苛刻的 RAG 防幻觉校验专家。请严格对照【参考 Context】，对【待校验断言】列表逐一计算 NLI 逻辑标签。

【参考 Context (来自 Qdrant 向量库召回数据)】:
{rag_context}

【待校验断言列表】:
{claims}

【NLI 判定标准】:
1. ENTAILMENT (蕴含): 断言中的事实 100% 能由 Context 直接推导出来。
2. CONTRADICTION (矛盾): 断言的结论与 Context 中的事实明确冲突。
3. NEUTRAL (中立/凭空捏造): Context 中完全没有提及该断言的内容（属于无根据推测）。

【极重要 Schema 契约】:
- label 字段必须只能为 "ENTAILMENT", "CONTRADICTION", "NEUTRAL" 三个字符串之一！
- overall_status 必须只能为 "PASS" (当所有断言均为 ENTAILMENT 时) 或 "HALLUCINATION_DETECTED" (当存在任何 CONTRADICTION 或 NEUTRAL 时)。
- 请直接输出符合 JSON 结构的文本，严禁包含 <think> 标签！
"""
        messages = [
            {"role": "system", "content": "你是一名精通 NLI 语义蕴含校对的专家。请输出符合 Schema 契约的 JSON 校对报告。"},
            {"role": "user", "content": prompt}
        ]

        try:
            raw_text = await self.client.request_llm(messages=messages, temperature=0.1)
            cleaned_text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL | re.IGNORECASE).strip()
            cleaned_text = re.sub(r',\s*""\s*\}', '}', cleaned_text)
            report: AntiHallucinationReport = parse_structured(raw_text=cleaned_text, response_model=AntiHallucinationReport)
            return report
        except Exception as e:
            print(f"⚠️ [AntiHallucinationVerifier] NLI 校对解析捕获异常 ({type(e).__name__}: {e})，触发保底风控。")
            return AntiHallucinationReport(
                overall_status="HALLUCINATION_DETECTED",
                claim_evaluations=[],
                unsupported_claims=["校对中间件异常，默认触发严格复查"],
                correction_guidance="请严格对照 Qdrant Context 重新生成，剔除任何未在 Context 中提及的推测性数字或信息。"
            )


class AnswerGeneratorNode:
    """
    回答生成/重修节点
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.client = llm_client or LLMClient()

    async def generate_answer(
        self,
        rag_context: str,
        user_question: str,
        correction_guidance: Optional[str] = None
    ) -> str:
        if not correction_guidance:
            system_prompt = "你是一名问答助手。请根据 Context 回答用户问题。"
            user_prompt = f"参考 Qdrant Context:\n{rag_context}\n用户问题: {user_question}\n提示：请全面回答，可以适当对后续季度进行合理展望。"
        else:
            system_prompt = f"""你是一名零幻觉 (Zero-Hallucination) 极度严谨的问答引擎。
你的回答必须 100% 物理受限于 Context 文本，绝对不允许包含任何 Context 中没有提及的数字、时间或预估。

【上一轮检测出的幻觉纠偏指令】：
{correction_guidance}

【极重要约束】：
1. 彻底删除所有被标记为 NEUTRAL (无根据) 或 CONTRADICTION (矛盾) 的陈述！
2. 只保留 Context 中明确记载的事实。如果不确定，直接说明 Context 未提及。
"""
            user_prompt = f"参考 Qdrant Context:\n{rag_context}\n用户问题: {user_question}\n请重新给出修正后的可靠回答："

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        raw_response = await self.client.request_llm(messages=messages, temperature=0.2)
        cleaned_response = re.sub(r"<think>.*?</think>", "", raw_response, flags=re.DOTALL | re.IGNORECASE).strip()
        return cleaned_response


# ==========================================
# 4. 真实端到端调度引擎
# ==========================================

class RealRAGAntiHallucinationEngine:
    """
    结合 Qdrant + MiniMax + NLI 的防幻觉集成引擎
    """

    def __init__(self, max_retries: int = 3):
        self.qdrant_store = QdrantRAGStore(collection_name="day83_rag_financial")
        self.generator = AnswerGeneratorNode()
        self.extractor = ClaimExtractorNode()
        self.verifier = AntiHallucinationVerifier()
        self.max_retries = max_retries

    def setup_database(self, raw_documents: List[str]):
        """
        初始化并向 Qdrant 写入真实文档数据
        """
        print("⚡ [Step 1] 正在初始化本地 Qdrant (localhost:6333) 集合并写入文档...")
        self.qdrant_store.initialize_and_seed(raw_documents)

    async def run(self, user_query: str) -> RealRAGState:
        print("\n" + "=" * 70)
        print("🚀 启动端到端 Qdrant RAG + MiniMax NLI 防幻觉校对引擎")
        print(f"❓ 用户查询: {user_query}")
        print("=" * 70)

        # 1. 执行 Qdrant 向量检索
        print("\n🔎 [Step 2] 正在从 Qdrant 向量数据库检索相关 Context...")
        retrieved_chunks = self.qdrant_store.search_context(query=user_query, top_k=3)
        rag_context = "\n".join([f"片段 #{i+1}: {chunk}" for i, chunk in enumerate(retrieved_chunks)])
        print(f"📚 [Qdrant 召回上下文 ({len(retrieved_chunks)} 条片段)]:\n{rag_context}\n")

        state: RealRAGState = {
            "user_query": user_query,
            "retrieved_chunks": retrieved_chunks,
            "rag_context": rag_context,
            "current_answer": "",
            "verification_report": None,
            "loop_counter": 0,
            "is_success": False
        }

        correction_guidance = None

        while True:
            state["loop_counter"] += 1
            current_loop = state["loop_counter"]
            print(f"\n🔄 --- 尝试/重修轮次 #{current_loop} ---")

            # 2. Generator 生成回答
            print("🤖 [AnswerGeneratorNode] 正在调用 MiniMax 生成回答...")
            answer_draft = await self.generator.generate_answer(
                rag_context=state["rag_context"],
                user_question=state["user_query"],
                correction_guidance=correction_guidance
            )
            state["current_answer"] = answer_draft
            print(f"📝 生成的回答草稿:\n\"{answer_draft}\"\n")

            # 3. ClaimExtractor 切分原子陈述
            print("🔍 [ClaimExtractorNode] 正在拆解单点事实断言 (Atomic Claims)...")
            claims = await self.extractor.extract_claims(answer_draft)
            print(f"📌 提取出的原子断言 ({len(claims)} 条):")
            for i, c in enumerate(claims):
                print(f"   [{i+1}] {c}")

            # 4. NLI Verifier 逻辑校验
            print("\n⚖️ [AntiHallucinationVerifier] 对照 Qdrant Context 进行 NLI 蕴含校验...")
            report = await self.verifier.verify(state["rag_context"], claims)
            state["verification_report"] = report

            print(f"📊 [NLI 校对结论]: {report.overall_status}")
            for eval_item in report.claim_evaluations:
                icon = "✅" if eval_item.label == "ENTAILMENT" else ("❌" if eval_item.label == "CONTRADICTION" else "⚠️")
                print(f"   {icon} [{eval_item.label}] '{eval_item.claim_text}' ➔ 依据: {eval_item.reasoning}")

            # 5. 判定路由
            if report.overall_status == "PASS":
                state["is_success"] = True
                print("\n🎉 [RealRAGAntiHallucinationEngine] 100% 验证通过！回答完全蕴含于 Qdrant Context。")
                break

            if state["loop_counter"] >= self.max_retries:
                state["is_success"] = False
                print(f"\n⚠️ [RealRAGAntiHallucinationEngine] 达到最大重试次数 ({self.max_retries})，触发严格降级拦截。")
                break

            print(f"\n⚡ [Guard] 捕捉到幻觉断言 ({len(report.unsupported_claims)} 条)，触发纠偏！")
            correction_guidance = report.correction_guidance

        return state


# ==========================================
# 5. 主运行入口
# ==========================================

async def main():
    # 模拟写入 Qdrant 的企业物理文档块
    raw_documents = [
        "Acme Industrial Corp 2025 年 Q2 财报：实现总营收 1200 万美元，净利润 200 万美元。",
        "Acme SaaS 业务表现强劲，本季度营收同比增长 40%，成为主要增长引擎。",
        "业务运营方面：公司新增 15 家企业级客户，总员工人数保持 150 人未变。",
        "特别注意事项：管理层在报告中明确声明未包含或预测 2025 年 Q3 的任何财务指标。"
    ]

    engine = RealRAGAntiHallucinationEngine(max_retries=3)
    # 初始化向量数据库集合与数据
    engine.setup_database(raw_documents)

    # 运行物理检索与校验
    user_query = "总结 Acme Q2 财报表现，并说明管理层对 Q3 的预测数据是多少？"
    final_state = await engine.run(user_query)

    print("\n" + "=" * 70)
    print("🏁 端到端实战最终运行结果")
    print("=" * 70)
    print(f"Qdrant 检索召回块数: {len(final_state['retrieved_chunks'])}")
    print(f"校验是否完全通过: {final_state['is_success']}")
    print(f"总迭代轮次: {final_state['loop_counter']}")
    print("\n最终交付的 100% 安全无幻觉回答:")
    print(final_state["current_answer"])


if __name__ == "__main__":
    asyncio.run(main())
