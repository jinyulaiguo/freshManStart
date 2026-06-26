import abc
import functools
import json
import logging
import re
import time
from typing import Dict, Any

# 设置 logging 格式
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AgentFramework")


# ==========================================
# Day 3: 函数进阶与装饰器
# ==========================================
def log_tool(func):
    """
    Day 3 核心关联: 装饰器闭包与元数据保留。
    用于为 Tool 的 __call__ 执行自动包裹输入输出日志、异常捕获与耗时统计。
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        tool_name = getattr(self, "name", self.__class__.__name__)
        logger.info(f"🚀 [Tool: {tool_name}] Calling with args: {args}, kwargs: {kwargs}")
        start_time = time.perf_counter()
        try:
            # 执行底层工具逻辑
            result = func(self, *args, **kwargs)
            duration = (time.perf_counter() - start_time) * 1000  # 转换为毫秒
            logger.info(f"✅ [Tool: {tool_name}] Completed in {duration:.2f}ms. Output: {result}")
            return result
        except Exception as e:
            duration = (time.perf_counter() - start_time) * 1000
            error_msg = f"Error: Tool execution failed with exception: {type(e).__name__}: {str(e)}"
            logger.error(f"❌ [Tool: {tool_name}] Failed after {duration:.2f}ms. Exception: {e}")
            # 异常拦截保护，防止整个 Agent 引擎奔溃
            return error_msg
    return wrapper


# ==========================================
# Day 4 & Day 5: OOP 魔法方法与接口抽象
# ==========================================
class Tool(abc.ABC):
    """
    Day 5 抽象基类 (ABC)。
    Day 4 魔法方法: 实现了 __call__ 使实例像函数一样可调用，实现 __repr__ 控制台可视化。
    """
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    @abc.abstractmethod
    def execute(self, *args, **kwargs) -> str:
        """
        具体工具逻辑，由子类实现。
        """
        pass

    @log_tool
    def __call__(self, *args, **kwargs) -> str:
        """
        使得 tool_instance(*args, **kwargs) 可以直接调用，且自动执行装饰器的拦截与日志逻辑。
        """
        return self.execute(*args, **kwargs)

    def __repr__(self) -> str:
        return f"Tool(name='{self.name}', description='{self.description}')"


# ==========================================
# Day 5: 常用设计模式——单例模式 LLM 模拟器
# ==========================================
class LLMClient:
    """
    Day 5 单例设计模式。
    模拟调用大语言模型，返回多步思考流文本（含 Markdown 代码块 JSON）。
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_mock_responses()
        return cls._instance

    def _init_mock_responses(self):
        # 预设的 LLM 模拟回复列表
        self.responses = [
            # 步骤 1：合法 Action JSON，调用 calculator
            '我需要先计算 351 加 982 的结果。\n```json\n{"action": "calculator", "args": {"a": 351, "b": 982, "op": "+"} }\n```\n请先帮我执行这个计算。',
            
            # 步骤 2：损坏的 Action JSON，尾部有多余逗号，用于测试 Day 2 的 JSON 容错解析
            '好的，计算得到了结果。现在我需要查询北京的天气，以便判断是否适合出行。\n```json\n{"action": "weather", "args": {"city": "Beijing"},}\n```\n请提取天气信息。',
            
            # 步骤 3：容错后再次调用（纠正后的合法 JSON）
            '抱歉刚才生成的格式不标准，我重新生成：\n```json\n{"action": "weather", "args": {"city": "Beijing"}}\n```',
            
            # 步骤 4：无 JSON 块，代表 Agent 给出最终回答
            '根据刚才的计算和查询结果，351 + 982 的计算结果是 1333.0；而北京今天的天气是晴朗转多云，气温 25°C。现在所有任务已完成！'
        ]
        self.current_index = 0

    def ask(self, prompt: str) -> str:
        """
        获取大模型模拟响应。
        """
        if self.current_index < len(self.responses):
            resp = self.responses[self.current_index]
            self.current_index += 1
        else:
            resp = "我已经完成了所有的规划与答复。"
        return resp

    def reset(self):
        """
        便于单元测试重置 LLM 状态。
        """
        self.current_index = 0


# ==========================================
# Day 2: 正则表达式提取与 JSON 容错解析
# ==========================================
def parse_action(text: str) -> Dict[str, Any]:
    """
    Day 2 核心关联: 正则与 JSON 容错清洗。
    解析大模型的响应文本，检测并提取 json 格式的 action 指令。
    """
    # 匹配 Markdown json 块（不区分大小写，支持 json 标识可选）
    pattern = r"```(?:json)?\s*(.*?)\s*```"
    match = re.search(pattern, text, re.DOTALL)
    
    if not match:
        # 如果没有匹配到 JSON 块，代表是最终回复类型
        return {"type": "finish", "content": text}
    
    json_str = match.group(1).strip()
    
    # 尝试直接解析
    try:
        parsed = json.loads(json_str)
        return _validate_action_payload(parsed)
    except json.JSONDecodeError as original_error:
        # Day 2 异常机制: 捕获 JSONDecodeError，并尝试自动容错修复
        # 常见损坏 1: 结尾多余的逗号，如 {"city": "Beijing",} -> 改为 {"city": "Beijing"}
        cleaned_str = re.sub(r",\s*}", "}", json_str)
        cleaned_str = re.sub(r",\s*]", "]", cleaned_str)
        try:
            parsed = json.loads(cleaned_str)
            logger.info("🩹 Detect and repair trailing comma in JSON successfully!")
            return _validate_action_payload(parsed)
        except json.JSONDecodeError:
            # 容错失败，返回 error Payload
            return {
                "type": "error",
                "error_msg": f"Failed to parse action JSON: {original_error.msg} at line {original_error.lineno}"
            }


def _validate_action_payload(parsed: Any) -> Dict[str, Any]:
    """
    Day 1 核心关联: 嵌套字典的 get() 默认值。
    验证解析出来的字典，提取 action 和 args，避免 KeyError 报错。
    """
    if not isinstance(parsed, dict):
        return {"type": "error", "error_msg": "Decoded JSON is not a dictionary object."}
    
    # 使用 get() 避开 KeyError
    action = parsed.get("action")
    args = parsed.get("args")
    
    if not action:
        return {"type": "error", "error_msg": "Missing required field 'action'."}
    
    # 确保 args 必须为字典，如果没有提供则默认为空字典
    if args is None:
        args = {}
    elif not isinstance(args, dict):
        return {"type": "error", "error_msg": "Field 'args' must be a JSON object (dictionary)."}
        
    return {
        "type": "action",
        "action": str(action),
        "args": args
    }


# ==========================================
# Day 5: 动态反射与 Agent 运行引擎
# ==========================================
class AgentExecutor:
    """
    核心执行调度引擎。
    管理工具，并在思考循环中调度 LLMClient 和工具进行交互。
    """
    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self.llm = LLMClient()
        self.history = []

    def register_tool(self, tool: Tool):
        if not isinstance(tool, Tool):
            raise TypeError("Registered tool must inherit from Tool ABC.")
        self.tools[tool.name] = tool
        logger.info(f"🛠️ Registered tool: {tool.name}")

    def run(self, prompt: str, max_steps: int = 5) -> str:
        # 重置 LLM 状态
        self.llm.reset()
        self.history = [{"role": "user", "content": prompt}]
        
        step = 0
        while step < max_steps:
            step += 1
            logger.info(f"\n--- 🤖 Agent Step {step} ---")
            
            # Day 1: 简单的列表拼接，模拟多轮对话的上下文
            context = "\n".join([f"[{item['role']}]: {item['content']}" for item in self.history])
            
            # 调用大语言模型模拟器
            llm_response = self.llm.ask(context)
            logger.info(f"LLM Reply:\n{llm_response}")
            self.history.append({"role": "assistant", "content": llm_response})
            
            # 解析 Action
            parsed = parse_action(llm_response)
            payload_type = parsed.get("type")
            
            if payload_type == "finish":
                logger.info("🎯 Received finish signal. Agent loop terminated successfully.")
                return parsed.get("content", "")
                
            elif payload_type == "error":
                error_msg = parsed.get("error_msg", "Unknown parsing error.")
                logger.warning(f"⚠️ Error detected: {error_msg}")
                # 将错误反馈至 Context 重新让大模型修正 (模拟 ReAct 自我修正机制)
                self.history.append({
                    "role": "system",
                    "content": f"Execution Error: {error_msg}. Please correct your command format."
                })
                
            elif payload_type == "action":
                action_name = parsed.get("action")
                action_args = parsed.get("args", {})
                
                # Day 5 核心关联: 动态反射 (getattr) 或 字典查找分发
                tool = self.tools.get(action_name)
                if not tool:
                    err_msg = f"Error: Tool '{action_name}' is not registered."
                    logger.warning(f"⚠️ {err_msg}")
                    self.history.append({"role": "system", "content": err_msg})
                    continue
                
                # 动态查找方法并触发调用。使用 getattr 反射获取 '__call__'
                try:
                    call_method = getattr(tool, "__call__")
                    # 通过 **action_args 关键字参数解包 (Day 3 args & kwargs)
                    result = call_method(**action_args)
                    self.history.append({
                        "role": "system",
                        "content": f"Tool '{action_name}' executed. Result: {result}"
                    })
                except Exception as e:
                    err_msg = f"Error during reflection execution of tool '{action_name}': {e}"
                    logger.error(f"⚠️ {err_msg}")
                    self.history.append({"role": "system", "content": err_msg})
        
        logger.warning("⚠️ Max execution steps exceeded without a final answer.")
        return "Max steps reached without finding a final answer."


# ==========================================
# 具体的工具类实现
# ==========================================
class CalculatorTool(Tool):
    """
    数学计算工具。
    """
    def __init__(self):
        super().__init__("calculator", "Calculate math expressions. Args: a (float), b (float), op (str: '+','-','*','/')")

    def execute(self, a: float, b: float, op: str = "+", **kwargs) -> str:
        # Day 2 异常机制: 防范输入类型无法转换为 float 以及被零除
        try:
            val_a = float(a)
            val_b = float(b)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Arguments 'a' and 'b' must be numeric. Details: {e}")
            
        if op == "+":
            return str(val_a + val_b)
        elif op == "-":
            return str(val_a - val_b)
        elif op == "*":
            return str(val_a * val_b)
        elif op == "/":
            if val_b == 0:
                raise ZeroDivisionError("Division by zero is undefined.")
            return str(val_a / val_b)
        else:
            raise ValueError(f"Unsupported math operator: '{op}'")


class WeatherTool(Tool):
    """
    天气查询工具。
    """
    def __init__(self):
        super().__init__("weather", "Query weather of a city. Args: city (str)")

    def execute(self, city: str, **kwargs) -> str:
        city_clean = str(city).strip().lower()
        if "beijing" in city_clean:
            return "Beijing: Sunny, 25°C, Wind: East 3."
        elif "shanghai" in city_clean:
            return "Shanghai: Rainy, 22°C, Wind: South 2."
        else:
            return f"Weather information for city '{city}' is currently unavailable."


# ==========================================
# 演示入口
# ==========================================
if __name__ == "__main__":
    print("=================== Starting Micro Agent Framework Demo ===================")
    
    # 实例化工具
    calc_tool = CalculatorTool()
    weather_tool = WeatherTool()
    
    # 创建执行器
    executor = AgentExecutor()
    executor.register_tool(calc_tool)
    executor.register_tool(weather_tool)
    
    # 启动交互
    final_ans = executor.run("计算北京今天的天气并且帮我把 351 加上 982")
    
    print("\n=================== Agent Final Answer ===================")
    print(final_ans)
    print("==========================================================")
