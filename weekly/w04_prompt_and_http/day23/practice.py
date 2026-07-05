"""
Week 4 Day 23 练习模板：大模型原生结构化输出（Structured Outputs）与 Pydantic 运行时类型契约校验

设计方案：
1. 设计意图：
   通过 Pydantic 声明强类型契约模型，用于拦截并校验大模型输出的 JSON 参数。
   学员将学习：
   - 如何通过 Pydantic 定义多层嵌套的数据模型（UserInfo 与 SkillDetail）。
   - 如何使用 @field_validator 编写自定义的字段级业务校验规则（邮箱格式、数值范围）。
   - 如何提取 Pydantic 抛出的 ValidationError 中的结构化元数据（loc 与 msg），进行防御性拦截与报错展示。
   - 如何结合大模型输出 JSON 格式文本，并通过契约模型进行运行时转化。

2. 类与函数结构：
   - SkillDetail: 嵌套模型，包含熟练度校验。
   - UserInfo: 根模型，包含邮箱校验与嵌套技能字典。
   - StructuredLLMClient: 结构化请求客户端，继承自公共 BaseLLMClient。
     - request_structured_user_info(prompt: str) -> UserInfo: 请求 LLM 并校验转换。
   - format_validation_error(e: ValidationError) -> str: 格式化校验报错。

3. 关键数据流向：
   用户 Query ──> StructuredLLMClient ──> 发送包含 JSON Schema 约束的 Prompt ──> 
   获取大模型原始 JSON ──> UserInfo.model_validate_json() ──> 
   [成功] ──> 返回 UserInfo 实例
   [失败] ──> 抛出 ValidationError ──> format_validation_error() ──> 提取越界报错细节。
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

import json
import re
from typing import Dict
from pydantic import BaseModel, Field, ValidationError, field_validator

# 导入公共工具基类
from weekly.w04_prompt_and_http.utils import LLMClient as BaseLLMClient


# =====================================================================
# Pydantic 边界契约模型声明
# =====================================================================

class SkillDetail(BaseModel):
    """嵌套技能明细模型"""
    level: int = Field(..., description="熟练度分值，范围必须在 1 至 100 之间")
    years_of_experience: float = Field(..., description="技能使用年限，必须为正数")

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: int) -> int:
        """自定义校验：熟练度 level 必须在 1 到 100 之间"""
        # TODO: 校验 v 是否在 [1, 100] 范围内，越界则抛出 ValueError
        raise NotImplementedError("TODO: 实现技能熟练度校验")


class UserInfo(BaseModel):
    """根用户信息强类型契约模型"""
    name: str = Field(..., description="用户姓名")
    email: str = Field(..., description="用户的电子邮箱")
    skills: Dict[str, SkillDetail] = Field(..., description="技能字典，Key 为技能名称，Value 为技能明细")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """自定义校验：简单邮箱格式正则校验"""
        # TODO: 使用正则表达式校验 v 是否是合法的邮箱格式（必须包含 @ 和域名后缀），非法则抛出 ValueError
        raise NotImplementedError("TODO: 实现邮箱格式校验")


# =====================================================================
# 结构化请求客户端与异常格式化引擎
# =====================================================================

class StructuredLLMClient(BaseLLMClient):
    """支持结构化输出校验的大模型客户端"""

    async def request_structured_user_info(self, user_description: str) -> UserInfo:
        """
        请求大模型抽取结构化用户信息，并通过 UserInfo 进行运行时类型契约校验。
        """
        # TODO: 1. 获取 UserInfo 模型的 JSON Schema，并将其作为系统提示词的一部分告知大模型
        #          提示词中需明确要求模型仅输出符合该 JSON Schema 的合法 JSON 字符串，严禁包含 markdown 标记
        # TODO: 2. 构造 messages 并调用父类的 self.request_llm()
        # TODO: 3. 使用 UserInfo.model_validate_json() 校验并实例化，最后返回 UserInfo 实例
        raise NotImplementedError("TODO: 实现结构化输出抽取与校验")


def format_validation_error(e: ValidationError) -> str:
    """
    格式化捕获到的 Pydantic 校验错误，将其转化为人类易读的越界报错分析。
    格式要求：
    - 需展示发生错误的字段路径（例如: skills -> python -> level）
    - 需展示报错的具体原因（msg）
    - 需展示导致校验失败的原始输入值（input）
    """
    # TODO: 循环遍历 e.errors()，精确定位字段路径 loc，提取 msg 与 input 字段，组装成清晰的控制台报错信息
    raise NotImplementedError("TODO: 实现 ValidationError 格式化引擎")


# =====================================================================
# 练习用例与运行入口 (带 TODO 拦截提示)
# =====================================================================

if __name__ == "__main__":
    print("=== Week 4 Day 23 结构化数据类型契约练习 (已引入公共工具) ===")
    
    # 初始化客户端
    try:
        client = StructuredLLMClient()
    except Exception as e:
        print(f"❌ 客户端初始化失败: {e}")
        import sys
        sys.exit(1)

    async def run_practice():
        user_description = "我的名字叫周易，我的常用邮箱是 zhouyi@example.com。我精通 Python，熟练度达到了 95 分，已经用了 5.5 年；另外我还懂 Go 语言，熟练度 80 分，开发过 2 年。"
        
        # 1. 正常数据提取流测试
        try:
            print("\n[测试点 1] 运行真实大模型进行结构化字段提取...")
            user_info = await client.request_structured_user_info(user_description)
            print(f"✅ 提取并校验成功！")
            print(f"姓名: {user_info.name}")
            print(f"邮箱: {user_info.email}")
            print(f"技能明细: {user_info.skills}")
        except NotImplementedError as ne:
            print(f"❌ 测试点 1 拦截: {ne}")
        except Exception as ex:
            print(f"❌ 测试点 1 发生非预期错误: {ex}")

        # 2. 脏数据拦截与 ValidationError 格式化测试
        try:
            print("\n[测试点 2] 故意构造不合法的 JSON 触发校验异常...")
            bad_json = """
            {
                "name": "测试用户",
                "email": "invalid-email-format",
                "skills": {
                    "Python": {
                        "level": 150,
                        "years_of_experience": -1.0
                    }
                }
            }
            """
            print("正在解析脏 JSON 数据...")
            UserInfo.model_validate_json(bad_json)
            print("⚠️ 警告: 脏 JSON 居然通过了校验！这不符合预期！")
        except ValidationError as ve:
            print("✅ 成功捕获 ValidationError，准备运行格式化引擎...")
            try:
                formatted_err = format_validation_error(ve)
                print("\n=== 格式化越界报错详情 ===")
                print(formatted_err)
                print("===========================")
            except NotImplementedError as ne:
                print(f"❌ 测试点 2 拦截: {ne}")
        except NotImplementedError as ne:
            print(f"❌ 测试点 2 拦截: {ne}")

    import asyncio
    asyncio.run(run_practice())
