import asyncio
import traceback
from typing import Dict, List, Type, Annotated, Callable, Any, TypedDict
import httpx
from pydantic import BaseModel, Field, model_validator


# ==========================================
# 1. 异常定义与状态管理 (Day 8 & Day 13)
# ==========================================

class ToolExecuteError(Exception):
    """自定义工具执行包装异常"""
    pass


def merge_messages(old_messages: List[str], new_messages: List[str]) -> List[str]:
    """消息合并 Reducer"""
    if not isinstance(old_messages, list) or not isinstance(new_messages, list):
        raise TypeError("Reducer inputs must be lists.")
    return old_messages + new_messages


class RunnerState(TypedDict):
    """工具调度器全局状态限制"""
    tool_name: str
    steps: int
    messages: Annotated[List[str], merge_messages]


# ==========================================
# 2. 回调钩子定义 (Day 13)
# ==========================================

class BaseCallback:
    """事件监听回调基类"""
    def on_tool_start(self, tool_name: str, raw_args: str) -> None:
        """工具即将执行前触发"""
        pass

    def on_tool_success(self, tool_name: str, result: str) -> None:
        """工具正常执行完成并获得返回后触发"""
        pass

    def on_tool_error(self, tool_name: str, error: Exception) -> None:
        """工具校验或执行中发生任何异常时触发"""
        pass


# ==========================================
# 3. 工具参数 Pydantic 校验模型定义 (Day 9 & Day 10)
# ==========================================

class CalculatorArgs(BaseModel):
    """计算器工具入参模型"""
    x: float = Field(description="操作数 x")
    y: float = Field(description="操作数 y")
    operator: str = Field(description="运算符，只能是 +, -, *, / 之一")

    @model_validator(mode="after")
    def validate_operator(self) -> 'CalculatorArgs':
        if self.operator not in ['+', '-', '*', '/']:
            raise ValueError("运算符只能是 +, -, *, / 之一")
        return self


class WeatherArgs(BaseModel):
    """天气工具入参模型"""
    city: str = Field(description="查询城市名称")
    start_date: str = Field(description="查询起始日期，格式 YYYY-MM-DD")
    end_date: str = Field(description="查询结束日期，格式 YYYY-MM-DD")

    @model_validator(mode="after")
    def check_date_range(self) -> 'WeatherArgs':
        if self.start_date > self.end_date:
            raise ValueError("开始日期不能晚于结束日期")
        return self


# ==========================================
# 4. 核心异步工具调度器 (Day 11, 12, 13 & 14)
# ==========================================

class AsyncToolRunner:
    def __init__(self, callback: BaseCallback | None = None):
        # 1. 注册表：存储工具名与其绑定的 Pydantic 模型、异步函数
        self.registry: Dict[str, Dict[str, Any]] = {}
        # 2. 回调钩子实例
        self.callback = callback or BaseCallback()
        # 3. 初始化调度器状态 (Day 8)
        self.state: RunnerState = {
            "tool_name": "none",
            "steps": 0,
            "messages": ["Scheduler initialized."]
        }

    def register_tool(self, name: str, args_model: Type[BaseModel], func: Callable[[Any], Any]) -> None:
        """
        注册工具至调度中心。
        args_model: 参数对应的 Pydantic 模型类
        func: 异步执行函数 (async def)
        """
        self.registry[name] = {"args_model": args_model, "func": func}

    def get_tool_schemas(self) -> Dict[str, Dict]:
        """
        导出所有已注册工具的标准 JSON Schema 声明。
        """
        schemas = {}
        for name, info in self.registry.items():
            schemas[name] = info["args_model"].model_json_schema()
        return schemas

    async def run_tool(self, name: str, raw_json: str) -> str:
        """
        单工具安全调度执行主逻辑。
        1. 递增 steps 步数，记录状态中的 tool_name。
        2. 触发 on_tool_start 回调。
        3. 进行 Pydantic 反序列化与校验（校验失败需要捕获异常并包装）。
        4. 异步调用核心函数。
        5. 触发 on_tool_success 回调，使用 Reducer 合并状态。
        6. 捕获任何异常，包装为 ToolExecuteError，绑定原异常，触发 on_tool_error，向上抛出。
        """
        self.state["steps"] += 1
        self.state["tool_name"] = name
        
        self.callback.on_tool_start(name, raw_json)
        
        tool = self.registry.get(name)
        if not tool:
            err = ValueError(f"工具 {name} 未注册")
            wrapped = ToolExecuteError(str(err))
            wrapped.__cause__ = err
            self.callback.on_tool_error(name, wrapped)
            raise wrapped

        try:
            # 3. Pydantic 反序列化与数据拦截校验
            clean_args = tool["args_model"].model_validate_json(raw_json)
            
            # 4. 异步非阻塞执行
            result = await tool["func"](clean_args)
            result_str = str(result)
            
            # 5. 回调成功通知与状态归约更新
            self.callback.on_tool_success(name, result_str)
            self.state["messages"] = merge_messages(
                self.state["messages"],
                [f"Tool {name} executed successfully. Result: {result_str}"]
            )
            return result_str
            
        except Exception as e:
            # 6. 异常包装链式传递，并派发错误回调事件
            if isinstance(e, ToolExecuteError):
                self.callback.on_tool_error(name, e)
                raise e
            
            wrapped_err = ToolExecuteError(f"工具 {name} 运行出错")
            wrapped_err.__cause__ = e
            self.callback.on_tool_error(name, wrapped_err)
            raise wrapped_err

    async def run_concurrent_tools(self, requests: List[Dict[str, str]]) -> List[str]:
        """
        批量工具高吞吐异步并发调度引擎。
        requests: 例如 [{'name': 'calculator', 'args': '{"x": 1, "y": 2, "operator": "+"}'}, ...]
        使用 asyncio.gather 并发执行，收集并返回所有的结果列表。
        """
        tasks = []
        for req in requests:
            tasks.append(self.run_tool(req["name"], req["args"]))
        return await asyncio.gather(*tasks)


async def fetch_weather_api(args: WeatherArgs) -> str:
    """使用 httpx 异步网络 I/O 获取真实天气信息 (基于 wttr.in)，并在异常时使用 Mock 兜底返回"""
    # 真实 API 地址，wttr.in 支持无需 API key 的简单查询
    url = f"https://wttr.in/{args.city}?format=j1"
    try:
        # 使用 httpx.AsyncClient 发起非阻塞 HTTP 请求
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                current = data.get("current_condition", [{}])[0]
                temp_c = current.get("temp_C", "N/A")
                weather_desc = current.get("weatherDesc", [{}])[0].get("value", "N/A")
                return f"Weather in {args.city} from {args.start_date} to {args.end_date}: {weather_desc}, {temp_c}°C"
            else:
                raise httpx.HTTPStatusError(
                    f"HTTP error {response.status_code}",
                    request=response.request,
                    response=response
                )
    except Exception as e:
        # 若网络不可达、超时或服务故障，通过自定义异常传递/日志记录，并返回 Mock 数据进行业务降级
        # 返回 Mock 数据保证调用端可以获得合法返回值
        return f"Weather in {args.city} from {args.start_date} to {args.end_date}: Sunny (Mock/Fallback)"

