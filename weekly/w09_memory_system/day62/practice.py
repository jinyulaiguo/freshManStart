"""
Day 62: 自适应决策 - 记忆路由 (Memory Router) 与 RAG 多路检索协同 (Practice Template)

设计方案说明：
1. **设计意图**：
   在复杂的 Agent 管道中，盲目对每一次交互（如“你好”）执行全检索，会导致首字时延（TTFT）大幅膨胀。
   本模块设计前置意图路由决策器，根据用户提问在毫秒级内将流量分流至 MEM, RAG 或 NONE，
   实现自适应的“按需检索”，最大化降低系统延迟与计算开销。
2. **类与核心结构**：
   - `MemoryRouter`: 检索流向路由器类。
     - `route(query)`: 调用大模型进行三路意图分类 (MEM, RAG, NONE)，需防范 CoT 思维链干扰。
     - `execute_pipeline(query, user_id)`: 根据路由结果调用对应检索子系统，并测试性能收益。
3. **关键数据流向**：
   - Query -> LLM 分流特征匹配 -> 确定路由分支。
   - MEM 分支 -> 召回 Facts ； RAG 分支 -> 检索外部 Docs ； NONE 分支 -> 直接短路流式生成。
"""

import time
from typing import Dict, Any, List, Optional
from weekly.w04_prompt_and_http.utils import LLMClient

class MemoryRouter:
    """自适应检索流量分配路由器"""

    def __init__(self, client: Optional[LLMClient] = None):
        """初始化路由器。

        Args:
            client: 真实大模型请求客户端。
        """
        self.client = client or LLMClient()

    async def route(self, query: str) -> str:
        """分析用户当前 Query 意图，返回路由决策：MEM, RAG 或 NONE。

        - MEM: 查询涉及个人人设、个人历史偏好或先前事实（如：“我喜欢什么语言？”）。
        - RAG: 查询涉及外部专业知识、Leiden算法、PDF文档细节等（如：“Leiden原理是什么？”）。
        - NONE: 日常寒暄、日常口语或通用常识（如：“你好”、“1+1等于几”）。

        Args:
            query: 用户输入的请求提问。

        Returns:
            决策路由值：'MEM' | 'RAG' | 'NONE' 之一。
        """
        # TODO: 1. 构造强规分类 Prompt 规范
        # TODO: 2. 请求大模型，获取分类响应文本
        # TODO: 3. 防护思维链 CoT 污染（清洗掉 <think> 区域）
        # TODO: 4. 返回清洗后的大写路由值，防止首尾空白符
        raise NotImplementedError("TODO: 请实现 MemoryRouter.route")

    async def execute_pipeline(self, query: str, user_id: str) -> Dict[str, Any]:
        """根据路由决策执行具体的虚拟检索流水线，并返回执行耗时（Rtt）。

        Args:
            query: 用户输入的请求提问。
            user_id: 租户标识符。

        Returns:
            包含路由分支、检索耗时和模拟数据包的字典。
        """
        # TODO: 1. 调用 self.route 判定检索方向
        # TODO: 2. 根据方向计算并统计时间开销：
        #    - 若路由为 'NONE'，短路跳过检索，开销为 0ms
        #    - 若路由为 'MEM'，模拟读取偏好，开销为 100ms
        #    - 若路由为 'RAG'，模拟读取向量库，开销为 250ms
        # TODO: 3. 返回包含路由决策 'route'、检索时延 'rtt_ms' 和数据包 'payload' 的结果
        raise NotImplementedError("TODO: 请实现 MemoryRouter.execute_pipeline")


# 调试主入口
if __name__ == "__main__":
    print("=== 启动 Day 62 自适应检索路由调试入口 ===")
    
    router = MemoryRouter()
    
    try:
        # 尝试触发 TODO 拦截
        print("\n尝试对输入进行自适应路由决策...")
        import asyncio
        asyncio.run(router.route("你好"))
    except NotImplementedError as e:
        print(f"❌ 捕获到预期的 TODO 拦截错误: {e}")
        print("💡 请学员根据 practice.py 中的 TODO 注释编写路由与分流 Pipeline 逻辑。")
