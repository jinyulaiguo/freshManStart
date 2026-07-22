"""
Fact Extractor Module.

设计方案说明：
1. **设计意图**：
   本模块实现长期记忆偏好提取引擎（Fact Extractor），用于从多轮交互会话中提取结构化的原子事实 Facts 实体。
   这能够克服全量会话 Summary 信息被稀释的问题，实现对于用户人设与偏好的精准捕获。
2. **类结构**：
   - `FactItem(BaseModel)`: Facts 的数据格式契约规范。
   - `FactExtractor`: 核心 Facts 提取器类。
     - `extract_facts(dialogue_history)`: 调用大模型并利用正则及 Pydantic 反序列化数据。
3. **健壮防爆设计**：
   - 提取过程使用 JSON 格式强规 Prompt。
   - 内置正则匹配器，即使大模型抽风带上 Markdown 块或正文说明，也能物理截取出 JSON 数组。
   - 对单条 Fact 执行 Pydantic 异常捕获，单条格式出错不影响其他事实的正常沉淀。
"""

import sys
import os
import json
import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

# 确保导入 config
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from config import get_llm_client
from weekly.w04_prompt_and_http.utils import LLMClient

class FactItem(BaseModel):
    """原子事实偏好数据结构契约"""
    fact_key: str = Field(description="事实的主体属性名，使用下划线蛇形命名，如 user_prefer_language, user_company")
    fact_value: str = Field(description="事实的具体内容值，必须精准、精炼，如 Python, 谷歌")


class FactExtractor:
    """原子事实提取微引擎。"""

    def __init__(self, client: Optional[LLMClient] = None):
        """初始化 Facts 提取引擎。

        Args:
            client: 真实大模型请求客户端。
        """
        self.client = client or get_llm_client()

    async def extract_facts(self, dialogue_history: List[Dict[str, str]]) -> List[FactItem]:
        """异步调用大模型，从多轮会话历史中抽取出结构化原子 Facts 列表。

        Args:
            dialogue_history: 多轮对话消息列表。

        Returns:
            提取校验成功后的 FactItem 实例列表。
        """
        # 步骤 1: 构造 JSON 输出约束 Prompt，严禁大模型多言
        system_prompt = (
            "你是一个高保真的实体事实与偏好提取引擎。\n"
            "你的任务是分析用户的对话历史，抽取出关于用户的永久事实、偏好、职业、姓名等信息。\n"
            "不要提取临时的状态或普通的闲聊。每一个事实必须使用下划线命名的 fact_key，以及精确简练的 fact_value。\n\n"
            "必须输出且仅输出以下 JSON 格式的数据，禁止附带任何额外的Markdown解释或正文：\n"
            "[\n"
            "  {\"fact_key\": \"user_prefer_language\", \"fact_value\": \"Python\"},\n"
            "  {\"fact_key\": \"user_hobby\", \"fact_value\": \"咖啡\"}\n"
            "]"
        )
        
        user_prompt = (
            "请从以下对话历史中提取出所有符合要求的事实与偏好：\n"
            "=== 对话历史 ===\n"
            f"{json.dumps(dialogue_history, ensure_ascii=False)}\n"
            "==============="
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        print("[FactExtractor] 发起异步大模型请求以提取 Facts 实体...")
        try:
            # 步骤 2: 调用 LLM 执行意图提取，低温度以防幻觉
            response_text = await self.client.request_llm(messages, temperature=0.1)
            
            # 清洗思维链内容，避免 <think> 干扰
            cleaned_response = response_text.strip()
            if "</THINK>" in cleaned_response.upper():
                cleaned_response = cleaned_response.upper().split("</THINK>")[-1].strip()

            # 步骤 3: 使用正则提取 JSON 数组块，防止 Markdown 块报错
            json_match = re.search(r"\[\s*\{.*\}\s*\]", cleaned_response, re.DOTALL)
            if json_match:
                cleaned_response = json_match.group(0)

            # 步骤 4: 物理反序列化并执行契约类型校验
            parsed_data = json.loads(cleaned_response)
            validated_facts = []
            
            if isinstance(parsed_data, list):
                for item in parsed_data:
                    try:
                        # 兼容性清洗：将所有 key 都转为小写，防范大模型输出 FACT_KEY 等大写格式
                        cleaned_item = {}
                        if isinstance(item, dict):
                            for k, v in item.items():
                                cleaned_item[k.lower()] = v
                        else:
                            continue
                            
                        # 转换并触发 Pydantic 字段检查
                        fact_item = FactItem(**cleaned_item)
                        # 去除键值两端多余空格
                        fact_item.fact_key = fact_item.fact_key.strip().lower()
                        fact_item.fact_value = fact_item.fact_value.strip()
                        if fact_item.fact_key and fact_item.fact_value:
                            validated_facts.append(fact_item)
                    except Exception as val_err:
                        print(f"⚠️ [FactExtractor] 单条 Fact 容错校验失败被跳过 (数据: {item}): {val_err}", file=sys.stderr)
            
            print(f"[FactExtractor] 事实提取结束。成功获取 {len(validated_facts)} 条有效 Facts。")
            return validated_facts
            
        except Exception as e:
            # 步骤 5: 防爆机制，避免 API 出错导致整个 Agent 主 Pipeline 卡死
            print(f"❌ [FactExtractor] 提取大模型 Facts 异常或 JSON 解析崩溃: {e}", file=sys.stderr)
            return []
