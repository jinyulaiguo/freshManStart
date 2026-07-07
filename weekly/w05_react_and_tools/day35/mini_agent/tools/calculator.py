"""
MiniAgent Framework v1.0 — 计算器工具

设计说明：
纯 Python 实现的数学表达式计算器，使用白名单 eval 安全沙箱，
防止恶意代码注入，仅允许数学运算符和内置数学函数。
"""
from __future__ import annotations

import math

from ..agent.registry import tool


@tool
async def calculator(expression: str) -> str:
    """
    执行数学表达式计算，支持四则运算、幂运算和常见数学函数。

    Args:
        expression: 数学表达式字符串，例如 "2 + 3 * 4"、"sqrt(16)"、"2 ** 10"。
    """
    # 白名单安全沙箱：只允许访问 math 模块的函数和基础内置函数
    # 明确拒绝 __import__、eval、exec 等危险操作
    allowed_names = {
        # 数学常量
        "pi": math.pi,
        "e": math.e,
        # 常用数学函数
        "sqrt": math.sqrt,
        "pow": math.pow,
        "abs": abs,
        "round": round,
        "floor": math.floor,
        "ceil": math.ceil,
        "log": math.log,
        "log10": math.log10,
        "log2": math.log2,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "factorial": math.factorial,
        "max": max,
        "min": min,
        "sum": sum,
    }

    # 表达式安全校验：拒绝包含危险关键字的输入
    dangerous_keywords = ["__", "import", "exec", "eval", "open", "os", "sys", "subprocess"]
    for kw in dangerous_keywords:
        if kw in expression:
            raise ValueError(
                f"表达式包含不允许的关键字 '{kw}'。"
                f"计算器只支持数学表达式（如 '2 + 3 * 4', 'sqrt(16)'）。"
            )

    try:
        # 在白名单沙箱中执行表达式
        result = eval(expression, {"__builtins__": {}}, allowed_names)  # noqa: S307
        # 格式化输出（整数不显示小数点）
        if isinstance(result, float) and result.is_integer():
            return f"{expression} = {int(result)}"
        return f"{expression} = {result}"
    except ZeroDivisionError:
        raise ValueError(f"表达式 '{expression}' 存在除零错误。")
    except NameError as e:
        raise ValueError(
            f"表达式 '{expression}' 包含未知标识符：{e}。"
            f"支持的函数：sqrt, pow, abs, round, floor, ceil, log, sin, cos, tan, factorial 等。"
        )
    except SyntaxError:
        raise ValueError(f"表达式 '{expression}' 语法错误，请检查括号是否匹配。")
    except Exception as e:
        raise ValueError(f"计算表达式 '{expression}' 时发生错误：{e}")
