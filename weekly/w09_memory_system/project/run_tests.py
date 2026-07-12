"""
Test Runner Script.

设计方案说明：
1. **设计意图**：
   本脚本用于在本地一键触发整个 `tests/` 目录下的自动化测试用例，
   方便学生和开发人员快速验证路由预测、时序冲突消解、Session 热重构及多租户物理隔离。
2. **核心机制**：
   - 动态添加 sys.path 保证测试查找路径正确。
   - 调用 `pytest.main` 执行测试，并在控制台高亮输出格式化的测试结果。
"""

import sys
import os
import pytest

# 物理定位并添加路径
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if os.path.join(current_dir, "app") not in sys.path:
    sys.path.insert(0, os.path.join(current_dir, "app"))

def main():
    """执行全部 pytest 测试并打印报告。"""
    print("==========================================================")
    echo_cyan = "\033[96m"
    echo_end = "\033[0m"
    print(f"{echo_cyan}🧪  正在启动多层级记忆增强 Agent 单元与集成测试套件...{echo_end}")
    print("==========================================================")
    
    # 执行 pytest，-s 代表允许打印 stdout，-v 代表详细列表
    exit_code = pytest.main(["tests/", "-s", "-v"])
    
    print("==========================================================")
    if exit_code == 0:
        echo_green = "\033[92m"
        print(f"{echo_green}🎉  所有测试用例已全部通过！过关校验成功。{echo_end}")
    else:
        echo_red = "\033[91m"
        print(f"{echo_red}❌  测试套件运行失败，请查看上方详细报错。{echo_end}")
    print("==========================================================")
    
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
