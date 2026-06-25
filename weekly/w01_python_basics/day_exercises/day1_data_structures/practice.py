"""
Day 1: 核心数据结构与字典深度操作完整学习样例

本文件展示了以下核心知识点：
1. 列表 (List)、元组 (Tuple)、集合 (Set) 的高频常规操作代码演示
2. 嵌套字典的安全路径提取（防范 KeyError/TypeError/IndexError）
3. 字典的深度操作（get() 默认值、字典推导式）
"""

from typing import Any, Union, List


# ==========================================
# 🛡️ 核心工具函数：安全字典提取
# ==========================================
def safe_get(
    data: Union[dict, list], 
    path: Union[str, List[Union[str, int]]], 
    default: Any = None
) -> Any:
    """安全地从多层嵌套的字典或列表中提取指定路径的值。
    
    参数:
        data: 待提取的嵌套字典或列表
        path: 提取路径。支持 "a.b.c" 形式的字符串，或 ["a", 0, "b"] 形式的混合列表
        default: 路径不存在或类型不匹配时返回的默认值
    """
    if isinstance(path, str):
        keys = [k for k in path.split(".") if k]
    else:
        keys = path

    current = data
    for key in keys:
        if isinstance(current, dict):
            if key in current:
                current = current[key]
            else:
                return default
        elif isinstance(current, list):
            try:
                idx = int(key)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return default
            except (ValueError, TypeError):
                return default
        else:
            return default
    return current


# ==========================================
# 🌟 核心数据类型操作演示
# ==========================================
def demo_list_operations():
    """演示列表 (List) ── 可变与有序容器的常用操作"""
    print("\n--- [List 列表常规操作] ---")
    # 1. 初始化
    tools = ["web_search", "calculator"]
    print(f"初始列表: {tools}")
    
    # 2. 增加元素
    tools.append("fetch_url")          # 尾部追加
    tools.insert(1, "code_interpreter") # 指定位置插入
    print(f"添加元素后: {tools}")
    
    # 3. 删除元素
    popped = tools.pop()               # 弹出尾部元素
    print(f"弹出的尾部元素: {popped}, 剩余列表: {tools}")
    tools.remove("calculator")         # 按值删除第一个匹配项
    print(f"移除 calculator 后: {tools}")
    
    # 4. 切片 (Slicing) - 格式 [start:stop:step]
    numbers = [0, 1, 2, 3, 4, 5]
    print(f"原数字列表: {numbers}")
    print(f"切片 [1:4]: {numbers[1:4]}")       # 获取索引 1 到 3 的元素
    print(f"切片 [::2]: {numbers[::2]}")       # 步长为 2 提取（偶数索引）
    print(f"切片 [::-1]: {numbers[::-1]}")     # 列表反转
    
    # 5. 排序
    unsorted = [5, 2, 9, 1]
    # sorted() 返回新列表，不修改原列表；.sort() 原地修改
    print(f"临时排序 sorted(): {sorted(unsorted)}, 原列表未变: {unsorted}")


def demo_tuple_operations():
    """演示元组 (Tuple) ── 不可变与安全防护容器的操作"""
    print("\n--- [Tuple 元组常规操作] ---")
    # 1. 初始化与只读特性
    coordinate = (39.9, 116.4)
    print(f"地理坐标元组: {coordinate}")
    # 尝试修改元组会抛出 TypeError，因此它常用于安全的配置参数
    
    # 2. 元组解包 (Unpacking)
    lat, lng = coordinate
    print(f"元组解包 -> 纬度: {lat}, 经度: {lng}")
    
    # 3. 剩余元素解包（带星号，常用于参数分发）
    message_info = ("system", "User is online", "2026-06-24", "info_level")
    role, content, *meta = message_info
    print(f"角色: {role}")
    print(f"内容: {content}")
    print(f"剩余元数据列表: {meta}")


def demo_set_operations():
    """演示集合 (Set) ── 去重与数学集合运算"""
    print("\n--- [Set 集合常规操作] ---")
    # 1. 自动去重与初始化
    raw_tags = ["search", "math", "search", "translate", "math"]
    unique_tags = set(raw_tags)
    print(f"原始列表 (有重复): {raw_tags}")
    print(f"转换为集合 (自动去重): {unique_tags}")
    
    # 2. 集合运算（并集、交集、差集）
    agent_a_tools = {"search", "calculator", "fetch_url"}
    agent_b_tools = {"calculator", "python_interpreter", "sql_writer"}
    print(f"Agent A 工具箱: {agent_a_tools}")
    print(f"Agent B 工具箱: {agent_b_tools}")
    
    # 交集：两者共有的工具
    common = agent_a_tools & agent_b_tools
    print(f"交集 (共用工具): {common}")
    
    # 并集：合并所有不重复工具
    union = agent_a_tools | agent_b_tools
    print(f"并集 (所有可用工具): {union}")
    
    # 差集：A 有但 B 没有的工具
    difference = agent_a_tools - agent_b_tools
    print(f"差集 (Agent A 独有工具): {difference}")


def demo_dict_deep_operations():
    """演示字典 (Dict) ── 嵌套提取、防御性编程与推导式"""
    print("\n--- [Dict 字典深度操作] ---")
    
    # 模拟大模型返回的 Payload 结构
    mock_payload = {
        "id": "chatcmpl-123",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Hello!"
                }
            }
        ],
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 5
        },
        "config": None
    }
    print(f"大模型 Payload 结构已加载")

    # 1. 使用 get() 设置默认值防止 KeyError
    # 即使 'model_name' 键不存在，也会安全返回 'gpt-4o' 而不会崩溃
    model = mock_payload.get("model_name", "gpt-4o")
    print(f"get() 提取缺失键 (默认值生效): {model}")

    # 2. 嵌套字典的安全路径提取演示 (调用 safe_get)
    content = safe_get(mock_payload, "choices.0.message.content", default="空")
    print(f"safe_get 提取嵌套路径: '{content}'")
    
    # 提取不存在且易导致报错的深层路径
    invalid_path_val = safe_get(mock_payload, "config.api_key.value", default="Default_Key")
    print(f"safe_get 提取 None 节点的子键 (防范崩溃): '{invalid_path_val}'")

    # 3. 字典推导式 (Dict Comprehension)
    # 将 usage 中的数据放大 10 倍（模拟多轮对话 Token 估算），并将 key 转为大写
    usage_data = mock_payload["usage"]
    scaled_usage = {
        key.upper(): val * 10 
        for key, val in usage_data.items()
    }
    print(f"字典推导式转换前: {usage_data}")
    print(f"字典推导式转换后: {scaled_usage}")


# ==========================================
# 运行主入口
# ==========================================
if __name__ == "__main__":
    print("=== Python 核心数据结构常规操作演示 ===")
    demo_list_operations()
    demo_tuple_operations()
    demo_set_operations()
    demo_dict_deep_operations()
