"""
Week 4 公共辅助工具模块：环境变量加载与大模型基础 API 请求客户端

设计方案：
1. 设计意图：
   提供本周所有练习与大作业共享的底层配置加载和 API 请求基础设施。
   将重复性的环境变量寻址、httpx 异步网络客户端封装在此，使每日课程和练习能专注于其核心业务知识（如自一致性投票、JSON 纠错栈、Pydantic 运行时契约等）。

2. 核心结构：
   - `load_env_file()`: 手动防御性加载主工作区根目录下的 .env 环境变量文件。
   - `LLMClient`: 大模型通用异步网络通信类。
     - `request_llm(messages, temperature, max_tokens)`: 执行底层的 httpx.AsyncClient POST 调用并返回纯文本内容，包含温度值校验防御及异常转换。
"""

import os
import httpx
from typing import List, Dict, Optional, Any

def load_env_file():
    """手动防御性加载 .env 文件，防止依赖缺包"""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        # 向上寻找 3 层到达主工作区根目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.abspath(os.path.join(current_dir, "../../.env"))
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    val = val.strip().strip('"').strip("'")
                    os.environ[key.strip()] = val

# 在导入模块时自动触发一次环境变量加载
load_env_file()


class LLMClient:
    """真实大模型请求客户端基类"""
    
    def __init__(self):
        self.api_key = os.getenv("MINIMAX_API_KEY")
        self.base_url = os.getenv("MINIMAX_BASE_URL") or "https://api.minimax.chat/v1"
        self.model_name = os.getenv("MINIMAX_MODEL") or "MiniMax-M3"
        
        if not self.api_key:
            raise ValueError(
                "未在环境变量或 .env 中配置有效的 MINIMAX_API_KEY，请检查配置！"
            )

    async def request_llm(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1500,
        response_format: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        异步请求 LLM 接口
        :param response_format: 可选的 API 级格式约束，如 {"type": "json_object"} 强制厂商返回 JSON
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # 部分大模型 API 限制温度区间，在此执行防御性过滤
        temp_param = max(0.01, min(temperature, 1.0))
        
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temp_param,
            "max_tokens": max_tokens
        }
        
        # 如果调用方指定了厂商级 response_format 约束
        if response_format:
            payload["response_format"] = response_format
        
        # 统一设置细粒度网络超时控制 (读取超时放宽至 300 秒以防长研报生成超时)
        timeout_policy = httpx.Timeout(connect=15.0, read=300.0, write=300.0, pool=300.0)
        
        # 增加网络超时防抖重试 (最多重试 1 次)
        for attempt in range(2):
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
            except (httpx.ReadTimeout, httpx.ConnectTimeout) as net_err:
                if attempt == 1:
                    raise RuntimeError(f"LLM API 网络请求超时 (300s): {net_err}") from net_err
                print(f"⚠️ [LLMClient] 网络请求超时抖动 ({net_err})，正在自动发起第 2 次尝试...")
