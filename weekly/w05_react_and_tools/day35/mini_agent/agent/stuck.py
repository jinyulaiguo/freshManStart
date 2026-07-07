"""
MiniAgent Framework v1.0 — StuckDetector 死循环检测器

设计方案：
1. 设计意图：
   从 Day29 的 stuck_detector.py 重构而来，核心算法保持不变（MD5 滑动窗口哈希比对），
   主要变化：
   - 异常类型改为从 schema/exception.py 导入统一的 StuckException
   - 增加 reset() 方法支持在新一轮 Agent 任务启动时清空窗口
   - 增加 window_state 属性用于 Logger 记录当前窗口状态

2. 类与函数结构：
   - StuckDetector: 死循环检测器
     - __init__(window_size): 初始化滑动哈希窗口
     - check_and_push(action, params): 压入决策并检测死循环
     - reset(): 清空滑动窗口（用于新任务启动）
     - window_state: 属性，返回当前窗口内哈希值列表
     - _normalize_params(params): 递归排序参数防止乱序哈希扰动

3. 数据流流向：
   - Runner 每轮决策循环，在处理 tool_calls 前调用 check_and_push
   - 对每个 tool_call 中的 action 和 params 进行 MD5 哈希计算
   - 将哈希值压入 deque(maxlen=window_size)
   - 若窗口已满且所有哈希值完全相同，抛出 StuckException（统一异常体系）
   - Runner 捕获 StuckException 后终止主循环并回滚状态
"""
from __future__ import annotations

import hashlib
import json
from collections import deque
from typing import Any

from ..schema.exception import StuckException


class StuckDetector:
    """
    Agent 死循环检测器。

    通过维护一个固定大小的滑动哈希窗口，检测大模型是否在连续 N 次决策中
    生成了完全相同的 Action + Arguments 组合，一旦检测到死循环即刻抛出异常，
    强制阻断主控制循环，防止无限重复调用同一工具造成费用灾难。

    算法原理：
        1. 对每次决策的 (action, params) 进行参数 key 排序后 JSON 序列化
        2. 将序列化字符串与 action 名拼接后计算 MD5 哈希
        3. 将哈希值压入 deque(maxlen=window_size)（自动弹出最旧的哈希）
        4. 若窗口已满且所有哈希值唯一数为 1，则判定为死循环

    特性：
        - 参数 key 乱序安全：{"a":1,"b":2} 与 {"b":2,"a":1} 哈希一致
        - 窗口自动管理：deque 满后自动弹出最旧记录，无需手动清理
        - 多工具场景：Parallel Tool Calls 中对每个 tool_call 独立检测
    """

    def __init__(self, window_size: int = 3) -> None:
        """
        初始化死循环监测器。

        Args:
            window_size: 滑动窗口大小（连续 N 次相同视为死循环），默认为 3。
        """
        self.window_size = window_size
        # deque 的 maxlen 参数使其在超出容量时自动弹出最旧元素，实现滑动窗口语义
        self._window: deque[str] = deque(maxlen=window_size)

    def _normalize_params(self, params: Any) -> str:
        """
        递归排序参数字典并去除所有空白符，防止因乱序或空格产生哈希扰动。

        核心策略：
        - 对字典的所有 key 进行递归排序（sorted(params.keys())）
        - 使用 separators=(',', ':') 消除 JSON 序列化后的全部空格
        - 递归处理嵌套字典和列表中的字典元素

        Args:
            params: 原始参数（字典、列表或原始值）。

        Returns:
            标准化后的 JSON 字符串（不含任何空格）。
        """
        if isinstance(params, dict):
            normalized: dict = {}
            for k in sorted(params.keys()):
                v = params[k]
                if isinstance(v, dict):
                    # 递归排序嵌套字典
                    normalized[k] = self._normalize_params(v)
                elif isinstance(v, list):
                    # 递归处理列表中的嵌套字典
                    normalized[k] = [
                        self._normalize_params(item) if isinstance(item, dict) else item
                        for item in v
                    ]
                else:
                    normalized[k] = v
            # separators=(',', ':') 彻底消除序列化产生的所有空格
            return json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        else:
            # 非字典类型直接转字符串
            return str(params)

    def check_and_push(self, action: str, params: dict) -> None:
        """
        将本次决策的 (action, params) 计算 MD5 哈希后压入滑动窗口，
        并检测是否触发死循环拦截条件。

        每次 LLM 输出 tool_call 后调用此方法，在工具执行前进行死循环检测，
        一旦触发立即阻断后续的工具调度，避免无效 API 调用和费用损耗。

        Args:
            action: 本次决策调用的工具名称。
            params: 工具入参字典（LLM 原始输出）。

        Raises:
            StuckException: 当滑动窗口内所有哈希值完全一致时抛出。
        """
        # 1. 标准化参数 → 消除 key 乱序干扰
        normalized_str = self._normalize_params(params)
        # 2. 拼接 action 名 + 参数标准化字符串 → 计算 MD5
        payload = f"{action}:{normalized_str}"
        action_hash = hashlib.md5(payload.encode("utf-8")).hexdigest()

        # 3. 压入滑动窗口（deque maxlen 自动弹出最旧元素）
        self._window.append(action_hash)

        # 4. 仅在窗口已填满时执行死循环检测（前 N-1 次不触发，避免误报）
        if len(self._window) == self.window_size:
            if len(set(self._window)) == 1:
                # 唯一哈希数为 1 → 所有窗口内记录完全一致 → 死循环
                raise StuckException(
                    action=action,
                    action_hash=action_hash,
                    window_size=self.window_size,
                )

    def reset(self) -> None:
        """
        清空滑动窗口。

        在新一轮 Agent 任务启动时调用，确保上一次任务的哈希记录
        不会影响当前任务的死循环检测。
        """
        self._window.clear()

    @property
    def window_state(self) -> list[str]:
        """
        返回当前滑动窗口内的哈希值列表（供 Logger 记录）。

        Returns:
            当前窗口内所有 MD5 哈希值的列表，按时间先后顺序排列。
        """
        return list(self._window)
