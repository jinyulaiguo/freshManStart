import time
import threading
from enum import Enum
from typing import Protocol, List, Any

# ==========================================
# 1. 状态与异常体系
# ==========================================
class AgentType(Enum):
    PLANNER = "PlannerAgent"
    CODER = "CoderAgent"

class AgentState(Enum):
    IDLE = "空闲"
    THINKING = "思考中"
    ACTING = "执行中"
    DONE = "已完成"

class AgentException(Exception):
    """智能体框架基类异常"""
    pass

class ToolError(AgentException):
    """工具异常基类"""
    pass

class ToolNotFoundError(ToolError):
    """未找到工具"""
    pass

class SecurityValidationError(ToolError):
    """安全拦截异常"""
    pass

class InvalidToolFormatError(ToolError):
    """非 Callable 属性异常"""
    pass


# ==========================================
# 2. 契约接口 (Protocols)
# ==========================================
class ToolProtocol(Protocol):
    @property
    def name(self) -> str:
        """工具名称"""
        ...

    def run(self, **kwargs: Any) -> Any:
        """执行工具的核心逻辑"""
        ...

class ObserverProtocol(Protocol):
    def on_state_change(self, agent_name: str, state: AgentState, message: str) -> None:
        """观察者状态监听回调"""
        ...


# ==========================================
# 3. 线程安全单例模式 (LLMClient)
# ==========================================
class LLMClient:
    """
    大模型客户端单例类。
    TODO 1: 请使用 双重检查锁定 (Double-Checked Locking) 机制，
    结合类属性 _lock 与 _instance，实现一个线程安全的全局唯一单例。
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        # -----------------
        # TODO 1: 开始实现双重锁定单例
        # -----------------
        pass

    def ask(self, prompt: str) -> str:
        """模拟大模型调用"""
        return f"[Mock LLM Response] processed: '{prompt}'"


# ==========================================
# 4. 安全反射与工具箱
# ==========================================
class AgentToolbox:
    """存储并管理智能体可调用方法的工具箱"""
    def __init__(self) -> None:
        self.api_version = "v1"  # 用于验证非法 Callable 调用测试

    def search_web(self, query: str) -> str:
        """公开的搜索工具"""
        return f"[检索成功] 查询词: '{query}'"

    def send_email(self, to: str, content: str) -> str:
        """公开的邮件通知工具"""
        return f"[发送成功] 收件人: {to} | 内容: {content}"

    def _delete_system_logs(self) -> str:
        """内部敏感操作，绝对禁止反射调用"""
        return "[警告] 系统日志已被擦除！"


def safe_call_tool(toolbox: Any, tool_name: str, **kwargs: Any) -> Any:
    """
    带安全防卫的反射执行函数。
    TODO 2: 请根据安全围栏设计要求，使用 getattr 动态获取方法并执行。
    必须满足以下防御规则：
    1. 拦截私有或魔法方法：若 tool_name 以 "_" 开头，抛出 SecurityValidationError
    2. 校验是否存在：若获取失败或不存在，抛出 ToolNotFoundError
    3. 校验是否可调用：若获取的内容不可被 callable 调用，抛出 InvalidToolFormatError
    4. 执行并捕捉常规报错：将 TypeError 等异常转化为细化的 ToolError 抛出
    """
    # -----------------
    # TODO 2: 开始实现安全反射
    # -----------------
    pass


class DynamicTool:
    """
    将 Toolbox 中的方法动态转换为隐式符合 ToolProtocol 的工具实例。
    """
    def __init__(self, toolbox: Any, method_name: str) -> None:
        self.toolbox = toolbox
        self.method_name = method_name

    @property
    def name(self) -> str:
        return self.method_name

    def run(self, **kwargs: Any) -> Any:
        return safe_call_tool(self.toolbox, self.method_name, **kwargs)


# ==========================================
# 5. 智能体引擎与观察者解耦 (BaseAgent & Subject)
# ==========================================
class BaseAgent:
    """
    智能体基类。
    实现观察者注册、广播与防崩溃沙箱隔离。
    """
    def __init__(self, name: str, toolbox: Any) -> None:
        self.name = name
        self.toolbox = toolbox
        self.state = AgentState.IDLE
        self._observers: List[ObserverProtocol] = []
        self.llm_client = LLMClient()  # 线程安全单例大模型客户端

    def register_observer(self, observer: ObserverProtocol) -> None:
        if observer not in self._observers:
            self._observers.append(observer)

    def remove_observer(self, observer: ObserverProtocol) -> None:
        if observer in self._observers:
            self._observers.remove(observer)

    def notify(self, message: str) -> None:
        """
        广播状态。
        TODO 3: 请遍历 _observers 列表，将当前智能体的 name、state 以及 message 广播出去。
        注意：为保证高可用，必须进行沙箱防御隔离，确保某个观察者执行出错抛出异常时，
        不会影响其他观察者被通知，更不会阻断或中断核心智能体的执行进程！
        """
        # -----------------
        # TODO 3: 开始实现防卫式广播
        # -----------------
        pass

    def update_state(self, state: AgentState, message: str) -> None:
        self.state = state
        self.notify(message)

    def execute_tool(self, tool_name: str, **kwargs: Any) -> Any:
        return safe_call_tool(self.toolbox, tool_name, **kwargs)

    def run(self, prompt: str) -> str:
        raise NotImplementedError("子类必须实现 run()")


class PlannerAgent(BaseAgent):
    """
    规划智能体。
    TODO 4: 实现 run 推理流程。
    要求在运行中更新并广播自身状态：
    1. 切换至 THINKING 状态并广播开始规划
    2. 使用 llm_client.ask 发出大模型提问
    3. 切换至 ACTING 状态，并使用 self.execute_tool 动态调用工具箱中的 "search_web"
    4. 执行完毕后切换至 DONE 状态并广播完成
    5. 返回包含搜索结果的 Planner 报告字符串
    """
    def run(self, prompt: str) -> str:
        # -----------------
        # TODO 4: 开始实现 Planner 推理与反射调用
        # -----------------
        pass


class CoderAgent(BaseAgent):
    """
    编码智能体。
    TODO 5: 实现 run 推理流程。
    要求在运行中更新并广播自身状态：
    1. 切换至 THINKING 状态并广播开始分析
    2. 使用 llm_client.ask 发出大模型提问
    3. 切换至 ACTING 状态，并使用 self.execute_tool 动态调用工具箱中的 "send_email"
       (接收人传 "dev@test.com"，内容传 "代码已编写完毕")
    4. 执行完毕后切换至 DONE 状态并广播完成
    5. 返回包含邮件结果的 Coder 报告字符串
    """
    def run(self, prompt: str) -> str:
        # -----------------
        # TODO 5: 开始实现 Coder 推理与反射调用
        # -----------------
        pass


# ==========================================
# 6. 智能体工厂 (Factory)
# ==========================================
class AgentFactory:
    """
    TODO 6: 编写工厂方法的实例化与装配分支，
    支持根据传入的 AgentType 创建并返回对应的 Agent 实例。
    """
    @staticmethod
    def create_agent(agent_type: AgentType, name: str, toolbox: Any) -> BaseAgent:
        # -----------------
        # TODO 6: 开始实现工厂实例化
        # -----------------
        pass
