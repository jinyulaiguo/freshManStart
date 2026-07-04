"""
OpsChat CLI - SRE 智能故障诊断助手终端主入口 (main.py)

=========================================
设计方案说明
=========================================
1. 设计意图：
   整合 Week 3 的所有核心模块，提供一个高可用、可观测、精准计费的 SRE 终端交互界面。
   包含会话管理、自动上下文裁剪、多模型动态降级以及 CSV 计费账单的生成。
   设计美观的命令行 UI 和非阻塞异步 REPL 输入循环。

2. 主要流程：
   - 初始化环境变量与大模型流式适配器。
   - 创建 FallbackController、SessionManager、SmartContextCutter 与 TokenAuditor。
   - 启动异步命令式交互循环 (REPL)。
   - 捕捉各种退出与系统指令（/audit, /clear, /switch, /help）。
   - 实现输入流式输出渲染与性能度量控制台输出。
=========================================
"""

import os
import sys
import asyncio
from typing import List, Dict, Any

from weekly.w03_llm_and_api.project.adapters.minimax_stream_adapter import MiniMaxStreamAdapter
from weekly.w03_llm_and_api.project.adapters.openai_stream_adapter import OpenAIStreamAdapter
from weekly.w03_llm_and_api.project.core.fallback_controller import FallbackController
from weekly.w03_llm_and_api.project.core.session_manager import SessionManager, Session
from weekly.w03_llm_and_api.project.core.context_cutter import SmartContextCutter
from weekly.w03_llm_and_api.project.core.token_auditor import TokenAuditor
from weekly.w03_llm_and_api.project.exceptions import LLMError

# ANSI 颜色转义字符
COLOR_HEADER = "\033[95m"
COLOR_BLUE = "\033[94m"
COLOR_CYAN = "\033[96m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
COLOR_MAGENTA = "\033[95m"
COLOR_BOLD = "\033[1m"
COLOR_RESET = "\033[0m"

SYSTEM_PROMPT = (
    "You are OpsChat AI, a veteran SRE and Linux administration expert. "
    "You help engineers troubleshoot issues with Kubernetes, databases (MySQL/PostgreSQL), "
    "network connectivity, Linux systems, and cloud architectures. "
    "Provide extremely concise, precise, and actionable bash commands or technical analysis. "
    "Always focus on root cause analysis. Avoid introductory fluff and summaries unless requested."
)


def print_banner():
    """
    在终端输出精美的 ASCII 艺术 Banner。
    """
    banner = fr"""
{COLOR_CYAN}{COLOR_BOLD}========================================================================
   ____               _____ _           _        ____ _     ___ 
  / __ \ _ __  ___   / ____| |         | |      / ___| |   |_ _|
 | |  | | '_ \/ __| | |    | |__   __ _| |_    | |   | |    | | 
 | |__| | |_) \__ \ | |    | '_ \ / _` | __|   | |___| |___ | | 
  \____/| .__/|___/  \_____|_| |_|\__,_|\__|    \____|_____|___|
        |_|                                                     
                 -- SRE Smart Diagnostics Terminal (v1.0) --
========================================================================{COLOR_RESET}
    * 架构：{COLOR_BLUE}全异步非阻塞{COLOR_RESET}
    * 容错：{COLOR_GREEN}500ms 动态 Fallback 降级 (MiniMax -> DeepSeek){COLOR_RESET}
    * 安全：{COLOR_YELLOW}LRU 会话限制 + tiktoken 3000 Token 滑动窗口裁剪{COLOR_RESET}
    * 审计：{COLOR_MAGENTA}自动记录 csv 话单计费{COLOR_RESET}
    * 输入 {COLOR_BOLD}exit{COLOR_RESET} 或 {COLOR_BOLD}quit{COLOR_RESET} 退出终端。输入 {COLOR_BOLD}/help{COLOR_RESET} 查看可用命令。
------------------------------------------------------------------------
"""
    print(banner)


async def get_async_input(prompt: str) -> str:
    """
    以非阻塞的方式获取用户键盘输入，防止挂起 asyncio 事件循环。
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, input, prompt)


async def main():
    print_banner()

    # 1. 初始化各层组件
    # 读取环境变量中的 API 密钥
    minimax_key = os.getenv("MINIMAX_API_KEY")
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")

    if not minimax_key or not deepseek_key:
        print(f"{COLOR_YELLOW}[Warning] Missing MINIMAX_API_KEY or DEEPSEEK_API_KEY. "
              f"System will run in MOCK mode for unavailable adapters.{COLOR_RESET}")

    # 实例化大模型流式适配器
    minimax_adapter = MiniMaxStreamAdapter(
        api_key=minimax_key or "mock",
        model_name=os.getenv("MINIMAX_MODEL") or "MiniMax-M3"
    )
    deepseek_adapter = OpenAIStreamAdapter(
        api_key=deepseek_key or "mock",
        model_name="deepseek-chat"
    )

    # 注入 FallbackController，首选 MiniMax，备选 DeepSeek，超时为 500ms (0.5 秒)
    controller = FallbackController(clients=[minimax_adapter, deepseek_adapter], timeout=5)

    # 初始化 SessionManager (LRU 淘汰阈值设为 10)
    session_manager = SessionManager(max_sessions=10)
    
    # 3000 Token 上下文离线裁剪器
    cutter = SmartContextCutter(max_tokens=3000)

    # 话单审计模块
    auditor = TokenAuditor()

    # 当前会话 ID，默认 session_0
    current_session_id = "session_0"

    print(f"{COLOR_GREEN}[System] Core components initialized successfully. Current Session: {current_session_id}{COLOR_RESET}")

    while True:
        try:
            # 非阻塞获取输入
            prompt_str = f"\n{COLOR_CYAN}{COLOR_BOLD}[{current_session_id}]{COLOR_RESET} OpsChat > "
            user_input = await get_async_input(prompt_str)
            user_input = user_input.strip()

            if not user_input:
                continue

            # 命令解析
            if user_input.lower() in ("exit", "quit"):
                summary = auditor.get_summary()
                print(f"\n{COLOR_CYAN}=== 会话退出结算 (可观测性审计) ==={COLOR_RESET}")
                print(f"  * 累计交互请求数: {summary['total_requests']}")
                print(f"  * 累计消耗 Token: {summary['total_tokens']} (Input: {summary['total_input_tokens']} | Output: {summary['total_output_tokens']})")
                print(f"  * 累计美元费用: {COLOR_GREEN}${summary['total_cost_usd']:.6f}{COLOR_RESET}")
                print(f"  * 自动降级切换次数: {summary['fallback_count']}")
                print(f"  * 结构化审计日志保存在: {auditor.csv_filepath}")
                print(f"{COLOR_CYAN}=================================={COLOR_RESET}")
                print(f"{COLOR_GREEN}Goodbye!{COLOR_RESET}")
                break

            elif user_input.startswith("/switch"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print(f"{COLOR_RED}[Error] Usage: /switch <session_id>{COLOR_RESET}")
                else:
                    new_session_id = parts[1].strip()
                    current_session_id = new_session_id
                    print(f"{COLOR_GREEN}[System] Switched to session: {current_session_id}{COLOR_RESET}")
                continue

            elif user_input == "/clear":
                # 清空当前 session 的历史记录
                session = await session_manager.get_session(current_session_id, create_if_missing=True)
                session.history.clear()
                print(f"{COLOR_GREEN}[System] Session {current_session_id} history cleared.{COLOR_RESET}")
                continue

            elif user_input == "/audit":
                summary = auditor.get_summary()
                print(f"\n{COLOR_CYAN}=== 实时 Token 与计费账单审计 ==={COLOR_RESET}")
                print(f"  * 累计请求数: {summary['total_requests']}")
                print(f"  * 累计 Token 消耗: {summary['total_tokens']}")
                print(f"  * 美元总开销: {COLOR_GREEN}${summary['total_cost_usd']:.6f}{COLOR_RESET}")
                print(f"  * 自动降级切换次数: {summary['fallback_count']}")
                print(f"  * CSV 审计日志路径: {auditor.csv_filepath}")
                print(f"{COLOR_CYAN}=================================={COLOR_RESET}")
                continue

            elif user_input == "/help":
                print(f"\n{COLOR_BOLD}可用系统命令清单：{COLOR_RESET}")
                print(f"  * {COLOR_CYAN}/switch <session_id>{COLOR_RESET} : 切换至指定会话（若不存在则新建）")
                print(f"  * {COLOR_CYAN}/clear{COLOR_RESET}               : 清空当前会话的消息历史记录")
                print(f"  * {COLOR_CYAN}/audit{COLOR_RESET}               : 审计当前运行期间的 Token 消耗与美元费用统计")
                print(f"  * {COLOR_CYAN}/help{COLOR_RESET}                : 显示此帮助命令菜单")
                print(f"  * {COLOR_CYAN}exit / quit{COLOR_RESET}          : 安全保存审计日志并退出程序")
                continue

            # 处理用户对话输入
            # 1. 提取当前会话实例
            session = await session_manager.get_session(current_session_id, create_if_missing=True)

            # 2. 追加用户消息入会话历史 (会话并发锁保护)
            await session.append_message({"role": "user", "content": user_input})

            # 3. 构造包含 System Prompt 的完整消息数组，并执行 tiktoken 滑动裁剪
            full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + session.history
            cut_messages = cutter.cut(full_messages)

            # 4. 调用降级控制器，开启异步非阻塞流式生成
            print(f"\n{COLOR_YELLOW}[AI Response]{COLOR_RESET} ", end="", flush=True)
            
            response_text = ""
            start_time = asyncio.get_event_loop().time()
            ttft_measured = 0.0
            
            try:
                # 迭代流式输出
                async for chunk in controller.stream(cut_messages, temperature=0.1):
                    # 打字机输出
                    print(chunk.content, end="", flush=True)
                    response_text += chunk.content

                print() # 换行

                # 5. 生成结束，获取性能元数据与计费审计
                model_used = controller.last_active_model or "Unknown"
                is_fallback = controller.last_is_fallback
                metrics = controller.last_metrics

                ttft_ms = metrics.ttft_ms if metrics else 0.0
                tps = metrics.tokens_per_sec if metrics else 0.0

                # 将 Assistant 响应追加至会话历史中
                await session.append_message({"role": "assistant", "content": response_text})

                # 记录审计日志
                record = auditor.record_audit(
                    session_id=current_session_id,
                    model_name=model_used,
                    input_messages=cut_messages,
                    response_text=response_text,
                    ttft_ms=ttft_ms,
                    is_fallback=is_fallback
                )

                # 输出诊断性能元数据看板
                fb_status = f"{COLOR_RED}Yes (Primary Failed){COLOR_RESET}" if is_fallback else f"{COLOR_GREEN}No{COLOR_RESET}"
                meta_bar = (
                    f"{COLOR_BLUE}------------------------------------------------------------------------\n"
                    f"[Metrics] Model: {COLOR_BOLD}{model_used}{COLOR_RESET} | "
                    f"TTFT: {COLOR_GREEN}{ttft_ms:.1f}ms{COLOR_RESET} | "
                    f"Speed: {COLOR_GREEN}{tps:.1f} tokens/s{COLOR_RESET} | "
                    f"Cost: {COLOR_YELLOW}${record.cost_usd:.6f}{COLOR_RESET} | "
                    f"Fallback: {fb_status}\n"
                    f"------------------------------------------------------------------------{COLOR_RESET}"
                )
                print(meta_bar)

            except Exception as e:
                print(f"\n{COLOR_RED}[Error] Failed to complete generation: {e}{COLOR_RESET}")
                # 清理刚才追加的未闭环 User 消息
                if session.history and session.history[-1]["role"] == "user":
                    session.history.pop()

        except EOFError:
            print(f"\n{COLOR_YELLOW}[System] EOF detected. Exiting...{COLOR_RESET}")
            break
        except KeyboardInterrupt:
            # 捕获 Ctrl+C
            print(f"\n{COLOR_YELLOW}[System] KeyboardInterrupt detected. Please type 'exit' to quit safely.{COLOR_RESET}")
        except Exception as e:
            print(f"\n{COLOR_RED}[Fatal Error] Loop exception: {e}{COLOR_RESET}")


if __name__ == "__main__":
    # 执行主协程
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
