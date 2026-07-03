"""
Day 17: Tokenizer BPE 算法原理与带 System 优先权的离线上下文裁剪器 - 参考标准答案

设计方案说明：
1. 设计意图：
   在大模型交互的长对话中，避免因上下文超出 Context Limit 导致服务报错。
   使用 tiktoken 对对话历史消息列表进行高精度 Token 预测，实现带优先级的滑动窗口裁剪算法。
2. 类与函数结构：
   - `SmartContextCutter` 类：
     - `__init__(self, max_tokens: int, model_name: str = "gpt-4o")`: 配置最大 Token 限制并加载分词器。
     - `_count_message_tokens(self, message: dict) -> int`: 依据 ChatML 格式计算单条消息的精确 Token 消耗。
     - `cut(self, messages: list) -> list`: 执行核心的分离-反向聚合裁剪逻辑。
3. 关键数据流流向：
   `输入消息历史` -> `计算 System 与普通消息的 Token` -> `从末尾倒序合并普通消息` 
   -> `触达上限拦截` -> `组装原序的 System 和普通消息` -> `完成输出`
"""

import unittest
import tiktoken
from typing import List, Dict


class SmartContextCutter:
    """
    带 System 优先权的离线上下文消息裁剪器
    """
    def __init__(self, max_tokens: int, model_name: str = "gpt-4o"):
        self.max_tokens = max_tokens
        try:
            self.encoding = tiktoken.encoding_for_model(model_name)
        except KeyError:
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def _count_message_tokens(self, message: Dict[str, str]) -> int:
        """
        计算单条消息所占用的 Token 数量。
        使用 OpenAI ChatML 格式标准估算：每一条消息包含 role, content，并伴有格式封装 Token。
        """
        num_tokens = 4  # 每一条消息的基础封装开销 (如 <|im_start|>, <|im_sep|>, <|im_end|>)
        
        content = message.get("content", "")
        num_tokens += len(self.encoding.encode(content))
        
        role = message.get("role", "")
        num_tokens += len(self.encoding.encode(role))
        
        return num_tokens

    def cut(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        根据 max_tokens 阈值裁剪消息列表。
        """
        system_messages = []
        other_messages = []
        
        # 1. 分离 System 消息与普通消息，保留其原始顺序
        for msg in messages:
            if msg.get("role") == "system":
                system_messages.append(msg)
            else:
                other_messages.append(msg)
                
        # 2. 统计 System 消息所占的总 Token 数
        system_tokens = sum(self._count_message_tokens(msg) for msg in system_messages)
        
        # 3. 如果 System 消息的 Token 已经超过或等于 max_tokens 限制，
        # 则无条件保留 System 消息，不保留任何普通消息（按要求：必须无条件保留 System Prompt，即使它很长）
        if system_tokens >= self.max_tokens:
            return system_messages
            
        allowed_other_tokens = self.max_tokens - system_tokens
        accepted_other = []
        current_other_tokens = 0
        
        # 4. 从最新消息（列表尾部）向最旧消息（列表头部）倒序累加评估普通消息
        for msg in reversed(other_messages):
            msg_tokens = self._count_message_tokens(msg)
            if current_other_tokens + msg_tokens <= allowed_other_tokens:
                accepted_other.insert(0, msg)  # 维持原有时序排列
                current_other_tokens += msg_tokens
            else:
                # 触及上限，更早的消息全被淘汰
                break
                
        # 5. 重组并返回消息列表
        return system_messages + accepted_other


# --- 单元测试套件 ---
class TestSmartContextCutter(unittest.TestCase):
    def setUp(self):
        self.sample_messages = [
            {"role": "system", "content": "You are a helpful programming assistant."},
            {"role": "user", "content": "Hello, how do I write a fast sort in Python?"},
            {"role": "assistant", "content": "You can use quick sort or Python's built-in sorted() function."},
            {"role": "user", "content": "Can you show me the quick sort code?"},
            {"role": "assistant", "content": "Sure! Here is the implementation: def quicksort(arr): ..."},
            {"role": "user", "content": "Awesome! How about its time complexity?"}
        ]

    def test_no_cut_needed(self):
        # 足够大的 Token 空间，不应该有任何消息被裁剪
        cutter = SmartContextCutter(max_tokens=1000)
        result = cutter.cut(self.sample_messages)
        self.assertEqual(len(result), len(self.sample_messages))
        self.assertEqual(result[0]["role"], "system")
        self.assertEqual(result[-1]["content"], "Awesome! How about its time complexity?")

    def test_system_prompt_preservation_only(self):
        # 极限限制：空间极小，仅够容纳 System 消息
        cutter = SmartContextCutter(max_tokens=20)
        result = cutter.cut(self.sample_messages)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["role"], "system")

    def test_slide_cutting_behavior(self):
        # 设置适中阈值，应该只保留 System 和最晚的 2-3 条对话
        cutter = SmartContextCutter(max_tokens=80)
        result = cutter.cut(self.sample_messages)
        
        # 必须含有 System Prompt
        self.assertEqual(result[0]["role"], "system")
        # 最新的消息必须保留
        self.assertEqual(result[-1]["content"], "Awesome! How about its time complexity?")
        # 验证没有截断单条消息的内容
        for msg in result:
            self.assertIn("content", msg)
            self.assertIn("role", msg)

    def test_huge_system_prompt(self):
        # 即使 System Prompt 超出最大限制，也要保留 System 且丢弃其他所有消息
        messages = [
            {"role": "system", "content": "System " * 100},
            {"role": "user", "content": "Hello"}
        ]
        cutter = SmartContextCutter(max_tokens=30)
        result = cutter.cut(messages)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["role"], "system")


if __name__ == "__main__":
    print("=== 运行单元测试验证 SmartContextCutter ===")
    # 构造测试装载器
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSmartContextCutter)
    runner = unittest.TextTestRunner(verbosity=2)
    test_result = runner.run(suite)
    
    if test_result.wasSuccessful():
        print("\n🎉 单元测试全部通过！")
        
        # 直观展示裁剪效果
        print("\n--- 裁剪效果直观演示 ---")
        messages = [
            {"role": "system", "content": "System prompt: Coding expert."},
            {"role": "user", "content": "Message 1 (very old)"},
            {"role": "assistant", "content": "Message 2 (old)"},
            {"role": "user", "content": "Message 3 (recent)"},
            {"role": "assistant", "content": "Message 4 (latest)"}
        ]
        
        print("原始总消息数：", len(messages))
        for max_t in [60, 40, 25]:
            cutter = SmartContextCutter(max_tokens=max_t)
            cut_result = cutter.cut(messages)
            print(f"\n[Max Tokens = {max_t}] 裁剪后保留了 {len(cut_result)} 条消息：")
            for m in cut_result:
                print(f"  - {m['role'].upper()}: {m['content']}")
    else:
        print("\n❌ 单元测试发现错误，请检查实现！")
