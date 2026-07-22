"""
Buffer Memory Manager Module.

设计方案说明：
1. **设计意图**：
   本模块实现短期工作记忆管理器，负责维护当前会话（Working Memory）的活跃消息窗口。
   为了防止上下文物理窗口（Token 限制）迅速溢出以及降低长对话下的 API 开销，
   本管理器支持基于 Token 计量（字符长度限制）的后台非阻塞异步摘要压缩与滑窗更新。
2. **类结构**：
   - `BufferMemoryManager`: 短期记忆滑动窗口监控管理器。
     - `append(message, store, session_id)`: 追加新消息，并在超限时自动启动异步归约任务。
     - `get_messages()`: 返回包含先前摘要 system prompt 在内的上下文消息列表。
     - `_async_summarize(slice_index, store, session_id)`: 后台大模型压缩线程。
     - `load_state(store, session_id)`: 从数据库中物理恢复摘要与活跃消息列表，保障断电一致性。
3. **时序与 Race Condition 防护**：
   - 使用异步锁机制 `_is_summarizing` 防止多任务重入。
   - 采用精准切片 `slice_index` 隔离：在后台网络 API 请求期间，用户新追加的交互消息会被安全保留，不会被后台归约后覆写抹除。
"""

import sys
import os
import asyncio
from typing import List, Dict, Any, Optional
from weekly.w04_prompt_and_http.utils import LLMClient

# 确保导入 config
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from config import get_llm_client
from db import PersistenceStore

class BufferMemoryManager:
    """具备异步摘要压缩与时序一致性防护的短期记忆管理器。"""

    def __init__(self, token_limit: int = 1500, client: Optional[LLMClient] = None):
        """初始化短期记忆管理器。

        Args:
            token_limit: 触发异步摘要的字符长度阈值（简化的 Token 计数方式）。
            client: 真实大模型请求客户端。
        """
        self.token_limit = token_limit
        self.client = client or get_llm_client()
        
        # 内存中维护的当前活跃消息窗口（未总结的消息列表）
        self.messages: List[Dict[str, str]] = []
        
        # 当前会话的累计精炼摘要
        self.current_summary: str = ""
        
        # 当前会话 ID 标识
        self.current_session_id: Optional[str] = None
        
        # 并发状态锁，防止在后台大模型请求期间因多次追加触发重入
        self._is_summarizing: bool = False

    async def load_state(self, store: PersistenceStore, session_id: str) -> None:
        """断电恢复接口：从 SQLite 物理介质中完全复原内存摘要与活跃滑动窗口状态。

        Args:
            store: 数据库物理存储器。
            session_id: 会话唯一标识符。
        """
        self.current_session_id = session_id
        # 步骤 1: 物理载入该 session 存储的累计摘要
        self.current_summary = await store.get_session_summary(session_id)
        
        # 步骤 2: 载入尚未被摘要的活跃会话历史消息流
        self.messages = await store.load_session_context(session_id)
        
        print(f"[短期记忆] 重塑状态完成。累积摘要长度: {len(self.current_summary)}, 活跃消息数: {len(self.messages)}")

    def append(self, message: Dict[str, str], store: PersistenceStore, session_id: str) -> None:
        """追加一条新交互消息到工作记忆，并在超标时触发非阻塞后台摘要任务。

        Args:
            message: 符合格式的消息字典，如 {"role": "user", "content": "内容"}。
            store: 数据库持久化存储器，用于在后台完成摘要和消息物理清理。
            session_id: 当前会话 ID。
        """
        # 步骤 1: 契约类型安全检查
        if not isinstance(message, dict) or "role" not in message or "content" not in message:
            raise ValueError("消息契约不合法，必须包含 'role' 与 'content' 字段。")
            
        # 步骤 2: 写入内存中的工作记忆消息列表
        self.messages.append(message)
        
        # 步骤 3: 计量当前内存消息长度（以字符数代表 Token 占用）
        total_tokens = sum(len(msg["content"]) for msg in self.messages)
        
        # 步骤 4: 若超出设定阈值且当前未处于后台总结中，同步上锁并物理启动异步总结任务
        if total_tokens > self.token_limit and not self._is_summarizing:
            self._is_summarizing = True
            
            # 精准切片锁定：当前需要进行压缩的历史范围是 [0:slice_index]
            slice_index = len(self.messages)
            print(f"\n⚠️ [Token 限制监控] 活跃短期记忆已达 {total_tokens} 字符，超过阈值 {self.token_limit}。")
            print(f"[Token 限制监控] 启动非阻塞后台异步归约摘要任务，锁定切片数: {slice_index} ...")
            
            # 利用 asyncio.create_task 启动非阻塞后台任务，杜绝主进程阻塞
            asyncio.create_task(self._async_summarize(slice_index, store, session_id))

    def get_messages(self) -> List[Dict[str, str]]:
        """获取当前活跃的上下文消息列表。若先前存在累积摘要，则拼装在头部作为 System 背景。

        Returns:
            符合 API 格式的消息字典列表。
        """
        # 若当前存在有效的会话历史摘要，则将其作为 system role 背景拼装在消息最前部
        if self.current_summary:
            system_prompt = {
                "role": "system",
                "content": (
                    "你是一个专业的 AI 助手。\n"
                    "以下是先前与该用户交互的精炼历史摘要，请作为当前回答的参考背景信息，"
                    "确保前后偏好与设定能够保持一致：\n"
                    f"=== 历史摘要 ===\n{self.current_summary}\n============="
                )
            }
            return [system_prompt] + self.messages
            
        return list(self.messages)

    async def _async_summarize(self, slice_index: int, store: PersistenceStore, session_id: str) -> None:
        """后台非阻塞协程：调用大模型将历史消息合并归约，同步更新内存摘要与 SQLite 持久化层。

        Args:
            slice_index: 触发总结那一刻的活跃消息切片终点。
            store: 数据库持久化存储器。
            session_id: 会话 ID。
        """
        # 步骤 1: 截取锁定切片进行压缩归约
        messages_to_compress = self.messages[:slice_index]
        
        # 步骤 2: 组装归约 Prompt
        summary_prompt = [
            {
                "role": "system",
                "content": (
                    "你是一个高保真的会话归纳引擎。你的任务是分析先前的对话历史，"
                    "精炼总结为一段话，核心保留用户的名称、职业、技术偏好以及当前提及的重要项目信息。"
                    "如果先前已经有旧的摘要，你需要将旧摘要与新对话内容合并成一段新摘要。"
                    "总结需极其精炼，严禁输出任何废话或前导介绍词。"
                )
            },
            {
                "role": "user",
                "content": (
                    f"【先前的历史摘要】: \"{self.current_summary}\"\n\n"
                    f"【需要被归约的新对话内容】: \n{messages_to_compress}\n\n"
                    "请输出最新合并摘要："
                )
            }
        ]
        
        try:
            print("[后台摘要] 正在请求大模型生成归约摘要...")
            # 步骤 3: 异步请求大模型（此时主交互线程不受任何影响，可以正常流式生成）
            summary_result = await self.client.request_llm(summary_prompt, temperature=0.3)
            cleaned_summary = summary_result.strip()
            
            # 思维链清洗，如果使用了 DeepSeek 等带有 think 的模型
            if "</THINK>" in cleaned_summary.upper():
                cleaned_summary = cleaned_summary.upper().split("</THINK>")[-1].strip()
                
            print(f"[后台摘要] 摘要生成成功。新摘要: \"{cleaned_summary}\"")
            
            # 步骤 4: 更新内存状态
            self.current_summary = cleaned_summary
            
            # 步骤 5: 防御并发时序竞争 (Race Condition)
            # 原地移除已被归约的 [0:slice_index] 部分，保留后台总结期间用户新发的消息
            self.messages = self.messages[slice_index:]
            
            # 步骤 6: 数据库物理持久化一致性对齐
            # A. 保存最新的摘要到 sessions 表
            await store.update_session_summary(session_id, self.current_summary)
            # B. 同步删除数据库 messages 表中已经被归纳的消息（即最近保留 self.messages 的消息长度）
            await store.keep_last_n_messages(session_id, len(self.messages))
            
            print(f"[后台摘要] 数据库一致性写入与内存切片截断成功。内存剩余消息数: {len(self.messages)}")
            
        except Exception as e:
            # 步骤 7: 异常隔离，防范网络/API 问题导致锁无法释放
            print(f"❌ [后台摘要] 异步压缩归约失败: {e}", file=sys.stderr)
        finally:
            # 步骤 8: 无论成功与否，必须释放并发总结状态锁，确保后续超标时能再次触发
            self._is_summarizing = False
