import abc
import functools
import json
import logging
import re
import time
from typing import Dict, Any

# 设置 logging 格式
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AgentPractice")


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
        # TODO: 1. 获取当前工具的名称 (尝试从 self 获取 name 属性，获取不到则用类名)
        # TODO: 2. 打印 Tool 开始调用的日志 (logger.info)，记录调用参数 args 和 kwargs
        # TODO: 3. 记录开始时间 (使用 time.perf_counter())
        # TODO: 4. 尝试执行被装饰的函数 func(self, *args, **kwargs)
        # TODO: 5. 执行成功后，计算耗时 (毫秒级)，打印成功日志并返回执行结果
        # TODO: 6. 如果执行过程中抛出任何异常，捕获该异常，计算耗时，打印错误日志 (logger.error)，
        #          安全地返回一个错误描述字符串 (例如: "Error: Tool execution failed with exception: ...")
        #          注意：不要把异常向上抛出，以保护 Agent 主引擎不崩溃。
        pass
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
        # TODO: 初始化 name 和 description 属性
        pass

    @abc.abstractmethod
    def execute(self, *args, **kwargs) -> str:
        """
        具体工具逻辑，由子类实现。
        """
        pass

    @log_tool
    def __call__(self, *args, **kwargs) -> str:
        """
        使得 tool_instance(*args, **kwargs) 可以直接调用。
        """
        # TODO: 在此处直接调用具体的 execute 方法并返回结果。
        # 注意: 这里的 __call__ 方法已被 @log_tool 装饰，它将自动拥有日志和异常拦截功能。
        pass

    def __repr__(self) -> str:
        # TODO: 返回该工具的可视化表达字符串，例如: Tool(name='calculator', description='...')
        pass


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
        # TODO: 实现单例模式，确保多次实例化 LLMClient() 返回的是同一个对象。
        # 提示: 如果 cls._instance 为 None，则调用 super().__new__(cls) 创建它，并调用 _init_mock_responses 初始化模拟数据。
        pass

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
        # TODO: 根据 self.current_index 返回 self.responses 中的对应文本，并推进 index。
        # 如果超出范围，可以返回默认字符串，例如 "我已经完成了所有的规划与答复。"
        pass

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
    # TODO: 1. 使用正则表达式匹配 Markdown 中的 JSON 代码块 (格式如 ```json\n...\n``` 或 ```\n...\n```)
    #          提示: 可以使用 re.search 与 re.DOTALL 标志。
    # TODO: 2. 如果没有匹配到任何 JSON 块，说明 LLM 给出了最终纯文本答复，
    #          请返回: {"type": "finish", "content": text}
    # TODO: 3. 提取出 JSON 字符串，清洗其首尾空白字符。
    # TODO: 4. 尝试通过 json.loads 进行解析。解析成功后，调用并返回 _validate_action_payload(parsed_dict) 的结果。
    # TODO: 5. 若发生 json.JSONDecodeError，进行容错清洗：
    #          利用正则过滤掉结尾多余的逗号，如 {"city": "Beijing",} -> {"city": "Beijing"}
    #          清洗后再尝试 json.loads 解析，若成功，依然调用并返回 _validate_action_payload 的结果。
    # TODO: 6. 若容错清洗后依然解析失败，捕获异常并返回异常 Payload:
    #          {"type": "error", "error_msg": "Failed to parse action JSON: 错误详情"}
    pass


def _validate_action_payload(parsed: Any) -> Dict[str, Any]:
    """
    Day 1 核心关联: 嵌套字典的 get() 默认值。
    验证解析出来的字典，提取 action 和 args，避免 KeyError 报错。
    """
    # TODO: 1. 验证 parsed 是否为 dict 类型，如果不是，返回 {"type": "error", "error_msg": "..."}
    # TODO: 2. 使用 get() 方法提取 action。如果 action 缺失，返回错误 Payload。
    # TODO: 3. 使用 get() 方法提取 args，如果 args 为 None 则默认赋值为空字典 {}。
    # TODO: 4. 验证 args 是否为 dict 类型，如果不是，返回错误 Payload。
    # TODO: 5. 校验全部通过后，返回结构化字典:
    #          {"type": "action", "action": str(action), "args": args}
    pass


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
        # TODO: 验证 tool 是否为 Tool 抽象基类的实例，如果不是，抛出 TypeError。
        # TODO: 将 tool 注册到 self.tools 字典中，Key 为 tool.name。
        pass

    def run(self, prompt: str, max_steps: int = 5) -> str:
        # TODO: 1. 调用 self.llm.reset() 重置大模型模拟器状态。
        # TODO: 2. 初始化 self.history 列表，将用户输入的 prompt 存入，例如: [{"role": "user", "content": prompt}]
        # TODO: 3. 启动思考执行循环 (while / for)，最大步数为 max_steps:
        #   a. 将当前 history 里的多轮对话拼接为一段 context 文本（例如 format 格式 "[role]: content"）。
        #   b. 调用 self.llm.ask(context) 获取大模型模拟响应，并记录到 history。
        #   c. 调用 parse_action 提取大模型的意图 (Action Payload)。
        #   d. 若 payload_type == "finish":
        #        - 打印完成日志，返回 content 内容，退出循环。
        #   e. 若 payload_type == "error":
        #        - 打印警告日志，并将错误以 {"role": "system", "content": ...} 的格式 append 到 history，
        #          以此模拟 ReAct 机制将报错传回给大模型让其修正。
        #   f. 若 payload_type == "action":
        #        - 提取 action_name 和 action_args。
        #        - 从 self.tools 中获取对应的工具实例。若工具未注册，打印警告并将错误反馈到 history，继续下一次循环。
        #        - 🚀 (Day 5 动态反射): 使用 getattr(tool, "__call__") 动态获取该工具实例的 __call__ 调用方法。
        #        - 🚀 (Day 3 解包): 使用关键字参数解包 (**action_args) 执行该工具方法，获取结果。
        #        - 将工具的执行结果以 {"role": "system", "content": ...} 格式追加到 history。
        # TODO: 4. 如果超出最大步数仍未给出 finish 结论，返回超时提示。
        pass


# ==========================================
# 具体的工具类实现
# ==========================================
class CalculatorTool(Tool):
    """
    数学计算工具。
    """
    def __init__(self):
        # TODO: 调用父类构造器，传入工具名 "calculator" 以及详细的工具描述信息
        pass

    def execute(self, a: float, b: float, op: str = "+", **kwargs) -> str:
        # TODO: 1. 尝试将入参 a 和 b 转换为 float。如果转换失败，抛出 ValueError。
        # TODO: 2. 根据 op 的类型 ('+', '-', '*', '/') 执行数学计算。
        #          - 注意：如果是 '/' 且除数 b 为 0，抛出 ZeroDivisionError。
        #          - 注意：如果是其他不支持的操作符，抛出 ValueError。
        # TODO: 3. 将计算结果转换为字符串返回。
        pass


class WeatherTool(Tool):
    """
    天气查询工具。
    """
    def __init__(self):
        # TODO: 调用父类构造器，传入工具名 "weather" 以及工具描述信息
        pass

    def execute(self, city: str, **kwargs) -> str:
        # TODO: 1. 清洗 city 参数（去空格并转换为小写）。
        # TODO: 2. 模拟返回数据：
        #          - 如果包含 "beijing": 返回 "Beijing: Sunny, 25°C, Wind: East 3."
        #          - 如果包含 "shanghai": 返回 "Shanghai: Rainy, 22°C, Wind: South 2."
        #          - 否则: 返回 "Weather information for city '...' is currently unavailable."
        pass


# ==========================================
# 演示入口
# ==========================================
if __name__ == "__main__":
    print("=================== Starting Micro Agent Framework Practice ===================")
    # TODO: 1. 实例化 CalculatorTool 和 WeatherTool
    # TODO: 2. 实例化 AgentExecutor
    # TODO: 3. 将工具注册到执行器中
    # TODO: 4. 运行 executor.run("计算北京今天的天气并且帮我把 351 加上 982")
    # TODO: 5. 打印最终的执行结果，观察控制台输出的 ReAct 日志。
    pass
