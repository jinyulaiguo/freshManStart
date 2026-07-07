"""
MiniAgent Framework v1.0 — 天气查询模拟工具

设计说明：
模拟真实天气 API 的行为，包含正常返回和城市不存在时的异常抛出，
用于验证 Framework 的基本工具调度能力和错误边界处理。
"""
from __future__ import annotations

import asyncio
import random

from ..agent.registry import tool


@tool
async def get_weather(city: str, unit: str = "celsius") -> str:
    """
    获取指定城市的当前天气状况（模拟 API）。

    Args:
        city: 目标城市名称，例如 "北京"、"上海"、"杭州"。
        unit: 温度单位，"celsius" 表示摄氏度，"fahrenheit" 表示华氏度。默认摄氏度。
    """
    # 模拟网络延迟（50-200ms）
    await asyncio.sleep(random.uniform(0.05, 0.2))

    # 城市天气数据库（模拟）
    weather_db: dict[str, dict] = {
        "北京": {"temp": 28, "condition": "晴天", "humidity": "45%", "wind": "东南风 2级"},
        "上海": {"temp": 32, "condition": "多云", "humidity": "72%", "wind": "东风 3级"},
        "杭州": {"temp": 30, "condition": "晴转多云", "humidity": "68%", "wind": "东南风 2级"},
        "广州": {"temp": 35, "condition": "雷阵雨", "humidity": "85%", "wind": "南风 4级"},
        "成都": {"temp": 26, "condition": "阴天", "humidity": "78%", "wind": "西北风 1级"},
        "深圳": {"temp": 34, "condition": "多云转晴", "humidity": "80%", "wind": "南风 3级"},
        "beijing": {"temp": 28, "condition": "Sunny", "humidity": "45%", "wind": "SE 2"},
        "shanghai": {"temp": 32, "condition": "Cloudy", "humidity": "72%", "wind": "E 3"},
        "hangzhou": {"temp": 30, "condition": "Partly Cloudy", "humidity": "68%", "wind": "SE 2"},
    }

    # 城市名归一化（去掉空格，首字母大写，统一小写查找）
    city_key = city.strip()
    city_lower = city_key.lower()

    data = weather_db.get(city_key) or weather_db.get(city_lower)
    if not data:
        raise ValueError(
            f"城市 '{city}' 不在天气服务覆盖范围内。"
            f"目前支持的城市：{', '.join(list(weather_db.keys())[:6])} 等。"
        )

    # 温度单位转换
    temp = data["temp"]
    if unit.lower() == "fahrenheit":
        temp = round(temp * 9 / 5 + 32, 1)
        unit_symbol = "°F"
    else:
        unit_symbol = "°C"

    return (
        f"{city_key} 当前天气：{data['condition']}，"
        f"气温 {temp}{unit_symbol}，"
        f"湿度 {data['humidity']}，"
        f"风力 {data['wind']}。"
    )
