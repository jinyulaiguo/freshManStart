"""
Day 2: 控制流、正则提取与 JSON 容错解析完整学习样例

本文件展示了以下核心知识点：
1. 条件判断（if-elif-else）与循环控制（for/while, break/continue）
2. 异常处理机制（try-except-else-finally）
3. 使用正则表达式提取混合文本中的 JSON 代码块
4. 非标准 JSON 的容错清洗与安全解析
"""

import json
import re
from typing import Any, Dict


# ==========================================
# 🛡️ 核心工具函数：安全正则提取与 JSON 容错解析
# ==========================================
def safe_parse_json_from_text(text: str) -> Dict[str, Any]:
    """从大模型混合输出的文本中，安全提取并解析 JSON 代码块。
    
    若解析失败，会尝试对提取出的字符串进行容错清洗；若彻底失败，安全返回包含错误信息的字典。
    
    参数:
        text: 包含 Markdown 标记的混合文本
        
    返回:
        解析后的字典，或包含错误信息的兜底字典
    """
    # 默认兜底字典
    fallback_dict = {
        "error": "Failed to parse JSON",
        "status": "failed",
        "raw_text": text
    }

    if not isinstance(text, str):
        fallback_dict["error"] = "Input text must be a string"
        return fallback_dict

    # 1. 尝试使用正则提取 Markdown 代码块中的 JSON 内容
    # 匹配 ```json ... ```，不区分大小写，且使用非贪婪匹配支持多行
    json_block_pattern = re.compile(r"```json\s*([\s\S]*?)\s*```", re.IGNORECASE)
    match = json_block_pattern.search(text)
    
    if match:
        extracted = match.group(1).strip()
    else:
        # 如果找不到 Markdown JSON 块，尝试把整个文本作为 JSON 解析（进行基础过滤首尾空白）
        extracted = text.strip()

    # 2. 尝试解析提取出来的 JSON
    try:
        return json.loads(extracted)
    except json.JSONDecodeError:
        # 记录初始异常，准备进入清洗重试流程
        pass

    # 3. 容错清洗流程 (Tolerant Cleaning)
    cleaned = clean_non_standard_json(extracted)

    # 4. 二次解析尝试
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as second_err:
        # 二次解析失败，返回兜底字典，并将解析器的报错信息放入字典，方便排查
        fallback_dict["error"] = f"JSONDecodeError: {second_err.msg} (at position {second_err.pos})"
        fallback_dict["extracted_text"] = extracted
        fallback_dict["cleaned_text"] = cleaned
        return fallback_dict


def clean_non_standard_json(raw_json_str: str) -> str:
    """清洗非标准 JSON 字符串的常见格式错误。"""
    cleaned = raw_json_str.strip()

    # 1. 替换中文符号为英文标准符号（中文双引号、单引号、逗号、冒号、大括号）
    chinese_to_english = {
        '“': '"',
        '”': '"',
        '‘': "'",
        '’': "'",
        '，': ',',
        '：': ':',
        '｛': '{',
        '｝': '}'
    }
    trans_table = str.maketrans(chinese_to_english)
    cleaned = cleaned.translate(trans_table)

    # 2. 将单引号包裹的键或值替换为双引号
    # 替换以单引号包裹的键
    cleaned = re.sub(r"'\s*(\w+)\s*'\s*:", r'"\1":', cleaned)
    # 将被单引号包围的字符串值替换为双引号
    cleaned = re.sub(r":\s*'([^']*)'", r': "\1"', cleaned)
    cleaned = re.sub(r",\s*'([^']*)'", r', "\1"', cleaned)
    cleaned = re.sub(r"\[\s*'([^']*)'", r'["\1"', cleaned)

    # 3. 处理尾随逗号 (Trailing Commas)
    cleaned = re.sub(r",\s*}", "}", cleaned)
    cleaned = re.sub(r",\s*]", "]", cleaned)

    # 4. 去除可能引起错误的物理换行符，但保留转义的换行（如 \n 符号本身）
    cleaned = re.sub(r"\n", " ", cleaned)
    cleaned = re.sub(r"\r", "", cleaned)

    return cleaned.strip()


# ==========================================
# 🌟 核心语法演示函数（控制流与异常处理）
# ==========================================
def demo_control_flow():
    """演示 Python 条件判断与循环控制流"""
    print("\n--- [Control Flow 控制流演示] ---")
    
    # 1. if-elif-else 条件分支
    score = 85
    if score >= 90:
        grade = "A"
    elif score >= 80:
        grade = "B"
    else:
        grade = "C"
    print(f"得分: {score}, 等级评定: {grade}")

    # 2. for 循环与 break/continue
    print("循环演示（跳过偶数，遇到大于 7 的数终止）：")
    numbers = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    for num in numbers:
        if num % 2 == 0:
            continue  # 跳过偶数，进入下一次循环
        if num > 7:
            break     # 大于 7，直接跳出循环
        print(f"  处理奇数: {num}")


def demo_exception_handling():
    """演示 try-except-else-finally 完整异常处理结构"""
    print("\n--- [Exception Handling 异常处理演示] ---")
    
    def divide(a: Any, b: Any) -> float:
        try:
            print(f"开始计算 {a} / {b} ...")
            val_a = float(a)
            val_b = float(b)
            result = val_a / val_b
        except ValueError as val_err:
            print(f"  捕获数值转换异常: 输入的参数无法转换为浮点数 ({val_err})")
            return 0.0
        except ZeroDivisionError:
            print("  捕获除零异常: 除数不能为 0")
            return float('inf')
        else:
            print(f"  计算成功完成，结果为: {result}")
            return result
        finally:
            print("  [Finally 块已执行] 无论计算是否成功，这里必定运行。")

    divide(10, 2)
    divide(10, 0)
    divide("abc", 5)


if __name__ == "__main__":
    # 运行基本控制流与异常处理演示
    demo_control_flow()
    demo_exception_handling()

    # 演示 safe_parse_json_from_text 各种输入场景
    print("\n--- [JSON 安全提取与解析演示] ---")
    
    # 样例 1: 标准 Markdown 混合文本
    mixed_text = (
        "你好，大模型已完成计算。下面是你要的 JSON 数据：\n"
        "```json\n"
        '{\n  "action": "web_search",\n  "query": "AI basics"\n}\n'
        "```\n"
        "请查收。"
    )
    print("【样例 1 标准 Markdown】")
    print(f"输入文本:\n{mixed_text}")
    print(f"解析结果: {safe_parse_json_from_text(mixed_text)}\n")

    # 样例 2: 包含尾随逗号和中文符号的非标准 JSON
    dirty_text = (
        "分析结果如下：\n"
        "```json\n"
        '｛\n  "status": "success",\n  "data": ["item1", "item2",],\n  "code": 200,\n｝\n'
        "```"
    )
    print("【样例 2 脏 JSON 修复】")
    print(f"输入文本:\n{dirty_text}")
    print(f"解析结果: {safe_parse_json_from_text(dirty_text)}\n")

    # 样例 3: 严重损坏的非法 JSON
    broken_text = '```json\n{"status": "error", "message": \n```'
    print("【样例 3 损坏 JSON 兜底处理】")
    print(f"输入文本:\n{broken_text}")
    print(f"解析结果: {safe_parse_json_from_text(broken_text)}\n")
