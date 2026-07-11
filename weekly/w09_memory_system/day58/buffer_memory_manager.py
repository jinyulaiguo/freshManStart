"""
Day 58: 短期记忆管理 - 基于滑动窗口与 Token 计量的异步摘要压缩 (Standard Answer)

设计方案说明：
1. **设计意图**：
   本类实现了非阻塞异步摘要压缩和精准切片替换，解决了并发长会话状态下工作记忆 Token 膨胀的问题，
   且通过时序切片定位（slice_index）阻断了并发下的 Race Condition。
2. **类结构**：
   - `BufferMemoryManager`: 核心管理器。
     - `append(message)`: 追加新消息并异步检测阈值。
     - `get_messages()`: 提供获取最新拼接摘要上下文的方法。
     - `_async_summarize(slice_index)`: 核心异步协程，完成大模型调用与原地部分切片更新。
3. **时序保护数据流**：
   - 发起后台总结时，传入当前的 `slice_index = len(self.messages)`。
   - 大模型在后台运行需要 1.5 秒。此期间用户新发的消息追加在 `self.messages[slice_index:]`。
   - 大模型总结完成后，替换操作为：`self.messages = self.messages[slice_index:]`（即物理保留后台响应期间新发的消息）。
"""

import asyncio
import sys
from typing import List, Dict, Any, Optional
from weekly.w04_prompt_and_http.utils import LLMClient

class BufferMemoryManager:
    """具备异步摘要压缩与时序一致性防护的短期记忆管理器"""

    def __init__(self, token_limit: int = 300, client: Optional[LLMClient] = None):
        """初始化短期记忆管理器。

        Args:
            token_limit: 触发异步摘要的字符长度阈值。
            client: 真实大模型请求客户端实例。
        """
        self.token_limit = token_limit
        self.client = client or LLMClient()
        
        # 存放短期活跃消息的列表
        self.messages: List[Dict[str, Any]] = []
        
        # 存放后台归约出来的最新会话摘要
        self.current_summary: str = ""
        
        # 并发状态锁，防止多个后台总结任务同时启动
        self._is_summarizing: bool = False

    def append(self, message: Dict[str, Any]) -> None:
        """向工作记忆追加一条消息。

        若累计消息长度超过 token_limit 且当前未在总结中，则在后台触发异步压缩。

        Args:
            message: 符合格式的消息字典。
        """
        # 步骤 1: 类型防御校验
        if not isinstance(message, dict) or "role" not in message or "content" not in message:
            raise ValueError("Invalid message contract: 'role' and 'content' are required.")
            
        # 步骤 2: 将消息追加至内部数组中
        self.messages.append(message)
        
        # 步骤 3: 计量总 Token（此处使用字符数长度简化计算）
        total_tokens = sum(len(msg["content"]) for msg in self.messages)
        
        # 步骤 4: 触发检测，如果超过阈值且当前未启动总结，则派发非阻塞后台异步压缩任务
        if total_tokens > self.token_limit and not self._is_summarizing:
            # 同步阶段立即加锁，防止 asyncio.create_task 排队调度期间因重入导致发起多个并发总结任务
            self._is_summarizing = True
            
            # 精准切片锁定：当前需要进行压缩的历史范围为 [0:slice_index]
            slice_index = len(self.messages)
            print(f"\n[Token 监控] 检测到 Token 达到限制 ({total_tokens}/{self.token_limit})。")
            print(f"[Token 监控] 派发后台异步摘要任务，锁定消息切片数: {slice_index} ...")
            
            # 使用 asyncio.create_task 物理派发后台任务，不阻塞主流程执行
            asyncio.create_task(self._async_summarize(slice_index))

    def get_messages(self) -> List[Dict[str, Any]]:
        """获取当前活跃的全部上下文消息列表（自动拼接最新摘要）。

        Returns:
            符合大模型输入的上下文消息列表。
        """
        # 步骤 1: 若当前存在有效的会话摘要，则将其拼入 system prompt 头部
        if self.current_summary:
            summary_prompt = {
                "role": "system",
                "content": f"你是一个专业的 AI 助手。以下是先前与该用户交互的精炼历史摘要，请作为当前回答的参考背景信息：\n=== 历史摘要 ===\n{self.current_summary}\n============="
            }
            return [summary_prompt] + self.messages
            
        return list(self.messages)

    async def _async_summarize(self, slice_index: int) -> None:
        """后台非阻塞协程：调用大模型将历史消息归纳并精准更新上下文。

        Args:
            slice_index: 触发总结那一刻需要进行归约的活跃消息切片终点。
        """
        # 此时锁已在同步 append 阶段锁定，无需重复锁定
        
        # 步骤 2: 截取锁定切片进行压缩
        messages_to_compress = self.messages[:slice_index]
        
        # 构造大模型 Prompt 进行总结归纳
        summary_prompt = [
            {
                "role": "system",
                "content": "你是一个高保真的会话归纳引擎。请将以下对话历史精炼总结为一段话，核心保留用户的名称、职业、技术偏好以及当前提及的重要项目信息。总结需极其精炼，禁止废话。"
            },
            {
                "role": "user",
                "content": f"请对以下对话历史进行压缩总结：\n{messages_to_compress}"
            }
        ]
        
        try:
            print("[后台摘要] 正在请求大模型生成归约摘要...")
            # 步骤 3: 异步请求大模型，此时主交互线程可以自由接收用户输入并返回响应
            summary_result = await self.client.request_llm(summary_prompt, temperature=0.3)
            print(f"[后台摘要] 总结生成成功：\"{summary_result.strip()}\"")
            
            # 步骤 4: 更新当前的系统摘要
            self.current_summary = summary_result.strip()
            
            # 步骤 5: 防御时序竞争 (Race Condition)
            # 仅物理移除 [0:slice_index] 范围的消息，保留在后台大模型处理期间用户新追加的消息 (即 index >= slice_index 部分)
            self.messages = self.messages[slice_index:]
            print(f"[后台摘要] 上下文原地替换完成。剩余活跃消息数: {len(self.messages)}")
            
        except Exception as e:
            # 步骤 6: 异常隔离，防止网络/API 报错导致总结状态锁死锁
            print(f"❌ [后台摘要] 后台异步总结任务执行失败: {e}", file=sys.stderr)
            
        finally:
            # 步骤 7: 无论成功与否，必须释放并发锁，确保后续 Token 超标能再次触发总结
            self._is_summarizing = False


# 调试主入口与并发验证
async def main() -> None:
    print("=== 运行 Day 58 短期记忆异步滑窗标准答案 ===")

    # 1. 实例化管理器，设置 Token 阈值为 120 字符
    manager = BufferMemoryManager(token_limit=120)

    # 2. 追加多轮消息以超越阈值
    print("\n--- 步骤 1: 用户输入多轮对话，引发 Token 超标 ---")
    manager.append({"role": "user", "content": "你好，我叫李明，我是一个 Python 开发者，主要负责多智能体并发调度系统的设计。"})
    manager.append({"role": "assistant", "content": "你好，李明！很高兴能与你探讨 Python 并发系统，我们可以聊聊 asyncio 和多线程相关的工程落地。"})
    
    # 此时总消息字符数已远超 120，后台异步总结任务已被非阻塞启动
    print(f"当前活跃消息数: {len(manager.messages)}")

    # 3. 模拟时序竞争（在大模型进行总结的 1~2 秒内，用户继续发出两条新消息）
    print("\n--- 步骤 2: 模拟时序竞争（在后台总结期间，用户继续进行输入） ---")
    manager.append({"role": "user", "content": "我的并发调度系统目前在遇到 API 超时时容易崩溃，不知道有什么防错设计？"})
    manager.append({"role": "assistant", "content": "你可以使用超时机制（httpx.Timeout）并在后台任务中加入 try...except 捕获，同时确保重设锁标记。"})
    
    print(f"当前活跃消息数（含异步期间追加的消息）: {len(manager.messages)}")

    # 4. 等待后台异步任务执行完毕（使用自旋检测锁状态，确保后台任务执行完后立即向下推进）
    print("\n--- 步骤 3: 等待后台异步总结任务执行完成 ---")
    wait_seconds = 0
    while manager._is_summarizing and wait_seconds < 30:
        await asyncio.sleep(1.0)
        wait_seconds += 1
    print(f"后台任务等待结束，共等待了 {wait_seconds} 秒。")

    # 5. 验证上下文拼接与时序一致性
    print("\n--- 步骤 4: 验证活跃上下文状态 ---")
    current_context = manager.get_messages()
    
    print("\n最终返回给 LLM 的上下文列表:")
    for idx, msg in enumerate(current_context):
        print(f"[{idx}] {msg['role'].upper()}: {msg['content'][:80]}...")

    # 确认后台响应期间新发的消息是否被完美保留（应该依然存在）
    has_race_survived = any("可以使用超时机制" in m["content"] for m in current_context)
    print(f"\n并发时序保护校验 (新消息未被误抹除): {'✅ 通过' if has_race_survived else '❌ 失败'}")

if __name__ == "__main__":
    asyncio.run(main())
