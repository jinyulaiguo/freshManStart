"""
设计方案：
1. 设计意图：构建一个具备反射分发与状态归约能力的 MiniReActEngine。引擎能够将 LLM 的决策符号反射调度执行本地真实的异步工具函数，通过 Pydantic 模型对参数做运行时强类型契约校验，并能将执行结果（Observation）原子归约合并至全局 State。
2. 类与函数结构：
   - AgentState: 存储 Agent 消息历史与步骤计数的状态容器。
   - ToolRegistry: 运行时反射注册中心类（复用自包含设计）。
   - MiniReActEngine: 核心 ReAct 引擎类。
     - __init__(self, registry: ToolRegistry, max_steps: int = 5)
     - run(self, initial_messages: list, mock_llm_responses: list) -> dict: 异步主循环。
     - dispatch_tool(self, action: str, raw_params: dict) -> str: 反射反序列化校验、解包分发并 await 执行本地协程。
3. 数据流流向：
   - LLM 决策输出 {"action": "calculator", "params": {"exp": "2*3"}}。
   - 主循环捕获该 Action，暂停 LLM 发射，路由给 dispatch_tool。
   - dispatch_tool 提取 ToolRegistry 中对应的 Pydantic 校验模型，校验并规整 raw_params 字典。
   - 提取绑定的本地异步函数，动态解包（**kwargs）并 await 执行，返回结果字符串。
   - 主循环获取结果后，封装成 role 为 "tool" 的消息结构追加回 messages 列表中（State Reduction 归约更新），步数累加，开启新一轮循环。
"""
import copy
import inspect
import re
import json
from typing import List, Dict, Any, Callable, Tuple
from pydantic import create_model, Field, BaseModel

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
        # 执行深拷贝隔离，防止运行期追加消息污染外部列表引用
        self.messages = copy.deepcopy(messages)
        self.steps = steps

class MiniReActEngine:
    def __init__(self, tool_registry: ToolRegistry, max_steps: int = 5):
        self.max_steps = max_steps
        self.registry = tool_registry
        self.current_state: AgentState = None
        self.history_states: List[AgentState] = []

    async def dispatch_tool(self, action: str, raw_params: Dict[str, Any]) -> str:
        """
        利用反射动态分发执行本地绑定的异步工具，包含强契约参数校验。
        
        Args:
            action: 工具函数名称
            raw_params: 未校验的原始入参字典
            
        Returns:
            工具执行的字符串结果 (Observation)
        """
        # TODO: 1. 从注册中心中获取指定名称的工具详情（func, model）
        # TODO: 2. 利用 Pydantic 校验模型对 raw_params 执行强契约反序列化校验与规整
        # TODO: 3. 解包规整后的字段参数，反射动态 await 执行本地异步协程函数
        # TODO: 4. 返回执行结果的字符串形式
        raise NotImplementedError("TODO: 请先在 dispatch_tool 中实现动态反射分发与强契约参数校验")

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
                current_step = self.current_state.steps
                
                if response_idx >= len(mock_llm_responses):
                    raise RuntimeError("模拟响应已耗尽，但模型尚未达成终止协议。")
                llm_response = mock_llm_responses[response_idx]
                response_idx += 1
                
                # 追加 LLM Assistant 消息
                self.current_state.messages.append({
                    "role": "assistant",
                    "content": llm_response["thought"],
                    "action": llm_response["action"],
                    "params": llm_response["params"]
                })
                
                # 判断终止
                if llm_response["action"] == "Finish":
                    return {
                        "status": "success",
                        "steps_used": self.current_state.steps,
                        "final_reply": llm_response["params"].get("result", "")
                    }
                    
                # TODO: 5. 命中工具调用，调用 dispatch_tool 执行反射分发并捕获结果
                # TODO: 6. 执行 Observation 状态归约：将结果以 role='tool' 格式追加至当前 State 消息历史中
                raise NotImplementedError("TODO: 请在循环中补全 dispatch_tool 调度与 Observation 归约追加")
                
            raise RuntimeError("超出最大步骤限制，任务未闭环。")
            
        except Exception as e:
            if self.history_states:
                self.current_state = self.history_states[-1]
            raise e

if __name__ == "__main__":
    print("=" * 60)
    print("运行 MiniReActEngine 调度调试模板...")
    print("=" * 60)
    
    # 注册一个测试工具
    @tool
    async def add_numbers(a: int, b: int) -> str:
        """
        计算两个整数的和。
        
        Args:
            a: 第一个加数。
            b: 第二个加数。
        """
        return str(a + b)
        
    engine = MiniReActEngine(registry, max_steps=3)
    
    initial_msgs = [{"role": "user", "content": "计算 12 加 15 的值"}]
    mock_responses = [
        {"thought": "调用 add_numbers 工具", "action": "add_numbers", "params": {"a": "12", "b": 15}}, # 故意将 a 传成字符串，测试 Pydantic 自动矫正
        {"thought": "已得出答案", "action": "Finish", "params": {"result": "计算结果为 27"}}
    ]
    
    try:
        import asyncio
        res = asyncio.run(engine.run(initial_msgs, mock_responses))
        print(f"🎉 引擎执行成功！最终输出：{res}")
    except NotImplementedError as e:
        print(f"\n❌ 拦截到 TODO 占位：\n{e}")
    except Exception as e:
        print(f"\n❌ 运行出错: {e}")
        
    print("=" * 60)
