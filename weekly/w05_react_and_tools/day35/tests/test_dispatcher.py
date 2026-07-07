"""Test2: ToolDispatcher 反射分发调度验证"""
import pytest
import asyncio
from weekly.w05_react_and_tools.day35.mini_agent.agent.registry import ToolRegistry
from weekly.w05_react_and_tools.day35.mini_agent.agent.dispatcher import ToolDispatcher
from weekly.w05_react_and_tools.day35.mini_agent.schema.observation import ObservationStatus
from weekly.w05_react_and_tools.day35.mini_agent.schema.exception import ValidationException


@pytest.fixture
def registry_with_tools():
    """创建含测试工具的独立 ToolRegistry"""
    reg = ToolRegistry()

    @reg.register
    async def multiply(a: int, b: int) -> str:
        """两数相乘。Args: a: 第一个整数。b: 第二个整数。"""
        return str(a * b)

    @reg.register
    async def greet(name: str, greeting: str = "你好") -> str:
        """生成问候语。Args: name: 名称。greeting: 问候词。"""
        return f"{greeting}，{name}！"

    @reg.register
    async def always_fail(x: int) -> str:
        """必然失败的工具（用于测试）。Args: x: 参数。"""
        raise RuntimeError(f"工具执行失败：x={x}")

    return reg


@pytest.fixture
def dispatcher(registry_with_tools):
    return ToolDispatcher(registry=registry_with_tools)


class TestToolDispatcher:
    """ToolDispatcher 核心分发调度测试组"""

    def test_dispatch_success_returns_observation(self, dispatcher):
        """测试：工具正常执行后返回 status=success 的 Observation"""
        obs = asyncio.run(dispatcher.dispatch("multiply", {"a": 3, "b": 7}, "call_001"))

        assert obs.status == ObservationStatus.SUCCESS
        assert obs.tool_name == "multiply"
        assert obs.tool_call_id == "call_001"
        assert "21" in obs.content
        assert obs.latency_ms >= 0

    def test_dispatch_with_type_coercion(self, dispatcher):
        """测试：Pydantic 自动类型转换（字符串 '3' → 整数 3）"""
        obs = asyncio.run(dispatcher.dispatch("multiply", {"a": "4", "b": "5"}, "call_002"))

        assert obs.status == ObservationStatus.SUCCESS
        assert "20" in obs.content

    def test_dispatch_with_default_param(self, dispatcher):
        """测试：未传入有默认值的参数时，使用默认值"""
        obs = asyncio.run(dispatcher.dispatch("greet", {"name": "Alice"}, "call_003"))

        assert obs.status == ObservationStatus.SUCCESS
        assert "Alice" in obs.content
        assert "你好" in obs.content  # 默认问候词

    def test_dispatch_missing_required_param_raises_validation_exception(self, dispatcher):
        """测试：缺少必填参数时抛出 ValidationException"""
        with pytest.raises(ValidationException) as exc_info:
            asyncio.run(dispatcher.dispatch("multiply", {"a": 3}, "call_004"))

        assert "multiply" in exc_info.value.tool_name

    def test_dispatch_unknown_tool_raises_key_error(self, dispatcher):
        """测试：调用未注册的工具时抛出 KeyError"""
        with pytest.raises(KeyError, match="未在注册中心注册"):
            asyncio.run(dispatcher.dispatch("nonexistent_tool", {}, "call_005"))

    def test_dispatch_tool_internal_error_raises_tool_exception(self, dispatcher):
        """测试：工具函数内部抛出异常时，转换为 ToolException"""
        from weekly.w05_react_and_tools.day35.mini_agent.schema.exception import ToolException
        with pytest.raises(ToolException) as exc_info:
            asyncio.run(dispatcher.dispatch("always_fail", {"x": 42}, "call_006"))

        assert exc_info.value.tool_name == "always_fail"

    def test_execute_single_isolates_exception_as_error_observation(self, dispatcher):
        """测试：_execute_single 就地捕获异常，返回 status=error 的 Observation"""
        obs = asyncio.run(dispatcher._execute_single("call_007", "always_fail", {"x": 99}))

        assert obs.status == ObservationStatus.ERROR
        assert obs.tool_name == "always_fail"
        assert obs.tool_call_id == "call_007"
        assert "失败" in obs.content or "error" in obs.content.lower()
        assert obs.error_type is not None
