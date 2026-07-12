"""
AetherMind Tool Base Abstraction
===============================

设计方案:
---------
本模块定义了 AetherMind 系统中工具的统一封装类 `Tool` 与工具注册机制。
所有挂载到 ReAct Planner 的工具均需要通过本类进行元数据描述，
以便大模型在 Planner 中正确识别并构造对应的 JSON 入参。

结构说明:
---------
- Tool: 工具抽象容器，包含名称、描述、入参 Pydantic Schema 及执行函数引用。
- tool_registry: 全局工具映射表。
- register_tool: 工具注册装饰器。
"""

from typing import Callable, Type, Optional, Any
from pydantic import BaseModel, Field


class Tool(BaseModel):
    """
    Agent 工具抽象容器类。
    """
    name: str = Field(..., description="工具唯一键名")
    description: str = Field(..., description="用于 LLM 识别该工具适用场景的中文描述")
    args_schema: Type[BaseModel] = Field(..., description="工具的入参 Pydantic 模型，生成 JSON Schema")
    func: Callable[..., Any] = Field(..., description="工具底层执行的 callable 函数")

    class Config:
        # 允许函数 callable 字段
        arbitrary_types_allowed = True

    async def run(self, **kwargs) -> str:
        """
        异步运行工具，执行异常捕获（Reflection 机制基础）。

        Returns:
            str: 工具执行结果的字符串形式（出错时返回异常摘要）。
        """
        try:
            # 无论底层函数是 async 还是 sync，都进行自适应调用
            import inspect
            if inspect.iscoroutinefunction(self.func):
                result = await self.func(**kwargs)
            else:
                result = self.func(**kwargs)
            return str(result)
        except Exception as e:
            # 捕获异常作为 Observation，供 ReAct Planner 自纠错
            return f"Error executing tool '{self.name}': {str(e)}"


# 全局工具注册中心
TOOL_REGISTRY: dict[str, Tool] = {}


def register_tool(name: str, description: str, args_schema: Type[BaseModel]):
    """
    注册工具的装饰器。
    """
    def decorator(func: Callable[..., Any]):
        tool = Tool(
            name=name,
            description=description,
            args_schema=args_schema,
            func=func
        )
        TOOL_REGISTRY[name] = tool
        return func
    return decorator
