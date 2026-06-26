import json
import pytest
from agent_framework import (
    LLMClient,
    parse_action,
    Tool,
    CalculatorTool,
    WeatherTool,
    AgentExecutor,
)


# ==========================================
# 1. 测试 LLMClient 的单例性质
# ==========================================
def test_llm_client_singleton():
    client1 = LLMClient()
    client2 = LLMClient()
    
    # 验证是否为同一个实例
    assert client1 is client2
    
    # 测试重置功能
    client1.reset()
    assert client1.current_index == 0
    
    # 获取第一个响应
    resp = client1.ask("test prompt")
    assert "我需要先计算 351 加 982 的结果" in resp
    assert client2.current_index == 1  # client2 的索引应当随之变化，证明是同一个单例


# ==========================================
# 2. 测试正则解析器在各种情况下的容错性
# ==========================================
def test_parse_action_valid_json():
    # 测试合法的 markdown json
    text = '这里的输出是:\n```json\n{"action": "calculator", "args": {"a": 1, "b": 2}}\n```\n结束。'
    res = parse_action(text)
    assert res["type"] == "action"
    assert res["action"] == "calculator"
    assert res["args"] == {"a": 1, "b": 2}


def test_parse_action_no_json():
    # 测试普通文本输出 (应当解析为 finish)
    text = "这是一个普通的回答，没有任何代码块。"
    res = parse_action(text)
    assert res["type"] == "finish"
    assert res["content"] == text


def test_parse_action_trailing_comma_tolerance():
    # 测试尾部多逗号的 JSON 容错
    text = '```json\n{"action": "weather", "args": {"city": "Beijing"},}\n```'
    res = parse_action(text)
    assert res["type"] == "action"
    assert res["action"] == "weather"
    assert res["args"] == {"city": "Beijing"}


def test_parse_action_missing_action():
    # 测试缺失 action 字段的 JSON
    text = '```json\n{"args": {"city": "Beijing"}}\n```'
    res = parse_action(text)
    assert res["type"] == "error"
    assert "Missing required field 'action'" in res["error_msg"]


def test_parse_action_invalid_args_type():
    # 测试 args 字段类型不正确 (应该是 dict)
    text = '```json\n{"action": "weather", "args": "Beijing"}\n```'
    res = parse_action(text)
    assert res["type"] == "error"
    assert "Field 'args' must be a JSON object" in res["error_msg"]


def test_parse_action_completely_broken_json():
    # 测试完全无法解析的损坏 JSON
    text = '```json\n{"action": "weather", "args": {\n```'
    res = parse_action(text)
    assert res["type"] == "error"
    assert "Failed to parse action JSON" in res["error_msg"]


# ==========================================
# 3. 测试 Tool 基类、装饰器、耗时统计与异常拦截保护
# ==========================================
class DummySuccessTool(Tool):
    def execute(self, val: str) -> str:
        return f"Hello {val}"


class DummyErrorTool(Tool):
    def execute(self, val: str) -> str:
        raise ValueError("Something went wrong inside the tool.")


def test_tool_call_and_repr():
    tool = DummySuccessTool("dummy", "A test tool")
    
    # 验证 repr
    assert repr(tool) == "Tool(name='dummy', description='A test tool')"
    
    # 验证可调用性 (魔法方法 __call__)
    res = tool(val="world")
    assert res == "Hello world"


def test_log_tool_decorator_exception_handling():
    tool = DummyErrorTool("error_tool", "A tool that raises error")
    
    # 验证异常被 log_tool 装饰器拦截，并返回错误描述，而不是向上抛出
    try:
        res = tool(val="test")
        assert "Error: Tool execution failed with exception" in res
        assert "ValueError" in res
        assert "Something went wrong inside the tool" in res
    except Exception as e:
        pytest.fail(f"Decorator failed to intercept exception: {e}")


def test_decorator_metadata_preservation():
    # 验证 wraps 装饰器正确保留了 __call__ 方法的名字和 docstring
    tool = DummySuccessTool("dummy", "A test tool")
    assert tool.__call__.__name__ == "__call__"


# ==========================================
# 4. 测试 AgentExecutor 完整的工具反射调用和闭合思考流
# ==========================================
def test_agent_executor_full_run():
    # 初始化组件
    calc = CalculatorTool()
    weather = WeatherTool()
    
    executor = AgentExecutor()
    executor.register_tool(calc)
    executor.register_tool(weather)
    
    # 验证工具注册
    assert "calculator" in executor.tools
    assert "weather" in executor.tools
    
    # 运行完整的 Agent
    final_output = executor.run("计算北京的天气并且帮我把 351 加上 982", max_steps=5)
    
    # 验证最终输出包含预期结果
    assert "351 + 982" in final_output
    assert "1333.0" in final_output
    assert "北京今天的天气是晴朗转多云" in final_output
    
    # 验证历史记录是否包含了 4 个大模型响应和 2 个工具响应
    # 第 1 步：LLM 请求计算器 -> 系统返回工具结果
    # 第 2 步：LLM 损坏的 weather JSON -> 系统报错
    # 第 3 步：LLM 修正 weather JSON -> 系统返回天气结果
    # 第 4 步：LLM 总结结束
    assert len(executor.history) >= 7
    roles = [item["role"] for item in executor.history]
    assert roles[0] == "user"
    assert "assistant" in roles
    assert "system" in roles
