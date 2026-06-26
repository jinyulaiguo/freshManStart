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
    采用双重检查锁定 (Double-Checked Locking) 保证线程安全与高性能。
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(LLMClient, cls).__new__(cls)
                    # 模拟底层 HTTP 初始化开销
                    time.sleep(0.01)
        return cls._instance

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
    """
    # 1. 拦截私有或魔法方法
    if tool_name.startswith("_"):
        raise SecurityValidationError(f"安全拦截: 禁止通过反射调用保护/私有/魔法方法 '{tool_name}'。")

    # 2. 获取属性并校验是否存在
    try:
        method = getattr(toolbox, tool_name)
    except AttributeError:
        raise ToolNotFoundError(f"未找到工具: '{tool_name}' 不存在于工具箱中。")

    # 3. 校验是否可调用
    if not callable(method):
        raise InvalidToolFormatError(f"格式错误: '{tool_name}' 不是一个可调用的工具方法。")

    # 4. 执行并捕捉常规参数传参等错误
    try:
        return method(**kwargs)
    except TypeError as e:
        raise ToolError(f"参数错误: 工具 '{tool_name}' 参数不匹配。详情: {e}")
    except Exception as e:
        raise ToolError(f"工具执行异常: 执行工具 '{tool_name}' 时发生未知错误: {e}")


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
        """广播状态，带观察者异常隔离"""
        for obs in self._observers:
            try:
                obs.on_state_change(self.name, self.state, message)
            except Exception as e:
                # 沙箱防御：单个观察者报错，不影响核心执行
                import sys
                print(f"[防卫隔离] 观察者 {obs.__class__.__name__} 回调报错: {e}", file=sys.stderr)

    def update_state(self, state: AgentState, message: str) -> None:
        self.state = state
        self.notify(message)

    def execute_tool(self, tool_name: str, **kwargs: Any) -> Any:
        return safe_call_tool(self.toolbox, tool_name, **kwargs)

    def run(self, prompt: str) -> str:
        raise NotImplementedError("子类必须实现 run()")


class PlannerAgent(BaseAgent):
    def run(self, prompt: str) -> str:
        self.update_state(AgentState.THINKING, f"开始规划任务: '{prompt}'")
        decision = self.llm_client.ask(prompt)
        self.update_state(AgentState.ACTING, f"决策通过，调用工具进行信息检索...")
        
        # 动态反射执行
        search_res = self.execute_tool("search_web", query=prompt)
        
        self.update_state(AgentState.DONE, "规划完成。")
        return f"Planner 报告：{search_res}"


class CoderAgent(BaseAgent):
    def run(self, prompt: str) -> str:
        self.update_state(AgentState.THINKING, f"分析编码任务: '{prompt}'")
        decision = self.llm_client.ask(prompt)
        self.update_state(AgentState.ACTING, f"正在编写代码并发送同步报告...")
        
        # 动态反射执行
        email_res = self.execute_tool("send_email", to="dev@test.com", content=f"代码已编写完毕")
        
        self.update_state(AgentState.DONE, "开发任务交付。")
        return f"Coder 报告：{email_res}"


# ==========================================
# 6. 智能体工厂 (Factory)
# ==========================================
class AgentFactory:
    @staticmethod
    def create_agent(agent_type: AgentType, name: str, toolbox: Any) -> BaseAgent:
        if agent_type == AgentType.PLANNER:
            return PlannerAgent(name, toolbox)
        elif agent_type == AgentType.CODER:
            return CoderAgent(name, toolbox)
        else:
            raise ValueError(f"未知的 Agent 类型: {agent_type}")
