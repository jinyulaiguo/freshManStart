"""
OpsChat CLI - 数据模型定义 (models.py)

=========================================
设计方案说明
=========================================
1. 设计意图：
   提供流式输出中各个层级传递的标准数据实体。包含流式文本块 (StreamChunk)、
   性能度量统计 (StreamMetrics) 以及审计记录模型 (AuditRecord)，确保各模块间数据交互的标准与一致性。

2. 类与函数结构：
   - StreamChunk (dataclass): 包含生成内容、模型标识、结束标记的微型数据结构。
   - StreamMetrics (dataclass): 记录首字延迟 (TTFT)、吞吐速率 (TPS) 等性能指标。
   - AuditRecord (dataclass): 审计日志结构，包含 Token 数量、美元成本、首字延迟和降级标志。

3. 关键数据流流向：
   `LLM 客户端流式输出` -> `产生 StreamChunk` 
   `流式传输结束` -> `汇总生成 StreamMetrics` 
   `会话持久化` -> `由 StreamMetrics 组装生成 AuditRecord` -> `写入 CSV 审计日志`
=========================================
"""

from dataclasses import dataclass
from typing import Optional

@dataclass
class StreamChunk:
    """
    流式返回的单个文本分块实体。
    """
    content: str
    model_name: str
    finish_reason: Optional[str] = None

    def __repr__(self) -> str:
        return f"StreamChunk(content={self.content!r}, model={self.model_name}, finish_reason={self.finish_reason})"


@dataclass
class StreamMetrics:
    """
    流式生成性能度量统计实体。
    """
    ttft_ms: float          # 首字延迟 (Time to First Token)，单位为毫秒
    total_time_ms: float    # 整体对话生成耗时，单位为毫秒
    tokens_per_sec: float   # 单词生成吞吐速率 (Tokens / 秒)
    total_tokens: int       # 累计产出的 Token 数量 (由生成的 content 字符或 Token 数统计)

    def __repr__(self) -> str:
        return (f"StreamMetrics(ttft={self.ttft_ms:.2f}ms, "
                f"total_time={self.total_time_ms:.2f}ms, "
                f"tps={self.tokens_per_sec:.2f} tokens/s, "
                f"tokens={self.total_tokens})")


@dataclass
class AuditRecord:
    """
    审计日志记录实体，对应 CSV 文件中的单行数据。
    """
    timestamp: str          # ISO 格式的审计触发时间戳
    session_id: str         # 会话 ID
    model_name: str         # 最终响应大模型的名称
    input_tokens: int       # 输入上下文所占 Token 数量
    output_tokens: int      # 大模型输出所占 Token 数量
    cost_usd: float         # 产生的美元账单费用
    ttft_ms: float          # 首字时延 (毫秒)
    is_fallback: bool       # 本次请求是否触发了动态 Fallback 降级
