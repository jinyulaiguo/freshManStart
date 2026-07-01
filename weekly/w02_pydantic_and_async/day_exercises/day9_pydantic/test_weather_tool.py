"""
设计方案：
1. 设计意图：
   通过自动化单元测试，对 WeatherToolArgs 的数据校验准确性（正常入参校验、异常入参拦截）以及 export_openai_tool_schema 输出格式进行闭环验证。
2. 类与函数结构：
   - test_weather_tool_args_success(): 测试正确入参的解析与校验。
   - test_weather_tool_args_invalid_city(): 测试空城市名或缺失字段的情况。
   - test_weather_tool_args_invalid_date(): 测试非法日期格式的拦截。
   - test_export_openai_tool_schema(): 测试最终生成的 OpenAI Schema 字段结构完整性。
3. 关键数据流流向：
   测试框架构造各种边界字典 -> 输入给模型/导出函数 -> 使用 pytest 校验是否成功或捕获预期的 ValidationError/ValueError。
"""

import pytest
from pydantic import ValidationError
from weekly.w02_pydantic_and_async.day_exercises.day9_pydantic.weather_tool import WeatherToolArgs, export_openai_tool_schema


def test_weather_tool_args_success():
    """测试合法参数解析"""
    args = WeatherToolArgs(city="Beijing", date="2026-07-01")
    assert args.city == "Beijing"
    assert args.date == "2026-07-01"
    assert args.is_celsius is True  # 默认值校验

    args2 = WeatherToolArgs(city="Shanghai", date="2026-07-02", is_celsius=False)
    assert args2.is_celsius is False


def test_weather_tool_args_invalid_city():
    """测试非法城市（空字符串或缺失）"""
    with pytest.raises(ValidationError):
        WeatherToolArgs(city="", date="2026-07-01")

    with pytest.raises(ValidationError):
        # 缺失 city
        WeatherToolArgs(date="2026-07-01")  # type: ignore


def test_weather_tool_args_invalid_date():
    """测试非法日期格式校验"""
    with pytest.raises(ValidationError) as excinfo:
        WeatherToolArgs(city="Beijing", date="2026/07/01")
    assert "Date must be in YYYY-MM-DD format" in str(excinfo.value)

    with pytest.raises(ValidationError):
        WeatherToolArgs(city="Beijing", date="26-07-01")


def test_export_openai_tool_schema():
    """测试导出 OpenAI Function Schema 格式"""
    schema = export_openai_tool_schema(
        name="get_current_weather",
        description="Get the current weather for a location",
        model_cls=WeatherToolArgs
    )
    
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "get_current_weather"
    assert schema["function"]["description"] == "Get the current weather for a location"
    
    parameters = schema["function"]["parameters"]
    assert parameters["type"] == "object"
    assert "city" in parameters["properties"]
    assert "date" in parameters["properties"]
    assert "is_celsius" in parameters["properties"]
    
    # 确保字段描述和要求在 Schema 中正确反映
    assert "city" in parameters["required"]
    assert "date" in parameters["required"]
