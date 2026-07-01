"""
================================================================================
设计方案 (Design Specification)
================================================================================
设计意图:
    本模块为学员练习模版，用于实现 `UserDataclass` 和 `UserPydantic` 的定义。
    学员需要完成 Dataclass 的结构定义，以及 Pydantic 模型的字段级校验与模型级校验逻辑。

类与函数结构:
    1. UserDataclass (class): 基于 dataclasses.dataclass 实现的数据容器。
    2. UserPydantic (class): 基于 pydantic.BaseModel 实现的校验模型。
        - check_email (field_validator): 拦截校验 email 字段是否包含 '@'。
        - check_parental_consent (model_validator): 拦截校验若年龄小于 18 岁时，parental_consent 必须为 True。
================================================================================
"""

from dataclasses import dataclass
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Self

# ================================================================================
# 方案 A: 标准库 Dataclass 实现 (轻量级数据容器，无运行时自动拦截校验)
# ================================================================================

# TODO: 请使用 @dataclass 装饰器定义 UserDataclass，并包含：
# - username: str
# - email: str
# - age: int
# - parental_consent: bool (默认为 False)
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

    # TODO: 请在此处定义字段 (username, email, age, parental_consent)，使用 Field 加上描述
    username: str = Field(..., description="用户名")
    email: str = Field(..., description="邮箱")
    age: int = Field(..., description="年龄")
    parental_consent: bool = Field(default=False, description="家长同意")

    # TODO: 请使用 @field_validator 装饰器实现 check_email，校验 email 必须包含 '@'
    # 校验失败抛出 ValueError
    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("Email format is invalid, must contain '@'")
        return v

    # TODO: 请使用 @model_validator(mode="after") 装饰器实现 check_parental_consent
    # 校验未成年人（age < 18）必须有监护人同意（parental_consent 为 True），否则抛出 ValueError
    @model_validator(mode="after")
    def check_parental_consent(self) -> Self:
        if self.age < 18 and not self.parental_consent:
            raise ValueError("Minors under 18 must have parental consent to register")
        return self