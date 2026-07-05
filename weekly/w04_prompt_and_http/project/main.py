"""
Week 4 Day 28 综合实战 — 流水线主入口 (Main Entry Point)

设计方案：
1. 设计意图：
   纯拼装 + 生命周期管理的无逻辑主入口（遵循规范 §10）。
   只负责：加载环境变量 → 配置日志 → 实例化流水线 → 加载数据集 → 执行批量提取 → 打印报告 → 关闭连接池。
   不承担任何算法实现或策略逻辑。

2. 函数结构：
   - setup_logging(): 配置结构化日志格式
   - print_report(report): 格式化打印流水线执行报告
   - async main(): 主异步入口，串联微引擎拼装与生命周期管理
"""

import sys
import os
import asyncio
import logging

# =====================================================================
# 防御性 sys.path 补丁逻辑
# =====================================================================
current_dir = os.path.dirname(os.path.realpath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "../../.."))

if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from weekly.w04_prompt_and_http.utils import load_env_file
from weekly.w04_prompt_and_http.project.pipeline import ResumePipeline, PipelineReport
from weekly.w04_prompt_and_http.project.sample_resumes import SAMPLE_RESUMES


# =====================================================================
# 日志配置
# =====================================================================

def setup_logging():
    """配置结构化日志输出格式"""
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s [%(levelname)-7s] "
            "%(name)-30s | %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    # 降低 httpx 和 httpcore 的日志噪音
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


# =====================================================================
# 报告打印
# =====================================================================

def print_report(report: PipelineReport):
    """格式化打印流水线执行报告"""
    print("\n" + "=" * 80)
    print("📊 简历结构化提取流水线 — 执行报告")
    print("=" * 80)

    print(f"\n📋 总览:")
    print(f"  总简历数:        {report.total_count}")
    print(f"  成功提取:        {report.success_count} ({report.success_rate:.1f}%)")
    print(f"  自愈纠错成功:    {report.self_corrected_count} "
          f"(占成功总数 {report.self_correction_rate:.1f}%)")
    print(f"  熔断拦截:        {report.breaker_tripped_count}")
    print(f"  最终失败:        {report.failed_count}")
    print(f"  总执行耗时:      {report.total_time_seconds:.2f} 秒")

    print(f"\n📝 各条简历详情:")
    print("-" * 80)

    for result in report.results:
        status = "✅" if result.success else ("⛔ 熔断" if result.breaker_tripped else "❌")
        correction_info = ""
        if result.self_corrected:
            correction_info = f" | 自愈: {result.correction_rounds} 轮"

        print(f"  [{status}] #{result.resume_index:02d} | "
              f"{result.original_text[:50]}...{correction_info}")

        if result.success and result.resume_data:
            data = result.resume_data
            skills_str = ", ".join(
                f"{k}({v.level}分/{v.years_of_experience}年)"
                for k, v in data.skills.items()
            )
            exp_str = ", ".join(
                f"{e.company}({e.position}/{e.years}年)"
                for e in data.work_experience
            )
            print(f"       姓名: {data.name} | 邮箱: {data.email}")
            print(f"       技能: {skills_str}")
            print(f"       经历: {exp_str}")

        if result.error_message and not result.success:
            # 只显示错误消息的前 120 字符
            err_preview = result.error_message[:120]
            print(f"       错误: {err_preview}...")

    print("\n" + "=" * 80)


# =====================================================================
# 主异步入口
# =====================================================================

async def main():
    """主入口：加载 → 实例化 → 执行 → 报告 → 关闭"""
    print("=" * 80)
    print("🚀 Week 4 Day 28 综合实战：高并发简历结构化提取流水线")
    print("=" * 80)

    # 1. 加载环境变量
    load_env_file()

    # 2. 实例化流水线（注入微引擎参数）
    pipeline = ResumePipeline(
        max_concurrency=3,           # 信号量：同时最多 3 个协程请求 LLM
        breaker_threshold=5,         # 熔断器：连续 5 次失败触发熔断
        breaker_cooldown=30.0,       # 熔断器：冷却 30 秒
        max_correction_rounds=2      # 自愈：最多 2 轮纠错重试
    )

    try:
        # 3. 加载简历数据集
        resume_texts = [r["text"] for r in SAMPLE_RESUMES]
        print(f"\n📦 已加载 {len(resume_texts)} 条模拟简历")
        for r in SAMPLE_RESUMES:
            print(f"  #{r['id']:02d} {r['scenario']}")

        # 4. 执行批量提取
        print(f"\n🔄 开始批量提取 (最大并发: {pipeline.max_concurrency})...\n")
        report = await pipeline.run_batch(resume_texts)

        # 5. 打印执行报告
        print_report(report)

    finally:
        # 6. 关闭连接池
        await pipeline.close()


# =====================================================================
# 脚本入口
# =====================================================================

if __name__ == "__main__":
    setup_logging()
    asyncio.run(main())
