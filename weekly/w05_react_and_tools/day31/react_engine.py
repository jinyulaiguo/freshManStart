"""
设计方案：
1. 设计意图：构建一个 MiniReActEngine 执行引擎，实现异步 while 控制循环，通过 deepcopy 提供历史状态快照存储，并在执行步数溢出（max_steps 截断）或异常发生时自动执行状态回滚，确保全局上下文数据不被污染。
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
        
        response_idx = 0
        
        try:
            # 开启异步主控制环
            while self.current_state.steps < self.max_steps:
                # 1. 深度拷贝全局状态备份并压栈，确保物理内存完全隔离
                state_snapshot = copy.deepcopy(self.current_state)
                self.history_states.append(state_snapshot)
                
                # 2. 递增当前步骤计数器
                self.current_state.steps += 1
                current_step = self.current_state.steps
                
                print(f"-> 进入第 {current_step} 步控制循环...")
                
                # 3. 模拟接收大模型响应
                if response_idx >= len(mock_llm_responses):
                    raise RuntimeError("模拟响应已耗尽，但模型尚未达成终止协议。")
                    
                llm_response = mock_llm_responses[response_idx]
                response_idx += 1
                
                # 模拟记录大模型 Thought 推理
                self.current_state.messages.append({
                    "role": "assistant",
                    "content": llm_response["thought"],
                    "action": llm_response["action"],
                    "params": llm_response["params"]
                })
                
                print(f"   [Thought]: {llm_response['thought']}")
                print(f"   [Action] : '{llm_response['action']}' 参数: {llm_response['params']}")
                
                # 4. 判断终止协议 (Termination Protocol)
                if llm_response["action"] == "Finish":
                    print("   🎉 命中终止协议，平滑退出控制环。")
                    return {
                        "status": "success",
                        "steps_used": self.current_state.steps,
                        "final_reply": llm_response["params"].get("result", "")
                    }
                    
                # 模拟执行外部工具的逻辑延迟
                # 在真实 ReAct 引擎中，此处将进入 Tool Dispatch 阶段，产生 Observation 并追加回历史消息
                print("   [System] : 模拟调度工具并获得 Observation...")
                self.current_state.messages.append({
                    "role": "tool",
                    "name": llm_response["action"],
                    "content": "模拟工具执行结果: Success."
                })
            
            # 若退出 while 循环仍未达成 Finish，说明步骤数溢出，抛出强拦截异常
            raise AgentStepOverflowError(
                f"控制流强拦截：执行步骤已达到最大限制 {self.max_steps} 步，但未完成目标。"
            )
            
        except (AgentStepOverflowError, Exception) as e:
            print(f"\n🚨 引擎发生异常: {e}")
            # 5. 执行状态回滚 (Rollback)
            if self.history_states:
                # 回滚到发生本次异常循环前的最后一个健康快照状态
                self.current_state = self.history_states[-1]
                print(f"🔄 状态回滚机制生效：全局状态已安全恢复至最近一次快照 (快照步数: {self.current_state.steps})")
                print(f"   当前消息历史长度: {len(self.current_state.messages)}")
            else:
                print("⚠️ 快照栈为空，无法执行回滚恢复。")
            raise e

if __name__ == "__main__":
    import asyncio
    
    async def main():
        # --- 测试场景一：正常流程（在 max_steps 内平滑退出） ---
        print("=" * 60)
        print("【测试场景一】: 正常流程在步数限制内完成")
        print("=" * 60)
        
        engine = MiniReActEngine(max_steps=5)
        initial_msgs = [{"role": "user", "content": "查一下今天的天气并计算出行费用"}]
        
        mock_responses = [
            {"thought": "先查询天气", "action": "get_weather", "params": {"city": "北京"}},
            {"thought": "天气良好，再计算出行租车费用", "action": "calculator", "params": {"exp": "30 * 2"}},
            {"thought": "所有数据已齐备，输出最终答复", "action": "Finish", "params": {"result": "今天北京晴天，出行费用为 60 元"}}
        ]
        
        res = await engine.run(initial_msgs, mock_responses)
        print(f"\n最终返回结果: {res}\n")
        
        # --- 测试场景二：溢出强拦截与自动状态回滚 ---
        print("=" * 60)
        print("【测试场景二】: 步数超出 max_steps 阈值强拦截并回滚")
        print("=" * 60)
        
        # 设置 max_steps 为 2，但模拟响应需要 3 步才能完成
        strict_engine = MiniReActEngine(max_steps=2)
        
        try:
            # 期望在第 3 步开始前被 max_steps 强拦截，且状态恢复到第 2 步结束前的合法状态
            await strict_engine.run(initial_msgs, mock_responses)
        except AgentStepOverflowError:
            print("\n✅ 成功捕获预期的步数溢出异常！")
            print(f"验证回滚后的引擎状态步数: {strict_engine.current_state.steps} (回滚到步骤 2 开始前的健康快照 1)")
            
        print("=" * 60)

    asyncio.run(main())
