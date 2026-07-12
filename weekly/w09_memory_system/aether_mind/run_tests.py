"""
AetherMind Test Suite Runner
============================

设计方案:
---------
本脚本作为自动化测试启动入口，在当前工作区虚拟环境的 pytest 套件下运行
`tests/` 目录下的所有单元测试与集成测试。
自动补全 `PYTHONPATH` 确保 `aether_mind` 包能够正确被测试用例导入。
"""

import sys
import os
import pytest

if __name__ == "__main__":
    # 1. 动态将当前项目根目录与主工作区根目录添加到 python path 中，防止测试时 ModuleNotFoundError
    current_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_root = os.path.abspath(os.path.join(current_dir, "../../.."))
    sys.path.insert(0, workspace_root)
    sys.path.insert(0, current_dir)

    
    logger_header = "=" * 50
    print(logger_header)
    print("AetherMind V2 自动化测试套件启动...")
    print(logger_header)

    # 2. 执行 pytest，传递当前项目目录下的 tests 路径
    test_path = os.path.join(current_dir, "tests")
    exit_code = pytest.main([
        "-v",
        "-s",
        test_path
    ])
    
    sys.exit(exit_code)
