"""
设计方案：
- 设计意图：构建综合实战项目的入口引导模块 `main.py`。它用于贯穿演示 Week 1 & Week 2 的所有 14 天核心技术指标。通过 8 个分阶段的自动化测试演示，集中展现配置加载、日志树过滤、工具反射发现、Pydantic 输入强校验、并发协程分发、回调钩子链路、指数退避重试以及状态归约报告。
- 类与函数结构：
  - `main()` 异步函数：流程驱动函数。
  - 各个 Phase 的子逻辑打印快照。
- 关键数据流向：
  - 启动 -> 加载 `.env` 配置 -> 初始化日志树 -> 反射注册 tools 包中的类 -> 并发分发 API 任务 -> 制造防御性报错 -> 获取最终的 `RunnerState` 归约状态审计快照。
"""

import asyncio
import time
from weekly.w02_pydantic_and_async.project.config.settings import load_config
from weekly.w02_pydantic_and_async.project.log.factory import create_logger
from weekly.w02_pydantic_and_async.project.core.registry import ToolRegistry
from weekly.w02_pydantic_and_async.project.core.runner import AsyncToolRunner
from weekly.w02_pydantic_and_async.project.callbacks.console_tracer import ConsoleTracer
from weekly.w02_pydantic_and_async.project.exceptions.base import BaseProjectError
from weekly.w02_pydantic_and_async.project import tools

async def main():
    # =========================================================================
    # Phase 1: 加载配置 (.env → AppSettings)
    # =========================================================================
    print("\n" + "═" * 60)
    print("📋 [Phase 1] 正在加载环境配置...")
    print("═" * 60)
    settings = load_config()
    print(f"  ├─ HTTP 超时配置: {settings.http_timeout} 秒")
    print(f"  ├─ 最大重试次数: {settings.max_retries} 次")
    print(f"  ├─ 日志级别: {settings.log_level} | 是否写磁盘文件: {settings.log_to_file}")
    print(f"  ├─ 本地日志路径: {settings.log_file_path}")
    print(f"  └─ 天气/汇率 API 基地址: {settings.weather_api_base} | {settings.exchange_api_base}")

    # =========================================================================
    # Phase 2: 初始化日志系统（Logger 继承链）
    # =========================================================================
    print("\n" + "═" * 60)
    print("🌲 [Phase 2] 初始化日志树与 Handlers 分发...")
    print("═" * 60)
    logger = create_logger("main", settings)
    logger.info("系统日志引擎装配成功，支持控制台彩色和文件结构化 JSON 输出。")

    # =========================================================================
    # Phase 3: 注册工具（Registry + 自动发现）
    # =========================================================================
    print("\n" + "═" * 60)
    print("🔍 [Phase 3] 开始通过 inspect 反射扫描并自动发现工具类...")
    print("═" * 60)
    registry = ToolRegistry(settings)
    # 反射扫描 tools 模块中定义的所有工具子类并构造注入 settings 依赖
    registry.discover(tools)
    logger.info(f"注册表工具反射状态: {repr(registry)}")

    # =========================================================================
    # Phase 4: 导出 JSON Schema（OpenAI Function Calling 格式）
    # =========================================================================
    print("\n" + "═" * 60)
    print("📄 [Phase 4] 批量反射导出工具参数定义 JSON Schema (Function Calling)...")
    print("═" * 60)
    schemas = registry.list_schemas()
    for name, sc in schemas.items():
        print(f"\n🔑 工具名称: {name}")
        print(f"  ├─ 描述信息: {sc.get('description', '')}")
        print(f"  └─ 参数字段: {list(sc.get('properties', {}).keys())}")

    # =========================================================================
    # Phase 5: 初始化调度引擎并单工具执行演示
    # =========================================================================
    print("\n" + "═" * 60)
    print("🚀 [Phase 5] 初始化调度引擎并发起单工具安全调用流程...")
    print("═" * 60)
    tracer = ConsoleTracer(create_logger("callbacks", settings))
    runner = AsyncToolRunner(settings, registry, callback=tracer)

    # 1. 运算器调用 (本地 CPU)
    logger.info("准备调用本地计算器工具...")
    calc_res = await runner.run_tool(
        "calculator",
        '{"x": 100.5, "y": 2.0, "operator": "*"}'
    )
    logger.info(f"计算器返回结果: {calc_res}")

    # 2. 天气工具调用 (真实网络 API)
    logger.info("准备调用真实天气查询工具 (网络 I/O)...")
    try:
        weather_res = await runner.run_tool(
            "weather",
            '{"city": "Beijing", "days": 3}'
        )
        logger.info(f"天气工具返回结果: {weather_res}")
    except Exception as e:
        logger.warning(f"天气工具执行失败 (已捕获以防阻碍 demo): {e}")

    # 3. 汇率工具调用 (真实网络 API)
    logger.info("准备调用真实汇率转换工具 (网络 I/O)...")
    try:
        exchange_res = await runner.run_tool(
            "exchange",
            '{"base_currency": "USD", "target_currency": "CNY", "amount": 100.0}'
        )
        logger.info(f"汇率工具返回结果: {exchange_res}")
    except Exception as e:
        logger.warning(f"汇率工具执行失败 (已捕获以防阻碍 demo): {e}")

    # =========================================================================
    # Phase 6: 高吞吐并发调度（3 城市天气 + 2 汇率转换）
    # =========================================================================
    print("\n" + "═" * 60)
    print("⚡ [Phase 6] 批量工具非阻塞异步高并发派发 (asyncio.gather)...")
    print("═" * 60)
    batch_requests = [
        {"name": "weather", "args": '{"city": "Shanghai", "days": 1}'},
        {"name": "weather", "args": '{"city": "Guangzhou", "days": 1}'},
        {"name": "weather", "args": '{"city": "Shenzhen", "days": 1}'},
        {"name": "exchange", "args": '{"base_currency": "EUR", "target_currency": "CNY", "amount": 50.0}'},
        {"name": "exchange", "args": '{"base_currency": "GBP", "target_currency": "USD", "amount": 100.0}'},
        {"name": "calculator", "args": '{"x": 999.0, "y": 999.0, "operator": "*"}'}
    ]

    start_time = time.perf_counter()
    batch_results = await runner.run_batch(batch_requests)
    duration = time.perf_counter() - start_time
    
    logger.info(f"并发批处理执行完毕！总计耗时: {duration:.4f}s（大幅小于串行累加等待时间）")
    for idx, res in enumerate(batch_results):
        logger.info(f"  ├─ 任务 #{idx+1} 响应结果: {res}")

    # =========================================================================
    # Phase 7: 防御性压力测试与异常链可观测性
    # =========================================================================
    print("\n" + "═" * 60)
    print("🛡️ [Phase 7] 防御性边界测试：制造异常并验证因果链 (raise ... from)...")
    print("═" * 60)

    # 1. 脏输入校验失败拦截
    logger.info("引发 Pydantic 模型校验拦截：城市名输入为空字符串...")
    try:
        await runner.run_tool("weather", '{"city": "", "days": 1}')
    except BaseProjectError as e:
        logger.error(f"成功拦截异常! 业务错误码: {e.error_code} | 堆栈包含原因为: {type(e.__cause__).__name__}")

    # 2. 运行时零除错误
    logger.info("引发本地工具计算异常：除以零操作...")
    try:
        await runner.run_tool("calculator", '{"x": 10.0, "y": 0.0, "operator": "/"}')
    except BaseProjectError as e:
        logger.error(f"成功捕获计算异常! 业务错误码: {e.error_code} | 友好提示: {e.user_message}")

    # 3. 汇率货币不支持异常
    logger.info("引发汇率业务参数逻辑错误：输入相同货币互转...")
    try:
        await runner.run_tool(
            "exchange",
            '{"base_currency": "CNY", "target_currency": "CNY", "amount": 100}'
        )
    except BaseProjectError as e:
        logger.error(f"成功拦截相同货币转换! 友好提示: {e.user_message}")

    # 4. 未注册工具
    logger.info("调用未注册的工具名称...")
    try:
        await runner.run_tool("gpt_4_chat", '{"prompt": "hello"}')
    except BaseProjectError as e:
        logger.error(f"成功拦截未注册工具! 异常错误码: {e.error_code} | 提示: {e.message}")

    # =========================================================================
    # Phase 8: 状态归约报告
    # =========================================================================
    print("\n" + "═" * 60)
    print("📊 [Phase 8] 打印引擎全局审计状态快照 (RunnerState Reducer)...")
    print("═" * 60)
    state = runner.state
    print(f"  ├─ 总执行步数 (steps): {state['total_steps']}")
    print(f"  ├─ 成功执行次数: {state['success_count']}")
    print(f"  ├─ 失败拦截次数: {state['error_count']}")
    print(f"  ├─ 历史结算结果汇编 (tool_results):")
    for k, v in state["tool_results"].items():
        print(f"  │    ├─ [{k}]: {v}")
    print("  └─ 历史全生命周期日志记录 (messages):")
    for msg in state["messages"]:
        print(f"       * {msg}")
    print("\n" + "═" * 60)
    print("🎉 异步多工具调度引擎（Real-World Tool Runner）演示全部完成！")
    print("═" * 60)

if __name__ == "__main__":
    asyncio.run(main())
