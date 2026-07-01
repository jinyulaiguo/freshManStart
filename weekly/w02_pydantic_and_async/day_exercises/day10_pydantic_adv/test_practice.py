"""
================================================================================
设计方案 (Design Specification)
================================================================================
设计意图:
    本模块为学员练习模版 `practice.py` 的测试用例。学员完成 `practice.py` 后，
    运行此测试以验证其实现的校验行为是否符合预期。
================================================================================
"""

import pytest
from pydantic import ValidationError
from weekly.w02_pydantic_and_async.day_exercises.day10_pydantic_adv.practice import UserDataclass, UserPydantic

def test_dataclass_behavior():
    # 即使类型标注为 int，传入 str 也能成功实例化，不抛出异常
    user = UserDataclass(username="alice", email="alice@example.com", age="eighteen") # type: ignore
    assert user.age == "eighteen"

def test_pydantic_type_validation():
    with pytest.raises(ValidationError) as exc_info:
        UserPydantic(username="alice", email="alice@example.com", age="eighteen")
    assert "Input should be a valid integer" in str(exc_info.value)

def test_pydantic_field_validation():
    with pytest.raises(ValidationError) as exc_info:
        UserPydantic(username="alice", email="invalid_email", age=20)
    assert "Email format is invalid" in str(exc_info.value)

def test_pydantic_model_validation():
    with pytest.raises(ValidationError) as exc_info:
        UserPydantic(username="bob", email="bob@example.com", age=16, parental_consent=False)
    assert "Minors under 18 must have parental consent" in str(exc_info.value)

    user = UserPydantic(username="bob", email="bob@example.com", age=16, parental_consent=True)
    assert user.age == 16
    assert user.parental_consent is True

def test_pydantic_valid_construction():
    user = UserPydantic(username="charlie", email="charlie@example.com", age="25")
    assert user.age == 25
    assert isinstance(user.age, int)
