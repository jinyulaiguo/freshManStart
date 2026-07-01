"""
设计方案：
1. 设计意图：
   通过 Pydantic 库对天气查询工具的参数（WeatherToolArgs）进行强类型约束与结构化数据校验，并自动将其转换为符合 OpenAI Function Calling 标准的 JSON Schema。
2. 类与函数结构：
   - WeatherToolArgs (BaseModel): 存储和校验天气工具参数。
     - city (str): 城市名，要求不为空字符串，使用 Field 进行元数据配置。
     - date (str): 日期，要求符合 YYYY-MM-DD 格式，使用 Field 进行元数据配置。
     - is_celsius (bool): 是否使用摄氏度，提供默认值 True，使用 Field 进行元数据配置。
   - export_openai_tool_schema(name: str, description: str, model_cls: Type[BaseModel]) -> dict:
     将 Pydantic 模型类转换为 OpenAI Function Calling 标准的 JSON Schema。
3. 关键数据流流向：
   用户调用或测试用例传入非结构化字典 -> Pydantic 进行类型反序列化与校验拦截 -> 生成经过校验的 WeatherToolArgs 实例 -> 调用 model_json_schema 提取字段的 JSON 描述 -> 拼接为符合 OpenAI 标准的 Function Tool Schema。
"""

from typing import Type
import re
from pydantic import BaseModel, Field, field_validator


class WeatherToolArgs(BaseModel):
    """天气查询工具参数校验模型"""
    city: str = Field(
        ...,
        description="城市名称，例如：北京, 上海",
        min_length=1
    )
    date: str = Field(
        ...,
        description="查询的日期，格式必须为 YYYY-MM-DD"
    )
    is_celsius: bool = Field(
        default=True,
        description="是否使用摄氏度度量，默认为 True"
    )

    @field_validator("date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        """校验日期格式是否为 YYYY-MM-DD"""
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("Date must be in YYYY-MM-DD format")
        return v


def export_openai_tool_schema(name: str, description: str, model_cls: Type[BaseModel]) -> dict:
    """
    将 Pydantic 模型类转换为符合 OpenAI 规范的 Function Tool Schema
    """
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": model_cls.model_json_schema()
        }
    }
