"""
Week 4 Day 22 参考答案：基于真实 API 自一致性（Self-Consistency）与 CoT 的异步并行投票路由引擎

设计方案：
1. 设计意图：
   使用真实的大模型接口，对存在业务边界模糊的复杂路由指令进行决策分类。
   通过在 Python 侧以 asyncio.gather 并发拉取多次采样（合理温度采样如 T=0.7），
   并利用正则匹配提取返回文本中的 [[AgentName]] 选项，最后通过多数票表决输出最终高置信度路由，
   以此直观演示自一致性提升路由稳定性的底层机制。

2. 类与函数 structure：
   - 包含工程级 sys.path 自动补丁逻辑，确保任何执行路径下均能正确导入工程模块。
   - 继承自公共工具模块 `weekly.w04_prompt_and_http.utils.LLMClient` 基类。
   - `LLMClient`: 路由专属 API 客户端，封装特定 Prompt 与推理指令，调用基类网络接口。
   - `SelfConsistencyEvaluator`: 自一致性异步并发评估器。
     - `evaluate()`: 异步并发采样并执行多数票路由选择。
     - `_extract_choice()`: 使用正则匹配决策标识。
     - `_vote()`: 统计有效票数与置信度。

3. 关键数据流向：
   Query ──> Evaluator.evaluate() ──(并发 asyncio.gather)──> LLMClient (调用公共 API) ──> 
   获取 N 个真实 CoT 文本 ──> _extract_choice() 正则提取 ──> _vote() 统计 ──> 输出高置信度 Agent。
"""

import sys
import os

# =====================================================================
# 防御性 sys.path 补丁逻辑 (防止跨层级目录执行时发生 ModuleNotFoundError)
# =====================================================================
# current_dir: weekly/w04_prompt_and_http/day22
# .. -> weekly/w04_prompt_and_http
# ../.. -> weekly
# ../../../ -> 03.freshManStart (工作区根目录)
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "../../.."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import asyncio
import re
from collections import Counter
# 导入公共工具基类
from weekly.w04_prompt_and_http.utils import LLMClient as BaseLLMClient

# =====================================================================
# 核心架构与业务引擎实现
# =====================================================================

class LLMClient(BaseLLMClient):
    """路由专属大模型客户端，继承自公共请求基类"""

    async def generate_routing_decision(self, query: str, temperature: float = 0.7) -> str:
        """异步请求大模型，返回包含 CoT 推理及 [[AgentName]] 包裹的路由文本"""
        # 强制简短 CoT 与严格选项输出格式，控制 Token 预算
        system_prompt = (
            "你是一个高精度规划路由 Agent (Routing Agent)。你的职责是根据用户的 Query，"
            "分析用户意图，决定是将任务分发给 DatabaseAgent 还是 CodeAgent。\n"
            "【路由规则】\n"
            "1. 如果用户意图涉及‘查询数据库’、‘检索数据表’、‘提取SQL数据’等，输出 Choice: [[DatabaseAgent]]。\n"
            "2. 如果用户意图涉及‘计算’、‘编写代码’、‘算法处理’、‘生成报表计算’等，输出 Choice: [[CodeAgent]]。\n"
            "【格式限制】\n"
            "- 请先进行简短分步推理 (Chain-of-Thought)，字数控制在 100 字以内。\n"
            "- 最后另起一行，必须且只能输出一行结果，格式为: Choice: [[AgentName]]，其中 AgentName 只能是 DatabaseAgent 或 CodeAgent。"
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"用户的 Query 如下：\n{query}\n\n请开始你的分步推理并给出最终 Choice："}
        ]
        
        # 直接调用公共基类的 request_llm 方法，避免重复拼装 HTTP 头和超时设置
        return await self.request_llm(messages, temperature=temperature, max_tokens=800)


class SelfConsistencyEvaluator:
    """自一致性（Self-Consistency）异步并发评估器"""

    def __init__(self, client: LLMClient, sample_size: int = 5, temperature: float = 0.7):
        self.client = client
        self.sample_size = sample_size
        self.temperature = temperature
        # 匹配双中括号选项，如 [[DatabaseAgent]]
        self.pattern = re.compile(r"\[\[([a-zA-Z0-9_]+)\]\]")

    def _extract_choice(self, text: str) -> str | None:
        """正则匹配提取，过滤废票与脏格式"""
        match = self.pattern.search(text)
        if not match:
            return None
        choice = match.group(1)
        # 排除模型生成的无关/无效占位符
        if choice in ("UnknownFormat", "AgentName", "None"):
            return None
        return choice

    def _vote(self, choices: list[str]) -> tuple[str, float]:
        """多数票投票机制与置信度计算"""
        valid_choices = [c for c in choices if c is not None]
        if not valid_choices:
            return "FallbackAgent", 0.0
            
        counter = Counter(valid_choices)
        most_common = counter.most_common(1)[0]
        best_choice = most_common[0]
        # 置信度 = 多数票数 / 有效总票数
        confidence = most_common[1] / len(valid_choices)
        return best_choice, confidence

    async def evaluate(self, query: str) -> dict:
        """执行自一致性投票的异步主入口"""
        # 并发向大模型发送 API 请求采样
        tasks = [
            self.client.generate_routing_decision(query, self.temperature) 
            for _ in range(self.sample_size)
        ]
        
        # 收集异步响应结果，隔离网络异常报错，防止部分异常拖垮全局
        raw_responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        extracted_choices = []
        clean_responses = []
        
        for idx, resp in enumerate(raw_responses):
            if isinstance(resp, Exception):
                print(f"[⚠️ WARNING] 采样 {idx+1} 请求网络异常: {resp}")
                clean_responses.append(f"Network error: {str(resp)}")
                continue
                
            clean_responses.append(resp)
            choice = self._extract_choice(resp)
            if choice:
                extracted_choices.append(choice)
                
        # 投票决策与兜底降级
        if not extracted_choices:
            return {
                "decision": "FallbackAgent",
                "confidence": 0.0,
                "raw_votes": {},
                "raw_responses": clean_responses
            }
            
        decision, confidence = self._vote(extracted_choices)
        raw_votes = dict(Counter(extracted_choices))
        
        return {
            "decision": decision,
            "confidence": confidence,
            "raw_votes": raw_votes,
            "raw_responses": clean_responses
        }


# =====================================================================
# 多方案对比调试与运行主入口 (物理隔离与冗余设计)
# =====================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("🚀 Week 4 Day 22 真实 API 自一致性投票对比实验 (已引入公共工具模块)")
    print("=" * 70)
    
    # 实例化真实 API 客户端
    try:
        client = LLMClient()
    except Exception as e:
        print(f"❌ 初始化大模型客户端失败: {e}")
        print("请确认项目根目录下已配置正确的 .env 环境变量文件。")
        import sys
        sys.exit(1)

    # 复杂歧义输入：既涉及数据库，又涉及复杂的 Python 计算重构
    query = "帮我从 SQL 数据库提取上个月的销售额度，并写个 Python 脚本把这些数据做复杂的二次回归计算和报表分析"

    # -----------------------------------------------------------------
    # 【方案一】 低温度贪婪搜索测试 (Temperature = 0.01)
    # -----------------------------------------------------------------
    print("\n[方案一] 运行贪婪搜索采样 (Temperature = 0.01)...")
    evaluator_greedy = SelfConsistencyEvaluator(client, sample_size=3, temperature=0.01)
    
    async def run_greedy():
        result = await evaluator_greedy.evaluate(query)
        print(f"最终路由决策: {result['decision']}")
        print(f"多数票置信度: {result['confidence'] * 100:.1f}%")
        print("各路径输出汇总:")
        for idx, resp in enumerate(result['raw_responses']):
            if result['decision'] == "FallbackAgent":
                print(f"  采样 [{idx+1}] 完整输出:\n{resp}\n")
            else:
                lines = resp.split("\n")
                print(f"  采样 [{idx+1}] 结尾: ... " + " | ".join([line.strip() for line in lines[-2:] if line.strip()]))
            
    asyncio.run(run_greedy())

    print("-" * 70)

    # -----------------------------------------------------------------
    # 【方案二】 异步并发自一致性投票 (Temperature = 0.7)
    # -----------------------------------------------------------------
    print("\n[方案二] 运行自一致性并行投票采样 (Temperature = 0.7)...")
    evaluator_sc = SelfConsistencyEvaluator(client, sample_size=5, temperature=0.7)
    
    async def run_sc():
        result = await evaluator_sc.evaluate(query)
        print(f"最终路由决策: {result['decision']}")
        print(f"多数票置信度: {result['confidence'] * 100:.1f}%")
        print(f"有效票数统计: {result['raw_votes']}")
        print("各路径输出汇总:")
        for idx, resp in enumerate(result['raw_responses']):
            if result['decision'] == "FallbackAgent":
                print(f"  采样 [{idx+1}] 完整输出:\n{resp}\n")
            else:
                lines = resp.split("\n")
                print(f"  采样 [{idx+1}] 结尾: ... " + " | ".join([line.strip() for line in lines[-2:] if line.strip()]))
            
    asyncio.run(run_sc())
    print("=" * 70)
