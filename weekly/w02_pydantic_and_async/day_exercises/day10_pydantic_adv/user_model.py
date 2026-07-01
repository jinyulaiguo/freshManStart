"""
================================================================================
设计方案 (Design Specification)
================================================================================
设计意图:
    本模块旨在对比 Python 标准库的 `dataclass` 与 Pydantic 的 `BaseModel` 在运行时数据校验上的差异。
    通过定义相同的用户数据契约，演示 Pydantic 强大的字段级校验（field_validator）与模型级校验（model_validator）能力。

类与函数结构:
    1. UserDataclass (class): 基于 dataclasses.dataclass 实现的数据容器，定义了 username, email, age, parental_consent 字段。
    2. UserPydantic (class): 基于 pydantic.BaseModel 实现的校验模型，定义了相同的字段。
        - check_email (field_validator): 拦截校验 email 字段是否包含 '@'。
        - check_parental_consent (model_validator): 拦截校验若年龄小于 18 岁时，parental_consent 必须为 True。

关键数据流流向:
    - 实例化 UserDataclass -> 直接绑定属性值（无运行时校验拦截）。
    - 实例化 UserPydantic -> 触发属性类型检查 -> 触发 field_validator -> 触发 model_validator -> 实例化成功或抛出 ValidationError。
================================================================================
"""

from dataclasses import dataclass
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Self

# ================================================================================
# 方案 A: 标准库 Dataclass 实现 (轻量级数据容器，无运行时自动拦截校验)
# ================================================================================

@dataclass
class UserDataclass:
    username: str
    email: str
    age: int
    parental_consent: bool = False


# ================================================================================
# 方案 B: Pydantic BaseModel 实现 (运行时强契约校验，自动数据转换与拦截)
# ================================================================================

class UserPydantic(BaseModel):
    username: str = Field(..., description="用户名")
    email: str = Field(..., description="用户邮箱")
    age: int = Field(..., description="用户年龄")
    parental_consent: bool = Field(default=False, description="是否获得家长同意")

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        """
        字段级校验器：拦截 email 字段的输入值，执行初步的格式契约校验。
        """
        if "@" not in v:
            raise ValueError("Email format is invalid, must contain '@'")
        return v

    @model_validator(mode="after")
    def check_parental_consent(self) -> Self:
        """
        模型级联合校验器：在各字段完成独立校验后，执行多字段关联逻辑约束。
        约束条件：若用户年龄未满 18 岁，则必须获得家长同意（parental_consent=True）。
        """
        if self.age < 18 and not self.parental_consent:
            raise ValueError("Minors under 18 must have parental consent to register")
        return self
