"""
Day 13 工业级可观测性监控工程 - 标准参考答案

本文件包含两套演进方案，演示如何从“传统接口契约回调”重构到“生产级低侵入发布订阅与 AOP 切面”架构。
两套方案在物理上彻底隔离，各自包含所需的完整依赖定义。

================================================================================
【方案 A】 传统接口契约回调注入模式（显式耦合）
================================================================================
"""

import time
import uuid
import logging
import traceback
from typing import Dict, Any, List, Callable

# 设置日志格式
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

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
        
        # 1. 触发 on_step_start 回调，使用 try-except 进行旁路隔离
        for cb in self.callbacks:
            try:
                cb.on_step_start(run_id, step_name, task_data)
            except Exception as cb_err:
                logging.error(f"[CallbackA] on_step_start 触发失败: {cb_err}")
        
        try:
            if "fail_trigger" in task_data:
                raise KeyError(f"Missing required parameter: {task_data['fail_trigger']}")
            
            result = {"status": "success", "data": f"Executed {step_name} successfully."}
            duration = time.perf_counter() - start_time
            
            # 2. 触发 on_step_end 回调
            for cb in self.callbacks:
                try:
                    cb.on_step_end(run_id, step_name, result, duration)
                except Exception as cb_err:
                    logging.error(f"[CallbackA] on_step_end 触发失败: {cb_err}")
            
            return result
        except Exception as original_err:
            duration = time.perf_counter() - start_time
            wrapped_err = ToolExecuteError(str(original_err), tool_name=step_name, execution_time=duration)
            wrapped_err.__cause__ = original_err
            
            # 3. 触发 on_step_error 回调
            for cb in self.callbacks:
                try:
                    cb.on_step_error(run_id, step_name, wrapped_err, duration)
                except Exception as cb_err:
                    logging.error(f"[CallbackA] on_step_error 触发失败: {cb_err}")
            
            raise wrapped_err from original_err


# ================================================================================
# 【方案 B】 生产级低侵入发布订阅与 AOP 装饰器拦截模式
# ================================================================================
"""
方案 B 说明：
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
                    logging.error(f"[EventBus] 执行订阅者事件处理失败: {e}")

def trace_event(step_name: str):
    """
    AOP 拦截装饰器。
    """
    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            run_id = str(uuid.uuid4())
            # 假设第一个参数通常是 self，获取真实的输入参数字典
            inputs = {"args": args[1:] if len(args) > 1 else args, "kwargs": kwargs}
            
            # 发布开始事件
            EventBus.publish("step_start", {
                "run_id": run_id,
                "step_name": step_name,
                "inputs": inputs
            })
            
            start_time = time.perf_counter()
            try:
                # 执行核心业务函数
                result = func(*args, **kwargs)
                
                duration = time.perf_counter() - start_time
                # 发布结束事件
                EventBus.publish("step_end", {
                    "run_id": run_id,
                    "step_name": step_name,
                    "outputs": result,
                    "duration": duration
                })
                return result
            except Exception as e:
                duration = time.perf_counter() - start_time
                wrapped_err = AgentSystemError(str(e), trace_id=run_id)
                wrapped_err.__cause__ = e
                
                # 发布异常事件
                EventBus.publish("step_error", {
                    "run_id": run_id,
                    "step_name": step_name,
                    "error": wrapped_err,
                    "duration": duration
                })
                raise wrapped_err from e
        return wrapper
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
    print("=== [Day 13 Standard Answer] 物理隔离架构演进对比测试 ===")
    
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
    except ToolExecuteError as e:
        print(f"🎉 [Main] 方案 A 捕获到 ToolExecuteError: {e}")

    # ---------------- 运行方案 B 调试 ----------------
    print("\n--- [方案 B] AOP 与 EventBus 拦截测试 ---")
    # 注册订阅者事件处理器，完全与引擎隔离
    def log_bus_start(data: Dict[str, Any]):
        print(f"🔥 [Bus][Start] 拦截到步骤 [{data['step_name']}] 开始，ID: {data['run_id'][:8]}，参数: {data['inputs']}")

    def log_bus_end(data: Dict[str, Any]):
        print(f"✨ [Bus][End] 拦截到步骤 [{data['step_name']}] 完成，耗时: {data['duration']:.4f}s")

    def log_bus_error(data: Dict[str, Any]):
        print(f"💥 [Bus][Error] 拦截到步骤 [{data['step_name']}] 崩溃，耗时: {data['duration']:.4f}s")
        # 格式化打印包装后的链式堆栈
        err = data['error']
        tb = "".join(traceback.format_exception(type(err), err, err.__traceback__))
        print("------------- 方案 B 订阅端堆栈日志 -------------")
        print(tb.strip())
        print("-----------------------------------------------")
        
    EventBus.subscribe("step_start", log_bus_start)
    EventBus.subscribe("step_end", log_bus_end)
    EventBus.subscribe("step_error", log_bus_error)
    
    runner_b = AgentRunnerB()
    
    # 1. 测试方案 B 正常调用流程
    runner_b.load_config("app_config.yaml")
    
    # 2. 测试方案 B 崩溃拦截流程
    try:
        runner_b.load_config("invalid_config.json") # 会触发 ValueError 从而被装饰器捕获
    except AgentSystemError as e:
        print(f"🎉 [Main] 方案 B 捕获到解耦后的 AgentSystemError: {e}")
