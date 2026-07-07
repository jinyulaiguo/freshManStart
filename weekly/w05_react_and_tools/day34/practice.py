"""
设计方案：
1. 设计意图：构建一个具备工具层异常自愈与主控制流 Self-Correction 反思环的 MiniReActEngine。引擎通过真实的 API 接口调用 LLM，并在运行时将工具抛出的异常就地捕获并规整为 Error-Boundary Prompt 反馈给模型，引导模型在下一轮决策的 Thought 阶段自动进行参数反思并重新生成合规请求，实现运行期弹性纠偏。
2. 类与函数结构：
   - AgentState: 上下文状态容器（支持 deepcopy）。
   - ToolRegistry: 运行时反射注册中心。
   - MiniReActEngine: 核心 ReAct 自愈引擎。
     - __init__(self, registry: ToolRegistry, max_steps: int = 5)
     - _format_messages(self) -> list: 辅助规整 current_state.messages 为 API 期望的标准格式。
     - dispatch_tool(self, action: str, raw_params: dict) -> str: 工具反射调度与校验。
     - run(self, initial_messages: list) -> dict: 执行包含真实 LLM 交互和自愈反思环的主控制循环。
3. 数据流流向：
   - 外部传入 initial_messages 启动。
   - 主循环启动，调用 LLMClient 对接真实 Minimax API。
   - 解析 LLM 吐出的 JSON 指令（包含 thought, action, params）。
   - 判断为工具调用，执行 dispatch_tool。
   - 若本地工具（例如日期不合规）抛出 ValueError，异常在 run 的调用处被捕获，通过 Error-Boundary 规整为 "Error...请反思纠错" 的 Observation 消息体追加至上下文。
   - 步数累加，下一轮循环启动。LLM 读取到 Error Observation，通过 Thought 执行反思并产出规范日期参数（YYYY-MM-DD）。
   - 再次调度工具并成功返回数据，大模型达成 Finish 协议安全退出。
"""
import copy
import inspect
import re
import json
import asyncio
from typing import List, Dict, Any, Callable, Tuple
from pydantic import create_model, Field

# 导入真实 API 客户端与环境变量寻址工具
from weekly.w04_prompt_and_http.utils import LLMClient

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
        self.llm_client = LLMClient()
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

    def _format_messages(self) -> List[Dict[str, str]]:
        """
        辅助规整 current_state 中的自定义消息流为 OpenAI API 兼容格式，并注入 System Prompt 引导规范。
        """
        # 构建强约束 System Prompt，迫使模型输出标准格式 JSON
        system_prompt = (
            "你是一个具备工具调用能力的智能助手。你可以使用以下工具解答问题：\n\n"
            "工具列表：\n"
        )
        
        # 动态拼装工具 Schema 描述
        for t_name, t_info in self.registry._tools.items():
            schema = t_info["schema"]["function"]
            system_prompt += f"- 名称: {t_name}\n"
            system_prompt += f"  描述: {schema['description']}\n"
            system_prompt += f"  参数定义: {json.dumps(schema['parameters'], ensure_ascii=False)}\n\n"
            
        system_prompt += (
            "你必须严格以 JSON 格式输出你的 Thought 和 Action！不允许输出任何其他非 JSON 文本。\n"
            "输出的 JSON 结构如下：\n"
            "{\n"
            '  "thought": "你的推理思考过程，包括分析上一步工具是否报错以及如何调整参数",\n'
            '  "action": "调用的工具名称，如果没有可调用的工具或已获得最终答案，则填 \'Finish\'",\n'
            '  "params": {\n'
            '     "参数名": "参数值"\n'
            "  }\n"
            "}\n"
            "注意：如果你的 action 是 'Finish'，你的 params 中必须包含 'result' 键，值为最终答复。"
        )
        
        api_messages = [{"role": "system", "content": system_prompt}]
        
        for msg in self.current_state.messages:
            if msg["role"] == "user":
                api_messages.append({"role": "user", "content": msg["content"]})
            elif msg["role"] == "assistant":
                # 重新序列化为大模型熟悉的 JSON 输出形式
                content = json.dumps({
                    "thought": msg["content"],
                    "action": msg.get("action", ""),
                    "params": msg.get("params", {})
                }, ensure_ascii=False)
                api_messages.append({"role": "assistant", "content": content})
            elif msg["role"] == "tool":
                # 将工具执行结果 (Observation) 作为 user 消息喂回 (兼容性最高)
                content = f"工具 '{msg['name']}' 返回执行结果: {msg['content']}"
                api_messages.append({"role": "user", "content": content})
                
        return api_messages

    async def run(self, initial_messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        执行包含真实 LLM 交互与自愈反思环的 ReAct 主控制循环。
        """
        self.current_state = AgentState(messages=initial_messages, steps=0)
        self.history_states = []
        
        try:
            while self.current_state.steps < self.max_steps:
                # 快照压栈
                state_snapshot = copy.deepcopy(self.current_state)
                self.history_states.append(state_snapshot)
                
                self.current_state.steps += 1
                current_step = self.current_state.steps
                
                print(f"\n-> [步骤 {current_step}] 正在请求真实 LLM API...")
                
                # 1. 规整消息格式
                api_msgs = self._format_messages()
                
                # TODO: 2. 调用真实大模型：self.llm_client.request_llm(api_msgs)
                # TODO: 3. 解析模型输出：从返回文本中清洗提取 JSON，解析出 thought, action, params
                # TODO: 4. 记录 Assistant 消息状态
                # TODO: 5. 校验终止协议：命中 Finish 则平滑退出
                # TODO: 6. 工具分发调度与【自愈容灾机制】：
                #          在调用 dispatch_tool 时使用 try-except ValueError 捕获参数契约异常。
                #          若发生错误，切断硬崩溃，将错误信息包装成 Error-Boundary Prompt 消息追加至 state 中（role='tool'），引导 LLM 在下一步反思，实现自愈！
                
                raise NotImplementedError("TODO: 请补全真实 LLM 对接、JSON 提取解析与 Error-Boundary 异常自愈逻辑")
                
            raise RuntimeError("超出最大迭代步数限制，任务闭环失败。")
            
        except Exception as e:
            if self.history_states:
                self.current_state = self.history_states[-1]
            raise e

if __name__ == "__main__":
    print("=" * 60)
    print("运行 MiniReActEngine 异常自愈调试模板...")
    print("=" * 60)
    
    # 注册一个包含严格正则日期校验规则的数据库查询工具
    @tool
    async def query_user_records(username: str, date: str) -> str:
        """
        查询特定用户在指定日期的注册记录。
        
        Args:
            username: 目标用户的名字。
            date: 查询 the 日期。
        """
        # 严格正则匹配 YYYY-MM-DD 格式，否则抛出 ValueError 强校验错误
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            raise ValueError(
                f"日期参数 '{date}' 格式不合规！日期必须是符合 YYYY-MM-DD 格式的字符串 (例如 2026-06-01)。"
            )
        return f"查询成功：用户 {username} 在 {date} 注册，注册渠道为 GitHub 推荐。"
        
    engine = MiniReActEngine(registry, max_steps=5)
    
    # 故意传入非规范日期 2026-6-1，迫使模型首次提取出不合规的参数，从而触发自愈拦截
    initial_msgs = [{"role": "user", "content": "帮我查一下小明在 2026-6-1 的注册记录。你必须使用 query_user_records 工具来查询。"}]
    
    try:
        res = asyncio.run(engine.run(initial_msgs))
        print(f"\n🎉 引擎运行成功！最终答案：{res}")
    except NotImplementedError as e:
        print(f"\n❌ 拦截到 TODO 占位：\n{e}")
    except Exception as e:
        print(f"\n❌ 运行出错: {e}")
        
    print("=" * 60)
