"""
设计方案：
- 设计意图：使用 Python 的 `abc.ABC` 与 `@abstractmethod` 声明标准工具抽象基类。本类是工具模块的顶层接口契约，通过统一结构确保任何工具的注册、模式导出（Schema 导出）、参数解析和具体异步执行均遵从统一规范。
- 类与函数结构：
  - `BaseTool` 抽象基类：
    - `name` 抽象属性：返回工具标识。
    - `args_model` 抽象属性：返回对应的 Pydantic BaseModel 类型。
    - `_execute` 抽象异步方法：由具体子类实现的核心业务逻辑。
    - `schema` 方法：利用 Pydantic 的反射能力自动导出符合规范的 JSON Schema 结构描述。
    - `__call__` 异步魔法方法：整合“校验拦截”与“异步运行”，提供类似函数的可调用入口。
    - `__repr__` 魔法方法：输出便于开发者调试的工具摘要。
- 关键数据流向：
  - 外部 JSON 数据 -> 调用 `__call__(raw_json)` -> 使用 `args_model` 进行类型安全检验拦截 -> 传递强类型模型实例至 `_execute` -> 异步处理并返回结果。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Type
from pydantic import BaseModel

class BaseTool(ABC):
    """大模型/调度引擎可调用的异步工具基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具唯一注册标示名称"""
        pass

    @property
    @abstractmethod
    def args_model(self) -> Type[BaseModel]:
        """工具入参所绑定的 Pydantic 模型类"""
        pass

    @abstractmethod
    async def _execute(self, validated_args: Any) -> str:
        """核心异步执行协程，子类必须重写并完成业务逻辑"""
        pass

    def schema(self) -> Dict[str, Any]:
        """导出该工具参数的标准 JSON Schema 协议声明（用于大模型 Function Calling 参数填充）"""
        return self.args_model.model_json_schema()

    async def __call__(self, raw_json: str) -> str:
        """
        Dunder Dunder 魔法方法：使工具对象像异步函数一样可被直接调用。
        在执行前会自动进行 Pydantic 反序列化与入参拦截校验。
        """
        # 利用 Pydantic 对传入的 JSON 字符串进行反序列化与字段级/模型级多重拦截校验
        validated_args = self.args_model.model_validate_json(raw_json)
        return await self._execute(validated_args)

    def __repr__(self) -> str:
        """面向调试的友好字符串表达"""
        fields = list(self.args_model.model_fields.keys())
        return f"<BaseTool name='{self.name}' args={fields}>"
