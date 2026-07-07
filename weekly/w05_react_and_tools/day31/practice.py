"""
设计方案：
1. 设计意图：构建一个 MiniReActEngine 执行引擎骨架，实现异步 while 控制循环，通过 deepcopy 提供历史状态快照存储，并在执行步数溢出（max_steps 截断）或异常发生时自动执行状态回滚，确保全局上下文数据不被污染。
2. 类与函数结构：
   - AgentState: 存储 Agent 上下文状态的容器类。
     - __init__(self, messages: list, steps: int = 0)
   - AgentStepOverflowError: 步数溢出自定义异常。
   - MiniReActEngine: 核心 ReAct 执行循环类。
     - __init__(self, max_steps: int = 5): 初始化最大限制步数与状态存储。
     - run(self, initial_messages: list, mock_llm_responses: list) -> dict: 执行主循环，模拟调用 LLM，并在出错或溢出时回滚。
3. 数据流流向：
   - 外部传入 initial_messages 初始化引擎的 current_state。
   - 异步循环开始，在 steps >= max_steps 时触发溢出异常。
   - 每一轮循环开始前，将 current_state 深拷贝并追加进 history_states 快照栈。
   - steps 计数加 1。
   - 从 mock_llm_responses 中取出当前轮次的 LLM 模拟输出，判断是否为终止（如 action 为 'Finish'）。
   - 如果遇到意外执行错误（或 mock 抛错），在 try-except 块中捕获，并将 current_state 恢复为 history_states 栈顶的合法状态。
"""
import copy
from typing import List, Dict, Any

class AgentState:
    def __init__(self, messages: List[Dict[str, Any]], steps: int = 0):
        self.messages = messages
        self.steps = steps

class AgentStepOverflowError(Exception):
    """当 Agent 执行步数超过 max_steps 时抛出的异常"""
    pass

class MiniReActEngine:
    def __init__(self, max_steps: int = 5):
        """
        初始化 ReAct 引擎
        
        Args:
            max_steps: 引擎允许的最大执行循环步数，默认为 5
        """
        self.max_steps = max_steps
        self.current_state: AgentState = None
        self.history_states: List[AgentState] = []

    async def run(self, initial_messages: List[Dict[str, Any]], mock_llm_responses: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        执行异步主控制环。
        
        Args:
            initial_messages: 初始输入的消息流
            mock_llm_responses: 模拟 LLM 决策输出的序列。每项包含：
                                {"thought": str, "action": str, "params": dict}
                                其中 action 为 "Finish" 代表终止。
                                
        Returns:
            执行结果字典，包含退出状态及最终消息
        """
        self.current_state = AgentState(messages=initial_messages, steps=0)
        self.history_states = []
        
        # 记录 LLM 响应指针
        response_idx = 0
        
        try:
            # TODO: 实现限制在 max_steps 内的异步主循环
            # TODO: 每次循环前，必须对 self.current_state 进行 copy.deepcopy 备份，并压入 self.history_states
            # TODO: 递增 steps 计数器
            # TODO: 模拟 LLM 决策，解析终止标识（action == "Finish"）并平滑退出
            # TODO: 如果响应序列耗尽且未终止，抛出异常以模拟运行期失控
            
            raise NotImplementedError("TODO: 请先在 run 中实现主决策 while 循环与状态深拷贝备份逻辑")
            
        except (AgentStepOverflowError, Exception) as e:
            # TODO: 捕获异常后，从 self.history_states 快照栈中恢复到最近一次健康的 state
            raise NotImplementedError("TODO: 请实现状态回滚机制")

if __name__ == "__main__":
    print("=" * 60)
    print("运行 MiniReActEngine 调试模板...")
    print("=" * 60)
    
    engine = MiniReActEngine(max_steps=3)
    
    # 模拟输入
    initial_msgs = [{"role": "user", "content": "帮我计算一下数据"}]
    
    # 模拟 LLM 在第 2 轮结束
    mock_responses = [
        {"thought": "需要调用计算器", "action": "calculator", "params": {"exp": "1+1"}},
        {"thought": "已得出答案", "action": "Finish", "params": {"result": "2"}}
    ]
    
    try:
        import asyncio
        result = asyncio.run(engine.run(initial_msgs, mock_responses))
        print(f"🎉 正常执行退出成功: {result}")
    except NotImplementedError as e:
        print(f"\n❌ 拦截到 TODO 占位：\n{e}")
    except Exception as e:
        print(f"\n❌ 运行异常: {e}")
        
    print("=" * 60)
