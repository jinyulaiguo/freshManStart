"""
设计方案：
1. 设计意图：
   测试学员在 practice.py 中的实现是否完全正确。
2. 类与函数结构：
   - 与 test_weather_tool.py 类似的测试用例，导入 practice.py 进行验证。
"""

import pytest
from pydantic import ValidationError
from weekly.w02_pydantic_and_async.day_exercises.day9_pydantic.practice import WeatherToolArgs, export_openai_tool_schema


def test_practice_success():
    args = WeatherToolArgs(city="Beijing", date="2026-07-01")
    assert args.city == "Beijing"
    assert args.date == "2026-07-01"
    assert args.is_celsius is True

    args2 = WeatherToolArgs(city="Shanghai", date="2026-07-02", is_celsius=False)
    assert args2.is_celsius is False


def test_practice_invalid_city():
    with pytest.raises(ValidationError):
        WeatherToolArgs(city="", date="2026-07-01")


def test_practice_invalid_date():
    with pytest.raises(ValidationError) as excinfo:
        WeatherToolArgs(city="Beijing", date="2026/07/01")
    assert "Date must be in YYYY-MM-DD format" in str(excinfo.value)


def test_practice_schema():
    schema = export_openai_tool_schema(
        name="get_current_weather",
        description="Get the current weather for a location",
        model_cls=WeatherToolArgs
    )
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "get_current_weather"
    assert schema["function"]["parameters"]["type"] == "object"
