"""
AetherMind Context Engineering & Prompt Builder
==============================================

设计方案:
---------
本模块实现上下文拼装器 `ContextBuilder`。
负责将大模型的全部输入参数在运行时组装为最终的 messages 数组，并执行严格的
**Context Token 预算防爆机制 (Context Budget Enforcement)**。

核心组装逻辑 (两端夹逼策略):
--------------------------
1. 为防止大模型在超长 Context 的中段遗失关键信息（Lost in the Middle 痛点），
   RAG 文档切片在 ReRank 时重排为首尾分布。
2. 提示词分层组装：
   - 头部 System Prompt：注入用户人设偏好、会话摘要、以及重排后的 RAG 知识和 GraphRAG 图论线索。
   - 对话历史 History：保留最近 N 轮（默认 4 条）的活跃对话记录。
   - 尾部 User Prompt：注入用户最新 Query 问题。
3. Token 防溢出裁剪：
   - 系统、摘要、新 Query 为最高优先级，严禁裁切。
   - 其次保留最近活跃对话消息。
   - 如超预算（以字符数进行近似计算），按由远到近、优先级由低到高的顺序物理裁剪旧对话及 RAG Chunks。

结构说明:
---------
- ContextBuilder: 上下文提示词组装与防溢出控制器。
"""

from typing import List, Dict, Any
from aether_mind.utils.logging import logger
from aether_mind.config import settings


class ContextBuilder:
    """
    上下文构建与 Token 预算拦截控制器。
    """

    def __init__(self, char_budget: int = 4000):
        """
        初始化拼装器。

        Args:
            char_budget (int): 上下文最大字符数上限（默认 4000），防止超出大模型窗口或暴涨费用。
        """
        self.char_budget = char_budget

    def assemble(
        self,
        query: str,
        long_term_memories: List[str],
        rag_chunks: List[Any],
        graph_rag_context: str,
        session_summary: str,
        active_history: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        分层拼装并计算/裁剪出最终的大模型输入提示词。

        Args:
            query (str): 用户 Query。
            long_term_memories (List[str]): 检索出的长期个性化记忆。
            rag_chunks (List[Any]): 检索并 Rerank 的客观文档切片列表（支持字符串或包含 source/text 字典）。
            graph_rag_context (str): 知识图谱关联检索线索。
            session_summary (str): 会话累积背景摘要。
            active_history (List[Dict[str, Any]]): 滑窗内最近对话历史。

        Returns:
            List[Dict[str, Any]]: 组装完成且安全未爆的最终大模型 Messages 格式列表。
        """
        # 1. 组装背景知识
        memories_str = "\n".join(f"- {m}" for m in long_term_memories) if long_term_memories else "无"
        
        rag_parts = []
        if rag_chunks:
            for c in rag_chunks:
                if isinstance(c, dict):
                    text = c.get("text", "")
                    source = c.get("source", "未知来源")
                    rag_parts.append(f"[文档切片 (来源: {source})]:\n{text}")
                else:
                    rag_parts.append(f"[文档切片]:\n{c}")
            rag_str = "\n\n".join(rag_parts)
        else:
            rag_str = "无"
        
        # 组合 RAG 文本与图谱检索线索
        knowledge_parts = []
        if rag_str != "无":
            knowledge_parts.append(rag_str)
        if graph_rag_context:
            knowledge_parts.append(f"[图谱拓扑综述]:\n{graph_rag_context}")
            
        rag_knowledge_final = "\n\n".join(knowledge_parts) if knowledge_parts else "无"
        summary_final = session_summary if session_summary else "无"

        # 2. 填充 System Prompt 模板
        system_content = (
            "你是一个专业的 AI Agent 开源框架与多协同技术研究助手。\n"
            "请结合以下给定的上下文背景和用户偏好，提供严密、客观的分析。\n\n"
            "【注意】：如果下面的【关于用户的长期人设与偏好记忆】中包含用户的特定技术偏好（而非'无'），\n"
            "当用户提问关于其技术习惯、喜欢用什么等个人问题时，你必须直接、明确地根据该偏好回答，\n"
            "说出对应的名称（例如：如果记忆中写着用户极其偏好使用某个框架，你应该直接说出该框架名称），严禁假装不知道或再次向用户提问。\n\n"
            "【引用规范】：在回答用户问题时，请务必紧密依据给定的【检索到的开源框架原理解析与背景知识】。如果采信了某个【文档切片】的内容，你必须且只能在回答句子的末尾使用 `[来源: 文件名]` (如 `[来源: doc_name.txt]`) 进行精确的信息来源标注，绝对不能编造不存在的文件来源。\n\n"
            "【关于用户的长期人设与偏好记忆】:\n"
            f"{memories_str}\n\n"
            "【检索到的开源框架原理解析与背景知识】:\n"
            f"{rag_knowledge_final}\n\n"
            "【先前会话的累计背景摘要】:\n"
            f"{summary_final}\n"
        )


        # 3. 计算保留优先级与 Token 裁剪
        # 固定开销: System Prompt + 最新 Query = 绝对保留
        system_msg = {"role": "system", "content": system_content}
        query_msg = {"role": "user", "content": query}
        
        # 可变开销: 历史对话列表 (History)
        history_msgs = []
        for msg in active_history:
            history_msgs.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        # 4. 执行防溢出截断 (Budget Enforcement)
        # 按照优先级，如果超出 char_budget：
        # 我们最先裁剪较远的历史对话，其次减少 RAG 知识片段的注入
        total_len = len(system_content) + len(query) + sum(len(m["content"]) for m in history_msgs)

        if total_len <= self.char_budget:
            # 未超限，直接拼接输出
            return [system_msg] + history_msgs + [query_msg]

        logger.warning(
            f"[Prompt 预算监控] 当前总长度 ({total_len} 字符) 超出预算 ({self.char_budget} 字符)，启动物理裁剪..."
        )

        # 从头（最老的消息）开始物理裁切历史对话，直到满足预算，或只剩 2 条消息
        while total_len > self.char_budget and len(history_msgs) > 2:
            removed = history_msgs.pop(0)
            total_len -= len(removed["content"])
            logger.info(f"[预算控制] 裁剪掉一条老旧历史消息: '{removed['content'][:30]}...'")

        # 如果还是超出，只能裁剪 System Prompt 中的 RAG 文本（降级为单轮常识问答）
        if total_len > self.char_budget:
            logger.warning("[预算控制] 对话裁剪后依然超额，强制限制 RAG 提示词注入长度...")
            # 缩减 system_content 长度重新拼装
            system_content_short = (
                "你是一个专业的 AI Agent 开源框架与多协同技术研究助手。\n"
                "【注意】：如果【关于用户的长期人设与偏好记忆】中包含用户的特定技术偏好（而非'无'），"
                "当用户询问其个人的偏好或技术习惯时，你必须直接、具体地引用并说出对应的名称（例如：用户偏好使用某个框架，你应该直接说出该框架名称），严禁假装不知道。\n\n"
                "【关于用户的长期人设与偏好记忆】:\n"
                f"{memories_str}\n\n"
                "【先前会话的累计背景摘要】:\n"
                f"{summary_final}\n"
                "(警告: RAG 客观文档因上下文过长已被系统忽略)\n"
            )
            system_msg["content"] = system_content_short

        return [system_msg] + history_msgs + [query_msg]
