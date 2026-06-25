# Day 2 学习笔记：控制流、正则提取与 JSON 容错解析

在 LLM（大语言模型）应用开发中，Agent 需要处理大量非结构化文本并将其转化为程序可读取的结构化数据（通常是 JSON 字典）。本篇笔记系统地总结了 Python 的控制流、异常捕获、正则表达式匹配以及在 Agent 交互过程中必不可少的“非标准 JSON 容错清洗”技术。

---

## 目录
1. [控制流与循环结构](#1-控制流与循环结构)
2. [异常处理机制（Exception Handling）](#2-异常处理机制exception-handling)
3. [正则表达式基础与 re 模块](#3-正则表达式基础与-re-模块)
4. [大模型输出 JSON 的容错清洗技巧](#4-大模型输出-json-的容错清洗技巧)
5. [Agent 核心关联与工程实践意义](#5-agent-核心关联与工程实践意义)

---

## 1. 控制流与循环结构

### ① 条件分支 (if-elif-else)
Python 通过缩进来区分代码块，使用简明的 `if-elif-else` 进行条件判断。
```python
if condition_a:
    # 执行逻辑 A
elif condition_b:
    # 执行逻辑 B
else:
    # 执行逻辑 C
```

### ② 循环结构 (for 与 while)
*   `for` 循环：用于遍历可迭代对象（如列表、元组、字典、集合或字符串）。
*   `while` 循环：基于条件表达式的真假来决定是否继续循环。

### ③ 循环中断与控制 (break / continue)
*   `continue`：**跳过当前轮次**。立即结束本次循环的剩余语句，直接进入下一轮循环的条件判定。
*   `break`：**彻底终止循环**。直接跳出当前循环体，执行循环后面的代码。

---

## 2. 异常处理机制（Exception Handling）

在处理来自外部或 LLM 产生的不确定数据时，必须使用异常处理防止整个系统崩溃。

### ① `try-except-else-finally` 完整语法
```python
try:
    # 可能会抛出异常的代码
    result = json.loads(data)
except json.JSONDecodeError as e:
    # 仅在捕获到指定异常时执行
    print(f"JSON 解析失败: {e}")
else:
    # 仅在 try 块【没有发生任何异常】时运行
    print("解析成功，没有异常。")
finally:
    # 【无论是否发生异常】都必须执行的清理代码
    print("这里一定会被执行。")
```

### ② 捕获多个异常
你可以通过元组形式在同一个 `except` 块中捕获多种不同的异常，或者使用多个 `except` 块分别捕获处理。
```python
try:
    # 可能会发生 IOError, ValueError 或 TypeError 的操作
    pass
except (ValueError, TypeError) as type_err:
    # 处理类型或值异常
    pass
except IOError as io_err:
    # 处理输入输出异常
    pass
```

---

## 3. 正则表达式基础与 re 模块

在处理 LLM 输出的非结构化混合文本时，正则表达式是提取 JSON 等结构化内容的第一利器。

### ① Python `re` 模块高频 API
*   `re.search(pattern, string)`：扫描整个字符串，寻找**第一个**匹配的位置并返回对应的 Match 对象；如果未找到匹配，则返回 `None`。
*   `re.findall(pattern, string)`：寻找字符串中**所有**匹配的子串，并以列表形式返回所有匹配到的内容。
*   `re.compile(pattern, flags)`：将正则表达式编译成 Pattern 对象，便于复用并提高匹配效率。常见 flags 包含 `re.IGNORECASE`（忽略大小写）。

### ② 匹配 Markdown JSON 代码块的核心正则
```python
pattern = r"```json\s*([\s\S]*?)\s*```"
```
*   ` ```json `：精确匹配 Markdown 代码块的开头。
*   `\s*`：匹配开头标记与 JSON 内容之间的任意空白字符（包括空格、换行）。
*   `([\s\S]*?)`：
    *   `[\s\S]`：匹配任意字符，包括空格、换行符（比单纯的 `.` 更好，因为 `.` 默认无法匹配换行符）。
    *   `*?`：**非贪婪匹配**。在遇到最近的一个结束标记 ` ``` ` 时就立即停止匹配。这在文本中包含多个 Markdown 代码块时能避免误将它们合并成一个整体提取。
*   `\s*```` ：匹配代码块的结束标记。

---

## 4. 大模型输出 JSON 的容错清洗技巧

LLM 输出的数据往往包含少许杂质，我们通常在 `try-except` 的容错机制下进行如下清洗重试：

| 异常表现 | 清洗方式 (Python 实现) | 目的说明 |
| :--- | :--- | :--- |
| **首尾空白/控制符** | `raw_text.strip()` | 去除首尾的空格、换行符、制表符等。 |
| **中文标点符号** | `raw.translate(str.maketrans({...}))` | LLM 偶尔会输出中文引号或逗号，使用映射表在 C 语言层面一次性全部替换为英文标准符号，避免产生大量临时中间对象。 |
| **尾部多余逗号** | `re.sub(r",\s*}", "}", raw)` | 字典或数组尾部多加了逗号（如 `{"a": 1,}`）是不合法的 JSON，需要去除。 |
| **物理换行符** | `re.sub(r"\n", " ", raw)` | JSON 字符串内部的 Key/Value 间若有未转义的物理换行会导致报错，需转为空格。 |

---

## 5. Agent 核心关联与工程实践意义

1.  **容错保障**：大模型受限于温度参数（Temperature）及自身的偶然性，偶尔无法严格输出标准 JSON。如果在代码中直接采用 `json.loads(llm_output)`，只要一次解析失败就会导致 Agent 的 Tool Call 循环完全崩溃中断。
2.  **正则提取**：LLM 输出往往是“思维链（CoT）+ JSON 结果”的混合体（例如 `"根据你的要求，我计算出如下结果：\n\n\`\`\`json\n...\n\`\`\`\n如有问题请联系。"`）。必须通过正则精准匹配捕获，才能去除杂质。
3.  **多级异常处理**：工程实践中，我们通过 `try-except` 实现“尝试直接解析 -> 失败后清洗修复 -> 再次解析 -> 最终失败兜底”的多级保障机制。这种防御式编程是 Agent 工业级落地的必由之路。
