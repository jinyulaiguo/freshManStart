"""Test1: ToolRegistry @tool 装饰器自动注册验证"""
import pytest
from weekly.w05_react_and_tools.day35.mini_agent.agent.registry import ToolRegistry, tool as global_tool


# ==================== 使用独立 Registry 实例进行测试（隔离全局状态）====================

class TestToolRegistry:
    """ToolRegistry 核心功能测试组"""

    def setup_method(self):
        """每个测试方法前，创建独立的 ToolRegistry 实例，避免全局状态污染"""
        self.registry = ToolRegistry()

    def test_register_basic_async_tool(self):
        """测试：基本异步工具注册成功，工具名出现在注册表中"""
        @self.registry.register
        async def my_tool(city: str) -> str:
            """查询城市信息。Args: city: 城市名。"""
            return f"城市: {city}"

        # 验证工具已被注册
        assert "my_tool" in self.registry
        assert self.registry.list_tools() == ["my_tool"]

    def test_schema_format_compliant_with_openai(self):
        """测试：导出的 Schema 符合 OpenAI function schema 格式规范"""
        @self.registry.register
        async def get_weather(city: str, days: int = 1) -> str:
            """
            获取城市天气预报。

            Args:
                city: 城市名称。
                days: 预报天数。
            """
            return f"{city} 天气"

        schema = self.registry.get_tool_schema("get_weather")

        # 验证顶层格式
        assert schema["type"] == "function"
        assert "function" in schema

        func = schema["function"]
        assert func["name"] == "get_weather"
        assert "描述" in func["description"] or "天气" in func["description"]

        # 验证参数 schema
        params = func["parameters"]
        assert params["type"] == "object"
        assert "city" in params["properties"]
        assert "days" in params["properties"]
        # 只有 city 是必填参数
        assert "city" in params.get("required", [])

    def test_schema_no_title_field(self):
        """测试：导出的 Schema 中不含冗余的 title 键"""
        @self.registry.register
        async def simple_tool(query: str) -> str:
            """简单搜索工具。Args: query: 搜索词。"""
            return query

        schema = self.registry.get_tool_schema("simple_tool")

        def has_title(obj):
            if isinstance(obj, dict):
                if "title" in obj:
                    return True
                return any(has_title(v) for v in obj.values())
            if isinstance(obj, list):
                return any(has_title(item) for item in obj)
            return False

        assert not has_title(schema), "Schema 中不应包含 title 键"

    def test_register_non_async_function_raises_type_error(self):
        """测试：注册同步函数时抛出 TypeError"""
        with pytest.raises(TypeError, match="异步协程函数"):
            @self.registry.register
            def sync_tool(query: str) -> str:
                return query

    def test_register_missing_type_annotation_raises_value_error(self):
        """测试：参数缺少类型注解时抛出 ValueError"""
        with pytest.raises(ValueError, match="类型注解"):
            @self.registry.register
            async def bad_tool(query) -> str:
                return str(query)

    def test_get_all_schemas_returns_list(self):
        """测试：get_all_schemas 返回所有已注册工具的 Schema 列表"""
        @self.registry.register
        async def tool_a(x: int) -> str:
            """工具 A。Args: x: 整数参数。"""
            return str(x)

        @self.registry.register
        async def tool_b(y: str) -> str:
            """工具 B。Args: y: 字符串参数。"""
            return y

        schemas = self.registry.get_all_schemas()
        assert len(schemas) == 2
        names = [s["function"]["name"] for s in schemas]
        assert "tool_a" in names
        assert "tool_b" in names

    def test_get_tool_model_returns_pydantic_model(self):
        """测试：get_tool_model 返回 Pydantic 模型，可用于参数校验"""
        @self.registry.register
        async def typed_tool(count: int, label: str = "default") -> str:
            """带类型参数的工具。Args: count: 数量。label: 标签。"""
            return f"{label}: {count}"

        Model = self.registry.get_tool_model("typed_tool")
        # 验证 Pydantic 模型可以实例化并校验参数
        instance = Model(count=5)
        assert instance.count == 5
        assert instance.label == "default"

        # 验证类型自动转换（字符串 "10" → 整数 10）
        instance2 = Model(count="10", label="test")
        assert instance2.count == 10

    def test_contains_operator(self):
        """测试：支持 `if name in registry` 语法"""
        @self.registry.register
        async def my_func(x: str) -> str:
            """测试函数。Args: x: 参数。"""
            return x

        assert "my_func" in self.registry
        assert "nonexistent" not in self.registry

    def test_len_operator(self):
        """测试：len(registry) 返回已注册工具数量"""
        assert len(self.registry) == 0

        @self.registry.register
        async def func1(x: str) -> str:
            """工具1。Args: x: 参数。"""
            return x

        assert len(self.registry) == 1
