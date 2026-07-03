"""
Day 17: Tokenizer BPE 算法原理与带 System 优先权的离线上下文裁剪器 - 练习模板

设计方案说明：
1. 设计意图：
   在向大模型 API 发送对话历史之前，通过本地 tiktoken 计算 Token 数，以进行精准的上下文裁剪。
   保证 System 角色消息无条件保留，优先保留最新的对话消息，且采用“消息物理完整性”过滤规则，不打碎单条消息。
2. 类与函数结构：
   - `SmartContextCutter` 类：
     - `__init__(self, max_tokens: int, model_name: str = "gpt-4o")`: 设定最大 Token 限制，并加载对应的 tiktoken 编码器。
     - `_count_message_tokens(self, message: dict) -> int`: 估算单条消息在模型传输中的 Token 占用量。
     - `cut(self, messages: list) -> list`: 执行裁剪逻辑，并拼装出安全的上下文消息列表。
3. 关键数据流流向：
   `原始消息列表` -> `区分 System 消息与普通消息` -> `从最新到最旧评估普通消息` 
   -> `根据剩余 Token 额度截断旧消息` -> `重新组装 System 消息与未被裁剪的普通消息` -> `安全输出列表`
"""

import tiktoken
from typing import List, Dict


class SmartContextCutter:
    """
    带 System 优先权的离线上下文消息裁剪器
    """
    def __init__(self, max_tokens: int, model_name: str = "gpt-4o"):
        self.max_tokens = max_tokens
        # 使用 tiktoken 获取模型的对应编码器（如 cl100k_base 或 o200k_base）
        try:
            self.encoding = tiktoken.encoding_for_model(model_name)
        except KeyError:
            # 备选加载
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def _count_message_tokens(self, message: Dict[str, str]) -> int:
        """
        计算单条消息所占用的 Token 数量。
        每一条消息不仅包含 content 的字符，还包含 role 等控制参数带来的额外 Token 开销。
        
        估算公式：
        - 消息内容本身的 Token 数：len(self.encoding.encode(message.get("content", "")))
        - 消息元数据（role）开销：基础开销 3-4 个 Token。
        """
        # TODO: 编写单条消息的精确 Token 计算逻辑
        raise NotImplementedError("TODO: 实现单条消息 Token 计算逻辑")

    def cut(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        根据 max_tokens 阈值裁剪消息列表。
        裁剪原则：
        1. 必须无条件保留 System 消息（即使 System 消息已经超出了 max_tokens，也需要将其保留，其余非 System 消息全部丢弃）。
        2. 非 System 消息按时间由新到旧（从列表尾部到头部）评估保留，直到剩余 Token 不足。
        3. 消息不能从中间拆开截断，只能整条淘汰。
        4. 被保留的消息应维持在原本的相对先后顺序输出（System 通常在最前）。
        """
        # TODO: 实现滑动裁剪逻辑
        # 1. 拆分 system 消息与非 system 消息
        # 2. 计算 system 消息占用的总 token 数
        # 3. 计算非 system 消息的 token 数
        # 4. 从最新的普通消息（即列表末尾）向前累加 token，直到超出 (max_tokens - system_tokens) 的容量限制
        # 5. 将保留下来的普通消息按原始顺序与 system 消息组合，返回安全的消息列表
        raise NotImplementedError("TODO: 实现带优先级的消息滑动裁剪逻辑")


if __name__ == "__main__":
    print("=== Day 17 离线上下文裁剪测试 ===")
    
    # 模拟历史对话数据
    sample_messages = [
        {"role": "system", "content": "You are a helpful programming assistant."},
        {"role": "user", "content": "Hello, how do I write a fast sort in Python?"},
        {"role": "assistant", "content": "You can use quick sort or Python's built-in sorted() function."},
        {"role": "user", "content": "Can you show me the quick sort code?"},
        {"role": "assistant", "content": "Sure! Here is the implementation: def quicksort(arr): ..."},
        {"role": "user", "content": "Awesome! How about its time complexity?"}
    ]
    
    # 阈值设置极小，以测试滑动剪裁行为
    cutter = SmartContextCutter(max_tokens=60)
    
    try:
        safe_messages = cutter.cut(sample_messages)
        print("\n裁剪后的消息列表：")
        for idx, msg in enumerate(safe_messages):
            print(f"[{idx}] {msg['role'].upper()}: {msg['content'][:40]}...")
    except NotImplementedError as e:
        print(f"\n[拦截提示] 核心逻辑尚未实现: {e}")
        print("请补全 TODO 后再次运行验证。")
