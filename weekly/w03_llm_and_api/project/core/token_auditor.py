"""
OpsChat CLI - Token 审计与美元账单计费模块 (token_auditor.py)

=========================================
设计方案说明
=========================================
1. 设计意图：
   提供高精度 Token 审计与美元计费模块。在每次大模型会话交互结束时，
   利用 tiktoken 离线分词器精确统计输入 Prompt 和输出 Response 的 Token 消耗，
   根据配置的费率表计算其所产生的美元费用，并以追加模式写入 CSV 结构化审计日志。
   这为运维团队提供了对 AI 辅助诊断系统的精确费用预算审计支撑。

2. 类与函数结构：
   - TokenAuditor:
     - __init__(csv_filepath: Optional[str] = None): 配置 CSV 输出文件路径。
     - count_input_tokens(messages: List[Dict[str, str]], model_name: str) -> int: 计算输入 Token 数。
     - count_output_tokens(text: str, model_name: str) -> int: 计算输出 Token 数。
     - record_audit(...) -> AuditRecord: 计算本次交互费用，组装并写入 CSV，同时写入内存记录。
     - get_summary() -> Dict[str, Any]: 获取本次运行周期内累计消耗与费用总结。

3. 关键数据流流向：
   `会话生成结束` -> `提取对话输入和输出响应文本`
   -> `tiktoken 编码计算 Token 数` -> `查阅 LLM_PRICING 表计算美元费用`
   -> `创建 AuditRecord` -> `Append 写入 csv 文件` -> `缓存至内存记录中`
=========================================
"""

import os
import csv
import datetime
from typing import List, Dict, Any, Optional
import tiktoken

from weekly.w03_llm_and_api.project.models import AuditRecord
from weekly.w03_llm_and_api.project.config import LLM_PRICING, DEFAULT_AUDIT_LOG_PATH


class TokenAuditor:
    """
    Token 审计与美元账单计费审计类。
    """
    def __init__(self, csv_filepath: Optional[str] = None):
        self.csv_filepath: str = csv_filepath or DEFAULT_AUDIT_LOG_PATH
        self.records: List[AuditRecord] = []
        
        # 预先缓存 tiktoken 编码器以提高多次调用的性能
        self.encodings: Dict[str, tiktoken.Encoding] = {}

    def _get_encoding(self, model_name: str) -> tiktoken.Encoding:
        """
        获取对应模型的 tiktoken 编码器。
        """
        # 对常见模型名做前缀归一化匹配以选用正确的分词表
        if "gpt" in model_name.lower() or "deepseek" in model_name.lower():
            encoding_name = "cl100k_base"
        elif "minimax" in model_name.lower():
            # MiniMax-M3 推荐使用 cl100k_base 做本地 Token 粗估
            encoding_name = "cl100k_base"
        else:
            encoding_name = "cl100k_base"

        if encoding_name not in self.encodings:
            try:
                self.encodings[encoding_name] = tiktoken.get_encoding(encoding_name)
            except Exception:
                self.encodings[encoding_name] = tiktoken.get_encoding("cl100k_base")
        return self.encodings[encoding_name]

    def count_input_tokens(self, messages: List[Dict[str, str]], model_name: str) -> int:
        """
        计算输入对话历史的 Token 数量 (按 ChatML 标准)。
        """
        encoding = self._get_encoding(model_name)
        num_tokens = 0
        for message in messages:
            num_tokens += 4  # 每一条消息的基础封装开销
            num_tokens += len(encoding.encode(message.get("content", "")))
            num_tokens += len(encoding.encode(message.get("role", "")))
        num_tokens += 2  # 最终生成的包装指示开销
        return num_tokens

    def count_output_tokens(self, text: str, model_name: str) -> int:
        """
        计算生成响应文本的 Token 数量。
        """
        encoding = self._get_encoding(model_name)
        return len(encoding.encode(text))

    def record_audit(
        self,
        session_id: str,
        model_name: str,
        input_messages: List[Dict[str, str]],
        response_text: str,
        ttft_ms: float,
        is_fallback: bool
    ) -> AuditRecord:
        """
        计算费用，写入 CSV 审计日志，并追加至内存缓冲。
        """
        # 1. 统计 Token 数量
        input_tokens = self.count_input_tokens(input_messages, model_name)
        output_tokens = self.count_output_tokens(response_text, model_name)

        # 2. 匹配计费费率
        pricing = LLM_PRICING.get(model_name)
        if not pricing:
            # 模糊匹配
            matched = False
            for k, v in LLM_PRICING.items():
                if k.lower() in model_name.lower():
                    pricing = v
                    matched = True
                    break
            if not matched:
                pricing = LLM_PRICING["default"]

        # 3. 计算美元费用 (rate 是每 1M tokens 价格)
        input_cost = (input_tokens / 1_000_000.0) * pricing["input"]
        output_cost = (output_tokens / 1_000_000.0) * pricing["output"]
        cost_usd = input_cost + output_cost

        # 4. 构建 AuditRecord
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record = AuditRecord(
            timestamp=timestamp,
            session_id=session_id,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            ttft_ms=ttft_ms,
            is_fallback=is_fallback
        )

        # 5. 追加到内存缓冲
        self.records.append(record)

        # 6. 持久化到 CSV 文件 (即时追加模式以防丢失)
        file_exists = os.path.exists(self.csv_filepath)
        
        # 确保父目录存在
        os.makedirs(os.path.dirname(os.path.abspath(self.csv_filepath)), exist_ok=True)
        
        headers = [
            "timestamp", "session_id", "model_name", 
            "input_tokens", "output_tokens", "total_tokens", 
            "cost_usd", "ttft_ms", "is_fallback"
        ]

        with open(self.csv_filepath, mode="a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                # 写入表头
                writer.writerow(headers)
            
            writer.writerow([
                record.timestamp,
                record.session_id,
                record.model_name,
                record.input_tokens,
                record.output_tokens,
                record.input_tokens + record.output_tokens,
                f"{record.cost_usd:.6f}",
                f"{record.ttft_ms:.2f}",
                str(record.is_fallback)
            ])

        return record

    def get_summary(self) -> Dict[str, Any]:
        """
        汇总本周期内所有审计记录。
        """
        total_input = sum(r.input_tokens for r in self.records)
        total_output = sum(r.output_tokens for r in self.records)
        total_cost = sum(r.cost_usd for r in self.records)
        fallback_count = sum(1 for r in self.records if r.is_fallback)
        total_requests = len(self.records)

        return {
            "total_requests": total_requests,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "total_cost_usd": total_cost,
            "fallback_count": fallback_count
        }
