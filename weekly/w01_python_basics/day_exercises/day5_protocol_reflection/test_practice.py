# pyrefly: ignore [missing-import]
import pytest
import threading
from typing import List, Tuple
# pyrefly: ignore [missing-import]
from practice import (
    AgentType,
    AgentState,
    ToolNotFoundError,
    SecurityValidationError,
    InvalidToolFormatError,
    ToolError,
    LLMClient,
    AgentToolbox,
    safe_call_tool,
    DynamicTool,
    ToolProtocol,
    ObserverProtocol,
    AgentFactory,
)

# ==========================================
# 1. 单例模式测试 (多线程并发)
# ==========================================
def test_llm_client_singleton_multithreaded():
    instances: List[LLMClient] = []
    
    def get_client():
        instances.append(LLMClient())

    # 启动 50 个线程并发获取单例
    threads = [threading.Thread(target=get_client) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(instances) == 50
    first_id = id(instances[0])
    for inst in instances:
        assert id(inst) == first_id


# ==========================================
# 2. 动态反射与防御性安全测试
# ==========================================
def test_safe_call_tool_success():
    toolbox = AgentToolbox()
    # 正常调用 search_web
    res = safe_call_tool(toolbox, "search_web", query="pytest test")
    assert "检索成功" in res
    assert "pytest test" in res

    # 正常调用 send_email
    res_mail = safe_call_tool(toolbox, "send_email", to="test@test.com", content="pytest body")
    assert "发送成功" in res_mail
    assert "test@test.com" in res_mail


def test_safe_call_tool_not_found():
    toolbox = AgentToolbox()
    with pytest.raises(ToolNotFoundError) as excinfo:
        safe_call_tool(toolbox, "format_disk")
    assert "未找到工具" in str(excinfo.value)


def test_safe_call_tool_security_violation():
    toolbox = AgentToolbox()
    with pytest.raises(SecurityValidationError) as excinfo:
        safe_call_tool(toolbox, "_delete_system_logs")
    assert "安全拦截" in str(excinfo.value)

    with pytest.raises(SecurityValidationError) as excinfo:
        safe_call_tool(toolbox, "__str__")
    assert "安全拦截" in str(excinfo.value)


def test_safe_call_tool_invalid_format():
    toolbox = AgentToolbox()
    with pytest.raises(InvalidToolFormatError) as excinfo:
        safe_call_tool(toolbox, "api_version")
    assert "格式错误" in str(excinfo.value)


def test_safe_call_tool_args_mismatch():
    toolbox = AgentToolbox()
    with pytest.raises(ToolError) as excinfo:
        safe_call_tool(toolbox, "search_web", wrong_key="value")
    assert "参数错误" in str(excinfo.value)


# ==========================================
# 3. Protocol 隐式兼容性测试
# ==========================================
def test_dynamic_tool_protocol_compatibility():
    toolbox = AgentToolbox()
    tool: ToolProtocol = DynamicTool(toolbox, "search_web")
    
    assert tool.name == "search_web"
    res = tool.run(query="test_protocol")
    assert "[检索成功]" in res


# ==========================================
# 4. 观察者模式状态流转与崩坏测试
# ==========================================
class MockObserver:
    def __init__(self) -> None:
        self.history: List[Tuple[AgentState, str]] = []

    def on_state_change(self, agent_name: str, state: AgentState, message: str) -> None:
        self.history.append((state, message))


class CorruptObserver:
    def on_state_change(self, agent_name: str, state: AgentState, message: str) -> None:
        if state == AgentState.ACTING:
            raise RuntimeError("模拟广播失败：管道破裂")


def test_observer_state_transitions():
    toolbox = AgentToolbox()
    agent = AgentFactory.create_agent(AgentType.PLANNER, "测试智能体", toolbox)
    
    observer = MockObserver()
    agent.register_observer(observer)
    
    res = agent.run("pytest 演示任务")
    assert "Planner 报告：" in res
    
    states = [item[0] for item in observer.history]
    assert AgentState.THINKING in states
    assert AgentState.ACTING in states
    assert AgentState.DONE in states


def test_broken_observer_isolation(capsys):
    toolbox = AgentToolbox()
    agent = AgentFactory.create_agent(AgentType.CODER, "测试编码智能体", toolbox)
    
    observer = MockObserver()
    corrupt_obs = CorruptObserver()
    
    agent.register_observer(observer)
    agent.register_observer(corrupt_obs)
    
    res = agent.run("开发登录页面")
    assert "Coder 报告：" in res
    
    states = [item[0] for item in observer.history]
    assert AgentState.DONE in states
    
    stderr = capsys.readouterr().err
    assert "[防卫隔离] 观察者 CorruptObserver 回调报错" in stderr
