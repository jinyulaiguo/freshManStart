"""
设计方案：
1. 设计意图：
   学员通过编写 WeatherToolArgs 类和 export_openai_tool_schema 函数，学习如何使用 Pydantic 进行类型校验、参数描述元数据配置以及将类导出为 JSON Schema 的完整闭环。
2. 类与函数结构：
   - WeatherToolArgs (BaseModel): 存储和校验天气工具参数。
     - 需定义字段：city (str), date (str), is_celsius (bool)
     - 需使用 Field 配置描述与校验规则。
     - 需使用 field_validator 校验 date 字段的 YYYY-MM-DD 格式。
   - export_openai_tool_schema(name: str, description: str, model_cls: Type[BaseModel]) -> dict:
     提取并拼装符合 OpenAI 规范的 JSON Schema 格式。
3. 关键数据流流向：
   字典输入 -> WeatherToolArgs 实例化与校验 -> 产生 ValidationError 或合规对象 -> 通过 model_json_schema 转换为 JSON Schema 参数部分并包装。
"""

import re
from typing import Type
from pydantic import BaseModel, Field, field_validator


class WeatherToolArgs(BaseModel):
    """
    练习定义 Pydantic 参数校验模型
    - city: 字符串类型，不能为空
    - date: 字符串类型，必须是 YYYY-MM-DD 格式
    - is_celsius: 布尔类型，默认值为 True
    """
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
