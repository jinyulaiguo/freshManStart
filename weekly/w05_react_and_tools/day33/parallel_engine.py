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
        """
        解析函数 docstring 文本，分离出工具主描述以及各个参数的说明文字。

        Args:
            doc: 原始函数 docstring 字符串

        Returns:
            Tuple[str, Dict[str, str]]:
                - 第一个元素为工具的主功能描述
                - 第二个元素为参数名字典映射到描述信息的 dict {"param_name": "description"}
        """
        if not doc:
            return "", {}
        doc = doc.strip()
        lines = doc.split("\n")
        
        # 1. 提取 Args 部分前的函数主干功能描述
        main_desc_lines = []
        for line in lines:
            if line.strip().startswith(("Args:", "Parameters:", "Args", "Parameters")):
                break
            main_desc_lines.append(line.strip())
        main_desc = "\n".join(main_desc_lines).strip()
        
        # 2. 正则提取 Args 段落内的字段名及具体注释
        param_descs = {}
        # 匹配 "  name: description" 或 "  name (type): description" 格式
        pattern = re.compile(r"^\s*([\w_]+)\s*(?:\([^)]+\))?\s*:\s*(.+)$")
        
        in_args_section = False
        for line in lines:
            cleaned_line = line.strip()
            # 定位 Args 分割线
            if cleaned_line.startswith(("Args:", "Parameters:", "Args", "Parameters")):
                in_args_section = True
                continue
            if in_args_section:
                # 若遇到无缩进的非空行，代表进入其他段落，退出 Args 段
                if not line.startswith(" ") and cleaned_line:
                    in_args_section = False
                    continue
                match = pattern.match(line)
                if match:
                    name, desc = match.groups()
                    param_descs[name.strip()] = desc.strip()
        return main_desc, param_descs

    def _clean_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        递归清洗 JSON Schema，移除 Pydantic 默认生成的 'title' 键。
        有些 LLM 接口校验对于 Schema 纯净度有高要求，title 会产生冗余 Token 消耗。

        Args:
            schema: 原始 Pydantic JSON Schema 字典

        Returns:
            清洗掉 'title' 属性的规范 JSON Schema 字典
        """
        if not isinstance(schema, dict):
            return schema
        cleaned = {}
        for k, v in schema.items():
            if k == "title":
                continue
            if isinstance(v, dict):
                # 递归清洗子字典
                cleaned[k] = self._clean_schema(v)
            elif isinstance(v, list):
                # 递归清洗列表中的子结构
                cleaned[k] = [self._clean_schema(item) if isinstance(item, dict) else item for item in v]
            else:
                cleaned[k] = v
        return cleaned

    def register(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """
        利用运行时反射提取异步函数的元数据与类型契约，在内存中动态创建 Pydantic 校验模型，
        并重构为 OpenAI 规范的 Tool Schema。

        Args:
            func: 目标工具异步函数 (必须是 async def)

        Returns:
            原始函数引用（以便装饰器链式调用）

        Raises:
            TypeError: 当传入非异步函数时抛出
            ValueError: 当参数未定义类型注解时抛出
        """
        # 1. 校验异步契约
        if not inspect.iscoroutinefunction(func):
            raise TypeError("工具函数必须是异步协程函数 (async def)")
        tool_name = func.__name__
        sig = inspect.signature(func)
        doc = inspect.getdoc(func) or ""
        
        # 2. 提取 docstring 主描述及参数详细说明
        main_desc, param_descs = self._parse_docstring(doc)
        
        # 3. 循环反射扫描参数列表，校验强类型约束并提取默认值
        fields_spec = {}
        for param_name, param in sig.parameters.items():
            if param.annotation == inspect.Parameter.empty:
                raise ValueError(f"注册工具失败：参数 '{param_name}' 缺失显式类型注解。")
            desc = param_descs.get(param_name, "")
            
            # Pydantic 动态建模字段规格配置: (类型, Field)
            if param.default == inspect.Parameter.empty:
                # 必填参数，无默认值
                fields_spec[param_name] = (param.annotation, Field(..., description=desc))
            else:
                # 选填参数，带默认值
                fields_spec[param_name] = (param.annotation, Field(default=param.default, description=desc))
                
        # 4. 内存动态生成 Pydantic 运行时校验模型
        model_name = f"{tool_name}Input"
        dynamic_model = create_model(model_name, **fields_spec)
        
        # 5. 生成 JSON Schema 并递归规整 title
        raw_schema = dynamic_model.model_json_schema()
        cleaned_schema = self._clean_schema(raw_schema)
        
        # 6. 对齐 OpenAI 原生 Function 协议格式
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
        根据动作符号反射映射本地函数，利用 Pydantic 进行前置契约类型校验，规整参数并 await 调度执行。

        Args:
            action: 调用的工具函数名称
            raw_params: 未经校验的模型输出原始参数字典

        Returns:
            工具函数的字符串格式执行结果 (Observation)

        Raises:
            KeyError: 当工具未在注册池中注册时抛出
            ValueError: 当参数类型不合规或必填字段缺失导致 Pydantic 校验拦截失败时抛出
            RuntimeError: 当工具函数在本地执行期抛出底层未捕获异常时抛出
        """
        # 1. 检测工具注册状态
        if action not in self.registry._tools:
            raise KeyError(f"调度失败：工具 '{action}' 尚未在注册池中注册。")
        tool_info = self.registry._tools[action]
        func = tool_info["func"]
        model = tool_info["model"]
        
        # 2. 对原始入参执行 Pydantic 契约型反序列化校验与自动类型转换
        try:
            validated_data = model(**raw_params)
        except Exception as e:
            raise ValueError(f"工具 '{action}' 参数契约校验拦截失败: {e}")
            
        # 3. 动态解包校验后规整的参数字典 (validated_data.model_dump()) 并执行协程调度
        try:
            clean_args = validated_data.model_dump()
            result = await func(**clean_args)
            return str(result)
        except Exception as e:
            raise RuntimeError(f"工具 '{action}' 在执行期发生底层运行时错误: {e}")

    async def _execute_single_tool(self, call_id: str, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        单任务并行工具执行包装器。
        就地捕获并拦截执行期和参数校验的一切异常，将其安全转化为包含错误提示的 tool 消息字典返回，
        实现局部崩溃隔离（Exception Isolation），防止破坏其他并发任务的正常执行。

        Args:
            call_id: 大模型下发的该工具调用的唯一标识 (tool_call_id)
            action: 工具函数名称
            params: 调用的原始参数字典

        Returns:
            符合 OpenAI Tool 消息格式规范的 dict:
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": action,
                "content": str(execution_result),
                "status": "success" | "error"
            }
        """
        try:
            # 执行底层分发，如果校验失败或执行报错，均抛出异常并由 except 块捕获
            observation = await self.dispatch_tool(action, params)
            return {
                "role": "tool",
                "tool_call_id": call_id,
                "name": action,
                "content": observation,
                "status": "success"
            }
        except Exception as e:
            # 【核心容灾设计】：截断异常传播，就地将错误信息包装成 content 返回给大模型上下文
            return {
                "role": "tool",
                "tool_call_id": call_id,
                "name": action,
                "content": f"Error executing tool '{action}': {str(e)}",
                "status": "error"
            }

    async def execute_parallel_tools(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        并行非阻塞工具调度入口。
        将多个并行 tool_calls 任务转换为独立的异常隔离任务，利用 asyncio.gather 并发分发，
        最大执行耗时取决于耗时最长的单个工具（T_max 机制）。

        Args:
            tool_calls: 包含多个工具调用的定义列表，每项需含 'id', 'action', 'params'

        Returns:
            经过并发执行并收集完毕的 OpenAI Tool 消息字典列表，顺序与原始输入保持严格一致
        """
        tasks = []
        for call in tool_calls:
            # 建立物理隔离任务包装队列
            tasks.append(
                self._execute_single_tool(
                    call_id=call["id"],
                    action=call["action"],
                    params=call["params"]
                )
            )
        # 并发非阻塞调用。指定 return_exceptions=True 保证单个协程彻底瘫痪时，其他协程能继续运行并收集结果
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return list(results)

    async def run(self, initial_messages: List[Dict[str, Any]], mock_llm_responses: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        执行 ReAct 异步主决策循环，驱动整个 Agent 生命周期。

        Args:
            initial_messages: 初始输入的上下文消息流列表
            mock_llm_responses: 用于测试模拟 LLM 决策输出的字典序列

        Returns:
            运行闭环结果字典

        Raises:
            RuntimeError: 超出步数限制仍未达成终止协议时抛出
        """
        # 初始化当前活跃状态，执行深拷贝防止引用污染
        self.current_state = AgentState(messages=initial_messages, steps=0)
        self.history_states = []
        response_idx = 0
        
        try:
            while self.current_state.steps < self.max_steps:
                # 1. 【安全第一防线】：每次开始新一轮决策前，深拷贝保存当前完整健康的 state 到快照栈
                state_snapshot = copy.deepcopy(self.current_state)
                self.history_states.append(state_snapshot)
                
                # 2. 累加当前执行步数
                self.current_state.steps += 1
                current_step = self.current_state.steps
                
                print(f"-> 进入第 {current_step} 步控制循环...")
                
                # 3. 消费模拟大模型响应
                if response_idx >= len(mock_llm_responses):
                    raise RuntimeError("模拟响应已耗尽，但模型尚未达成终止协议。")
                llm_response = mock_llm_responses[response_idx]
                response_idx += 1
                
                # 4. 追加 LLM 推理思维链（携带本轮下达的并发 tool_calls 工具清单）
                self.current_state.messages.append({
                    "role": "assistant",
                    "content": llm_response["thought"],
                    "tool_calls": llm_response.get("tool_calls", []),
                    "action": llm_response.get("action", "")
                })
                
                print(f"   [Thought]: {llm_response['thought']}")
                
                # 5. 命中 Finish 协议，平滑退出循环
                if llm_response.get("action") == "Finish":
                    print("   🎉 命中终止协议，平滑退出控制环。")
                    return {
                        "status": "success",
                        "steps_used": self.current_state.steps,
                        "final_reply": llm_response["params"].get("result", "")
                    }
                    
                # 6. 【并发决策链路】：如存在并行 tool_calls，调用非阻塞调度器并发执行并收集
                tool_calls = llm_response.get("tool_calls", [])
                if tool_calls:
                    print(f"   [System] : 触发 {len(tool_calls)} 个工具的并发分发调度...")
                    results = await self.execute_parallel_tools(tool_calls)
                    
                    # 7. 【状态归约 (State Reducing)】：将排好序的消息体字典依次追加至当前 State 消息历史中
                    for res_msg in results:
                        # 剥离辅助判断用的 status 字段，保证写入 state 的消息 100% 符合 OpenAI 官方规范
                        status = res_msg.pop("status", "success")
                        print(f"   [Observation (ID: {res_msg['tool_call_id']})]: {res_msg['content']} ({status})")
                        self.current_state.messages.append(res_msg)
                        
            raise RuntimeError("超出最大步骤限制，任务未闭环。")
            
        except Exception as e:
            # 8. 异常防护网：将当前状态还原回最后一次录入快照栈的健康备份
            if self.history_states:
                self.current_state = self.history_states[-1]
            raise e

if __name__ == "__main__":
    print("=" * 60)
    print("运行 MiniReActEngine 并行调度与异常隔离演示...")
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
            "params": {"result": "计算完成。正常工具执行成功，异常工具已被隔离拦截。"}
        }
    ]
    
    res = asyncio.run(engine.run(initial_msgs, mock_responses))
    print(f"\n🎉 引擎成功闭环！输出: {res}\n")
    print("消息历史中追加的并发 Observation 情况：")
    for msg in engine.current_state.messages:
        if msg["role"] == "tool":
            print(f"   - Tool: {msg['name']} (ID: {msg['tool_call_id']}) -> Output: {msg['content']}")
            
    print("=" * 60)
