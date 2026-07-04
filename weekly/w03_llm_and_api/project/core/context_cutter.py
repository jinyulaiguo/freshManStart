"""
OpsChat CLI - 带 System 优先权的离线上下文消息裁剪器 (context_cutter.py)

=========================================
设计方案说明
=========================================
1. 设计意图：
   限制多轮对话的上下文在 3000 Token 以内。若超出上限，利用 tiktoken 离线切词分块，
   采用滑动窗口裁剪较旧的普通消息，同时保证 System 指令消息绝对不被裁剪，保障模型的 SRE 人设不丢失。

2. 类与函数结构：
   - SmartContextCutter:
     - __init__(max_tokens: int, model_name: str = "gpt-4o"): 设定最大限制及分词器。
     - cut(messages: List[Dict[str, str]]) -> List[Dict[str, str]]: 执行裁剪逻辑。
=========================================
"""

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
        计算单条消息所占用的 Token 数量 (OpenAI ChatML 规范)
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
