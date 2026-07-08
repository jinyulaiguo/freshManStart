"""
Week 6 公共辅助工具模块：Embedding API 异步请求客户端

设计方案：
==========
1. 设计意图：
   提供本周所有练习与大作业共享的文本向量化网络请求基础设施。
   将 Embedding API 的请求格式适配（MiniMax 原生格式 vs OpenAI 兼容格式）、
   响应解析、异常处理封装在此，使每日课程能专注于距离计算、索引构建等
   核心业务逻辑。

2. 核心结构：
   - 复用 w04 的 load_env_file() 加载 .env 环境变量
   - EmbeddingClient: Embedding API 异步请求类
     - embed_texts(texts, embed_type): 批量文本向量化
     - embed_single(text, embed_type): 单文本向量化（便捷封装）

3. 关键数据流：
   调用方传入 list[str] → EmbeddingClient 构建 HTTP POST 请求
   → MiniMax /v1/embeddings 端点 → 解析响应为 list[list[float]]

4. API 格式兼容：
   MiniMax 的 Embedding 接口使用 `texts` 字段（区别于 OpenAI 的 `input` 字段），
   并需要额外的 `type` 字段指定向量用途（"db" = 文档存储，"query" = 检索查询）。
   本客户端优先尝试 MiniMax 原生格式，若失败则回退到 OpenAI 兼容格式。
"""

from __future__ import annotations

import os
import httpx

# ── 复用 w04 的环境变量加载器 ──
from weekly.w04_prompt_and_http.utils import load_env_file

# 在导入时自动触发一次环境变量加载
load_env_file()


class EmbeddingClient:
    """MiniMax Embedding API 异步请求客户端

    通过 /v1/embeddings 端点将文本列表转换为高维浮点向量列表。
    自动兼容 MiniMax 原生格式（texts 字段）和 OpenAI 兼容格式（input 字段）。

    环境变量配置：
        MINIMAX_API_KEY          : API 密钥（必需）
        MINIMAX_BASE_URL         : API 基础 URL（默认 https://api.minimax.chat/v1）
        MINIMAX_EMBEDDING_MODEL  : Embedding 模型名称（默认 embo-01）

    Attributes:
        api_key: API 密钥
        base_url: API 基础 URL（不含 /embeddings 路径后缀）
        model_name: Embedding 模型名称
    """

    def __init__(self) -> None:
        self.api_key: str = os.getenv("MINIMAX_API_KEY", "")
        self.base_url: str = (
            os.getenv("MINIMAX_BASE_URL") or "https://api.minimax.chat/v1"
        )
        self.model_name: str = (
            os.getenv("MINIMAX_EMBEDDING_MODEL") or "embo-01"
        )

        if not self.api_key:
            raise ValueError(
                "未在环境变量或 .env 中配置有效的 MINIMAX_API_KEY，请检查配置！"
            )

    async def embed_texts(
        self,
        texts: list[str],
        embed_type: str = "db",
    ) -> list[list[float]]:
        """批量文本向量化

        将一组文本字符串转换为对应的高维浮点向量。

        Args:
            texts: 待向量化的文本列表（单次最多 100 条）
            embed_type: 向量用途标识
                        "db"    — 文档存储（用于写入向量数据库的文档向量）
                        "query" — 检索查询（用于用户查询时的 query 向量）

        Returns:
            list[list[float]]: 每个文本对应的浮点向量列表，长度与 texts 一致

        Raises:
            ValueError: texts 为空列表时抛出
            RuntimeError: HTTP 请求失败或响应格式无法解析时抛出
        """
        # Step 0: 输入防御
        if not texts:
            raise ValueError("texts 列表不能为空")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Step 1: 优先尝试 MiniMax 原生格式（texts 字段 + type 字段）
        payload_minimax = {
            "model": self.model_name,
            "texts": texts,
            "type": embed_type,
        }

        timeout_policy = httpx.Timeout(timeout=30.0)
        url = f"{self.base_url}/embeddings"

        async with httpx.AsyncClient(timeout=timeout_policy) as client:
            response = await client.post(
                url, headers=headers, json=payload_minimax
            )

            # Step 2: 如果 MiniMax 原生格式返回非 200，回退到 OpenAI 兼容格式
            if response.status_code != 200:
                payload_openai = {
                    "model": self.model_name,
                    "input": texts,
                }
                response = await client.post(
                    url, headers=headers, json=payload_openai
                )

            # Step 3: 最终状态检查
            if response.status_code != 200:
                raise RuntimeError(
                    f"Embedding API 请求错误 (HTTP {response.status_code}): "
                    f"{response.text[:500]}"
                )

            data = response.json()

        # Step 4: 响应格式解析（兼容两种返回结构）
        #   MiniMax 原生格式: {"vectors": [[...], [...]]}
        #   OpenAI 兼容格式:  {"data": [{"embedding": [...], "index": 0}, ...]}
        if "vectors" in data:
            return data["vectors"]
        elif "data" in data:
            # 按 index 排序以确保顺序与输入一致
            sorted_items = sorted(data["data"], key=lambda x: x.get("index", 0))
            return [item["embedding"] for item in sorted_items]
        else:
            raise RuntimeError(
                f"无法解析 Embedding API 响应格式，顶层键: {list(data.keys())}"
            )

    async def embed_single(
        self,
        text: str,
        embed_type: str = "db",
    ) -> list[float]:
        """单文本向量化（embed_texts 的便捷封装）

        Args:
            text: 单个待向量化的文本字符串
            embed_type: 向量用途标识（同 embed_texts）

        Returns:
            list[float]: 该文本对应的浮点向量
        """
        vectors = await self.embed_texts([text], embed_type)
        return vectors[0]
