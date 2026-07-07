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
        # TODO: 递归对参数字典的所有层级进行 key 排序，并转换成无空白的 JSON 字符串
        raise NotImplementedError("TODO: 请先在 _normalize_params 中实现字典深度递归排序规范化")

    def check_and_push(self, action: str, params: dict) -> None:
        """
        将本次决策的 Action 和参数计算 MD5 值，并压入滑动窗口进行死循环拦截。
        
        Args:
            action: 调用的工具名
            params: 工具入参字典
            
        Raises:
            AgentStuckError: 当滑动窗口内哈希完全一致时抛出
        """
        # TODO: 计算 md5 哈希值，压入滑动窗口并检测是否触发连续重复
        raise NotImplementedError("TODO: 请先在 check_and_push 中实现滑动哈希窗口的死循环拦截算法")

if __name__ == "__main__":
    print("=" * 60)
    print("运行 StuckDetector 调试模板...")
    print("=" * 60)
    
    detector = StuckDetector(window_size=3)
    
    try:
        # 第一阶段测试：正常流程
        print("步骤 1: 调度 run_linter, 参数 {'file': 'main.py'}")
        detector.check_and_push("run_linter", {"file": "main.py"})
        print("  -> 状态: 安全\n")
        
        # 第二阶段测试：模拟乱序参数与死循环
        print("开始模拟连续 3 次相同调用以触发拦截...")
        for i in range(1, 4):
            # 故意使用不同的 key 顺序，测试递归规范化是否有效
            if i == 2:
                params = {"line": 10, "file": "main.py"}
            else:
                params = {"file": "main.py", "line": 10}
            print(f"调用 {i}: 调度 run_linter, 参数 {params}")
            detector.check_and_push("run_linter", params)
            print("  -> 状态: 安全")
            
    except NotImplementedError as e:
        print(f"\n❌ 拦截到 TODO 占位：\n{e}")
    except AgentStuckError as e:
        print(f"\n✅ 成功拦截死循环异常: {e}")
    except Exception as e:
        print(f"\n❌ 运行出错: {e}")
        
    print("=" * 60)
