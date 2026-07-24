"""
==============================================================================
LLM Reliability Adapter - 主适配器引擎 (adapter.py)
==============================================================================

设计方案说明：
1. 设计意图 (Design Intent)：
   作为 Universal LLM Reliability Adapter 中间件的核心入口与调度控制器。
   协调 Driver、Parser Pipeline (Normalizer -> Extractor -> Decoder -> Validator -> Repair) 
   以及 RecoveryEngine，完成上层请求的可靠解析与自修复。
2. 类与函数结构 (Class Structure)：
   - `UniversalAdapter`: 核心调度协调类。
3. 关键数据流 (Data Flow)：
   Upper Runtime ➔ UniversalAdapter.process(input_contract) ➔ AdapterOutput
4. 核心用例考量 (Test Case Intent)：
   - 验证成功率、重试轨迹 (recovery_path) 记录的完整性以及降级熔断有效性。
==============================================================================
"""

from typing import Generic, Optional, TypeVar
from pydantic import BaseModel, ValidationError

from .config import ReliabilityConfig
from .contracts.input_output import AdapterInput, AdapterOutput
from .drivers.base import BaseLLMDriver
from .parser_pipeline.decoder import StrictDecoder, JSONDecodeCustomError
from .parser_pipeline.extractor import BracketExtractor
from .parser_pipeline.normalizer import Normalizer
from .parser_pipeline.validator import SchemaValidator
from .recovery.engine import RecoveryEngine, RecoveryStrategyAction

T = TypeVar("T", bound=BaseModel)


class UniversalAdapter(Generic[T]):
    """
    通用 LLM 可靠性适配器管理器
    """

    def __init__(self, driver: BaseLLMDriver):
        """
        初始化适配器
        
        Args:
            driver: 实现 BaseLLMDriver 接口的大模型底层驱动实例
        """
        self.driver = driver

    def process(self, input_contract: AdapterInput[T]) -> AdapterOutput[T]:
        """
        步骤块：处理 Agent 提交的 AdapterInput，执行 Pipeline 与多级故障恢复
        
        Args:
            input_contract: 输入契约对象
            
        Returns:
            处理完成后的 AdapterOutput[T] 强类型契约
        """
        output = AdapterOutput[T](success=False, attempts=0)
        current_prompt = input_contract.prompt
        attempt = 0

        while attempt < input_contract.config.max_retries:
            attempt += 1
            output.attempts = attempt
            
            # 步骤 1：调用 Driver 执行 LLM 网络请求
            try:
                raw_text = self.driver.generate(
                    prompt=current_prompt,
                    system_instruction=input_contract.system_instruction,
                    context=input_contract.context
                )
                output.raw_response = raw_text
            except Exception as net_err:
                output.add_trace_step("DRIVER_NETWORK_ERROR", str(net_err))
                output.error_message = f"LLM Driver 呼叫失败: {net_err}"
                break

            # 步骤 2：执行 Parser Pipeline 节点 1 - Normalizer
            normalized = Normalizer.normalize(raw_text)

            # 步骤 3：执行 Parser Pipeline 节点 2 - Extractor
            extracted = BracketExtractor.extract_json_object(normalized)
            if not extracted:
                extracted = normalized

            # 步骤 4：尝试节点 3 Decoder & 节点 4 Validator 直接校验
            try:
                dict_data = StrictDecoder.decode(extracted)
                validated_obj = SchemaValidator.validate(dict_data, input_contract.response_model)
                
                # 直接校验成功！
                output.success = True
                output.data = validated_obj
                output.add_trace_step("NORMAL_SUCCESS", f"Attempt {attempt} Direct Pass")
                return output
            except (JSONDecodeCustomError, ValidationError, Exception) as parse_err:
                output.add_trace_step(
                    f"ATTEMPT_{attempt}_PARSER_FAILED",
                    f"Error: {parse_err}"
                )

                # 步骤 5：直接校验失败，优先尝试 Level 1 本地确定性修补 (0 Token 消耗)
                if input_contract.config.enable_local_repair:
                    repair_ok, repaired_obj, _ = RecoveryEngine.try_local_repair(
                        extracted_text=extracted,
                        response_model=input_contract.response_model
                    )
                    if repair_ok:
                        output.success = True
                        output.data = repaired_obj
                        output.add_trace_step("LOCAL_REPAIR_SUCCESS", f"Attempt {attempt} Repaired locally")
                        return output
                    else:
                        output.add_trace_step("LOCAL_REPAIR_FAILED", "Deterministic repair could not fix issue")

                # 步骤 6：Level 1 失败，计算 RecoveryEngine 策略 (Level 2 Re-ask 或 Level 3 Degrade)
                action, fallback_obj, next_step_msg = RecoveryEngine.handle_recovery(
                    input_contract=input_contract,
                    raw_output=raw_text,
                    current_attempt=attempt,
                    error=parse_err
                )

                if action == RecoveryStrategyAction.RETRY_LLM_REASK:
                    # 升维至 Level 2：更新 prompt 为纠错 Re-prompt 准备发起下一轮尝试
                    output.add_trace_step("LEVEL2_REASK_PREPARED", f"Prompt length: {len(next_step_msg)}")
                    current_prompt = next_step_msg
                    continue
                elif action == RecoveryStrategyAction.DEGRADE_FALLBACK:
                    # 升维至 Level 3：触发熔断降级
                    output.success = True
                    output.data = fallback_obj
                    output.add_trace_step("LEVEL3_FALLBACK_TRIGGERED", next_step_msg)
                    return output
                else:
                    # 无法恢复
                    output.error_message = next_step_msg
                    output.add_trace_step("UNRECOVERABLE", next_step_msg)
                    break

        return output
