"""
设计方案：
- 设计意图：构建一个纯本地执行的 CPU 计算工具，主要用于在高并发请求调度中与包含网络 I/O 调用的工具进行对比，提供精确的基础算术计算服务，并内置除以零的安全防线。
- 类与函数结构：
  - `CalculatorTool` 类：实现 `BaseTool` 契约，包括 `name`、`args_model` 属性和 `_execute` 方法。
- 关键数据流向：
  - `CalculatorArgs` 校验参数传入 -> 根据操作符决定分支（+, -, *, /） -> 校验除数是否为零 -> 计算结果并序列化为字符串输出。
"""

from typing import Type
from pydantic import BaseModel
from weekly.w02_pydantic_and_async.project.models.tool_args import CalculatorArgs
from weekly.w02_pydantic_and_async.project.tools.base import BaseTool

class CalculatorTool(BaseTool):
    """基础四则运算计算器工具（本地 CPU 密集型任务）"""

    @property
    def name(self) -> str:
        return "calculator"

    @property
    def args_model(self) -> Type[BaseModel]:
        return CalculatorArgs

    async def _execute(self, validated_args: CalculatorArgs) -> str:
        x = validated_args.x
        y = validated_args.y
        op = validated_args.operator

        if op == "+":
            result = x + y
        elif op == "-":
            result = x - y
        elif op == "*":
            result = x * y
        elif op == "/":
            if y == 0:
                raise ZeroDivisionError("除数不能为零（ZeroDivisionError）")
            result = x / y
        else:
            raise ValueError(f"未知操作符: {op}")

        return str(result)
