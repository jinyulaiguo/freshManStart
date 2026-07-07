"""
设计方案：
1. 设计意图：构建一个具备原生并行工具调用能力（Parallel Tool Calls）的 MiniReActEngine，实现并发非阻塞调度与局部故障隔离（Exception Isolation）。
2. 类与函数结构：
   - AgentState: 状态容器。
   - ToolRegistry: 反射工具注册中心。
   - MiniReActEngine: 核心 ReAct 引擎类。
     - __init__(self, registry: ToolRegistry, max_steps: int = 5)
     - run(self, initial_messages: list, mock_llm_responses: list) -> dict: 异步循环。
     - dispatch_tool(self, action: str, raw_params: dict) -> str: 反射分发。
     - execute_parallel_tools(self, tool_calls: list) -> list: 并发非阻塞调度入口。
     - _execute_single_tool(self, call_id: str, action: str, params: dict) -> dict: 单工具执行包装，执行异常就地捕获并转化为 Observation 文本，实现单点故障隔离。
3. 数据流流向：
   - LLM 下发包含 3 个并行调用任务的 tool_calls 列表。
   - 主循环触发 execute_parallel_tools。
   - execute_parallel_tools 将每个 tool_call 转换为 _execute_single_tool 协程任务。
   - 利用 asyncio.gather 并发拉起所有任务，指定 return_exceptions=True。
   - 某个协程（如 invalid_tool）抛出异常，在 _execute_single_tool 的 try-except 块中被捕获并转化为含错误文本的消息字典，不影响其他健康任务。
   - 收集完毕后，主协程依次将所有 Observation 消息字典有序归约追加回 current_state.messages 消息流中。
"""
import copy
import inspect
import re
import asyncio
from typing import List, Dict, Any, Callable, Tuple
from pydantic import create_model, Field

# ==================== 动态反射注册中心 (自包含设计) ====================
class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}

    def _parse_docstring(self, doc: str) -> Tuple[str, Dict[str, str]]:
        if not doc:
            return "", {}
        doc = doc.strip()
        lines = doc.split("\n")
        main_desc_lines = []
        for line in lines:
            if line.strip().startswith(("Args:", "Parameters:", "Args", "Parameters")):
                break
            main_desc_lines.append(line.strip())
        main_desc = "\n".join(main_desc_lines).strip()
        
        param_descs = {}
        pattern = re.compile(r"^\s*([\w_]+)\s*(?:\([^)]+\))?\s*:\s*(.+)$")
        in_args_section = False
        for line in lines:
            cleaned_line = line.strip()
            if cleaned_line.startswith(("Args:", "Parameters:", "Args", "Parameters")):
                in_args_section = True
                continue
            if in_args_section:
                if not line.startswith(" ") and cleaned_line:
                    in_args_section = False
                    continue
                match = pattern.match(line)
                if match:
                    name, desc = match.groups()
                    param_descs[name.strip()] = desc.strip()
        return main_desc, param_descs

    def _clean_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(schema, dict):
            return schema
        cleaned = {}
        for k, v in schema.items():
            if k == "title":
                continue
            if isinstance(v, dict):
                cleaned[k] = self._clean_schema(v)
            elif isinstance(v, list):
                cleaned[k] = [self._clean_schema(item) if isinstance(item, dict) else item for item in v]
            else:
                cleaned[k] = v
        return cleaned

    def register(self, func: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("工具函数必须是异步协程函数 (async def)")
        tool_name = func.__name__
        sig = inspect.signature(func)
        doc = inspect.getdoc(func) or ""
        main_desc, param_descs = self._parse_docstring(doc)
        
        fields_spec = {}
        for param_name, param in sig.parameters.items():
            if param.annotation == inspect.Parameter.empty:
                raise ValueError(f"参数 '{param_name}' 缺失类型注解。")
            desc = param_descs.get(param_name, "")
            if param.default == inspect.Parameter.empty:
                fields_spec[param_name] = (param.annotation, Field(..., description=desc))
            else:
                fields_spec[param_name] = (param.annotation, Field(default=param.default, description=desc))
                
        model_name = f"{tool_name}Input"
        dynamic_model = create_model(model_name, **fields_spec)
        raw_schema = dynamic_model.model_json_schema()
        cleaned_schema = self._clean_schema(raw_schema)
        
        openai_schema = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": main_desc,
                "parameters": cleaned_schema
            }
        }
        self._tools[tool_name] = {
            "func": func,
            "schema": openai_schema,
            "model": dynamic_model
        }
        return func

# 初始化全局注册池
registry = ToolRegistry()

def tool(func: Callable[..., Any]) -> Callable[..., Any]:
    return registry.register(func)


# ==================== 状态容器与执行引擎 ====================
class AgentState:
    def __init__(self, messages: List[Dict[str, Any]], steps: int = 0):
        # 隔离外部引用污染
        self.messages = copy.deepcopy(messages)
        self.steps = steps

class MiniReActEngine:
    def __init__(self, tool_registry: ToolRegistry, max_steps: int = 5):
        self.max_steps = max_steps
        self.registry = tool_registry
        self.current_state: AgentState = None
        self.history_states: List[AgentState] = []

    async def dispatch_tool(self, action: str, raw_params: Dict[str, Any]) -> str:
        if action not in self.registry._tools:
            raise KeyError(f"调度失败：工具 '{action}' 尚未注册。")
        tool_info = self.registry._tools[action]
        func = tool_info["func"]
        model = tool_info["model"]
        
        # 参数校验规整
        try:
            validated_data = model(**raw_params)
        except Exception as e:
            raise ValueError(f"工具 '{action}' 参数契约校验拦截失败: {e}")
            
        # 反射执行
        clean_args = validated_data.model_dump()
        result = await func(**clean_args)
        return str(result)

    async def _execute_single_tool(self, call_id: str, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        单工具执行包装器。捕获执行期一切异常并转化为 Observation 文本返回，实现单点隔离。
        """
        # TODO: 1. 在 try-except 中调用 dispatch_tool 并捕获所有异常
        # TODO: 2. 正常情况下，组装成 role='tool' 且携带 tool_call_id 的字典消息返回
        # TODO: 3. 发生异常时，就地处理，将 error message 包装成 content 返回，隔离单点崩溃
        raise NotImplementedError("TODO: 请先在 _execute_single_tool 中实现异常捕获隔离包装")

    async def execute_parallel_tools(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        并发非阻塞调度入口。
        """
        # TODO: 4. 遍历 tool_calls 并为每个调用包装成 _execute_single_tool 协程任务
        # TODO: 5. 调用 asyncio.gather 并行执行所有任务，确保 return_exceptions=True 开启
        # TODO: 6. 有序返回执行完的消息字典列表
        raise NotImplementedError("TODO: 请先在 execute_parallel_tools 中实现 asyncio.gather 并发调度")

    async def run(self, initial_messages: List[Dict[str, Any]], mock_llm_responses: List[Dict[str, Any]]) -> Dict[str, Any]:
        """执行 ReAct 主控制循环"""
        self.current_state = AgentState(messages=initial_messages, steps=0)
        self.history_states = []
        response_idx = 0
        
        try:
            while self.current_state.steps < self.max_steps:
                # 备份快照
                state_snapshot = copy.deepcopy(self.current_state)
                self.history_states.append(state_snapshot)
                
                self.current_state.steps += 1
                
                if response_idx >= len(mock_llm_responses):
                    raise RuntimeError("模拟响应已耗尽，但模型尚未达成终止协议。")
                llm_response = mock_llm_responses[response_idx]
                response_idx += 1
                
                # 追加 LLM 决策消息（携带并行 tool_calls 定义列表）
                self.current_state.messages.append({
                    "role": "assistant",
                    "content": llm_response["thought"],
                    "tool_calls": llm_response.get("tool_calls", []),
                    "action": llm_response.get("action", "") # 为兼容 Finish
                })
                
                # 判断终止
                if llm_response.get("action") == "Finish":
                    return {
                        "status": "success",
                        "steps_used": self.current_state.steps,
                        "final_reply": llm_response["params"].get("result", "")
                    }
                    
                # TODO: 7. 检测到并行 tool_calls，调度 execute_parallel_tools 并发调度
                # TODO: 8. 执行 Observation 状态归约：将返回的每个消息字典依次有序追加至 messages 队列中
                raise NotImplementedError("TODO: 请在主循环中完成并行调度与有序归约追加")
                
            raise RuntimeError("超出最大步骤限制，任务未闭环。")
            
        except Exception as e:
            if self.history_states:
                self.current_state = self.history_states[-1]
            raise e

if __name__ == "__main__":
    print("=" * 60)
    print("运行 MiniReActEngine 并发调度调试模板...")
    print("=" * 60)
    
    # 注册工具
    @tool
    async def add(a: int, b: int) -> str:
        """计算两数之和。"""
        return str(a + b)
        
    @tool
    async def multiply(a: int, b: int) -> str:
        """计算两数乘积。"""
        return str(a * b)
        
    engine = MiniReActEngine(registry, max_steps=3)
    
    initial_msgs = [{"role": "user", "content": "计算 (12 + 15) * 2 的值"}]
    
    # 模拟并行调度：其中一个工具参数缺失，期望该工具抛错被隔离，另外两个正常返回
    mock_responses = [
        {
            "thought": "我需要并发执行三个计算：12+15, 3*4, 以及一个错误的调用",
            "tool_calls": [
                {"id": "call_01", "action": "add", "params": {"a": 12, "b": 15}},
                {"id": "call_02", "action": "multiply", "params": {"a": 3, "b": 4}},
                {"id": "call_03", "action": "add", "params": {"b": 5}} # 缺失 a，必定抛错
            ]
        },
        {
            "thought": "已得出答案",
            "action": "Finish",
            "params": {"result": "并行计算完成"}
        }
    ]
    
    try:
        res = asyncio.run(engine.run(initial_msgs, mock_responses))
        print(f"🎉 引擎执行成功！最终输出：{res}")
        print("\n消息历史中追加的并发 Observation 情况：")
        for msg in engine.current_state.messages:
            if msg["role"] == "tool":
                print(f"   - Tool: {msg['name']} (ID: {msg['tool_call_id']}) -> Status: {'Success' if 'Error' not in msg['content'] else 'Failed'} -> Output: {msg['content']}")
    except NotImplementedError as e:
        print(f"\n❌ 拦截到 TODO 占位：\n{e}")
    except Exception as e:
        print(f"\n❌ 运行出错: {e}")
        
    print("=" * 60)
