# Day 6 & Day 7 综合实战：微型 Agent 执行框架原型 (Chain-like)

这是一个基于 Python 基础、函数进阶与面向对象设计实现的微型 Agent 执行引擎。

## 🎯 任务目标
通过手写该框架，综合运用第一周所学知识点：
1. **Day 1**: 处理大模型输出的嵌套 Payload，规避 `KeyError`。
2. **Day 2**: 用正则表达式从大模型的自然语言混合输出中匹配出 JSON，并进行解析及容错。
3. **Day 3**: 编写带耗时统计和异常保护的工具日志装饰器。
4. **Day 4**: 基于魔法方法 `__call__` 使工具对象可调用，实现 `__repr__` 美化日志。
5. **Day 5**: 使用抽象基类定义 Tool 规范，运用单例模式实现 LLM 模拟器，利用反射（Reflection）/ 映射动态分发调用 Tool。

## 🛠️ 运行与练习方法

项目提供了两个核心实现文件：
1. **[agent_framework.py](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w01_python_basics/day_exercises/day6_7_agent_framework/agent_framework.py)**: 已经全部实现的完整工业级参考代码。
2. **[practice.py](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w01_python_basics/day_exercises/day6_7_agent_framework/practice.py)**: 为您特制的空白练习模板，里面包含了详细的 `TODO` 指引，需要您动手完成实现。

### ✍️ 自我动手练习
1. 打开 **[practice.py](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w01_python_basics/day_exercises/day6_7_agent_framework/practice.py)**，按照里面的 `TODO` 注释逐步编写代码。
2. 打开 **[test_agent_framework.py](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w01_python_basics/day_exercises/day6_7_agent_framework/test_agent_framework.py)**，将文件头部的：
   ```python
   from agent_framework import (
   ```
   修改为：
   ```python
   from practice import (
   ```
3. 在当前目录下运行单元测试，以验证您的代码是否完全正确：
   ```bash
   pytest test_agent_framework.py -v
   ```

### 运行完整演示
运行您自己实现的或者参考答案的 Agent 交互：
```bash
python practice.py
# 或
python agent_framework.py
```
