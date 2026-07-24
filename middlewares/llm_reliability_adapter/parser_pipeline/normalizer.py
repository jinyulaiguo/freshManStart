"""
==============================================================================
LLM Reliability Adapter - Normalizer 微组件 (parser_pipeline/normalizer.py)
==============================================================================

设计方案说明：
1. 设计意图 (Design Intent)：
   作为 Parser Pipeline 的第一道工序，负责物理剥离 LLM 输出中混杂的思考过程标签
   (如 <think>...</think>, <thought>...</thought>) 以及 Markdown 代码块包裹符 (```json ... ```)，
   提纯出干净的候选 JSON 文本段落。
2. 类与函数结构 (Class Structure)：
   - `Normalizer`: 包含 normalize() 静态方法与辅助物理清理函数。
3. 关键数据流 (Data Flow)：
   Raw LLM Output ➔ Normalizer.normalize() ➔ Normalized Text (无思维链、无 Markdown 标记)
4. 核心用例考量 (Test Case Intent)：
   - 验证处理 DeepSeek-R1 / Qwen 等带 <think> 标签模型输出时的干净剥离率。
   - 验证多级 Markdown 代码块（如 ```json { ... } ``` 或裸 ``` { ... } ```）的清洗稳健性。
==============================================================================
"""

import re


class Normalizer:
    """
    LLM 原始文本规范化清洗器
    """
    
    @staticmethod
    def normalize(raw_output: str) -> str:
        """
        步骤块：执行文本规范化清洗
        
        Args:
            raw_output: 大模型生成的未经处理的原始响应文本
            
        Returns:
            剥离思维链与 Markdown 标记后的规范文本
        """
        if not raw_output:
            return ""
            
        text = raw_output.strip()
        
        # 步骤 1：物理剥离 <think>...</think> 或 <thought>...</thought> 思考过程段落
        stripped = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        stripped = re.sub(r"<thought>.*?</thought>", "", stripped, flags=re.DOTALL | re.IGNORECASE).strip()
        
        # 防御性降级：若剥离思考标签后为空串，但原始文本包含 '{'，保留原文本供 BracketExtractor 提取
        if not stripped and "{" in text:
            text = text
        else:
            text = stripped
        
        # 步骤 2：识别并剥离 Markdown 代码块（如 ```json ... ``` 或 ``` ... ```）
        if "```json" in text:
            # 匹配包含 ```json 开始和对应 ``` 结尾的块
            parts = text.split("```json")
            if len(parts) > 1:
                sub_part = parts[1].split("```")[0]
                text = sub_part.strip()
        elif "```" in text:
            # 匹配通用 ``` 代码块
            parts = text.split("```")
            if len(parts) > 1:
                # 抓取第一块非空代码块内容
                text = parts[1].strip()
                
        return text
