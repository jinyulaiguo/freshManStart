"""
Day 13 工业级可观测性监控工程 - 练习模板

本练习分两套演进方案，演示如何从“硬编码侵入式回调”重构到“生产级低侵入发布订阅与 AOP 切面”架构。
两套方案在物理上彻底隔离，各自包含所需的完整依赖定义。

================================================================================
【方案 A】 传统接口契约回调注入模式（显式耦合）
================================================================================
说明：
引擎在运行期需要显式持有并循环触发各种 CallbackHandler 的各个生命周期钩子。
"""

import time
import uuid
import logging
import traceback
from typing import Dict, Any, List, Callable

# ======================== 方案 A 依赖与定义 ========================

class BaseAgentException(Exception):
    """Agent 业务层异常基类"""
    def __init__(self, message: str, error_code: int = 50000, user_message: str = "系统执行异常，请稍后重试"):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.user_message = user_message

class ToolExecuteError(BaseAgentException):
    """工具调用/执行阶段异常"""
    def __init__(self, message: str, tool_name: str, execution_time: float = 0.0):
        full_msg = f"工具 [{tool_name}] 在运行 {execution_time:.4f} 秒后崩溃: {message}"
        super().__init__(full_msg, error_code=50001, user_message="外部工具执行失败，请检查输入参数")
        self.tool_name = tool_name
        self.execution_time = execution_time

class BaseAgentCallback:
    """Agent 生命周期回调基类契约"""
    def on_step_start(self, run_id: str, step_name: str, inputs: Dict[str, Any]) -> None:
        pass

    def on_step_end(self, run_id: str, step_name: str, outputs: Dict[str, Any], duration: float) -> None:
        pass

    def on_step_error(self, run_id: str, step_name: str, error: Exception, duration: float) -> None:
        pass

class AgentRunnerA:
    """方案 A 核心执行引擎：依赖回调注入"""
    def __init__(self, callbacks: List[BaseAgentCallback] = None):
        self.callbacks = callbacks or []

    def run_step(self, step_name: str, task_data: Dict[str, Any]) -> Dict[str, Any]:
        run_id = str(uuid.uuid4())
        start_time = time.perf_counter()
        
        # TODO 1: 触发所有已注册回调的 on_step_start 方法，注意用 try-except 进行旁路隔离
        
        try:
            if "fail_trigger" in task_data:
                raise KeyError(f"Missing required parameter: {task_data['fail_trigger']}")
            
            result = {"status": "success", "data": f"Executed {step_name} successfully."}
            duration = time.perf_counter() - start_time
            
            # TODO 2: 触发所有已注册回调的 on_step_end 方法，传入 run_id 与 duration
            
            return result
        except Exception as original_err:
            duration = time.perf_counter() - start_time
            wrapped_err = ToolExecuteError(str(original_err), tool_name=step_name, execution_time=duration)
            wrapped_err.__cause__ = original_err
            
            # TODO 3: 触发所有已注册回调的 on_step_error 方法，并向上 raise 抛出包装后的异常
            raise NotImplementedError("方案 A 回调触发与异常链包装逻辑待实现！")


# ================================================================================
# 【方案 B】 生产级低侵入发布订阅与 AOP 装饰器拦截模式
# ================================================================================
"""
说明：
主引擎 `AgentRunnerB` 与监控逻辑完全解耦，核心函数中看不见任何 Callback 调用的字眼。
完全通过一个 `@trace_event` 装饰器切面和全局 `EventBus` 实现生命周期的拦截和事件推送。
"""

# ======================== 方案 B 依赖与定义 ========================

class AgentSystemError(Exception):
    """方案 B 系统级核心异常，封装业务码与 Trace ID"""
    def __init__(self, message: str, trace_id: str, error_code: int = 50002):
        super().__init__(f"[TraceID: {trace_id}] {message}")
        self.trace_id = trace_id
        self.error_code = error_code

class EventBus:
    """全局事件总线（发布订阅模式）"""
    _subscribers: Dict[str, List[Callable]] = {}

    @classmethod
    def subscribe(cls, event_type: str, handler: Callable) -> None:
        """注册监听指定事件类型的回调函数"""
        if event_type not in cls._subscribers:
            cls._subscribers[event_type] = []
        cls._subscribers[event_type].append(handler)

    @classmethod
    def publish(cls, event_type: str, data: Dict[str, Any]) -> None:
        """发布事件通知所有订阅者（进行防御性调用）"""
        if event_type in cls._subscribers:
            for handler in cls._subscribers[event_type]:
                try:
                    handler(data)
                except Exception as e:
                    # 旁路防爆保护
                    logging.error(f"[EventBus] 执行订阅者事件处理失败: {e}")

# TODO 4: 完成 AOP 装饰器 trace_event 的编写，动态拦截底层方法的开始、结束和异常
def trace_event(step_name: str):
    """
    AOP 拦截装饰器。
    
    事件机制：
    - 开始时向 EventBus 发布 "step_start" 事件，参数携带 run_id, step_name, inputs。
    - 成功时向 EventBus 发布 "step_end" 事件，参数携带 run_id, step_name, outputs, duration。
    - 失败时向 EventBus 发布 "step_error" 事件，参数携带 run_id, step_name, error, duration。
    """
    def decorator(func: Callable):
        # 提示：在此处编写装饰器 wrapper 逻辑，使用 time.perf_counter() 统计耗时，并捕获异常包装抛出
        # 记得使用 uuid 生成 run_id 并在抛出异常时将其作为 trace_id 绑定到 AgentSystemError 中
        raise NotImplementedError("AOP 拦截装饰器逻辑待实现！")
    return decorator

class AgentRunnerB:
    """方案 B 核心引擎：高内聚，零回调逻辑硬编码"""
    
    @trace_event(step_name="LoadConfiguration")
    def load_config(self, config_path: str) -> Dict[str, Any]:
        """模拟加载配置文件的同步操作，可能有配置丢失风险"""
        time.sleep(0.05) # 模拟 I/O 耗时
        if not config_path.endswith(".yaml"):
            raise ValueError(f"不支持的文件格式: {config_path}")
        return {"db_host": "localhost", "port": 5432}

# ======================== 全局调试启动入口 ========================

if __name__ == "__main__":
    print("=== [Day 13 Practice] 物理隔离架构演进对比练习 ===")
    
    # ---------------- 运行方案 A 调试 ----------------
    print("\n--- [方案 A] 传统显式注入回调测试 ---")
    class DemoCallbackA(BaseAgentCallback):
        def on_step_start(self, run_id: str, step_name: str, inputs: Dict[str, Any]):
            print(f"[A][Start] 运行 {step_name}，ID: {run_id[:8]}")
        def on_step_end(self, run_id: str, step_name: str, outputs: Dict[str, Any], duration: float):
            print(f"[A][End] 成功，耗时: {duration:.4f}s")
        def on_step_error(self, run_id: str, step_name: str, error: Exception, duration: float):
            print(f"[A][Error] 失败！耗时: {duration:.4f}s，异常: {error}")
            
    runner_a = AgentRunnerA(callbacks=[DemoCallbackA()])
    try:
        runner_a.run_step("CallAPI", {"fail_trigger": "connection_lost"})
    except NotImplementedError as e:
        print(f"❌ 方案 A 拦截未实现提示: {e}")
    except ToolExecuteError as e:
        print(f"🎉 方案 A 运行成功，捕获到 ToolExecuteError: {e}")

    # ---------------- 运行方案 B 调试 ----------------
    print("\n--- [方案 B] AOP 与 EventBus 拦截测试 ---")
    # 注册订阅者事件处理器，完全与引擎隔离
    def log_bus_start(data: Dict[str, Any]):
        print(f"🔥 [Bus][Start] 拦截到步骤 [{data['step_name']}] 开始，ID: {data['run_id'][:8]}，参数: {data['inputs']}")

    def log_bus_error(data: Dict[str, Any]):
        print(f"💥 [Bus][Error] 拦截到步骤 [{data['step_name']}] 崩溃，耗时: {data['duration']:.4f}s，错误码: {data['error'].error_code}")
        
    EventBus.subscribe("step_start", log_bus_start)
    EventBus.subscribe("step_error", log_bus_error)
    
    runner_b = AgentRunnerB()
    try:
        runner_b.load_config("invalid_config.json") # 会触发 ValueError 从而被装饰器捕获
    except NotImplementedError as e:
        print(f"❌ 方案 B 拦截未实现提示: {e}")
    except AgentSystemError as e:
        print(f"🎉 方案 B 运行成功，捕获到解耦后的 AgentSystemError: {e}")
