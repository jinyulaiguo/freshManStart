"""
设计方案：
- 设计意图：对工具入参进行严格的静态字段强校验与联合逻辑验证，确保脏输入能在进入核心计算/网络前被阻断在最外层。
- 类与函数结构：
  - `test_calculator_args` 函数：验证计算器运算符白名单校验。
  - `test_weather_args` 函数：验证天气查询天数越界拦截。
  - `test_exchange_args` 函数：验证汇率转换的币种清洗、大写转换、负数拦截以及同币种转换拦截。
- 关键数据流向：
  - 测试参数字典 -> 实例化对应 Args 类 -> 执行校验器 (model_validator / field_validator) -> 抛出 ValidationError。
"""

import pytest
from pydantic import ValidationError
from weekly.w02_pydantic_and_async.project.models.tool_args import (
    CalculatorArgs,
    WeatherArgs,
    ExchangeArgs,
)

def test_calculator_args():
    # 合法入参
    args = CalculatorArgs(x=1.0, y=2.0, operator="+")
    assert args.operator == "+"
    
    # 不支持的操作符拦截
    with pytest.raises(ValidationError) as exc:
        CalculatorArgs(x=1.0, y=2.0, operator="%")
    assert "不支持的运算符" in str(exc.value)

def test_weather_args():
    # 合法语义
    args = WeatherArgs(city="Shanghai", days=3)
    assert args.days == 3
    
    # 城市名不能为空字符串拦截
    with pytest.raises(ValidationError):
        WeatherArgs(city="", days=3)

    # 查询天数越界拦截 (8 > 7)
    with pytest.raises(ValidationError):
        WeatherArgs(city="Beijing", days=8)

def test_exchange_args():
    # 合法语义与自动格式规整清洗
    args = ExchangeArgs(base_currency=" usd ", target_currency="cny", amount=100.5)
    assert args.base_currency == "USD"
    assert args.target_currency == "CNY"
    assert args.amount == 100.5

    # 负数金额拦截
    with pytest.raises(ValidationError):
        ExchangeArgs(base_currency="USD", target_currency="CNY", amount=-10.0)

    # 货币代码长度不合法拦截
    with pytest.raises(ValidationError):
        ExchangeArgs(base_currency="USDT", target_currency="CNY", amount=10.0)

    # 相同货币互转拦截
    with pytest.raises(ValidationError) as exc:
        ExchangeArgs(base_currency="USD", target_currency="usd", amount=50.0)
    assert "目标货币不能相同" in str(exc.value)
