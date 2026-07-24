"""
==============================================================================
LLM Reliability Adapter - 一键极简门面函数 (facade.py)
==============================================================================

设计方案说明：
1. 设计意图 (Design Intent)：
   提供 0 门槛、0 依赖、开箱即用的高层门面函数 parse_structured()。
   解决上层业务已拥有 LLM 网络请求逻辑时，导入中间件过度臃肿、漏出底层 5 步 Pipeline 实现细节的问题。
2. 类与函数结构 (Class Structure)：
   - `parse_structured()`: 一键式纯文本到强类型 Pydantic 对象的解析函数。
3. 关键数据流 (Data Flow)：
   Raw Text + Model Class ➔ parse_structured() ➔ Pipeline/Repairer ➔ Safe Typed Object
4. 核心用例考量 (Test Case Intent)：
   - 验证只用一行函数调用即可完成提纯、栈提取、解码、Pydantic 校验与 Level 1 本地修复。
==============================================================================
"""

from typing import Type, TypeVar, Optional
from pydantic import BaseModel

from .parser_pipeline.normalizer import Normalizer
from .parser_pipeline.extractor import BracketExtractor
from .parser_pipeline.decoder import StrictDecoder
from .parser_pipeline.repair import DeterministicRepairer
from .parser_pipeline.validator import SchemaValidator

T = TypeVar("T", bound=BaseModel)


def parse_structured(
    raw_text: str,
    response_model: Type[T],
    enable_local_repair: bool = True
) -> T:
    """
    一键极简结构化解析与修补门面函数 (High-Level Facade Function)

    Args:
        raw_text: 大模型返回的原始未经处理的文本 (包含思考链、Markdown、杂质等)
        response_model: 期望解析到的目标 Pydantic Schema 类型
        enable_local_repair: 是否开启 Level 1 本地 0 延迟确定性修补 (默认 True)

    Returns:
        解析提纯并通过强校验的目标 Pydantic 对象实例

    Raises:
        JSONDecodeCustomError / ValidationError: 当无法解析且修补失败时抛出精细异常
    """
    if not raw_text:
        raise ValueError("raw_text 不能为空")

    # 步骤 1：Normalizer 物理剥离思考链 (<think>) 与 Markdown 代码块
    cleaned_text = Normalizer.normalize(raw_text)

    # 步骤 2：BracketExtractor 基于字符栈精准提取最外层 JSON
    target_str = BracketExtractor.extract_json_object(cleaned_text) or cleaned_text

    # 步骤 3 & 4：StrictDecoder 解码与 SchemaValidator 强校验
    try:
        dict_data = StrictDecoder.decode(target_str)
        return SchemaValidator.validate(dict_data, response_model)
    except Exception as primary_error:
        if not enable_local_repair:
            raise primary_error

    # 步骤 5：Level 1 DeterministicRepairer 本地 0 延迟确定性修补 (修补尾随逗号、未闭合大括号)
    repaired_str = DeterministicRepairer.repair_json_string(target_str)
    dict_data = StrictDecoder.decode(repaired_str)
    return SchemaValidator.validate(dict_data, response_model)
