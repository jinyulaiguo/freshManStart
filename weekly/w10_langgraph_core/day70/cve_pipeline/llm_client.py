"""
CVE Triage Pipeline — 统一 LLM 请求客户端

===================================================================================
模块设计方案 (Architectural Design)
===================================================================================
1. 设计意图：
   本模块封装所有与大模型 API 的网络交互，为上层业务节点提供三个语义清晰的
   调用接口：结构化分类（JSON Mode）、文本生成（返回文本 + Token 数）、
   以及带重试的结构化提取。

2. JSON 自愈解析机制（复用 AetherMind 的生产级方案）：
   LLM 在高负载或超时情况下可能返回截断的 JSON（缺少尾部括号），或在响应中
   混入 <think>...</think> 思考块（DeepSeek/MiniMax 的 CoT 输出）。
   自愈流程：
     Step 1: 正则剥离 <think>...</think> 块。
     Step 2: 替换中英文混用的引号、冒号（"" → ""，：→ :）。
     Step 3: 多候选提取：同时找出所有 { 和 [ 的起始位置，生成候选子串。
     Step 4: 对每个候选子串，使用括号补齐算法（parse_stack）尝试 json.loads。
     Step 5: 全部失败时抛出带上下文信息的 LLMParseError 异常。

3. 依赖注入：
   从项目根目录 .env 读取 MINIMAX_API_KEY / MINIMAX_BASE_URL / MINIMAX_MODEL。
   内部复用 weekly/w04_prompt_and_http/utils.py 中的 LLMClient 基础请求能力。
===================================================================================
"""

import os
import re
import json
import time
import asyncio
import hashlib
from pathlib import Path
from typing import Any, Optional

# 动态定位项目根目录并加载 .env
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_ENV_PATH = _PROJECT_ROOT / ".env"

if _ENV_PATH.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_PATH)
    except ImportError:
        with open(_ENV_PATH, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line or _line.startswith("#") or "=" not in _line:
                    continue
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

import httpx


# =============================================================================
# 自定义异常
# =============================================================================

class LLMParseError(Exception):
    """LLM 输出 JSON 解析失败异常，携带原始响应文本用于问题诊断。"""

    def __init__(self, message: str, raw_text: str = ""):
        super().__init__(message)
        self.raw_text = raw_text


class LLMRequestError(Exception):
    """LLM API 网络请求失败异常，携带 HTTP 状态码。"""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


# =============================================================================
# JSON 自愈解析器
# =============================================================================

def _strip_think_blocks(text: str) -> str:
    """剥离 LLM 输出中的 <think>...</think> CoT 思考块。

    Args:
        text: LLM 原始输出文本。

    Returns:
        剥离思考块后的纯净文本。
    """
    # 匹配 <think> 或 <thinking> 块，支持多行
    return re.sub(r"<think(?:ing)?[^>]*>.*?</think(?:ing)?>", "", text, flags=re.DOTALL | re.IGNORECASE)


def _normalize_json_text(text: str) -> str:
    """规范化 LLM 输出中的常见中英文混用符号。

    Args:
        text: 待规范化的文本。

    Returns:
        规范化后的文本。
    """
    # 替换中文双引号
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    # 替换中文单引号
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    # 替换中文冒号
    text = text.replace("\uff1a", ":")
    # 替换中文逗号
    text = text.replace("\uff0c", ",")
    return text


def _bracket_complete(candidate: str) -> str:
    """使用括号补齐算法修复截断的 JSON 字符串。

    遍历候选字符串，使用栈记录未闭合的括号，在字符串末尾补齐缺失的闭合括号。

    Args:
        candidate: 可能被截断的 JSON 候选子串。

    Returns:
        补齐闭合括号后的字符串。
    """
    stack = []
    in_string = False
    escape = False
    pair_map = {"{": "}", "[": "]"}
    close_set = {"}", "]"}

    for ch in candidate:
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in pair_map:
            stack.append(pair_map[ch])
        elif ch in close_set:
            if stack and stack[-1] == ch:
                stack.pop()

    # 将未闭合的括号倒序补全
    return candidate + "".join(reversed(stack))


def heal_and_parse_json(raw_text: str) -> Any:
    """JSON 自愈解析主入口。

    执行完整的自愈流程：剥离思考块 → 规范化符号 → 多候选提取 → 括号补齐 → json.loads。

    Args:
        raw_text: LLM 原始输出文本。

    Returns:
        解析成功的 Python 对象（dict 或 list）。

    Raises:
        LLMParseError: 所有候选子串均解析失败时抛出。
    """
    # Step 1: 剥离 CoT 思考块
    cleaned = _strip_think_blocks(raw_text)
    # Step 2: 规范化中英文混用符号
    cleaned = _normalize_json_text(cleaned)

    # Step 3: 多候选提取（找出所有 { 和 [ 的起始位置）
    candidates: list[str] = []
    for start_char in ("{", "["):
        idx = 0
        while True:
            pos = cleaned.find(start_char, idx)
            if pos == -1:
                break
            candidates.append(cleaned[pos:])
            idx = pos + 1

    if not candidates:
        raise LLMParseError(
            f"LLM 输出中未找到任何 JSON 起始符号 ({{ 或 [)",
            raw_text=raw_text
        )

    # Step 4: 对每个候选子串依次尝试括号补齐 + json.loads
    for candidate in candidates:
        completed = _bracket_complete(candidate)
        try:
            return json.loads(completed)
        except json.JSONDecodeError:
            continue

    raise LLMParseError(
        f"LLM 输出 JSON 自愈解析失败：所有 {len(candidates)} 个候选子串均无法反序列化",
        raw_text=raw_text
    )


# =============================================================================
# 统一 LLM 请求客户端
# =============================================================================

class CVELLMClient:
    """CVE Triage Pipeline 统一大模型请求客户端。

    封装 MiniMax API 的底层 httpx 异步请求，对外提供语义化的调用接口。
    所有方法均返回文本内容与 Token 消耗数的元组，支持全链路 Token 预算追踪。

    Attributes:
        api_key:    MiniMax API 密钥，从 .env 加载。
        base_url:   MiniMax API 基础 URL。
        model_name: 使用的模型名称。
        timeout:    单次请求的超时时限（秒）。
        max_retries: HTTP 请求最大重试次数（针对 429/5xx 错误）。
    """

    def __init__(
        self,
        timeout: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        """初始化客户端，从环境变量加载 API 凭证。

        Args:
            timeout:     单次 HTTP 请求超时秒数。
            max_retries: 遇到 429/503 时的最大重试次数。

        Raises:
            ValueError: 环境变量中未配置 MINIMAX_API_KEY 时抛出。
        """
        self.api_key = os.getenv("MINIMAX_API_KEY", "")
        self.base_url = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
        self.model_name = os.getenv("MINIMAX_MODEL", "MiniMax-M3")
        self.timeout = timeout
        self.max_retries = max_retries

        if not self.api_key:
            raise ValueError(
                "未在 .env 中配置 MINIMAX_API_KEY，请检查项目根目录的 .env 文件。"
            )

    async def _raw_request(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> tuple[str, int]:
        """执行底层 httpx 异步 POST 请求，带指数退避重试。

        Args:
            messages:    OpenAI 格式的消息列表。
            temperature: 采样温度，结构化输出建议使用 0.1~0.3。
            max_tokens:  最大生成 Token 数。

        Returns:
            (content_text, tokens_used) 元组。

        Raises:
            LLMRequestError: HTTP 请求最终失败时抛出。
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )

                if response.status_code == 429:
                    # 速率限制：指数退避等待
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)
                    last_error = LLMRequestError(
                        f"API 速率限制 (429)，等待 {wait_time}s 后重试 (第 {attempt+1}/{self.max_retries} 次)",
                        status_code=429
                    )
                    continue

                if response.status_code >= 500:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    last_error = LLMRequestError(
                        f"API 服务器错误 ({response.status_code})",
                        status_code=response.status_code
                    )
                    continue

                if response.status_code != 200:
                    raise LLMRequestError(
                        f"API 返回非预期状态码 {response.status_code}: {response.text[:200]}",
                        status_code=response.status_code
                    )

                data = response.json()
                content = data["choices"][0]["message"]["content"]
                tokens_used = data.get("usage", {}).get("total_tokens", 0)
                return content, tokens_used

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = LLMRequestError(f"网络连接异常: {e}")
                await asyncio.sleep(1.0 * (attempt + 1))
                continue

        raise LLMRequestError(
            f"LLM 请求在 {self.max_retries} 次重试后仍然失败: {last_error}"
        )

    async def classify(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 800,
    ) -> tuple[dict, int]:
        """结构化分类调用接口（JSON Mode）。

        要求 LLM 以 JSON 格式输出分类结果，内置 JSON 自愈解析。

        Args:
            system_prompt: 包含输出格式说明的系统提示词。
            user_prompt:   用户输入的分类请求。
            temperature:   采样温度，结构化输出建议 0.1。
            max_tokens:    最大生成 Token 数。

        Returns:
            (parsed_dict, tokens_used) 元组。

        Raises:
            LLMParseError:   JSON 解析失败时抛出。
            LLMRequestError: 网络请求失败时抛出。
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        raw_text, tokens = await self._raw_request(messages, temperature, max_tokens)
        parsed = heal_and_parse_json(raw_text)
        return parsed, tokens

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.6,
        max_tokens: int = 2000,
    ) -> tuple[str, int]:
        """文本生成调用接口。

        用于代码补丁生成、合规报告撰写等开放式文本生成场景。

        Args:
            system_prompt: 系统提示词（角色与任务定义）。
            user_prompt:   用户输入的生成请求。
            temperature:   采样温度，创意生成建议 0.5~0.7。
            max_tokens:    最大生成 Token 数。

        Returns:
            (generated_text, tokens_used) 元组。

        Raises:
            LLMRequestError: 网络请求失败时抛出。
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return await self._raw_request(messages, temperature, max_tokens)

    def compute_text_fingerprint(self, text: str) -> str:
        """计算文本内容的 MD5 指纹，用于补丁震荡检测。

        Args:
            text: 待计算指纹的文本（通常为 generated_patch_code）。

        Returns:
            8 位十六进制 MD5 摘要字符串。
        """
        return hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
