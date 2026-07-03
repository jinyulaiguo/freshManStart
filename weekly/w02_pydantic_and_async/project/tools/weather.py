"""
设计方案：
- 设计意图：构建一个调用真实公开 wttr.in API 的异步天气查询工具，支持基于 httpx 的非阻塞网络 I/O 交互，并通过多层嵌套字典安全提取防护机制解析复杂的 API 响应体，确保网络超时或格式变动时系统健壮。
- 类与函数结构：
  - `WeatherTool` 类：实现 `BaseTool` 契约，引入 `AppSettings` 进行网络属性与超时配置。
- 关键数据流向：
  - `WeatherArgs` 参数输入 -> 拼接 HTTP URL -> `httpx` 发起异步 GET 请求 -> 接收 JSON 响应流 -> Day 1 嵌套字典安全解构提取温度与天气状况描述 -> 拼接格式化结果返回。
  - 网络不可达或 HTTP 代码非 2xx -> 捕获异常 -> 转换抛出自定义 `APIConnectionError` 以便上层进行重试和兜底。
"""

from typing import Type
import httpx
from pydantic import BaseModel
from weekly.w02_pydantic_and_async.project.config.settings import AppSettings
from weekly.w02_pydantic_and_async.project.exceptions.base import APIConnectionError
from weekly.w02_pydantic_and_async.project.models.tool_args import WeatherArgs
from weekly.w02_pydantic_and_async.project.tools.base import BaseTool

class WeatherTool(BaseTool):
    """基于 wttr.in 公开网络 API 的异步天气查询工具（I/O 密集型）"""

    def __init__(self, settings: AppSettings):
        self.settings = settings
        # 延迟导入以防止循环依赖，或直接使用 factory 中定义好的 logger 名字空间
        from weekly.w02_pydantic_and_async.project.log.factory import create_logger
        self.logger = create_logger("tools.weather", settings)

    @property
    def name(self) -> str:
        return "weather"

    @property
    def args_model(self) -> Type[BaseModel]:
        return WeatherArgs

    async def _execute(self, validated_args: WeatherArgs) -> str:
        city = validated_args.city
        days = validated_args.days
        
        # wttr.in API 支持返回结构化 JSON
        url = f"{self.settings.weather_api_base}/{city}?format=j1"
        self.logger.debug(f"Requesting weather from real API: {url} (days requested: {days})")

        try:
            async with httpx.AsyncClient(timeout=self.settings.http_timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as e:
            self.logger.warning(f"Timeout connecting to weather API for city: {city}")
            raise APIConnectionError(f"天气 API 请求超时: {str(e)}") from e
        except httpx.HTTPStatusError as e:
            self.logger.warning(f"HTTP error {e.response.status_code} from weather API")
            raise APIConnectionError(f"天气 API 响应状态异常: HTTP {e.response.status_code}") from e
        except Exception as e:
            self.logger.warning(f"Connection failure to weather API: {str(e)}")
            raise APIConnectionError(f"天气 API 网络通信失败: {str(e)}") from e

        # Day 1: 嵌套字典安全提取防御性解析
        try:
            current_condition_list = data.get("current_condition", [])
            current = current_condition_list[0] if isinstance(current_condition_list, list) and len(current_condition_list) > 0 else {}
            
            temp_c = current.get("temp_C", "N/A")
            feels_like = current.get("FeelsLikeC", "N/A")
            
            weather_desc_list = current.get("weatherDesc", [])
            desc_dict = weather_desc_list[0] if isinstance(weather_desc_list, list) and len(weather_desc_list) > 0 else {}
            description = desc_dict.get("value", "Unknown")

            return (
                f"Weather in {city}: {description}, Current: {temp_c}°C (Feels like: {feels_like}°C). "
                f"Prediction days: {days}."
            )
        except Exception as e:
            # 如果响应体结构发生改变，容错返回 Mock/Fallback，防止核心引擎崩溃
            self.logger.error(f"Failed to parse weather API response: {str(e)}")
            return f"Weather in {city}: Clear (Mock/Fallback due to parse error)"
