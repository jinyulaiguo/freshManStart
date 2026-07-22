#!/usr/bin/env python3
"""
Day 70 自动化测试运行器

使用方式：
    python run_tests.py              # 运行所有测试
    python run_tests.py --no-llm     # 仅运行无 LLM 依赖的测试（路由 + 熔断 + 隔离）
"""
import sys
import subprocess


def main():
    no_llm = "--no-llm" in sys.argv

    print("=" * 70)
    print("🧪 Day 70 CVE Triage Pipeline — 自动化测试套件")
    print("=" * 70)

    if no_llm:
        # 仅运行不依赖真实 LLM 的测试模块
        test_targets = [
            "tests/test_nodes.py",
            "tests/test_routers.py",
            "tests/test_circuit_breaker.py",
            "tests/test_tenant_isolation.py",
        ]
        print("\n📋 模式：仅运行无 LLM 依赖测试（跳过 test_integration.py 中的真实 API 场景）\n")
    else:
        test_targets = ["tests/"]
        print("\n📋 模式：运行全部测试（包含集成测试，不调用真实 LLM）\n")

    cmd = [
        sys.executable, "-m", "pytest",
        *test_targets,
        "-v",
        "--tb=short",
        "--no-header",
    ]

    result = subprocess.run(cmd, cwd=__file__.replace("run_tests.py", ""))
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
