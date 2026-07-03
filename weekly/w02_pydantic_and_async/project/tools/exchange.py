"""
设计方案：
- 设计意图：构建一个调用真实公开 Frankfurter 汇率 API 的异步货币换算工具，演示异步网络通信与实时外部金融数据的获取与解析，并对不支持的币种进行动态容错与拦截。
- 类与函数结构：
  - `ExchangeTool` 类：实现 `BaseTool` 契约，引入 `AppSettings` 进行超时及 API 终结点配置。
- 关键数据流向：
  - `ExchangeArgs` (金额, 源币种, 目标币种) 校验参数输入 -> 拼接 HTTP URL -> `httpx` 发起异步 GET 请求 -> 接收最新汇率字典 -> 安全提取并计算转换后金额 -> 返回格式化汇率转换字符串。
  - 网络不可达或 HTTP 代码非 2xx -> 捕获异常 -> 转换抛出自定义 `APIConnectionError` 以便重试。
"""

from typing import Type
import httpx
from pydantic import BaseModel
from weekly.w02_pydantic_and_async.project.config.settings import AppSettings
from weekly.w02_pydantic_and_async.project.exceptions.base import APIConnectionError
from weekly.w02_pydantic_and_async.project.models.tool_args import ExchangeArgs
from weekly.w02_pydantic_and_async.project.tools.base import BaseTool

class ExchangeTool(BaseTool):
    """基于 frankfurter.app 公开网络 API 的异步汇率转换工具（I/O 密集型）"""

    def __init__(self, settings: AppSettings):
        self.settings = settings
        from weekly.w02_pydantic_and_async.project.log.factory import create_logger
        self.logger = create_logger("tools.exchange", settings)

    @property
    def name(self) -> str:
        return "exchange"

    @property
    def args_model(self) -> Type[BaseModel]:
        return ExchangeArgs

    async def _execute(self, validated_args: ExchangeArgs) -> str:
        base = validated_args.base_currency
        target = validated_args.target_currency
        amount = validated_args.amount

        # frankfurter.app v2 API 路径
        url = f"{self.settings.exchange_api_base}/rate/{base}/{target}"
        self.logger.debug(f"Requesting currency exchange from real API: {url}")

        try:
            async with httpx.AsyncClient(timeout=self.settings.http_timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as e:
            self.logger.warning(f"Timeout connecting to exchange API from {base} to {target}")
            raise APIConnectionError(f"汇率 API 请求超时: {str(e)}") from e
        except httpx.HTTPStatusError as e:
            self.logger.warning(f"HTTP error {e.response.status_code} from exchange API")
            # Frankfurter v2 如果遇到不支持的货币会返回 404 或 422
            if e.response.status_code in (400, 404, 422):
                raise ValueError(f"不支持的货币转换类型: {base} -> {target}，请确认货币代码是否在 Frankfurter 支持列表中") from e
            raise APIConnectionError(f"汇率 API 响应状态异常: HTTP {e.response.status_code}") from e
        except Exception as e:
            self.logger.warning(f"Connection failure to exchange API: {str(e)}")
            raise APIConnectionError(f"汇率 API 网络通信失败: {str(e)}") from e

        # Day 1: 嵌套字典安全提取与计算
        try:
            rate = data.get("rate")
            
            if rate is None:
                raise ValueError(f"API 响应中未找到目标货币 '{target}' 的汇率")

            converted = amount * rate
            return (
                f"{amount:.2f} {base} = {converted:.2f} {target} "
                f"(Rate: {rate:.4f} on {data.get('date', 'N/A')})"
            )
        except ValueError as e:
            raise e
        except Exception as e:
            self.logger.error(f"Failed to parse exchange API response: {str(e)}")
            # 返回降级 Mock 汇率以防引擎死机（降级为 1:1）
            return f"{amount:.2f} {base} = {amount:.2f} {target} (Mock/Fallback 1:1 due to parse error)"
