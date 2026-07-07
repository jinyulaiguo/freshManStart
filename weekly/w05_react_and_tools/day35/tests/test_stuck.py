"""Test5: StuckDetector 死循环拦截终止验证"""
import pytest
from weekly.w05_react_and_tools.day35.mini_agent.agent.stuck import StuckDetector
from weekly.w05_react_and_tools.day35.mini_agent.schema.exception import StuckException


class TestStuckDetector:
    """StuckDetector 死循环检测核心测试组"""

    def test_no_stuck_with_different_actions(self):
        """测试：不同的 Action 不触发死循环"""
        detector = StuckDetector(window_size=3)
        # 三种不同工具调用，不应触发死循环
        detector.check_and_push("weather", {"city": "北京"})
        detector.check_and_push("calculator", {"expression": "1+1"})
        detector.check_and_push("search", {"query": "Python"})
        # 到达此处说明没有抛出异常

    def test_no_stuck_with_same_action_different_params(self):
        """测试：相同 Action 但参数不同，不触发死循环"""
        detector = StuckDetector(window_size=3)
        detector.check_and_push("weather", {"city": "北京"})
        detector.check_and_push("weather", {"city": "上海"})
        detector.check_and_push("weather", {"city": "杭州"})
        # 参数不同，不应触发

    def test_stuck_detected_after_window_size_repetitions(self):
        """
        核心测试：连续 N 次（window_size=3）相同的 Action + Arguments 触发 StuckException。
        """
        detector = StuckDetector(window_size=3)

        detector.check_and_push("weather", {"city": "北京"})
        detector.check_and_push("weather", {"city": "北京"})

        with pytest.raises(StuckException) as exc_info:
            detector.check_and_push("weather", {"city": "北京"})

        err = exc_info.value
        assert err.action == "weather"
        assert err.window_size == 3
        assert len(err.action_hash) == 32  # MD5 哈希长度

    def test_params_key_order_invariant(self):
        """
        测试：参数 key 乱序但值相同，应被识别为相同调用（哈希一致）。
        {"a": 1, "b": 2} 与 {"b": 2, "a": 1} 应视为相同。
        """
        detector = StuckDetector(window_size=3)
        # 使用不同 key 顺序的参数
        detector.check_and_push("tool", {"a": 1, "b": 2})
        detector.check_and_push("tool", {"b": 2, "a": 1})  # 乱序，但等价

        with pytest.raises(StuckException):
            detector.check_and_push("tool", {"a": 1, "b": 2})

    def test_not_stuck_before_window_is_full(self):
        """测试：窗口未填满时不触发死循环（前 N-1 次不检测）"""
        detector = StuckDetector(window_size=3)
        # 只重复 2 次（window_size - 1），不应触发
        detector.check_and_push("tool", {"x": 1})
        detector.check_and_push("tool", {"x": 1})
        # 第 3 次触发检测，此时会抛出
        with pytest.raises(StuckException):
            detector.check_and_push("tool", {"x": 1})

    def test_window_slides_old_entries_out(self):
        """测试：窗口滑动特性——旧记录被推出后，新的不同调用应通过检测"""
        detector = StuckDetector(window_size=3)
        # 两次相同调用（未满窗口）
        detector.check_and_push("tool", {"x": 1})
        detector.check_and_push("tool", {"x": 1})
        # 插入不同调用，打破窗口内的一致性
        detector.check_and_push("other_tool", {"y": 2})
        # 再次相同调用，但窗口内不再全是相同哈希，不应触发
        detector.check_and_push("tool", {"x": 1})
        # 到达此处说明没有触发（窗口内哈希：tool+x1, other_tool+y2, tool+x1，不一致）

    def test_reset_clears_window(self):
        """测试：reset() 清空滑动窗口，重置后从零开始计数"""
        detector = StuckDetector(window_size=3)
        # 两次相同调用
        detector.check_and_push("tool", {"x": 1})
        detector.check_and_push("tool", {"x": 1})
        # 重置
        detector.reset()
        assert len(detector.window_state) == 0
        # 重置后再调用两次相同 action，不应触发（窗口重新从 0 开始）
        detector.check_and_push("tool", {"x": 1})
        detector.check_and_push("tool", {"x": 1})
        # 还需第 3 次才触发
        with pytest.raises(StuckException):
            detector.check_and_push("tool", {"x": 1})

    def test_window_state_property(self):
        """测试：window_state 属性返回当前窗口内的哈希列表"""
        detector = StuckDetector(window_size=3)
        assert detector.window_state == []

        detector.check_and_push("tool_a", {"x": 1})
        assert len(detector.window_state) == 1

        detector.check_and_push("tool_b", {"y": 2})
        assert len(detector.window_state) == 2

    def test_stuck_exception_contains_correct_info(self):
        """测试：StuckException 包含完整的调试信息（action / hash / window_size）"""
        detector = StuckDetector(window_size=3)

        for _ in range(2):
            detector.check_and_push("search", {"query": "hello"})

        with pytest.raises(StuckException) as exc_info:
            detector.check_and_push("search", {"query": "hello"})

        err = exc_info.value
        assert err.action == "search"
        assert err.window_size == 3
        # 错误消息应包含关键信息
        assert "search" in err.message
        assert "3" in err.message
