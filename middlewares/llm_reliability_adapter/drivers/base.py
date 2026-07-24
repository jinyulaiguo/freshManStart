"""
==============================================================================
LLM Reliability Adapter - Base Driver (drivers/base.py)
==============================================================================

设计方案说明：
1. 设计意图 (Design Intent)：
   定义抽象的 BaseLLMDriver 基础驱动接口，统一多模型 Provider (OpenAI, DeepSeek, Ollama 等)
   的网络请求提交契约，屏蔽底层 SDK 差异。
2. 类与函数结构 (Class Structure)：
   - `BaseLLMDriver`: 抽象基类，定义 execute() 异步/同步请求方法。
3. 关键数据流 (Data Flow)：
   Prompt ➔ BaseLLMDriver.generate() ➔ Raw LLM Response Text
4. 核心用例考量 (Test Case Intent)：
   - 允许通过继承 BaseLLMDriver 快速编写单元测试用 Mock Driver。
==============================================================================
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseLLMDriver(ABC):
    """
    大模型底层驱动抽象基类
    """

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        步骤块：同步网络生成方法
        
        Args:
            prompt: 发送给 LLM 的主提示词
            system_instruction: 可选的系统指令
            context: 运行时上下文
            
        Returns:
            LLM 生成的未经处理的原始响应文本
        """
        pass
