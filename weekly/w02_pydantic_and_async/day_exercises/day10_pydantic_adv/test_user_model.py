"""
================================================================================
设计方案 (Design Specification)
================================================================================
设计意图:
    本模块为 `user_model.py` 的单元测试套件，通过 pytest 验证 Dataclass 与 Pydantic
    在面对非法类型、违反字段约束以及违反模型关联约束时的差异性行为。

测试结构:
    1. test_dataclass_behavior: 验证 dataclass 不做运行时类型拦截。
    2. test_pydantic_type_validation: 验证 Pydantic 的自动类型转换与非法类型拦截。
    3. test_pydantic_field_validation: 验证 Pydantic 的 field_validator 拦截逻辑（email 校验）。
    4. test_pydantic_model_validation: 验证 Pydantic 的 model_validator 联合拦截逻辑（未成年人监护人同意校验）。
    5. test_pydantic_valid_construction: 验证正确数据输入时，Pydantic 正确实例化且完成类型强制转换。
================================================================================
"""

import pytest
from pydantic import ValidationError
from weekly.w02_pydantic_and_async.day_exercises.day10_pydantic_adv.user_model import UserDataclass, UserPydantic

def test_dataclass_behavior():
    """
    验证标准库 dataclass 在面临错误类型输入时默许通过（无运行时拦截）。
    """
    # 即使类型标注为 int，传入 str 也能成功实例化，不抛出异常
    user = UserDataclass(username="alice", email="alice@example.com", age="eighteen") # type: ignore
    assert user.age == "eighteen"

def test_pydantic_type_validation():
    """
    验证 Pydantic BaseModel 会进行运行时类型校验，非法类型会抛出 ValidationError。
    """
    with pytest.raises(ValidationError) as exc_info:
        UserPydantic(username="alice", email="alice@example.com", age="eighteen")
    assert "Input should be a valid integer" in str(exc_info.value)

def test_pydantic_field_validation():
    """
    验证 Pydantic 的 @field_validator 能够拦截非法 email 格式。
    """
    with pytest.raises(ValidationError) as exc_info:
        UserPydantic(username="alice", email="invalid_email", age=20)
    assert "Email format is invalid" in str(exc_info.value)

def test_pydantic_model_validation():
    """
    验证 Pydantic 的 @model_validator 联合校验器能够校验多字段关联逻辑。
    """
    # 未成年人未获家长同意，应该拦截
    with pytest.raises(ValidationError) as exc_info:
        UserPydantic(username="bob", email="bob@example.com", age=16, parental_consent=False)
    assert "Minors under 18 must have parental consent" in str(exc_info.value)

    # 未成年人获得家长同意，应该通过
    user = UserPydantic(username="bob", email="bob@example.com", age=16, parental_consent=True)
    assert user.age == 16
    assert user.parental_consent is True

def test_pydantic_valid_construction():
    """
    验证合法输入能够成功创建模型，且 Pydantic 能够进行自动类型强转（Coercion）。
    """
    # 传入字符串 "25"，会被 Pydantic 自动转换为整数 25
    user = UserPydantic(username="charlie", email="charlie@example.com", age="25")
    assert user.age == 25
    assert isinstance(user.age, int)
