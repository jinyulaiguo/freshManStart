"""
Day 80 练习模版: LLM-as-Critic 独立审查器与双模型博弈架构

【系统设计方案说明】
1. 设计意图 (Design Intent):
   构建生产级 Generator-Critic 双模型博弈架构引擎。引入独立系统提示词的 Critic 法官节点，
   扫描生成物中的逻辑漏洞、合规盲区与格式缺陷，输出强类型 Pydantic 决策 Payload (PASS/REJECT)。
   解决单一模型自查存在认知盲区与自我包庇的问题，提升高严肃性业务文本 (如英文法律合同) 的可靠性。

2. 类与函数结构 (Class & Function Architecture):
   - CriticReview: Pydantic 模型，定义物理隔离的审查决策契约 (decision, score, risk_items, critique_feedback)。
   - ContractDraft: Pydantic 模型，存储生成的合同文本草稿与版本号。
   - CriticGameState: TypedDict 状态容器，维护合同需求、当前草稿、历次审查记录与博弈计数器。
   - GeneratorNode: 负责根据用户需求或 Critic 反馈 Payload 生成/修订合同草稿。
   - CriticNode: 独立的审查法官节点，以防范风险为导向进行盲审，输出 CriticReview。
   - GameLoopGuard: 博弈收敛与熔断控制器，防止无限 REJECT 循环。

3. 关键数据流流向 (Data Flow):
   User Input ➔ GeneratorNode ➔ ContractDraft ➔ CriticNode ➔ CriticReview Payload
     ➔ Router Edge ➔ (If PASS & Score>=85) ➔ END Node
     ➔ Router Edge ➔ (If REJECT & Loop<3) ➔ GeneratorNode (Revision with Feedback)
     ➔ Router Edge ➔ (If Loop>=3) ➔ Manual Intercept / Fallback Node

4. 核心用例设计意图 (Test Case Design Intent):
   选取“自动生成合规的跨境软件服务 (SaaS) 英文法律合同”作为标准验证场景：
   - 验证点 1：测试 Generator 在初次生成时故意缺少关键保护条款（如未写违约金上限或终止通知期）。
   - 验证点 2：测试 Critic Node 能否独立识别出上述合同隐患，准确输出 REJECT 及针对性的修改指令。
   - 验证点 3：测试 Router 条件路由能否成功将 Critic Feedback 喂回 Generator 进行二次修改。
   - 验证点 4：测试修改后的合同草稿能否成功通过 Critic 审查（输出 PASS & Score>=85），验证博弈收敛能力。
"""

import asyncio
import json
from typing import Dict, List, Any, Optional, Literal, TypedDict
from pydantic import BaseModel, Field

# 从公共工具加载 API 凭证与配置 (规则 12 & 20)
from weekly.w04_prompt_and_http.utils import load_env_file, LLMClient

# 加载环境变量
load_env_file()


# ==========================================
# 1. 强类型 Pydantic Schema 契约
# ==========================================

class CriticReview(BaseModel):
    """
    Critic 独立审查法官强类型决策 Payload
    """
    decision: Literal["PASS", "REJECT"] = Field(description="审查结论：PASS(通过) 或 REJECT(驳回重构)")
    score: int = Field(ge=0, le=100, description="综合合规与严密性评分 (0-100)")
    risk_items: List[str] = Field(default_factory=list, description="检测到的缺陷、排版隐患或法律风险清单")
    critique_feedback: str = Field(description="具体的修订指令，供 Generator 在下一轮精准修复")


class ContractDraft(BaseModel):
    """
    生成器产出的合同草稿契约
    """
    title: str = Field(description="合同名称")
    content: str = Field(description="合同全文内容")
    version: int = Field(default=1, description="草稿版本号")


class CriticGameState(TypedDict):
    """
    LangGraph 状态图全局 TypedDict 容器
    """
    contract_requirement: str
    current_draft: Optional[ContractDraft]
    latest_review: Optional[CriticReview]
    loop_counter: int  # 博弈轮次计数器


# ==========================================
# 2. 核心微引擎实现 (学员 TODO 练习区)
# ==========================================

class GameLoopGuard:
    """
    博弈收敛与熔断控制器
    """

    def __init__(self, max_loops: int = 3, pass_score: int = 85):
        self.max_loops = max_loops
        self.pass_score = pass_score

    def evaluate_routing(self, state: CriticGameState) -> str:
        """
        判断博弈路由流向

        :param state: 全局 CriticGameState
        :return: 路由信号 ("TO_END", "TO_GENERATOR_REVISE", "TO_FALLBACK")
        """
        # TODO: 学员需实现博弈收敛与熔断路由逻辑
        # 提示: 判断 review.decision == "PASS" and review.score >= self.pass_score
        # 提示: 判断 state["loop_counter"] >= self.max_loops
        raise NotImplementedError("TODO: 请实现 GameLoopGuard.evaluate_routing 路由判定逻辑")


class GeneratorNode:
    """
    生成器节点 (Generator)
    负责初始生成合同，或根据 Critic 反馈进行针对性修订
    """

    def __init__(self):
        self.llm_client = LLMClient()

    async def generate_initial_draft(self, requirement: str) -> ContractDraft:
        """
        根据用户需求初始生成合同草稿
        """
        # TODO: 学员需实现初始合同生成的 Prompt 与结构化提取
        raise NotImplementedError("TODO: 请实现 GeneratorNode.generate_initial_draft 逻辑")

    async def revise_draft(self, draft: ContractDraft, feedback: str) -> ContractDraft:
        """
        根据 Critic 的修改意见针对性修订合同草稿
        """
        # TODO: 学员需实现结合 Feedback 修订合同的逻辑
        raise NotImplementedError("TODO: 请实现 GeneratorNode.revise_draft 逻辑")


class CriticNode:
    """
    独立审查法官节点 (Critic Node)
    物理隔离于 Generator，以严格法官身份进行盲审
    """

    def __init__(self):
        self.llm_client = LLMClient()

    async def review_contract(self, requirement: str, draft: ContractDraft) -> CriticReview:
        """
        审查合同草稿，输出强类型 CriticReview 决策 Payload
        """
        # TODO: 学员需实现独立审查提示词与 CriticReview 解析逻辑
        raise NotImplementedError("TODO: 请实现 CriticNode.review_contract 逻辑")


# ==========================================
# 3. 调试主入口 (规则 1 & 6)
# ==========================================

if __name__ == "__main__":
    print("=" * 70)
    print("Day 80 练习验证: LLM-as-Critic 独立审查器与双模型博弈架构")
    print("=" * 70)

    sample_requirement = "生成一份跨境 SaaS 软件授权服务协议 (SaaS Agreement)，需包含服务级别 SLA、数据隐私条款及责任限制。"

    print(f"\n[测试合同需求]: {sample_requirement}\n")

    try:
        generator = GeneratorNode()
        print("[1] 尝试拉起 GeneratorNode 生成初始草稿...")
        draft = asyncio.run(generator.generate_initial_draft(sample_requirement))
        print(f"✅ 生成初始草稿成功! 标题: {draft.title} (v{draft.version})")

    except NotImplementedError as e:
        print(f"\n⚠️  [拦截到未实现 TODO]: {e}")
        print("👉 请打开 `practice.py` 补充核心逻辑，或参考同目录下的标准答案代码。")
    except Exception as e:
        print(f"\n❌ [运行发生异常]: {e}")
