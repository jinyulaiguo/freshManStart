"""
Day 59: 长期记忆系统 - 实体级 Facts 提取与多租户物理隔离 (Standard Answer)

设计方案说明：
1. **设计意图**：
   本类实现了从非结构化交互对话中抽取稳定的 Facts/Preferences 实体，并存入基于 `user_id` 物理隔离的内存分区中。
   这避免了全局 Summary 在多代总结后产生的记忆漂移（Summary Drift），且在 DAO 访问层阻断了多租户数据泄露。
2. **类与数据模型**：
   - `FactItem(BaseModel)`: Facts 的数据格式校验契约。
   - `FactExtractor`: 核心 Facts 管理器。
     - `extract_facts(dialogue_history)`: 调用大模型并对返回的 JSON 文本进行反序列化与 Pydantic 过滤。
     - `save_facts(user_id, facts)`: 根据 user_id 建立字典隔离分区写入。
     - `recall_facts(user_id, query)`: 在对应的租户隔离分区执行检索。
3. **防爆/防漏设计**：
   - 使用 Markdown JSON 块提取的正则表达式过滤 LLM 输出的脏字符。
   - 多租户物理分区，在检索首层阻断越权（若 user_id 不存在则直接短路退出，不执行向量/字符比对）。
"""

import json
import re
import sys
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from weekly.w04_prompt_and_http.utils import LLMClient

class FactItem(BaseModel):
    """原子事实偏好数据结构契约"""
    fact_key: str = Field(description="事实的主体属性名，使用下划线蛇形命名，如 user_prefer_language, user_company")
    fact_value: str = Field(description="事实的具体内容值，必须精准、精炼，如 Python, 谷歌")


class FactExtractor:
    """事实提取与多租户物理隔离管理器"""

    def __init__(self, client: Optional[LLMClient] = None):
        """初始化 Facts 提取管理器。

        Args:
            client: 真实大模型请求客户端。
        """
        self.client = client or LLMClient()
        
        # 模拟持久化数据库：用字典在内存中维护物理分区的多租户数据
        # 结构：{user_id: {fact_key: fact_value}}
        self._isolated_db: Dict[str, Dict[str, Any]] = {}

    async def extract_facts(self, dialogue_history: List[Dict[str, str]]) -> List[FactItem]:
        """调用大模型，从多轮交互会话历史中提取出结构化事实 Facts。

        Args:
            dialogue_history: 多轮对话消息列表。

        Returns:
            提取出来的 FactItem 实例列表。
        """
        # 步骤 1: 构造强规 JSON 输出的 System Prompt，要求模型只返回指定格式的 JSON 数组
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
        
        # 步骤 2: 将对话历史序列化并构造大模型 Payload
        user_prompt = f"请从以下对话历史中提取出所有符合要求的事实与偏好：\n=== 对话历史 ===\n{json.dumps(dialogue_history, ensure_ascii=False)}\n==============="
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        print("[FactExtractor] 正在调用大模型提取原子 Facts ...")
        # 步骤 3: 请求模型响应
        response_text = await self.client.request_llm(messages, temperature=0.1)
        
        # 步骤 4: 防御性解析，使用正则提取可能存在的 JSON 块 (Markdown 代码块隔离防护)
        cleaned_json = response_text.strip()
        json_match = re.search(r"\[\s*\{.*\}\s*\]", cleaned_json, re.DOTALL)
        if json_match:
            cleaned_json = json_match.group(0)

        try:
            # 步骤 5: 反序列化并使用 Pydantic 进行类型契约约束校验
            parsed_data = json.loads(cleaned_json)
            validated_facts = []
            for item in parsed_data:
                # 显式校验并转换，若字段缺失或类型不对会在此抛出 ValidationError
                validated_facts.append(FactItem(**item))
            
            print(f"[FactExtractor] 成功提取出 {len(validated_facts)} 个 Facts 实体。")
            return validated_facts
            
        except Exception as e:
            # 步骤 6: 防错降级，若解析崩溃则返回空列表，防止主 Pipeline 因大模型输出格式错乱而中断
            print(f"❌ [FactExtractor] 提取大模型 Facts 解析校验失败: {e}", file=sys.stderr)
            print(f"大模型原始输出: {response_text}", file=sys.stderr)
            return []

    def save_facts(self, user_id: str, facts: List[FactItem]) -> None:
        """多租户隔离写入：将提取出的原子事实写入该用户独立的数据分区中。

        Args:
            user_id: 用户唯一租户标识符。
            facts: 提取出的 Facts 列表。
        """
        # 步骤 1: 进行防越权初始化检查
        if not user_id:
            raise ValueError("租户隔离 user_id 不能为空")
            
        # 步骤 2: 按租户 ID 建立专属分区
        if user_id not in self._isolated_db:
            self._isolated_db[user_id] = {}
            
        # 步骤 3: 写入或覆盖事实，实现 Facts 增量式原地累加，杜绝多代 Summary 的稀释
        for fact in facts:
            self._isolated_db[user_id][fact.fact_key] = fact.fact_value
            print(f"[数据分区] 已为租户 '{user_id}' 物理存盘 Facts: [{fact.fact_key} -> {fact.fact_value}]")

    def recall_facts(self, user_id: str, query: str, limit: int = 5) -> List[FactItem]:
        """多租户隔离检索：在对应用户的独立分区中执行检索召回。

        Args:
            user_id: 用户唯一租户标识符。
            query: 用户当前提问。
            limit: 最大召回限制。

        Returns:
            召回的 FactItem 列表。
        """
        # 步骤 1: 权限防护，在检索第一关物理阻断未授权的跨租户碰撞
        if user_id not in self._isolated_db:
            print(f"[安全警告] 租户 '{user_id}' 尚无已分配的数据分区空间，检索直接退出。")
            return []
            
        tenant_facts = self._isolated_db[user_id]
        recalled: List[FactItem] = []
        
        # 步骤 2: 基于关键字与 key 分词的轻量匹配检索 (生产环境为 Vector Similarity Search)
        for k, v in tenant_facts.items():
            words = k.lower().split("_")
            # 当 key 的拆分词存在于 query 中时召回，排除了 3 字符以下的虚词
            if any(word in query.lower() and len(word) > 3 for word in words):
                recalled.append(FactItem(fact_key=k, fact_value=v))
                if len(recalled) >= limit:
                    break
                    
        return recalled


# 调试主入口与租户隔离测试
async def main() -> None:
    print("=== 运行 Day 59 长期记忆 Facts 提取与多租户隔离标准答案 ===")

    # 1. 实例化核心组件
    extractor = FactExtractor()

    # 2. 模拟 5 轮混合了日常闲聊和用户偏好陈述的对话历史
    mock_history = [
        {"role": "user", "content": "你好，我叫李明。"},
        {"role": "assistant", "content": "你好，李明！请问有什么我可以帮你的？"},
        {"role": "user", "content": "我常用 Python 进行后端开发，目前供职于谷歌。"},
        {"role": "assistant", "content": "了解，谷歌的 Python 项目确实很多，我们可以多聊聊相关架构。"},
        {"role": "user", "content": "另外，我比较喜欢喝拿铁咖啡，讨厌茶。"},
    ]

    # 3. 运行事实提取
    extracted = await extractor.extract_facts(mock_history)
    print("\n提取到的结构化 Facts:")
    for fact in extracted:
        print(f" - {fact.fact_key}: {fact.fact_value}")

    # 4. 多租户物理隔离隔离存盘
    print("\n--- 物理写入测试 ---")
    # 李明的数据存入其专属租户 ID
    extractor.save_facts(user_id="user_leeming", facts=extracted)

    # 5. 租户防污染与安全检索验证
    print("\n--- 多租户隔离安全检索测试 ---")
    
    # 用李明的身份检索“你常用什么开发 language 吗？”
    print("\n[测试 1] 使用李明本人的租户身份 'user_leeming' 查询：")
    recalled_correct = extractor.recall_facts(user_id="user_leeming", query="你常用的开发 language 吗？")
    print(f"召回结果: {recalled_correct}")

    # 模拟未授权租户 "user_random" 使用相同的 query 尝试检索
    print("\n[测试 2] 使用外部隔离租户身份 'user_random' 查询同一 query：")
    recalled_leaked = extractor.recall_facts(user_id="user_random", query="你常用的开发 language 吗？")
    print(f"召回结果: {recalled_leaked}")
    
    # 验证是否完美隔离
    is_safe = (len(recalled_correct) > 0 and len(recalled_leaked) == 0)
    print(f"\n多租户物理隔离防护校验 (无越权碰撞泄露): {'✅ 通过' if is_safe else '❌ 失败'}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
