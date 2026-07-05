"""
Week 4 Day 28 综合实战 — 微引擎 2：反思自愈纠错引擎 (Self-Correction Engine)

设计方案：
1. 设计意图：
   当大模型输出的 JSON 无法通过 Pydantic 校验时（字段越界、类型错误、格式损坏等），
   本引擎自动执行以下自愈回路：
   a) 先尝试 Day 24 的脏 JSON 本地容错修复（正则边界提取 + 栈自愈闭合）
   b) 若本地修复后仍无法通过 Pydantic 校验，则提取 ValidationError 的精准报错信息，
      自动组装包含具体错误定位和修正指令的二次纠错 Prompt，发回大模型重试
   c) 循环执行直至校验通过或达到最大纠错轮次

2. 类与函数结构：
   - SelfCorrectionEngine:
     - __init__(llm_client, max_correction_rounds): 注入 LLM 客户端实例和最大纠错轮次
     - async extract_with_correction(resume_text, system_prompt) -> ExtractionResult: 核心自愈循环
     - _try_parse_and_validate(raw_output) -> ResumeInfo | None: 尝试解析与校验，返回实例或 None
     - _build_correction_prompt(raw_output, error_detail) -> list[dict]: 组装自愈纠错消息

3. 关键数据流向：
   resume_text + system_prompt ──→ LLM 初始提取 ──→ _try_parse_and_validate()
     ──→ 成功: 返回 ExtractionResult(self_corrected=False)
     ──→ 失败: _build_correction_prompt() ──→ LLM 二次纠错 ──→ _try_parse_and_validate()
     ──→ 循环至成功或达到 max_correction_rounds
"""

import sys
import os
import re
import json
import logging
from pydantic import ValidationError

# =====================================================================
# 防御性 sys.path 补丁逻辑
# =====================================================================
current_dir = os.path.dirname(os.path.realpath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "../../.."))

if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from weekly.w04_prompt_and_http.project.resume_schema import (
    ResumeInfo, ExtractionResult, format_validation_error
)
from weekly.w04_prompt_and_http.day24.state_tracker import robust_json_parser

logger = logging.getLogger(__name__)


# =====================================================================
# 反思自愈纠错引擎核心实现
# =====================================================================

class SelfCorrectionEngine:
    """
    反思自愈纠错引擎：当大模型输出不合规时，自动组装纠错 Prompt 进行多轮重试。

    核心自愈回路：
    1. LLM 初始提取 → 2. 脏 JSON 本地修复 → 3. Pydantic 校验
    → 4. 校验失败时组装纠错 Prompt → 5. LLM 重新生成 → 重复 2~3
    """

    def __init__(self, llm_client, max_correction_rounds: int = 2):
        """
        参数:
            llm_client: 具有 request_with_retry(messages, temperature) 方法的 LLM 客户端实例
            max_correction_rounds: 最大自愈纠错轮次（不含首次提取）
        """
        self.llm_client = llm_client
        self.max_correction_rounds = max_correction_rounds

    def _strip_thinking_tags(self, text: str) -> str:
        """剥离 Reasoning 模型输出的 <think>...</think> 思考过程标签"""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r"<details>.*?</details>", "", text, flags=re.DOTALL)
        return text.strip()

    def _try_parse_and_validate(self, raw_output: str) -> tuple:
        """
        尝试对 LLM 原始输出进行脏 JSON 修复 + Pydantic 校验。

        返回:
            (ResumeInfo 实例, None) — 成功
            (None, 格式化的错误字符串) — 失败
        """
        # 1. 剥离思考标签
        cleaned = self._strip_thinking_tags(raw_output)

        # 2. 尝试 Day 24 脏 JSON 容错修复
        try:
            parsed_dict = robust_json_parser(cleaned)
        except ValueError as parse_err:
            error_msg = f"脏 JSON 本地修复失败: {parse_err}"
            logger.warning(f"[自愈引擎] {error_msg}")
            return None, error_msg

        # 3. 尝试 Pydantic 校验
        try:
            # 将修复后的字典序列化为 JSON 字符串再用 model_validate_json 校验
            json_str = json.dumps(parsed_dict, ensure_ascii=False)
            resume_info = ResumeInfo.model_validate_json(json_str)
            return resume_info, None
        except ValidationError as ve:
            error_detail = format_validation_error(ve)
            logger.warning(
                f"[自愈引擎] Pydantic 校验失败，共 {ve.error_count()} 个错误:\n{error_detail}"
            )
            return None, error_detail

    def _build_correction_prompt(
        self,
        original_output: str,
        error_detail: str,
        resume_text: str
    ) -> list[dict]:
        """
        组装自愈纠错消息列表，包含原始错误输出、具体报错定位和修正指令。

        参数:
            original_output: 大模型上一轮的原始输出
            error_detail: format_validation_error() 格式化后的精准报错
            resume_text: 原始简历文本（供大模型参考）
        """
        correction_system = (
            "你是一个 JSON 纠错 Agent。上一轮你尝试从简历文本中提取结构化数据，"
            "但输出的 JSON 未能通过 Pydantic 类型校验。\n\n"
            "请根据以下报错信息，修正你的 JSON 输出。"
        )

        correction_user = (
            f"【原始简历文本】\n{resume_text}\n\n"
            f"【你上一轮输出的 JSON（有错误）】\n{original_output}\n\n"
            f"【Pydantic 校验报错详情】\n{error_detail}\n\n"
            f"【修正要求】\n"
            f"1. 请根据上述报错信息，逐一修正每个出错的字段。\n"
            f"2. 你必须且只能输出一个修正后的合法 JSON 字符串。\n"
            f"3. 严禁包含 Markdown 代码块标记、前言、后记或解释性文字。\n"
            f"4. 所有必填字段都必须填写，不能遗漏。\n"
            f"5. 如果某信息在原文中缺失且无法推断，邮箱使用 'unknown@placeholder.com'。"
        )

        return [
            {"role": "system", "content": correction_system},
            {"role": "user", "content": correction_user}
        ]

    async def extract_with_correction(
        self,
        resume_text: str,
        system_prompt: str,
        resume_index: int = 0
    ) -> ExtractionResult:
        """
        核心自愈提取入口：执行首次提取，校验失败时自动发起多轮纠错重试。

        参数:
            resume_text: 原始简历文本
            system_prompt: 渲染后的 System Prompt（含 JSON Schema）
            resume_index: 简历在批次中的序号

        返回:
            ExtractionResult 实例，包含提取结果和自愈元信息
        """
        text_preview = resume_text[:80]

        # ── 首次提取 ──
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"待提取的简历文本：\n{resume_text}"}
        ]

        try:
            raw_output = await self.llm_client.request_with_retry(
                messages, temperature=0.1
            )
        except Exception as e:
            logger.error(f"[自愈引擎] 简历 #{resume_index} 首次 LLM 请求失败: {e}")
            return ExtractionResult(
                resume_index=resume_index,
                original_text=text_preview,
                success=False,
                error_message=f"LLM 请求异常: {type(e).__name__}: {e}"
            )

        logger.info(f"[自愈引擎] 简历 #{resume_index} 首次提取完成，开始校验...")

        # ── 首次校验 ──
        resume_info, error_detail = self._try_parse_and_validate(raw_output)

        if resume_info is not None:
            logger.info(f"[自愈引擎] 简历 #{resume_index} 首次提取校验通过 ✅")
            return ExtractionResult(
                resume_index=resume_index,
                original_text=text_preview,
                success=True,
                resume_data=resume_info,
                self_corrected=False,
                correction_rounds=0
            )

        # ── 自愈纠错循环 ──
        for round_num in range(1, self.max_correction_rounds + 1):
            logger.info(
                f"[自愈引擎] 简历 #{resume_index} 启动第 {round_num} 轮自愈纠错..."
            )

            correction_messages = self._build_correction_prompt(
                original_output=raw_output,
                error_detail=error_detail,
                resume_text=resume_text
            )

            try:
                raw_output = await self.llm_client.request_with_retry(
                    correction_messages, temperature=0.05
                )
            except Exception as e:
                logger.error(
                    f"[自愈引擎] 简历 #{resume_index} 第 {round_num} 轮纠错 LLM 请求失败: {e}"
                )
                return ExtractionResult(
                    resume_index=resume_index,
                    original_text=text_preview,
                    success=False,
                    self_corrected=True,
                    correction_rounds=round_num,
                    error_message=f"纠错轮 LLM 请求异常: {type(e).__name__}: {e}"
                )

            # 纠错后再次校验
            resume_info, error_detail = self._try_parse_and_validate(raw_output)

            if resume_info is not None:
                logger.info(
                    f"[自愈引擎] 简历 #{resume_index} 在第 {round_num} 轮自愈纠错后校验通过 ✅"
                )
                return ExtractionResult(
                    resume_index=resume_index,
                    original_text=text_preview,
                    success=True,
                    resume_data=resume_info,
                    self_corrected=True,
                    correction_rounds=round_num
                )

        # ── 达到最大纠错轮次仍失败 ──
        logger.error(
            f"[自愈引擎] 简历 #{resume_index} 经过 {self.max_correction_rounds} 轮纠错仍失败"
        )
        return ExtractionResult(
            resume_index=resume_index,
            original_text=text_preview,
            success=False,
            self_corrected=True,
            correction_rounds=self.max_correction_rounds,
            error_message=f"最终校验失败: {error_detail}"
        )


# =====================================================================
# 模块自测主入口
# =====================================================================

if __name__ == "__main__":
    import asyncio

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    print("=" * 80)
    print("🚀 Day 28 微引擎 2：反思自愈纠错引擎自测")
    print("=" * 80)

    # 测试 1: _try_parse_and_validate 正常数据
    print("\n[测试 1] 正常 JSON 解析与校验...")
    engine = SelfCorrectionEngine(llm_client=None, max_correction_rounds=2)
    valid_json = json.dumps({
        "name": "测试用户",
        "email": "test@example.com",
        "skills": {"Python": {"level": 80, "years_of_experience": 3.0}},
        "work_experience": [{"company": "测试公司", "position": "开发", "years": 2.0}]
    }, ensure_ascii=False)
    result, error = engine._try_parse_and_validate(valid_json)
    if result:
        print(f"  ✅ 解析校验成功: {result.name}")
    else:
        print(f"  ❌ 解析校验失败: {error}")

    # 测试 2: _try_parse_and_validate 脏 JSON
    print("\n[测试 2] 脏 JSON（含 Markdown 包裹 + 单引号）修复与校验...")
    dirty_json = """```json
{'name': '脏数据', 'email': 'dirty@test.com', 'skills': {'Go': {'level': 70, 'years_of_experience': 2.0}}, 'work_experience': [{'company': '某公司', 'position': '开发', 'years': 1.0}]}
```"""
    result, error = engine._try_parse_and_validate(dirty_json)
    if result:
        print(f"  ✅ 脏 JSON 修复后校验成功: {result.name}")
    else:
        print(f"  ❌ 修复后校验失败: {error}")

    # 测试 3: _try_parse_and_validate 字段越界
    print("\n[测试 3] 字段越界触发 ValidationError...")
    bad_json = json.dumps({
        "name": "越界测试",
        "email": "bad_email",
        "skills": {"Python": {"level": 200, "years_of_experience": -1.0}},
        "work_experience": [{"company": "测试", "position": "开发", "years": -1.0}]
    }, ensure_ascii=False)
    result, error = engine._try_parse_and_validate(bad_json)
    if result is None:
        print(f"  ✅ 正确捕获到校验错误:\n{error}")
    else:
        print(f"  ⚠️ 不应通过校验！")

    # 测试 4: 纠错 Prompt 组装
    print("\n[测试 4] 纠错 Prompt 组装预览...")
    messages = engine._build_correction_prompt(
        original_output=bad_json,
        error_detail=error,
        resume_text="测试简历文本..."
    )
    print(f"  消息数量: {len(messages)}")
    print(f"  System 消息前 100 字符: {messages[0]['content'][:100]}...")
    print(f"  User 消息前 100 字符: {messages[1]['content'][:100]}...")

    print("\n" + "=" * 80)
