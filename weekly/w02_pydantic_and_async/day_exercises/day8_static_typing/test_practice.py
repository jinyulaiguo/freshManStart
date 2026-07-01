import pytest
from weekly.w02_pydantic_and_async.day_exercises.day8_static_typing.practice import (
    AgentState,
    StateTracker,
    merge_messages,
    add_message,
    update_tool,
)

def test_reducer_merge():
    # 测试常规合并
    old = ["A"]
    new = ["B"]
    assert merge_messages(old, new) == ["A", "B"]
    
    # 测试防御型类型检查
    with pytest.raises(TypeError):
        merge_messages("not a list", ["B"])  # type: ignore

def test_state_tracker_basic():
    initial_state = {
        "current_tool": "none",
        "steps": 0,
        "messages": ["Init"]
    }
    
    tracker = StateTracker(AgentState, initial_state)
    assert tracker.state["current_tool"] == "none"
    assert tracker.state["steps"] == 0
    assert tracker.state["messages"] == ["Init"]

def test_state_tracker_reduction():
    initial_state = {
        "current_tool": "none",
        "steps": 0,
        "messages": ["Init"]
    }
    tracker = StateTracker(AgentState, initial_state)
    
    # 更新没有 Reducer 的字段（覆盖）
    tracker.update({"current_tool": "calculator"})
    assert tracker.state["current_tool"] == "calculator"
    
    # 更新带有 Reducer 的字段（归约合并）
    tracker.update({"messages": ["Run Step 1"]})
    assert tracker.state["messages"] == ["Init", "Run Step 1"]
    
    # 连续更新
    tracker.update({"messages": ["Run Step 2"]})
    assert tracker.state["messages"] == ["Init", "Run Step 1", "Run Step 2"]

def test_state_tracker_invalid_key():
    initial_state = {
        "current_tool": "none",
        "steps": 0,
        "messages": ["Init"]
    }
    tracker = StateTracker(AgentState, initial_state)
    
    # 写入未定义字段，应触发 KeyError 拦截
    with pytest.raises(KeyError):
        tracker.update({"invalid_key": 123})
