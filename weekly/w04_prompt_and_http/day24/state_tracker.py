"""
Week 4 Day 24 参考答案：防御性 JSON 解析器与脏 JSON 格式化语法纠错引擎

设计方案：
1. 设计意图：
   在高频 Agent 执行中，针对端侧轻量化模型可能输出的 Markdown 代码包裹、非标单引号、多余尾逗号以及因 Token 截断导致的残损 JSON 字符串，
   在 Python 侧通过状态机与解析栈（Parsing Stack）自愈机制在本地就地原位修复，免去昂贵且高延迟的二次大模型网络重试。

2. 类与函数结构：
   - 包含防御性 sys.path 自动寻址补丁逻辑。
   - `robust_json_parser(dirty_str)`: 核心容错解析入口。
   - `_extract_json_boundary(text)`: 寻址最外层大括号或中括号起始，兼容截断尾部。
   - `_clean_syntax(text)`: 正则替换单引号并剥离非法多余尾逗号。
   - `_heal_truncated_brackets(text)`: 状态机压栈出栈对截断括号末尾补齐，设计了双引号字面量逃逸。

3. 关键数据流向：
   脏字符串 ──> robust_json_parser ──> 边界寻址 ──> 单引号/尾逗号清理 ──> 括号栈闭合自愈 ──> json.loads ──> 合法 Python 字典
"""

import sys
import os
import re
import json

# =====================================================================
# 防御性 sys.path 补丁逻辑
# =====================================================================
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "../../.."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)


# =====================================================================
# 防御性解析引擎核心方法实现
# =====================================================================

def _extract_json_boundary(text: str) -> str:
    """提取最外层大括号 {...} 或中括号 [...] 之间的 JSON 核心载荷"""
    start_brace = text.find('{')
    start_bracket = text.find('[')
    
    if start_brace == -1 and start_bracket == -1:
        raise ValueError("输入文本中找不到任何 JSON 起始边界符号 ({ 或 [)。")
        
    # 判断最外层起始符号
    if start_brace != -1 and start_bracket != -1:
        start_idx = min(start_brace, start_bracket)
    elif start_brace != -1:
        start_idx = start_brace
    else:
        start_idx = start_bracket
        
    # 提取起始位置到末尾的所有内容，保留截断可能
    payload = text[start_idx:]
    
    # 尝试逆向查找最后一个有效闭合符号，剥离可能存在的 Markdown 尾巴或杂乱后缀
    end_brace = payload.rfind('}')
    end_bracket = payload.rfind(']')
    end_idx = max(end_brace, end_bracket)
    
    if end_idx != -1:
        return payload[:end_idx + 1]
        
    # 如果找不到任何闭合符号，说明发生了物理截断，保留全部内容供后续阶段三栈自愈补齐
    return payload


def _clean_syntax(text: str) -> str:
    """替换单引号包裹、处理未转义字符及剔除多余的尾部逗号"""
    # 1. 替换非标的单引号为双引号
    text = text.replace("'", '"')
    
    # 2. 正则匹配并剥离对象或数组最后一项后面多余非法逗号
    # 匹配逗号及之后的空格，且其后紧邻闭合括号 } 或 ]
    text = re.sub(r",\s*(?=[}\]])", "", text)
    return text


def _heal_truncated_brackets(text: str) -> str:
    """基于编译原理解析栈（Parsing Stack）自愈机制，闭合因 Token 截断导致的残损括号"""
    stack = []
    bracket_map = {'{': '}', '[': ']'}
    
    in_string = False
    is_escaped = False
    
    for char in text:
        # 处理转义字符逃逸，如 \"
        if char == '\\' and not is_escaped:
            is_escaped = True
            continue
            
        # 处理双引号字面量边界判定
        if char == '"' and not is_escaped:
            in_string = not in_string
            
        is_escaped = False  # 重置转义
        
        # 核心防干扰设计：如果字符处于双引号字面量内部，则忽略其中的所有结构括号
        if in_string:
            continue
            
        if char in bracket_map:
            stack.append(char)
        elif char in bracket_map.values():
            if stack and bracket_map[stack[-1]] == char:
                stack.pop()
                
    # 对栈中残留的左括号，逆序追加对应的闭合右括号
    missing_brackets = [bracket_map[left] for left in reversed(stack)]
    return text + "".join(missing_brackets)


def robust_json_parser(dirty_str: str) -> dict:
    """脏 JSON 容错纠错解析器核心入口"""
    try:
        # 阶段 1: 边界剥离
        payload = _extract_json_boundary(dirty_str)
        # 阶段 2: 语法纠错
        cleaned = _clean_syntax(payload)
        # 阶段 3: 栈自愈括号匹配
        healed = _heal_truncated_brackets(cleaned)
        # 阶段 4: 反序列化
        return json.loads(healed)
    except Exception as e:
        raise ValueError(f"脏 JSON 修复失败，底层解析报错: {e}") from e


# =====================================================================
# 多方案对比调试与运行主入口 (物理隔离与冗余设计)
# =====================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("🚀 Week 4 Day 24 防御性 JSON 解析器与纠错状态机实验")
    print("=" * 80)

    # 包含各种典型格式损毁的脏数据样例
    dirty_samples = [
        {
            "desc": "样例 1: Markdown 语法块包裹且首尾带干扰叙述字",
            "text": "Based on user profile, here is the generated info: ```json\n{'name': '张三', 'age': 25}\n``` Please review it."
        },
        {
            "desc": "样例 2: 包含单引号键值、值中带字符串括号干扰且含有多余尾逗号",
            "text": "{'skills': ['Python', 'Golang',], 'desc': 'I like {coding} and [music],', 'city': '北京',}"
        },
        {
            "desc": "样例 3: 遭遇 max_tokens 物理截断残损未闭合（嵌套结构）",
            "text": '{"status": "success", "data": {"user_id": 1002, "roles": ["admin", "developer"'
        }
    ]

    # -----------------------------------------------------------------
    # 【方案一】 使用 Python 原生标准 json.loads 解析 (测试痛点场景)
    # -----------------------------------------------------------------
    print("\n" + "="*30 + " 方案一：使用原生 json.loads 直接解析 " + "="*30)
    for idx, sample in enumerate(dirty_samples):
        print(f"\n[{idx+1}] {sample['desc']}:")
        try:
            # 尝试正则剥除简单的 markdown 标记以示公平
            temp = sample['text'].replace("```json", "").replace("```", "").strip()
            result = json.loads(temp)
            print(f"  ✅ 解析成功: {result}")
        except Exception as e:
            print(f"  ❌ 原生解析崩溃报错: {e}")

    print("-" * 80)

    # -----------------------------------------------------------------
    # 【方案二】 使用防御性自愈纠错引擎 robust_json_parser 解析 (测试容错自愈)
    # -----------------------------------------------------------------
    print("\n" + "="*30 + " 方案二：使用 robust_json_parser 纠错自愈 " + "="*30)
    for idx, sample in enumerate(dirty_samples):
        print(f"\n[{idx+1}] {sample['desc']}:")
        try:
            result = robust_json_parser(sample['text'])
            print(f"  ✅ 修复并解析成功: {result}")
        except Exception as e:
            print(f"  ❌ 修复解析失败: {e}")
            
    print("=" * 80)
