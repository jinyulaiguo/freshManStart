"""
Week 4 Day 23 参考答案：大模型原生结构化输出（Structured Outputs）与 Pydantic 运行时类型契约校验

设计方案：
1. 设计意图：
   本代码演示了大模型与 Python 类型契约（Pydantic）结合的完整闭环：
   - 方案一：真实大模型结构化提取。将 Pydantic 自动生成的 JSON Schema 动态注入 System Prompt，强制大模型以纯 JSON 形式回复，并在 Python 端进行类型校验与反序列化，构建强类型的 UserInfo 实例。
   - 方案二：脏数据拦截与 ValidationError 精准解析。故意设计一个不合规的 JSON 数据结构输入 Pydantic，主动触发运行时类型校验异常，并手写格式化引擎还原出多级嵌套的错误路径 loc、具体原因与对应脏值，实现对错误边界的防御性编程。

2. 类与函数结构：
   - 方案一与方案二完全物理隔离，包含有意识的冗余设计，各自声明独立的 Schema 模型。
   - 方案一模块：
     - SkillDetailSchema1: 方案一技能明细 Pydantic 契约模型。
     - UserInfoSchema1: 方案一用户信息 Pydantic 契约模型。
     - StructuredLLMClient: 方案一结构化输出大模型客户端。
   - 方案二模块：
     - SkillDetailSchema2: 方案二技能明细 Pydantic 契约模型。
     - UserInfoSchema2: 方案二用户信息 Pydantic 契约模型。
     - format_validation_error: 方案二专用 ValidationError 格式化分析引擎。

3. 关键数据流向：
   - 方案一：描述文本 ──> StructuredLLMClient.request_structured_user_info() ──> Pydantic Schema 转换成 JSON Schema ──> 大模型 ──> 纯 JSON 文本 ──> UserInfoSchema1.model_validate_json() ──> 强类型 UserInfoSchema1 实例。
   - 方案二：脏 JSON 字符串 ──> UserInfoSchema2.model_validate_json() ──> 抛出 ValidationError ──> format_validation_error() ──> 格式化输出报错详情。
"""

import sys
import os

# =====================================================================
# 防御性 sys.path 补丁逻辑 (防止跨层级目录执行时发生 ModuleNotFoundError)
# =====================================================================
# current_dir: weekly/w04_prompt_and_http/day23
# .. -> weekly/w04_prompt_and_http
# ../.. -> weekly
# ../../../ -> 03.freshManStart (工作区根目录)
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "../../.."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import asyncio
import json
import re
from typing import Dict
from pydantic import BaseModel, Field, ValidationError, field_validator

# 导入公共工具基类
from weekly.w04_prompt_and_http.utils import LLMClient as BaseLLMClient


# =====================================================================
# ⚡ 方案一：真实大模型结构化提取与 Pydantic 类型契约校验 (物理隔离版)
# =====================================================================

class SkillDetailSchema1(BaseModel):
    """方案一：嵌套技能明细契约模型"""
    level: int = Field(..., description="熟练度分值，范围必须在 1 至 100 之间")
    years_of_experience: float = Field(..., description="技能使用年限，必须为正数")

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: int) -> int:
        """自定义校验：熟练度 level 必须在 1 到 100 之间"""
        if not (1 <= v <= 100):
            raise ValueError(f"熟练度分值 ({v}) 越界，合法的范围应在 [1, 100] 之间")
        return v


class UserInfoSchema1(BaseModel):
    """方案一：用户信息主契约模型"""
    name: str = Field(..., description="用户姓名")
    email: str = Field(..., description="用户的电子邮箱")
    skills: Dict[str, SkillDetailSchema1] = Field(..., description="技能字典，Key 为技能名称，Value 为技能明细")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """自定义校验：简单邮箱格式正则校验"""
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        if not re.match(pattern, v):
            raise ValueError(f"邮箱地址格式 ({v}) 非法，必须包含 '@' 符号及域名后缀")
        return v


class StructuredLLMClient(BaseLLMClient):
    """方案一专属：支持结构化输出校验的大模型客户端"""

    async def request_structured_user_info(self, user_description: str) -> UserInfoSchema1:
        """
        请求大模型抽取结构化用户信息，并自动完成 JSON Schema 校验转化
        """
        # 1. 动态获取 Pydantic 的 JSON Schema 定义，作为系统 Prompt 注入
        schema_dict = UserInfoSchema1.model_json_schema()
        
        system_prompt = (
            "你是一个高精度的数据抽取 Agent。你的任务是从用户的描述文本中，准确地抽取用户信息，并以 JSON 格式输出。\n"
            f"你输出的 JSON 字符串必须严格符合以下 JSON Schema 契约定义：\n"
            f"{json.dumps(schema_dict, ensure_ascii=False)}\n\n"
            "【输出限制】\n"
            "- 必须且只能输出一个合法的 JSON 字符串。\n"
            "- 严禁包含 ```json 等 Markdown 代码块标记，不要有任何前言、后记或解释性文字。\n"
            "- 必须输出完整的必填字段，不能遗漏。"
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"需要抽取的描述文本如下：\n{user_description}"}
        ]
        
        # 2. 调用底层基类的异步请求方法
        raw_response = await self.request_llm(messages, temperature=0.1, max_tokens=1000)
        
        # 防御性清洗大模型输出，排除 <think> 思考标签和 Markdown 包裹，并定位最外层大括号
        cleaned_json = raw_response.strip()
        
        # 1. 剥离 <think>...</think> 推理内容
        if "<think>" in cleaned_json and "</think>" in cleaned_json:
            cleaned_json = cleaned_json.split("</think>")[-1].strip()
            
        # 2. 剥离 Markdown 包裹
        if cleaned_json.startswith("```"):
            cleaned_json = re.sub(r"^```[a-zA-Z0-9]*\n", "", cleaned_json)
            cleaned_json = re.sub(r"\n```$", "", cleaned_json)
            cleaned_json = cleaned_json.strip()
            
        # 3. 通过正则提取最外层大括号包裹的完整 JSON (DOTALL 匹配换行)
        json_match = re.search(r"(\{.*\})", cleaned_json, re.DOTALL)
        if json_match:
            cleaned_json = json_match.group(1)
            
        # 3. 运行时进行强类型契约校验并实例化
        try:
            user_info = UserInfoSchema1.model_validate_json(cleaned_json)
            return user_info
        except ValidationError as ve:
            print(f"[❌ Schema 校验失败] 模型输出的 JSON 不合规。原始输出: {raw_response}")
            raise ve


async def run_scheme_one():
    """方案一的执行入口"""
    print("\n" + "="*30 + " 方案一：大模型结构化抽取测试 " + "="*30)
    
    # 模拟真实履历描述文本
    user_description = (
        "你好，我叫周易，我平时的工作邮箱是 zhouyi@example.com。我主要的技术栈是 Python，"
        "目前已经开发了 5.5 年，熟练度自我评估有 95 分。另外我还懂 Go 语言，有 2 年的开发经验，熟练度为 80 分。"
    )
    
    try:
        client = StructuredLLMClient()
        print(f"输入文本: {user_description}\n")
        print("正在向大模型发起结构化抽取请求...")
        user_info = await client.request_structured_user_info(user_description)
        
        print("\n🎉 结构化抽取校验成功！")
        print(f"姓名: {user_info.name} (类型: {type(user_info.name)})")
        print(f"邮箱: {user_info.email} (类型: {type(user_info.email)})")
        print("拥有的技能:")
        for skill_name, detail in user_info.skills.items():
            print(f" - {skill_name}: 熟练度 = {detail.level} 分, 经验 = {detail.years_of_experience} 年")
            
    except Exception as e:
        print(f"❌ 方案一运行中发生异常: {e}")


# =====================================================================
# ⚡ 方案二：脏数据拦截与 ValidationError 高精度解析 (物理隔离版)
# =====================================================================

class SkillDetailSchema2(BaseModel):
    """方案二：嵌套技能明细契约模型 (故意保留重复以保证 100% 物理隔离与自包含)"""
    level: int = Field(..., description="熟练度分值，范围必须在 1 至 100 之间")
    years_of_experience: float = Field(..., description="技能使用年限，必须为正数")

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: int) -> int:
        if not (1 <= v <= 100):
            raise ValueError(f"熟练度分值 ({v}) 越界，合法的范围应在 [1, 100] 之间")
        return v


class UserInfoSchema2(BaseModel):
    """方案二：用户信息主契约模型 (故意保留重复以保证 100% 物理隔离与自包含)"""
    name: str = Field(..., description="用户姓名")
    email: str = Field(..., description="用户的电子邮箱")
    skills: Dict[str, SkillDetailSchema2] = Field(..., description="技能字典，Key 为技能名称，Value 为技能明细")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        if not re.match(pattern, v):
            raise ValueError(f"邮箱地址格式 ({v}) 非法，必须包含 '@' 符号及域名后缀")
        return v


def format_validation_error(e: ValidationError) -> str:
    """
    方案二专属：将 ValidationError 里的结构化报错明细转化为人类易读的格式化报告
    """
    error_reports = []
    
    # e.errors() 返回一个包含所有错误明细的列表
    for idx, err in enumerate(e.errors()):
        # 1. 组装字段的多级嵌套路径 (例如 skills -> python -> level)
        loc_path = " -> ".join(map(str, err.get("loc", [])))
        
        # 2. 提取报错信息
        msg = err.get("msg", "Unknown validation error")
        
        # 3. 提取发生错误的原始输入值
        raw_input = err.get("input", "N/A")
        
        # 4. 提取错误类别代码
        err_type = err.get("type", "N/A")
        
        report = (
            f"错误 #{idx + 1}:\n"
            f"  📍 字段路径: {loc_path}\n"
            f"  🔍 报错原因: {msg}\n"
            f"  🏷️ 错误代码: {err_type}\n"
            f"  📥 原始输入: {raw_input}"
        )
        error_reports.append(report)
        
    return "\n\n".join(error_reports)


def run_scheme_two():
    """方案二的执行入口：脏数据拦截与精准报错格式化"""
    print("\n" + "="*30 + " 方案二：脏数据拦截与异常格式化测试 " + "="*30)
    
    # 构造一个充满非法脏字段的 JSON，用以触发多层校验拦截
    bad_user_json = """
    {
        "name": "脏数据测试员",
        "email": "bad_email_at_gmail_dot_com",
        "skills": {
            "Python": {
                "level": 180,
                "years_of_experience": -2.5
            },
            "Golang": {
                "level": 0,
                "years_of_experience": 1.5
            }
        }
    }
    """
    
    print("输入脏 JSON 数据串:")
    print(bad_user_json.strip())
    print("\n正在启动 Pydantic 类型契约进行安全校验拦截...")
    
    try:
        # 执行运行时校验
        UserInfoSchema2.model_validate_json(bad_user_json)
        print("⚠️ 警告：脏 JSON 数据居然通过了校验！这不符合预期！")
    except ValidationError as ve:
        print("✅ 校验拦截成功！数据已被安全截断，捕获到 ValidationError。")
        print("正在调用 format_validation_error() 格式化报错分析:")
        
        formatted_err = format_validation_error(ve)
        
        print("\n" + "*"*20 + " 格式化越界报错详情 " + "*"*20)
        print(formatted_err)
        print("*"*60)


# =====================================================================
# 主运行控制器
# =====================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("🚀 Week 4 Day 23 结构化输出与 Pydantic 边界契约参考答案运行入口")
    print("=" * 80)
    
    # 方案一：真实大模型结构化请求
    asyncio.run(run_scheme_one())
    
    print("\n" + "-" * 80)
    
    # 方案二：纯异常拦截与精细化格式解析
    run_scheme_two()
    
    print("\n" + "=" * 80)
