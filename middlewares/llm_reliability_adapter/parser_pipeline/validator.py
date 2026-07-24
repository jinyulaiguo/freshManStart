"""
==============================================================================
LLM Reliability Adapter - Schema Validator 微组件 (parser_pipeline/validator.py)
==============================================================================

设计方案说明：
1. 设计意图 (Design Intent)：
   作为 Parser Pipeline 的第五道工序，负责基于目标 Pydantic BaseModel 进行类型强校验。
   确保所有解析出来的 dict 对象符合预期的字段契约、数据类型及自定义业务校验规则。
2. 类与函数结构 (Class Structure)：
   - `SchemaValidator`: 包含 validate() 泛型校验静态函数。
3. 关键数据流 (Data Flow)：
   Python dict ➔ SchemaValidator.validate(data_dict, model_class) ➔ Validated Typed Object
4. 核心用例考量 (Test Case Intent)：
   - 验证缺少必填字段或类型不匹配时触发 pydantic.ValidationError 并保留详细错误 Traceback。
==============================================================================
"""

from typing import Any, Dict, Type, TypeVar
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class SchemaValidator:
    """
    基于 Pydantic 模型的结构化 Schema 强校验器
    """

    @staticmethod
    def validate(data_dict: Dict[str, Any], model_class: Type[T]) -> T:
        """
        步骤块：根据给定的目标 Pydantic 模型类执行数据校验
        
        Args:
            data_dict: 经过解包提取的 Python 字典数据
            model_class: 继承自 pydantic.BaseModel 的目标类型
            
        Returns:
            实例化且校验通过的目标类型对象
            
        Raises:
            ValidationError: 当字段缺失、类型不匹配或校验规则不满足时抛出
        """
        if not issubclass(model_class, BaseModel):
            raise TypeError(f"model_class 必须继承自 pydantic.BaseModel, 收到: {model_class}")

        # 使用 Pydantic 的 model_validate 执行强校验拦截
        return model_class.model_validate(data_dict)
