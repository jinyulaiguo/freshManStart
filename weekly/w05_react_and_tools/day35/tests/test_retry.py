"""Test4: RetryManager Self-Correction 自愈机制验证"""
import pytest
import asyncio
from weekly.w05_react_and_tools.day35.mini_agent.agent.retry import RetryManager
from weekly.w05_react_and_tools.day35.mini_agent.schema.exception import RetryExceededException


class TestRetryManager:
    """RetryManager 重试预算管理核心测试组"""

    def test_initial_state(self):
        """测试：初始状态重试次数为 0，can_retry 返回 True"""
        rm = RetryManager(max_retries=3)
        assert rm.retry_count == 0
        assert rm.can_retry() is True

    def test_record_retry_increments_count(self):
        """测试：record_retry 消耗一次预算，retry_count 递增"""
        rm = RetryManager(max_retries=3)
        rm.record_retry()
        assert rm.retry_count == 1
        assert rm.can_retry() is True

        rm.record_retry()
        assert rm.retry_count == 2
        assert rm.can_retry() is True

    def test_can_retry_false_when_budget_exhausted(self):
        """测试：重试次数达到 max_retries 后，can_retry 返回 False"""
        rm = RetryManager(max_retries=2)
        rm.record_retry()
        rm.record_retry()
        assert rm.can_retry() is False

    def test_record_retry_raises_when_exceeded(self):
        """测试：超出 max_retries 后调用 record_retry 抛出 RetryExceededException"""
        rm = RetryManager(max_retries=2)
        rm.record_retry()
        rm.record_retry()
        with pytest.raises(RetryExceededException) as exc_info:
            rm.record_retry()

        assert exc_info.value.max_retries == 2

    def test_reset_clears_count(self):
        """测试：工具成功后调用 reset()，retry_count 归零"""
        rm = RetryManager(max_retries=3)
        rm.record_retry()
        rm.record_retry()
        assert rm.retry_count == 2

        rm.reset()
        assert rm.retry_count == 0
        assert rm.can_retry() is True

    def test_backoff_delay_increases_exponentially(self):
        """测试：退避延迟随重试次数指数增长"""
        rm = RetryManager(max_retries=5, backoff_base=1.0)

        assert rm.backoff_delay == 0.0  # 第 0 次重试前无延迟

        rm.record_retry()
        assert rm.backoff_delay == 1.0  # 2^0 * 1.0 = 1.0s

        rm.record_retry()
        assert rm.backoff_delay == 2.0  # 2^1 * 1.0 = 2.0s

        rm.record_retry()
        assert rm.backoff_delay == 4.0  # 2^2 * 1.0 = 4.0s

    def test_backoff_zero_with_zero_base(self):
        """测试：backoff_base=0 时退避延迟始终为 0（禁用退避）"""
        rm = RetryManager(max_retries=3, backoff_base=0.0)
        rm.record_retry()
        assert rm.backoff_delay == 0.0

    def test_wait_backoff_no_blocking_when_zero(self):
        """测试：backoff_delay=0 时 wait_backoff 不阻塞（立即返回）"""
        rm = RetryManager(max_retries=3, backoff_base=0.0)
        # 不应阻塞超过 0.1 秒
        import time
        start = time.monotonic()
        asyncio.run(rm.wait_backoff())
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    def test_retry_workflow_simulating_self_correction(self):
        """
        集成测试：模拟 Self-Correction 工作流（失败 2 次后成功，验证预算管理）。

        场景：max_retries=3，前 2 次工具失败（触发 can_retry + record_retry），
        第 3 次成功（触发 reset），验证整个流程不抛出异常。
        """
        rm = RetryManager(max_retries=3)
        attempts = 0
        success_at = 3  # 第 3 次成功

        for i in range(1, success_at + 1):
            attempts += 1
            if i < success_at:
                # 失败 → 检查预算 → 消耗预算
                assert rm.can_retry() is True
                rm.record_retry()
            else:
                # 成功 → 重置计数器
                rm.reset()

        assert attempts == success_at
        assert rm.retry_count == 0  # 成功后计数器已归零

    def test_no_retry_allowed_when_max_retries_zero(self):
        """测试：max_retries=0 时，任何失败都不允许重试"""
        rm = RetryManager(max_retries=0)
        assert rm.can_retry() is False
