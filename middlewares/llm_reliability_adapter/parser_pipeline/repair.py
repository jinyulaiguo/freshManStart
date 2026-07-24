"""
==============================================================================
LLM Reliability Adapter - Deterministic Repairer 微组件 (parser_pipeline/repair.py)
==============================================================================

设计方案说明：
1. Design Intent:
   Implementation of Level 1 Local Fix zero-latency deterministic repairer.
   Fixes common LLM JSON syntax errors locally without invoking LLM:
   - Trailing commas before closing braces/brackets (e.g. `{"a": 1,}`)
   - Missing closing braces or brackets (e.g. `{"a": {"b": 1}`)
   - Unescaped newline characters inside strings
   - Single quote strings converted to standard double quotes
2. Class & Function Structure:
   - `DeterministicRepairer`: Contains repair_json_string() method.
3. Data Flow:
   Malformed JSON String ➔ DeterministicRepairer.repair_json_string() ➔ Repaired JSON String
4. Test Case Intent:
   - Verify zero-token cost repair rate for trailing commas and unclosed braces.
==============================================================================
"""

import re
from typing import Optional


class DeterministicRepairer:
    """
    Level 1 零延迟本地确定性 JSON 语法修补器
    """

    @staticmethod
    def repair_json_string(raw_json_str: str) -> str:
        """
        步骤块：对畸形 JSON 字符串执行确定性修补
        
        Args:
            raw_json_str: 待修补的畸形 JSON 字符串
            
        Returns:
            修补后的 JSON 字符串
        """
        if not raw_json_str:
            return ""

        repaired = raw_json_str.strip()

        # 步骤 1：物理移除对象或数组末尾多余的尾随逗号 (Trailing Commas)
        # 例如: {"a": 1,} -> {"a": 1} 或 [1, 2,] -> [1, 2]
        repaired = re.sub(r",\s*([\}\]])", r"\1", repaired)

        # 步骤 1.5：补齐字段之间或闭合括号后缺失的逗号 (Missing Commas between fields/objects)
        # 例如: "val" "key": -> "val", "key": 或 } "key": -> }, "key":
        repaired = re.sub(r'(["}\]true|false|null|\d+])\s+(?="[a-zA-Z0-9_]+" \s*:)', r'\1, ', repaired)

        # 步骤 2：把非标准单引号包裹的简单 key/string 转换为标准双引号 (注意保护内部缩写)
        # 例如: 'decision': 'REJECT' -> "decision": "REJECT"
        repaired = re.sub(r"(?<=[{\s,])'([a-zA-Z0-9_]+)':", r'"\1":', repaired)
        repaired = re.sub(r":\s*'([^']*)'", r': "\1"', repaired)

        # 步骤 3：替换裸换行符为 escaped \n，防止 json.loads 无严格模式时崩塌
        # (仅在 JSON 文本整体出现换行时修补)
        repaired = re.sub(r'[\r\n]+', ' ', repaired)

        # 步骤 4：栈平衡推算补齐缺失的尾部闭合大括号 '}' 或方括号 ']'
        open_braces = 0
        open_brackets = 0
        in_string = False
        is_escaped = False

        for char in repaired:
            if is_escaped:
                is_escaped = False
                continue
            if char == "\\":
                is_escaped = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if not in_string:
                if char == "{":
                    open_braces += 1
                elif char == "}":
                    open_braces = max(0, open_braces - 1)
                elif char == "[":
                    open_brackets += 1
                elif char == "]":
                    open_brackets = max(0, open_brackets - 1)

        # 若末尾由于 Token 被截断而缺失闭合符号，按逆序补齐
        # 如果当前还处于未闭合字符串状态，补充闭合双引号
        if in_string:
            repaired += '"'

        while open_brackets > 0:
            repaired += "]"
            open_brackets -= 1

        while open_braces > 0:
            repaired += "}"
            open_braces -= 1

        return repaired
