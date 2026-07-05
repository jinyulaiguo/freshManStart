"""
Week 4 Day 28 综合实战 — 微引擎 1：简历数据契约层 (Resume Schema)

设计方案：
1. 设计意图：
   为整个简历结构化提取流水线提供统一的 Pydantic 数据模型契约。
   所有从大模型提取的 JSON 必须通过本模块定义的类型校验后，才能进入下游业务逻辑。
   模型的 JSON Schema 会被动态注入到 Jinja2 提示词模板中，约束大模型的输出格式。

2. 类与函数结构：
   - SkillDetail(BaseModel): 单项技能明细，包含熟练度 (1-100) 与使用年限 (≥0) 两个字段级自定义校验器。
   - WorkExperience(BaseModel): 工作经历条目，包含公司名、职位、在职年限。
   - ResumeInfo(BaseModel): 简历主模型，聚合姓名、邮箱(正则校验)、手机号(可选)、技能字典、工作经历列表。
   - ExtractionResult(BaseModel): 单条简历提取结果的封装，携带原始文本、提取成功/失败状态、自愈纠错元信息。
   - format_validation_error(e): 将 Pydantic ValidationError 格式化为大模型可理解的精准报错字符串。

3. 关键数据流向：
   ResumeInfo.model_json_schema() ──→ Jinja2 模板注入 ──→ 大模型输出 JSON ──→
   ResumeInfo.model_validate_json() ──→ 校验通过返回实例 / 校验失败返回 ValidationError ──→
   format_validation_error() ──→ 人类/大模型可读的精准报错字符串
"""

import re
from typing import Dict, Optional
from pydantic import BaseModel, Field, ValidationError, field_validator


# =====================================================================
# 技能明细契约模型
# =====================================================================

class SkillDetail(BaseModel):
    """单项技能明细：熟练度分值 + 使用年限"""
    level: int = Field(..., description="熟练度分值，范围必须在 1 至 100 之间")
    years_of_experience: float = Field(..., description="该技能的使用年限，必须为非负数")

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: int) -> int:
        """自定义校验：熟练度 level 必须在 [1, 100] 闭区间内"""
        if not (1 <= v <= 100):
            raise ValueError(
                f"熟练度分值 ({v}) 越界，合法范围为 [1, 100]。"
                f"请将该值修正为 1 到 100 之间的整数。"
            )
        return v

    @field_validator("years_of_experience")
    @classmethod
    def validate_years(cls, v: float) -> float:
        """自定义校验：使用年限不允许为负数"""
        if v < 0:
            raise ValueError(
                f"使用年限 ({v}) 不合法，必须为非负数 (≥0)。"
                f"请将该值修正为 0 或正数。"
            )
        return v


# =====================================================================
# 工作经历契约模型
# =====================================================================

class WorkExperience(BaseModel):
    """单条工作经历条目"""
    company: str = Field(..., description="公司名称")
    position: str = Field(..., description="担任职位")
    years: float = Field(..., description="在职年限，必须为正数")

    @field_validator("years")
    @classmethod
    def validate_years(cls, v: float) -> float:
        """自定义校验：在职年限必须为正数"""
        if v <= 0:
            raise ValueError(
                f"在职年限 ({v}) 不合法，必须为正数 (>0)。"
                f"请将该值修正为大于 0 的数字。"
            )
        return v


# =====================================================================
# 简历主契约模型
# =====================================================================

class ResumeInfo(BaseModel):
    """简历结构化主模型：聚合个人基础信息、技能树与工作经历"""
    name: str = Field(..., description="候选人姓名")
    email: str = Field(..., description="候选人电子邮箱地址")
    phone: Optional[str] = Field(None, description="候选人手机号码（可选）")
    skills: Dict[str, SkillDetail] = Field(
        ..., description="技能字典，Key 为技能名称，Value 为技能明细对象"
    )
    work_experience: list[WorkExperience] = Field(
        ..., description="工作经历列表，按时间倒序排列"
    )

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """自定义校验：邮箱地址格式正则校验"""
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        if not re.match(pattern, v):
            raise ValueError(
                f"邮箱地址 '{v}' 格式非法，必须符合 xxx@domain.com 格式。"
                f"请修正为合法的电子邮箱地址。"
            )
        return v


# =====================================================================
# 提取结果封装模型
# =====================================================================

class ExtractionResult(BaseModel):
    """单条简历提取结果的封装，携带元信息用于最终统计报告"""
    resume_index: int = Field(..., description="简历在批次中的序号（从 0 开始）")
    original_text: str = Field(..., description="原始简历文本片段（截取前 80 个字符）")
    success: bool = Field(..., description="是否成功提取并通过校验")
    resume_data: Optional[ResumeInfo] = Field(None, description="提取成功时的结构化简历数据")
    self_corrected: bool = Field(False, description="是否经过自愈纠错才通过校验")
    correction_rounds: int = Field(0, description="自愈纠错经过的轮数")
    error_message: Optional[str] = Field(None, description="提取失败时的错误信息")
    breaker_tripped: bool = Field(False, description="是否被熔断器拦截")


# =====================================================================
# ValidationError 格式化引擎
# =====================================================================

def format_validation_error(e: ValidationError) -> str:
    """
    将 Pydantic ValidationError 中的结构化报错明细转化为大模型可理解的精准纠错指令。

    格式化后的字符串包含：
    - 字段路径（多级嵌套用 -> 分隔）
    - 具体报错原因
    - 触发错误的原始输入值
    - 错误类型代码

    该字符串会被直接拼装进自愈纠错 Prompt 发回给大模型，
    因此错误消息必须对大模型足够清晰、可操作。
    """
    error_reports = []

    for idx, err in enumerate(e.errors()):
        # 1. 组装多级嵌套字段路径 (例如: skills -> Python -> level)
        loc_path = " -> ".join(map(str, err.get("loc", [])))

        # 2. 提取报错消息
        msg = err.get("msg", "Unknown validation error")

        # 3. 提取触发错误的原始输入值
        raw_input = err.get("input", "N/A")

        # 4. 提取错误类型代码
        err_type = err.get("type", "N/A")

        report = (
            f"错误 #{idx + 1}:\n"
            f"  字段路径: {loc_path}\n"
            f"  报错原因: {msg}\n"
            f"  错误代码: {err_type}\n"
            f"  原始输入: {raw_input}"
        )
        error_reports.append(report)

    return "\n\n".join(error_reports)


# =====================================================================
# 模块自测主入口
# =====================================================================

if __name__ == "__main__":
    import json

    print("=" * 80)
    print("🚀 Day 28 微引擎 1：简历数据契约层自测")
    print("=" * 80)

    # 测试 1: 正常数据实例化
    print("\n[测试 1] 正常数据实例化...")
    valid_data = {
        "name": "周易",
        "email": "zhouyi@example.com",
        "phone": "13800138000",
        "skills": {
            "Python": {"level": 95, "years_of_experience": 5.5},
            "Go": {"level": 80, "years_of_experience": 2.0}
        },
        "work_experience": [
            {"company": "某科技公司", "position": "高级工程师", "years": 3.0},
            {"company": "某创业公司", "position": "后端开发", "years": 2.5}
        ]
    }
    try:
        resume = ResumeInfo.model_validate(valid_data)
        print(f"  ✅ 实例化成功: {resume.name}, 技能数: {len(resume.skills)}, 经历数: {len(resume.work_experience)}")
    except ValidationError as ve:
        print(f"  ❌ 实例化失败: {ve}")

    # 测试 2: JSON Schema 导出
    print("\n[测试 2] JSON Schema 导出...")
    schema = ResumeInfo.model_json_schema()
    print(f"  Schema 字段数: {len(schema.get('properties', {}))}")
    print(f"  Schema 预览 (前 200 字符): {json.dumps(schema, ensure_ascii=False)[:200]}...")

    # 测试 3: 脏数据触发 ValidationError
    print("\n[测试 3] 脏数据触发 ValidationError...")
    bad_data = {
        "name": "测试员",
        "email": "bad_email_no_at",
        "skills": {
            "Python": {"level": 150, "years_of_experience": -2.0}
        },
        "work_experience": [
            {"company": "某公司", "position": "开发", "years": -1.0}
        ]
    }
    try:
        ResumeInfo.model_validate(bad_data)
        print("  ⚠️ 脏数据居然通过了校验！")
    except ValidationError as ve:
        formatted = format_validation_error(ve)
        print(f"  ✅ 捕获到 {ve.error_count()} 个校验错误:")
        print(formatted)

    print("\n" + "=" * 80)
