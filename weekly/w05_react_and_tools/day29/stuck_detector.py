"""
设计方案：
1. 设计意图：构建一个轻量级死循环检测器，用于拦截 Agent 在 ReAct 决策循环中因为幻觉或外部工具报错导致的重复 Action 请求。
2. 类与函数结构：
   - AgentStuckError: 自定义异常类，继承自 Exception。
   - StuckDetector: 核心检测器。
     - __init__(self, window_size: int = 3): 初始化滑动窗口大小。
     - _normalize_params(self, params: dict) -> str: 递归排序字典防止因乱序哈希不同。
     - check_and_push(self, action: str, params: dict) -> None: 推入新决策并检测是否死循环。
3. 数据流流向：
   - Action 名称及参数字典传入 check_and_push
   - 提取参数并进行 key 排序、去除多余空白字符进行 JSON 序列化
   - 结合 Action 名字生成 MD5 哈希
   - 压入 deque(maxlen=window_size)
   - 统计 deque 内唯一哈希的数量。如果长度达到 window_size 且唯一哈希数为 1，则触发 AgentStuckError。
"""
import json
import hashlib
from collections import deque

class AgentStuckError(Exception):
    """当 Agent 陷入死循环时抛出的自定义异常"""
    pass

class StuckDetector:
    def __init__(self, window_size: int = 3):
        """
        初始化死循环监测器
        
        Args:
            window_size: 滑动窗口大小，默认为 3
        """
        self.window_size = window_size
        self.window = deque(maxlen=window_size)

    def _normalize_params(self, params: dict) -> str:
        """
        递归排序参数字典并去除所有空白符，防止因乱序或空格产生哈希扰动。
        
        Args:
            params: 原始参数字典
            
        Returns:
            标准化 JSON 字符串
        """
        if not isinstance(params, dict):
            return str(params)
            
        # 递归处理嵌套字典与列表
        normalized = {}
        for k in sorted(params.keys()):
            v = params[k]
            if isinstance(v, dict):
                normalized[k] = self._normalize_params(v)
            elif isinstance(v, list):
                # 递归处理列表内的嵌套字典
                normalized[k] = [
                    self._normalize_params(item) if isinstance(item, dict) else item 
                    for item in v
                ]
            else:
                normalized[k] = v
                
        # separators=(',', ':') 能够彻底去除 JSON 序列化后的所有空格，保证格式绝对一致
        return json.dumps(normalized, sort_keys=True, separators=(',', ':'))

    def check_and_push(self, action: str, params: dict) -> None:
        """
        将本次决策的 Action 和参数计算 MD5 值，并压入滑动窗口进行死循环拦截。
        
        Args:
            action: 调用的工具名
            params: 工具入参字典
            
        Raises:
            AgentStuckError: 当滑动窗口内哈希完全一致时抛出
        """
        normalized_str = self._normalize_params(params)
        payload = f"{action}:{normalized_str}"
        action_hash = hashlib.md5(payload.encode('utf-8')).hexdigest()
        
        self.window.append(action_hash)
        
        # 仅在滑动窗口已填满时进行唯一性哈希匹配校验
        if len(self.window) == self.window_size:
            if len(set(self.window)) == 1:
                raise AgentStuckError(
                    f"检测到 Agent 陷入死循环拦截：连续 {self.window_size} 次请求相同 Action '{action}'，"
                    f"且入参哈希完全一致 (Hash: {action_hash})"
                )

if __name__ == "__main__":
    print("=" * 60)
    print("运行 StuckDetector 标准答案测试与演示...")
    print("=" * 60)
    
    detector = StuckDetector(window_size=3)
    
    # 模拟正常调试流程，参数有变化
    steps = [
        ("run_linter", {"file": "main.py", "line": 10}),
        ("run_linter", {"file": "main.py", "line": 20}),  # 参数不同，通过
        ("run_linter", {"line": 10, "file": "main.py"}),  # 参数 key 乱序但值相同，与步骤 1 相同，通过
    ]
    
    try:
        for i, (action, params) in enumerate(steps, 1):
            print(f"步骤 {i}: 调度 Action -> '{action}' 参数 -> {params}")
            detector.check_and_push(action, params)
            print("  -> 状态: 安全")
            
        # 模拟重复的 Tool Calls，触发死循环拦截
        print("\n开始模拟连续相同的 Action 调用...")
        for i in range(1, 5):
            action = "run_linter"
            params = {"file": "main.py", "line": 10}
            print(f"重复步骤 {i}: 调度 Action -> '{action}' 参数 -> {params}")
            detector.check_and_push(action, params)
            print("  -> 状态: 安全")
            
    except AgentStuckError as e:
        print(f"\n🚨 拦截成功: {e}")
    except Exception as e:
        print(f"\n❌ 发生意外错误: {e}")
        
    print("=" * 60)
