"""
AetherMind Unified LLM & Embedding Client
=========================================

设计方案:
---------
该模块为 AetherMind 提供统一的大模型底层接口客户端。
它继承/封装了 Week 4 的 `LLMClient` 与 Week 6 的 `EmbeddingClient`，
在此基础上进行了生产级增强：
1. **异步流式输出 (Stream)**：支持 `request_llm_stream` 方法，利用 `httpx` 的 `stream` 异步迭代器解析大模型 SSE 输出。
2. **结构化 JSON 提取**：提供辅助解析器，即使大模型没有返回标准 JSON（如夹带 Markdown 围栏 ```json），也能鲁棒性地提取并利用 Pydantic 校验反序列化。
3. **向量计算集成**：代理了文本向量化接口，供长期记忆与 RAG 底层调用。

结构说明:
---------
- AetherMindLLMClient: 综合大模型客户端，集成推理、流式和 Embedding。
- extract_json_from_text(): 鲁棒性 JSON 正则提取工具函数。
"""

import json
import re
import os
import httpx
from typing import List, Dict, Any, AsyncGenerator, Type, Optional
from pydantic import BaseModel, ValidationError
from weekly.w04_prompt_and_http.utils import LLMClient
from weekly.w06_embedding_and_vector_db.utils import EmbeddingClient
from aether_mind.utils.logging import logger
from aether_mind.config import settings


def extract_json_from_text(text: str) -> str:
    """
    防错与自愈设计：从 LLM 输出的文本中清洗并提取 JSON 字符串。

    设计意图 (Design Intent):
    -----------------------
    大模型（尤其是具备深度推理能力的思考型大模型如 DeepSeek-R1）在输出 JSON 时，经常会伴随以下破坏 JSON 的格式问题：
    1. 含有以 `<think>...</think>` 包裹的思考推理链（Thinking Process Token）。
    2. 将外围 JSON 结构的双引号错写为单引号（如 `{'score': 1}`）。
    3. 在字符串值内部使用了单引号（如 `"entity 'name'"`）或未转义的双引号（如 `'Using "double quotes" inside single'`）。
    4. 带有 Markdown 的代码围栏（```json ... ```）。
    5. 使用了中文标点（如全角冒号 `：`、全角逗号 `，`）或中文弯引号（如 `“` 和 `”`）。
    6. 最后一个键值对后携带了非法尾逗号（如 `{"score": 1,}`），或因截断导致尾部括号未闭合。

    本实现通过 **单字符扫描状态机** 与 **后顾窥视校验器 (Lookahead Validator)** 彻底解决了上述痛点：
    - 精准记录并追踪当前是否处于字符串（双引号/单引号/中文弯双/弯单引号）内部，并感知包裹它的具体引号类型。
    - 如果是在字符串**内部**遇到双引号或单引号，通过后顾窥视检测其后随字符是否为标准的 JSON 分隔符（如 `,`, `}`, `]`, `:` 或 EOF）。如果是，则判定为合法的字符串闭合标志；如果不是（例如 `"answer": "讨论了 "Runtime Substrate" 的概念"` 内部的嵌套双引号），则自动将其在输出流中进行转义保护（`\"`），从而避免破坏外围 JSON 物理边界，引发 `Expecting ',' delimiter` 解析错误。
    - 优先且仅对 `{` 关联的字典格式候选体进行自愈解析，防止由于正文解析失败而降级匹配类似于 `[16]` 这样的数组干扰块，进而避免触发 Pydantic Schema 校验崩溃。
    """
    # 1. 过滤思考块
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    
    # 1.1 针对路由判定的文本回复（如 [Route]: ... 和 [Reason]: ...）进行正则匹配与 JSON 自动重构
    route_match = re.search(r"(?:\[?Route\]?):\s*([a-zA-Z_\+\-\d\+]+)", text, re.IGNORECASE)
    reason_match = re.search(r"(?:\[?Reason\]?):\s*([\s\S]+)", text, re.IGNORECASE)
    if route_match and reason_match:
        route_val = route_match.group(1).strip()
        reason_val = reason_match.group(1).strip()
        # 清理可能混入的后缀（例如 '，默认降级' 字符等）
        reason_val = re.split(r"\n|，默认降级", reason_val)[0].strip()
        return json.dumps({"route": route_val, "reason": reason_val}, ensure_ascii=False)

    # 2. 匹配 ```json ... ``` 围栏
    code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if code_block_match:
        candidates = [code_block_match.group(1).strip()]
    else:
        # 3. 寻找所有可能的 JSON 起点 { 或 [
        candidates = []
        brace_starts = [m.start() for m in re.finditer(r"\{", text)]
        last_brace_end = text.rfind("}")
        
        # 3.1 字典优先原则：如果文本中包含大括号，优先且仅尝试提取大括号内的对象，以防止匹配到 list 格式的干扰 ID 块（如 [16]）
        if brace_starts and last_brace_end != -1:
            for start in brace_starts:
                if start <= last_brace_end:
                    candidates.append(text[start:last_brace_end+1])
            for start in brace_starts:
                candidates.append(text[start:])
        else:
            # 3.2 仅在没有大括号的情况下才提取中括号包裹的数组候选
            bracket_starts = [m.start() for m in re.finditer(r"\[", text)]
            last_bracket_end = text.rfind("]")
            if bracket_starts and last_bracket_end != -1:
                for start in bracket_starts:
                    if start <= last_bracket_end:
                        candidates.append(text[start:last_bracket_end+1])
                for start in bracket_starts:
                    candidates.append(text[start:])

        if not candidates:
            candidates = [text.strip()]

    # 后顾窥视校验器：判断指定位置的引号是否为合法的 JSON 物理边界闭合引号
    def is_real_closing_quote(chars_list, index):
        j = index + 1
        # 跳过所有空白字符
        while j < len(chars_list) and chars_list[j].isspace():
            j += 1
        if j == len(chars_list):
            return True  # 到达文本尾部，是合法的闭合
        
        next_char = chars_list[j]
        # 如果后随字符是逗号、冒号、闭合大/中括号，则大概率是结构性闭合
        if next_char in ('}', ']', ':'):
            return True
        if next_char == ',':
            # 针对逗号做进一步校验，以区分 "A", published in 2024 (字符串内部逗号) 与 "key": "val", "key2" (结构逗号)
            k = j + 1
            while k < len(chars_list) and chars_list[k].isspace():
                k += 1
            # 检查逗号后是否紧跟另一个键名的前引号
            if k < len(chars_list) and chars_list[k] in ('"', "'", '\u201c', '\u201d', '\u2018', '\u2019'):
                quote_type = chars_list[k]
                # 兼容各类全角半角引号
                if quote_type in ('\u201c', '\u201d'):
                    quote_types = ('"', '\u201c', '\u201d')
                elif quote_type in ('\u2018', '\u2019'):
                    quote_types = ("'", '\u2018', '\u2019')
                else:
                    quote_types = (quote_type,)
                
                # 寻找该键名的后引号
                m = k + 1
                while m < len(chars_list) and chars_list[m] not in quote_types:
                    m += 1
                if m < len(chars_list):
                    # 后引号后面必须跟有冒号，才说明这是一个合法的 JSON 属性名，前面的逗号才是结构层逗号
                    n = m + 1
                    while n < len(chars_list) and chars_list[n].isspace():
                        n += 1
                    if n < len(chars_list) and chars_list[n] in (':', '：'):
                        return True
            return False
        return False

    # 4. 对每个候选 JSON 串进行状态机清洗与校验
    last_cleaned_res = None
    for cand in candidates:
        stack = []
        bracket_map = {'{': '}', '[': ']'}
        in_quote_char = None  # 记录当前包裹字符串的引号类型: None, '"', or "'"
        
        cleaned_chars = []
        i = 0
        chars = list(cand)
        while i < len(chars):
            char = chars[i]
            
            # 处理转义字符：如果在字符串内，我们只对冲突的引号或合法转义做保护
            if char == '\\' and in_quote_char is not None:
                if i + 1 < len(chars):
                    next_char = chars[i+1]
                    if in_quote_char == "'" and next_char == "'":
                        # 原单引号转为双引号后，原本转义的单引号不再需要转义
                        cleaned_chars.append("'")
                    elif in_quote_char == '"' and next_char == '"':
                        # 原双引号中转义的双引号保留
                        cleaned_chars.append('\\"')
                    else:
                        # 其它转义字符按原样输出
                        cleaned_chars.append('\\')
                        cleaned_chars.append(next_char)
                    i += 2
                    continue
                else:
                    cleaned_chars.append('\\')
                    i += 1
                    continue
            
            # 非字符串状态下 (正常 JSON 结构层)
            if in_quote_char is None:
                # 遇到双引号或中文弯双引号，标志着标准双引号字符串的开始
                if char in ('"', '\u201c', '\u201d'):
                    in_quote_char = '"'
                    cleaned_chars.append('"')
                    i += 1
                    continue
                # 遇到单引号或中文弯单引号，标志着单引号字符串的开始（我们将其在输出中标准化为双引号）
                if char in ("'", '\u2018', '\u2019'):
                    in_quote_char = "'"
                    cleaned_chars.append('"')
                    i += 1
                    continue
                
                # 结构层中的中文标点自动纠正为英文标点
                if char == '：':
                    cleaned_chars.append(':')
                    i += 1
                    continue
                if char == '，':
                    cleaned_chars.append(',')
                    i += 1
                    continue
                
                # 括号平衡追踪，用来在末尾自动补全因截断导致的缺失括号
                if char in bracket_map:
                    stack.append(char)
                elif char in bracket_map.values():
                    if stack and bracket_map[stack[-1]] == char:
                        stack.pop()
                
                # 非法尾逗号自愈：如遇到逗号且后随闭合括号，则跳过该逗号
                if char == ',':
                    next_non_space_idx = i + 1
                    while next_non_space_idx < len(chars) and chars[next_non_space_idx].isspace():
                        next_non_space_idx += 1
                    if next_non_space_idx < len(chars) and chars[next_non_space_idx] in ('}', ']'):
                        i = next_non_space_idx  # 跳过逗号直接前进到闭括号
                        continue
                
                cleaned_chars.append(char)
                i += 1
            
            # 双引号字符串内部
            elif in_quote_char == '"':
                # 遇到双引号，检查是否是真正的闭合引号
                if char == '"':
                    if is_real_closing_quote(chars, i):
                        in_quote_char = None
                        cleaned_chars.append('"')
                    else:
                        # 内部嵌套双引号，转义输出，防止截断
                        cleaned_chars.append('\\"')
                # 内部弯双引号，转义为 \"
                elif char in ('\u201c', '\u201d'):
                    cleaned_chars.append('\\"')
                else:
                    cleaned_chars.append(char)
                i += 1
            
            # 单引号字符串内部
            elif in_quote_char == "'":
                # 遇到单引号，检查是否是真正的闭合引号
                if char == "'":
                    if is_real_closing_quote(chars, i):
                        in_quote_char = None
                        cleaned_chars.append('"')
                    else:
                        # 内部嵌套单引号，保持单引号字符本身即可（因外围已标准化为双引号，故内部单引号合法）
                        cleaned_chars.append("'")
                # 由于外层单引号将被换成双引号，内部原有的双引号或弯双引号必须被转义为 \"，以防破坏新结构
                elif char in ('"', '\u201c', '\u201d'):
                    cleaned_chars.append('\\"')
                else:
                    cleaned_chars.append(char)
                i += 1

        # 闭合未完成的字符串与括号 (自愈机制)
        if in_quote_char is not None:
            cleaned_chars.append('"')
        
        while stack:
            unclosed = stack.pop()
            cleaned_chars.append(bracket_map[unclosed])
            
        result = "".join(cleaned_chars).strip()
        try:
            json.loads(result)
            return result
        except Exception:
            last_cleaned_res = result

    return last_cleaned_res or text.strip()


class AetherMindLLMClient:
    """
    AetherMind 专属的真实大模型与 Embedding 异步请求客户端。
    """

    def __init__(self):
        """
        初始化客户端。自动读取全局 settings。
        """
        # 复用已定义的 API Key 与 Base URL，使用 Pydantic settings 配置
        self.api_key = settings.minimax_api_key or os.getenv("MINIMAX_API_KEY")
        self.base_url = settings.minimax_base_url
        self.model_name = settings.llm_model
        
        if not self.api_key:
            raise ValueError("未在环境变量或 .env 中配置有效的 MINIMAX_API_KEY，请检查配置！")
            
        # 封装基础 Client
        self.base_client = LLMClient()
        self.base_client.api_key = self.api_key
        self.base_client.base_url = self.base_url
        self.base_client.model_name = self.model_name
        
        self.embed_client = EmbeddingClient()
        self.embed_client.api_key = self.api_key
        self.embed_client.base_url = self.base_url


    async def request_llm(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 4096
    ) -> str:
        """
        同步调用大模型，返回完整回复文本。

        Args:
            messages (List[Dict[str, Any]]): 消息列表。
            temperature (float): 采样温度。
            max_tokens (int): 最大 Token。

        Returns:
            str: 大模型完整返回的文本。
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        temp_param = max(0.01, min(temperature, 1.0))
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temp_param,
            "max_tokens": max_tokens
        }
        
        timeout_policy = httpx.Timeout(timeout=60.0)
        
        try:
            async with httpx.AsyncClient(timeout=timeout_policy) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                )
                
                if response.status_code != 200:
                    raise RuntimeError(
                        f"LLM API 请求错误 (HTTP {response.status_code}): {response.text}"
                    )
                    
                data = response.json()
                return data["choices"][0]["message"]["content"]
                
        except Exception as e:
            if "HTTP 402" in str(e) or "insufficient_balance" in str(e):
                logger.critical("🚨【AetherMind 致命配置错误】检测到大模型 API 余额不足 (HTTP 402)。请检查并更新配置文件 (如 .env) 中的 MINIMAX_API_KEY！")
            raise e

    async def request_llm_json(
        self,
        messages: List[Dict[str, Any]],
        response_model: Type[BaseModel],
        temperature: float = 0.1,
        max_tokens: int = 2048,
        max_retries: int = 2
    ) -> BaseModel:
        """
        调用大模型，并将输出结果鲁棒性地强转换为指定的 Pydantic Model 实例。
        包含自动重试与纠错。

        Args:
            messages (List[Dict[str, Any]]): 消息列表。
            response_model (Type[BaseModel]): 期望转换的 Pydantic 模型类。
            temperature (float): 温度（通常建议较低以保证 JSON 准确率）。
            max_tokens (int): 最大 Token。
            max_retries (int): 校验失败时的重试次数。

        Returns:
            BaseModel: 实例化后的 response_model。
        """
        # 1. 动态生成 Pydantic 模型的 JSON Schema，确保大模型明确感知字段契约
        schema_dict = response_model.model_json_schema()
        schema_str = json.dumps(schema_dict, ensure_ascii=False, indent=2)
        
        # 深拷贝消息列表，防止副作用修改入参
        current_messages = [msg.copy() for msg in messages]
        
        schema_instruction = (
            f"\n\n你必须严格以 JSON 格式输出结果。格式要求如下（JSON Schema 规范）：\n"
            f"```json\n{schema_str}\n```\n"
            f"请直接输出符合上述 Schema 规范的 JSON 数据本身（必须以 '{{' 开始，以 '}}' 结束），不要输出任何前缀、解释、注释或其它自然语言文字。"
        )
        
        # 2. 将 Schema 约束动态织入 System Prompt 中
        system_msg = next((m for m in current_messages if m["role"] == "system"), None)
        if system_msg:
            system_msg["content"] += schema_instruction
        else:
            current_messages.insert(0, {"role": "system", "content": schema_instruction})

        # 同时也追加到最后一个 user 消息中，强力纠偏大模型的注意力，避免复制 Schema 或生成前缀
        user_msg = next((m for m in reversed(current_messages) if m["role"] == "user"), None)
        if user_msg:
            user_msg["content"] += (
                "\n\n【重要要求】：请严格且仅输出符合上述 JSON Schema 规范的 JSON 对象本身。你必须且仅能以 '{' 字符开头并以 '}' 字符结尾。绝对不要复制、输出或包含 JSON Schema 定义本身，并且除了 JSON 之外不要带有任何前缀、解释、注释或自然语言文字。"
            )

        for attempt in range(max_retries + 1):
            try:
                # 3. 发起推理请求
                raw_text = await self.request_llm(
                    messages=current_messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                
                # 4. 提取 JSON 内容并校验反序列化
                json_str = extract_json_from_text(raw_text)
                parsed_data = json.loads(json_str)
                return response_model.model_validate(parsed_data)
                
            except (json.JSONDecodeError, ValidationError) as e:
                logger.warning(
                    f"[LLM JSON 解析失败] 尝试轮次 {attempt + 1}/{max_retries + 1}. 错误: {str(e)}"
                )
                if attempt == max_retries:
                    raise RuntimeError(
                        f"大模型未能输出符合 Pydantic 契约的合法 JSON 结构。错误: {str(e)}\n原始文本:\n{raw_text}"
                    )
                
                # 5. 动态将错误反馈给大模型，进行原地修正
                current_messages.append({"role": "assistant", "content": raw_text})
                current_messages.append({
                    "role": "user",
                    "content": f"先前输出格式不符合 JSON Schema 规范。解析错误：{str(e)}。请严格重新输出，除 JSON 内容外不要包含任何自然语言文字。"
                })

    async def request_llm_stream(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> AsyncGenerator[str, None]:
        """
        流式异步调用大模型，逐个 Yield 产出的 Token。

        Args:
            messages (List[Dict[str, Any]]): 消息历史。
            temperature (float): 采样温度。
            max_tokens (int): Token 限制。

        Yields:
            AsyncGenerator[str, None]: Token 字符串生成器。
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # 限制温度区间以保障稳定性
        temp_param = max(0.01, min(temperature, 1.0))
        
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temp_param,
            "max_tokens": max_tokens,
            "stream": True
        }
        
        url = f"{self.base_url}/chat/completions"
        timeout_policy = httpx.Timeout(timeout=30.0)

        # 4. 使用 httpx 的 stream 接口进行块迭代读取
        async with httpx.AsyncClient(timeout=timeout_policy) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise RuntimeError(
                        f"LLM Stream 错误 (HTTP {response.status_code}): {error_text.decode('utf-8')}"
                    )
                
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    
                    # 识别流关闭标志
                    if line == "data: [DONE]":
                        break
                    
                    if line.startswith("data: "):
                        json_str = line[len("data: "):]
                        try:
                            data = json.loads(json_str)
                            # 从 choices 提取内容 token
                            delta = data["choices"][0]["delta"]
                            if "content" in delta:
                                yield delta["content"]
                        except (json.JSONDecodeError, KeyError, IndexError):
                            # 防御性忽略异常的行
                            continue

    async def get_embedding(self, text: str, embed_type: str = "query") -> List[float]:
        """
        计算单个文本的高维向量特征（维度：1536）。

        Args:
            text (str): 输入文本。
            embed_type (str): 用途标识 ("db" | "query")。

        Returns:
            List[float]: 浮点向量。
        """
        return await self.embed_client.embed_single(text, embed_type=embed_type)

    async def get_embeddings(self, texts: List[str], embed_type: str = "db") -> List[List[float]]:
        """
        批量计算文本列表的向量。包含自动分批处理（最大限制 100 条/批），并对异常进行兜底防御。

        Args:
            texts (List[str]): 文本列表。
            embed_type (str): 类别标识。

        Returns:
            List[List[float]]: 向量列表。
        ```"""
        if not texts:
            return []

        batch_size = 10
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            try:
                # 调用底层的 embed_texts 并记录返回值
                logger.info(f"[Embedding Client] 正在请求第 {i // batch_size + 1} 批向量，条数: {len(batch_texts)}")
                batch_res = await self.embed_client.embed_texts(batch_texts, embed_type=embed_type)
                
                if batch_res is None:
                    logger.error(f"[Embedding Client] 错误：第 {i // batch_size + 1} 批向量化返回 None。执行零向量兜底。")
                    batch_res = [[0.0] * 1536 for _ in batch_texts]
                    
                all_embeddings.extend(batch_res)
            except Exception as ex:
                logger.error(f"[Embedding Client] 批量计算向量异常（第 {i // batch_size + 1} 批）: {str(ex)}。执行零向量兜底。", exc_info=True)
                # 使用全零向量进行兜底，保障 RAG/GraphRAG 索引全链路可以继续往下走，防止整机崩溃
                batch_res = [[0.0] * 1536 for _ in batch_texts]
                all_embeddings.extend(batch_res)
                
        return all_embeddings

