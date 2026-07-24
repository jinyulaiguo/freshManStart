"""
==============================================================================
LLM Reliability Adapter - Recovery Engine (recovery/engine.py)
==============================================================================

设计方案说明：
1. 设计意图 (Design Intent)：
   实现 Level 1 ➔ Level 2 ➔ Level 3 三级阶梯式故障恢复与自修复引擎。
   - Level 1 (Local Fix): 优先尝试 0 Token、0 延迟的本地确定性修补。
   - Level 2 (LLM Contextual Re-ask): 本地修补失败时，基于 LangChain RetryWithError 范式，
     生成包含 (Original Prompt, Faulty Completion, Validation Error) 三元组的纠错 Re-prompt。
   - Level 3 (Circuit Breaker Degrade): 重试耗尽后触发熔断降级。
2. 类与函数结构 (Class Structure)：
   - `RecoveryStrategyAction`: 恢复策略动作枚举。
   - `RecoveryEngine`: 故障恢复协调引擎。
3. 关键数据流 (Data Flow)：
   Parse Error ➔ RecoveryEngine ➔ (Level 1 Success / Level 2 Re-prompt / Level 3 Fallback)
4. 核心用例考量 (Test Case Intent)：
   - 验证三元组纠错 Prompt 生成的完整性，确保模型能准确定位缺失字段或语法错误点。
==============================================================================
"""

from enum import Enum
from typing import Any, Dict, Optional, Tuple, Type
from pydantic import BaseModel, ValidationError

from ..contracts.input_output import AdapterInput, AdapterOutput
from ..parser_pipeline.decoder import StrictDecoder, JSONDecodeCustomError
from ..parser_pipeline.repair import DeterministicRepairer
from ..parser_pipeline.validator import SchemaValidator


class RecoveryStrategyAction(str, Enum):
    """恢复策略动作"""
    LOCAL_REPAIR_SUCCESS = "LOCAL_REPAIR_SUCCESS"    # Level 1 本地修复成功
    RETRY_LLM_REASK = "RETRY_LLM_REASK"              # Level 2 向上层申请重新请求 LLM
    DEGRADE_FALLBACK = "DEGRADE_FALLBACK"            # Level 3 触发熔断降级兜底
    UNRECOVERABLE = "UNRECOVERABLE"                  # 无法修复且无兜底


class RecoveryEngine:
    """
    三级阶梯式故障恢复与修补引擎
    """

    @staticmethod
    def try_local_repair(
        extracted_text: str,
        response_model: Type[BaseModel]
    ) -> Tuple[bool, Optional[BaseModel], str]:
        """
        步骤块：执行 Level 1 本地零延迟确定性修补尝试
        
        Args:
            extracted_text: 无法被标准解码的提取字符串
            response_model: 目标 Pydantic Schema 类型
            
        Returns:
            Tuple[是否成功, 校验后的 Typed Object, 修补后的文本字符串]
        """
        if not extracted_text:
            return False, None, ""

        # 步骤 1：调用 DeterministicRepairer 执行本地规则修补
        repaired_text = DeterministicRepairer.repair_json_string(extracted_text)

        # 步骤 2：尝试对修补后的文本重新解码与校验
        try:
            dict_data = StrictDecoder.decode(repaired_text)
            validated_obj = SchemaValidator.validate(dict_data, response_model)
            return True, validated_obj, repaired_text
        except Exception:
            # Level 1 修补失败
            return False, None, repaired_text

    @staticmethod
    def build_reask_prompt(
        original_prompt: str,
        faulty_completion: str,
        error_detail: str,
        target_schema_json: str
    ) -> str:
        """
        步骤块：构建符合 LangChain RetryWithError 范式的 Level 2 Re-prompt 三元组
        
        Args:
            original_prompt: 原始的用户提示词
            faulty_completion: LLM 上一次生成的非法/报错响应文本
            error_detail: 解析器或 Validator 抛出的精细错误诊断
            target_schema_json: 目标 Pydantic Schema 的 JSON 表示
            
        Returns:
            具备充分上下文的纠错提示词
        """
        reask_prompt = f"""
[ERROR RECOVERY NOTICE]
Your previous output failed to satisfy the required JSON Schema or format criteria.

### ORIGINAL TASK PROMPT:
{original_prompt}

### YOUR PREVIOUS FAULTY OUTPUT:
```
{faulty_completion}
```

### DETAILED VALIDATION / PARSING ERRORS:
{error_detail}

### MANDATORY TARGET JSON SCHEMA:
{target_schema_json}

### INSTRUCTIONS FOR RE-GENERATION:
1. Carefully analyze the validation error above.
2. Fix all syntax errors, missing fields, or incorrect type values.
3. Output ONLY a 100% valid JSON object matching the target schema.
4. Do NOT include markdown explanations or code fences outside the JSON object.
"""
        return reask_prompt.strip()

    @staticmethod
    def handle_recovery(
        input_contract: AdapterInput,
        raw_output: str,
        current_attempt: int,
        error: Exception
    ) -> Tuple[RecoveryStrategyAction, Optional[BaseModel], str]:
        """
        步骤块：协调 Level 1 ➔ Level 2 ➔ Level 3 恢复策略
        
        Args:
            input_contract: 通用输入契约
            raw_output: 本轮大模型输出原文本
            current_attempt: 当前尝试的轮数 (1-indexed)
            error: 捕获的异常信息
            
        Returns:
            Tuple[动作策略, 结果对象(若有), 下一步提示词或说明]
        """
        # 判定是否还能进行 Level 2 LLM Re-prompt 重试
        can_retry_llm = current_attempt < input_contract.config.max_retries

        if can_retry_llm:
            # 构造 Level 2 三元组纠错 Prompt
            try:
                schema_json = input_contract.response_model.model_json_schema()
            except Exception:
                schema_json = str(input_contract.response_model)

            reask_prompt = RecoveryEngine.build_reask_prompt(
                original_prompt=input_contract.prompt,
                faulty_completion=raw_output,
                error_detail=str(error),
                target_schema_json=str(schema_json)
            )
            return RecoveryStrategyAction.RETRY_LLM_REASK, None, reask_prompt

        # 重试次数耗尽，尝试 Level 3 熔断降级 (Circuit Breaker & Fallback)
        if input_contract.config.enable_circuit_breaker and input_contract.fallback_factory:
            try:
                if callable(input_contract.fallback_factory):
                    fallback_obj = input_contract.fallback_factory()
                else:
                    fallback_obj = input_contract.fallback_factory
                return RecoveryStrategyAction.DEGRADE_FALLBACK, fallback_obj, "Circuit breaker fallback triggered."
            except Exception as fb_err:
                return RecoveryStrategyAction.UNRECOVERABLE, None, f"Fallback factory failed: {fb_err}"

        return RecoveryStrategyAction.UNRECOVERABLE, None, f"Exhausted {current_attempt} attempts without fallback."
