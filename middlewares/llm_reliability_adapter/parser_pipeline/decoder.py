"""
==============================================================================
LLM Reliability Adapter - Strict Decoder 微组件 (parser_pipeline/decoder.py)
==============================================================================

设计方案说明：
1. 设计意图 (Design Intent)：
   作为 Parser Pipeline 的第三道工序，负责严格的 JSON 字符串反序列化解码。
   当标准 json.loads() 产生异常时，禁止静默吞掉或直接抛出原生 SyntaxError，
   而是封装并抛出包含精确错误行列号 (line, col)、错误位置字符上下文的 JSONDecodeCustomError。
2. 类与函数结构 (Class Structure)：
   - `JSONDecodeCustomError`: 包含了错误位置上下文的自定义解码异常类。
   - `StrictDecoder`: 包含 decode() 静态解耦函数。
3. 关键数据流 (Data Flow)：
   Extracted String ➔ StrictDecoder.decode() ➔ Python dict (或抛出 JSONDecodeCustomError)
4. 核心用例考量 (Test Case Intent)：
   - 验证异常抛出时其 line, column 以及 context_snippet 的准确性，供后续 Level 2 Re-prompt 提示给 LLM。
==============================================================================
"""

import json
from typing import Any, Dict


class JSONDecodeCustomError(Exception):
    """
    自解释的 JSON 解码异常类
    封装具体的错误行号、列号与上下文切片
    """
    def __init__(self, message: str, raw_text: str, pos: int, lineno: int, colno: int):
        self.message = message
        self.raw_text = raw_text
        self.pos = pos
        self.lineno = lineno
        self.colno = colno
        
        # 截取错误位置前后各 30 个字符作为上下文诊断切片
        start = max(0, pos - 30)
        end = min(len(raw_text), pos + 30)
        self.context_snippet = raw_text[start:end]
        
        super().__init__(
            f"JSONDecodeCustomError: {message} at line {lineno} column {colno} (pos {pos}). "
            f"Snippet: ...{self.context_snippet}..."
        )


class StrictDecoder:
    """
    严格 JSON 解码器
    """

    @staticmethod
    def decode(json_str: str) -> Dict[str, Any]:
        """
        步骤块：执行严格 JSON 反序列化解码
        
        Args:
            json_str: 经过提取器抓取的 JSON 字符串
            
        Returns:
            解析后的 Python 字典
            
        Raises:
            JSONDecodeCustomError: 当字符串不符合 JSON 语法规范时抛出
        """
        if not json_str:
            raise JSONDecodeCustomError("Empty input string", raw_text="", pos=0, lineno=1, colno=1)

        try:
            # 使用 strict=False 容忍控制字符，但保留语法结构判定
            return json.loads(json_str, strict=False)
        except json.JSONDecodeError as err:
            # 捕获原生 JSONDecodeError 并封装为包含上下文的自定义异常
            raise JSONDecodeCustomError(
                message=err.msg,
                raw_text=err.doc,
                pos=err.pos,
                lineno=err.lineno,
                colno=err.colno
            ) from err
