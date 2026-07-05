"""
Week 4 Day 28 综合实战 — 微引擎 4：并发提取流水线核心 (Pipeline)

设计方案：
1. 设计意图：
   编排整个批量简历提取的并发执行流，串联所有微引擎：
   - 使用 asyncio.Semaphore 限制最大并发请求数（防止 API Key 触发 QPS 限流）
   - 使用 @circuit_breaker 装饰器包裹核心提取函数（外部 API 崩溃时自动熔断降级）
   - 内部调用 SelfCorrectionEngine 执行自愈纠错（脏 JSON 修复 + Pydantic 校验失败重试）
   - 底层使用 Day 26 的 PooledLLMClient 连接池化客户端（TCP/TLS 连接复用）
   - 使用 Jinja2 模板渲染 System Prompt（代码与提示词解耦）
   - 生成结构化执行报告（成功率、自愈成功率、熔断拦截数等）

2. 类与函数结构：
   - PipelineReport(BaseModel): 流水线执行报告数据模型
   - ResumePipeline:
     - __init__(max_concurrency, breaker_threshold, breaker_cooldown, max_correction_rounds):
       初始化信号量、熔断器参数、连接池客户端
     - _render_system_prompt() -> str: 使用 Jinja2 渲染提取 Prompt（注入 JSON Schema）
     - async _extract_single_inner(resume_text, resume_index) -> ExtractionResult:
       单条简历提取的内部实现（被 @circuit_breaker 装饰前的原始逻辑）
     - async _extract_single(resume_text, resume_index) -> ExtractionResult:
       信号量限流 + 熔断器包裹的单条提取入口
     - async run_batch(resume_texts) -> PipelineReport: 批量并发执行入口
     - async close(): 关闭连接池

3. 关键数据流向：
   sample_resumes ──→ run_batch() ──→ asyncio.gather() 并发调度
     ──→ _extract_single() [信号量限流]
       ──→ @circuit_breaker [熔断器检查]
         ──→ SelfCorrectionEngine.extract_with_correction() [自愈纠错]
           ──→ PooledLLMClient.request_with_retry() [连接池 + 重试]
             ──→ LLM API
   ──→ 汇总 ExtractionResult 列表 ──→ 生成 PipelineReport
"""

import sys
import os
import json
import asyncio
import logging
import time
import traceback
from typing import Optional

# =====================================================================
# 防御性 sys.path 补丁逻辑
# =====================================================================
current_dir = os.path.dirname(os.path.realpath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "../../.."))

if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from jinja2 import Template
from pydantic import BaseModel, Field

from weekly.w04_prompt_and_http.project.resume_schema import (
    ResumeInfo, ExtractionResult
)
from weekly.w04_prompt_and_http.project.self_correction import SelfCorrectionEngine
from weekly.w04_prompt_and_http.project.circuit_breaker import (
    circuit_breaker, CircuitBreakerOpenException
)
from weekly.w04_prompt_and_http.day26.state_tracker import PooledLLMClient

logger = logging.getLogger(__name__)


# =====================================================================
# 流水线执行报告数据模型
# =====================================================================

class PipelineReport(BaseModel):
    """批量提取流水线的结构化执行报告"""
    total_count: int = Field(..., description="总简历数")
    success_count: int = Field(0, description="成功提取数")
    self_corrected_count: int = Field(0, description="经自愈纠错后成功的数量")
    breaker_tripped_count: int = Field(0, description="被熔断器拦截的数量")
    failed_count: int = Field(0, description="最终失败数")
    total_time_seconds: float = Field(0.0, description="总执行耗时（秒）")
    results: list[ExtractionResult] = Field(
        default_factory=list, description="各条简历的详细提取结果"
    )

    @property
    def success_rate(self) -> float:
        """计算成功率百分比"""
        return (self.success_count / self.total_count * 100) if self.total_count > 0 else 0.0

    @property
    def self_correction_rate(self) -> float:
        """计算自愈成功率（占成功总数的百分比）"""
        return (self.self_corrected_count / self.success_count * 100) if self.success_count > 0 else 0.0


# =====================================================================
# 并发提取流水线核心
# =====================================================================

class ResumePipeline:
    """
    高并发简历结构化提取流水线。

    职责编排：
    1. asyncio.Semaphore 并发限流
    2. @circuit_breaker 熔断器保护
    3. SelfCorrectionEngine 自愈纠错
    4. PooledLLMClient 连接池化网络层
    5. Jinja2 提示词模板渲染
    """

    def __init__(
        self,
        max_concurrency: int = 3,
        breaker_threshold: int = 5,
        breaker_cooldown: float = 30.0,
        max_correction_rounds: int = 2
    ):
        """
        参数:
            max_concurrency: 最大并发协程数（Semaphore 容量）
            breaker_threshold: 熔断器连续失败阈值
            breaker_cooldown: 熔断器冷却秒数
            max_correction_rounds: 自愈纠错最大轮次
        """
        # 1. 信号量并发控制
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.max_concurrency = max_concurrency

        # 2. 连接池化 LLM 客户端（Day 26）
        self.llm_client = PooledLLMClient(
            max_connections=max_concurrency * 2,
            max_keepalive=max_concurrency
        )

        # 3. 自愈纠错引擎（Day 24 + Day 23）
        self.correction_engine = SelfCorrectionEngine(
            llm_client=self.llm_client,
            max_correction_rounds=max_correction_rounds
        )

        # 4. 熔断器参数（后续通过动态装饰应用）
        self.breaker_threshold = breaker_threshold
        self.breaker_cooldown = breaker_cooldown

        # 5. 渲染 System Prompt
        self.system_prompt = self._render_system_prompt()

        # 6. 熔断器状态跟踪（手动实现以支持实例级隔离）
        from weekly.w04_prompt_and_http.project.circuit_breaker import CircuitBreakerState
        self._breaker_state = CircuitBreakerState(breaker_threshold, breaker_cooldown)

        logger.info(
            f"[流水线] 初始化完成 | 最大并发: {max_concurrency} | "
            f"熔断阈值: {breaker_threshold} | 冷却: {breaker_cooldown}s | "
            f"最大纠错轮次: {max_correction_rounds}"
        )

    def _render_system_prompt(self) -> str:
        """使用 Jinja2 渲染简历提取的 System Prompt，注入 JSON Schema"""
        template_path = os.path.join(current_dir, "prompt_template.jinja")

        if not os.path.exists(template_path):
            raise FileNotFoundError(f"找不到提示词模板文件: {template_path}")

        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()

        template = Template(template_content)

        # 动态获取 Pydantic 模型的 JSON Schema
        json_schema = json.dumps(
            ResumeInfo.model_json_schema(),
            ensure_ascii=False,
            indent=2
        )

        # 渲染模板（resume_text 留空，在实际提取时由 SelfCorrectionEngine 填入）
        rendered = template.render(
            json_schema=json_schema,
            resume_text="{{resume_text_placeholder}}"
        )
        return rendered

    async def _extract_single_inner(
        self,
        resume_text: str,
        resume_index: int
    ) -> ExtractionResult:
        """
        单条简历提取的内部实现（不含信号量和熔断器包裹）。
        委托给 SelfCorrectionEngine 执行自愈纠错提取。
        """
        return await self.correction_engine.extract_with_correction(
            resume_text=resume_text,
            system_prompt=self.system_prompt,
            resume_index=resume_index
        )

    async def _extract_single(
        self,
        resume_text: str,
        resume_index: int
    ) -> ExtractionResult:
        """
        单条简历提取的完整入口：信号量限流 + 手动熔断器检查 + 内部提取。
        """
        text_preview = resume_text[:80]

        # 1. 熔断器前置检查
        try:
            self._breaker_state.check_state()
        except CircuitBreakerOpenException as cbe:
            logger.warning(
                f"[流水线] 简历 #{resume_index} 被熔断器拦截: {cbe}"
            )
            return ExtractionResult(
                resume_index=resume_index,
                original_text=text_preview,
                success=False,
                breaker_tripped=True,
                error_message=f"熔断器拦截: {cbe}"
            )

        # 2. 信号量限流
        async with self.semaphore:
            logger.info(
                f"[流水线] 简历 #{resume_index} 获取信号量，开始提取..."
            )
            start_time = time.time()

            try:
                result = await self._extract_single_inner(resume_text, resume_index)

                # 3. 成功：重置熔断器
                if result.success:
                    self._breaker_state.record_success()
                else:
                    # 提取逻辑失败（非网络异常），也计入失败
                    self._breaker_state.record_failure()

                elapsed = time.time() - start_time
                logger.info(
                    f"[流水线] 简历 #{resume_index} 提取完成 "
                    f"{'✅' if result.success else '❌'} | "
                    f"耗时: {elapsed:.2f}s | "
                    f"自愈: {result.self_corrected} | "
                    f"纠错轮次: {result.correction_rounds}"
                )
                return result

            except Exception as e:
                # 4. 未预期的异常：记录熔断器失败 + 保存完整调用栈
                self._breaker_state.record_failure()
                elapsed = time.time() - start_time
                tb = traceback.format_exc()
                logger.error(
                    f"[流水线] 简历 #{resume_index} 遭遇未预期异常 | "
                    f"耗时: {elapsed:.2f}s\n"
                    f"异常类型: {type(e).__name__}\n"
                    f"异常消息: {e}\n"
                    f"调用栈:\n{tb}"
                )
                return ExtractionResult(
                    resume_index=resume_index,
                    original_text=text_preview,
                    success=False,
                    error_message=f"未预期异常: {type(e).__name__}: {e}\n{tb}"
                )

    async def run_batch(self, resume_texts: list[str]) -> PipelineReport:
        """
        批量并发执行入口。

        使用 asyncio.gather 并发调度所有简历提取任务，
        信号量控制同一时刻最多 max_concurrency 个协程在执行。

        参数:
            resume_texts: 简历文本列表

        返回:
            PipelineReport 结构化执行报告
        """
        total = len(resume_texts)
        logger.info(f"[流水线] 开始批量提取 {total} 条简历，最大并发: {self.max_concurrency}")

        start_time = time.time()

        # 创建所有提取任务
        tasks = [
            self._extract_single(text, idx)
            for idx, text in enumerate(resume_texts)
        ]

        # 并发执行
        results = await asyncio.gather(*tasks, return_exceptions=True)

        total_time = time.time() - start_time

        # 汇总统计
        extraction_results: list[ExtractionResult] = []
        success_count = 0
        self_corrected_count = 0
        breaker_tripped_count = 0
        failed_count = 0

        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                # asyncio.gather 返回的异常
                logger.error(f"[流水线] 简历 #{idx} gather 异常: {result}")
                extraction_results.append(ExtractionResult(
                    resume_index=idx,
                    original_text=resume_texts[idx][:80],
                    success=False,
                    error_message=f"gather 异常: {type(result).__name__}: {result}"
                ))
                failed_count += 1
            elif isinstance(result, ExtractionResult):
                extraction_results.append(result)
                if result.success:
                    success_count += 1
                    if result.self_corrected:
                        self_corrected_count += 1
                elif result.breaker_tripped:
                    breaker_tripped_count += 1
                    failed_count += 1
                else:
                    failed_count += 1

        report = PipelineReport(
            total_count=total,
            success_count=success_count,
            self_corrected_count=self_corrected_count,
            breaker_tripped_count=breaker_tripped_count,
            failed_count=failed_count,
            total_time_seconds=round(total_time, 2),
            results=extraction_results
        )

        logger.info(
            f"[流水线] 批量提取完成 | 总数: {total} | "
            f"成功: {success_count} ({report.success_rate:.1f}%) | "
            f"自愈: {self_corrected_count} | "
            f"熔断拦截: {breaker_tripped_count} | "
            f"失败: {failed_count} | "
            f"总耗时: {total_time:.2f}s"
        )

        return report

    async def close(self):
        """关闭连接池，释放网络资源"""
        await self.llm_client.close()
        logger.info("[流水线] 连接池已关闭")
