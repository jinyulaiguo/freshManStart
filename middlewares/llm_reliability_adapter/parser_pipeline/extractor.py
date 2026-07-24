r"""
==============================================================================
LLM Reliability Adapter - Bracket Extractor 微组件 (parser_pipeline/extractor.py)
==============================================================================

设计方案说明：
1. 设计意图 (Design Intent)：
   作为 Parser Pipeline 的第二道工序，彻底替换易造成塌陷匹配的贪婪正则 re.search(r"\{.*\}")。
   采用字符栈/括号平衡计数算法 (Stack & Balance Counter)，在考虑字符串内部转义字符和双引号
   作用域的前提下，精确抽取最外层的完整 JSON 字典对象 `{ ... }`。
2. 类与函数结构 (Class Structure)：
   - `BracketExtractor`: 包含 extract_json_object() 主算法函数。
3. 关键数据流 (Data Flow)：
   Normalized Text ➔ BracketExtractor.extract_json_object() ➔ Extracted JSON Substring
4. 核心用例考量 (Test Case Intent)：
   - 验证嵌套字典（如 {"a": {"b": 1}}）的匹配完整性。
   - 验证字符串内容中包含花括号（如 {"prompt": "Hello {user}"}）时的抗干扰能力。
==============================================================================
"""

from typing import Optional


class BracketExtractor:
    """
    基于括号平衡栈计数的精准 JSON 提取器
    """

    @staticmethod
    def extract_json_object(text: str) -> Optional[str]:
        """
        步骤块：使用字符扫描与平衡栈精准定位最外层 {...}
        
        Args:
            text: 规范化后的纯文本字符串
            
        Returns:
            精准抓取到的 JSON 字典字符串片段，若找不到闭合字典则返回 None
        """
        if not text:
            return None

        first_brace_idx = text.find("{")
        if first_brace_idx == -1:
            return None

        # 步骤 1：状态变量初始化
        bracket_stack = 0
        in_string = False
        is_escaped = False
        start_index = -1

        # 步骤 2：单字符线性扫描匹配 (O(N) 时间复杂度)
        for idx in range(first_brace_idx, len(text)):
            char = text[idx]

            # 字符处于转义状态，跳过逻辑判定
            if is_escaped:
                is_escaped = False
                continue

            # 处理转义斜杠 '\'
            if char == "\\":
                is_escaped = True
                continue

            # 处理双引号作用域，防止字符串内部的 '{' 或 '}' 触发计数变更
            if char == '"':
                in_string = not in_string
                continue

            # 不在字符串内部时，统计大括号平衡度
            if not in_string:
                if char == "{":
                    if bracket_stack == 0:
                        start_index = idx
                    bracket_stack += 1
                elif char == "}":
                    if bracket_stack > 0:
                        bracket_stack -= 1
                        # 达到栈平衡 (0)，找到最外层完整的闭合 JSON 对象
                        if bracket_stack == 0 and start_index != -1:
                            return text[start_index : idx + 1]

        # 步骤 3：未找到完全闭合的右括号，截取从首个 '{' 开始的剩余文本供后续修补器尝试修补
        if start_index != -1:
            return text[start_index:]
            
        return None
