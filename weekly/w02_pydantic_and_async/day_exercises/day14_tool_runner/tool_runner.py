import asyncio
import traceback
from typing import Dict, List, Type, Annotated, Callable, Any, TypedDict
from pydantic import BaseModel, Field, model_validator


# ==========================================
# 1. 异常定义与状态管理 (Day 8 & Day 13)
# ==========================================

class ToolExecuteError(Exception):
    """自定义工具执行包装异常"""
    pass


def merge_messages(old_messages: List[str], new_messages: List[str]) -> List[str]:
    """消息合并 Reducer"""
    # TODO: 实现新老消息列表的追加合并
    raise NotImplementedError("TODO")


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
        self.registry: Dict[str, Dict[str, Any]] = {}
        self.callback = callback or BaseCallback()
        self.state: RunnerState = {
            "tool_name": "none",
            "steps": 0,
            "messages": ["Scheduler initialized."]
        }

    def register_tool(self, name: str, args_model: Type[BaseModel], func: Callable[[Any], Any]) -> None:
        """
        注册工具至调度中心。
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
            clean_args = tool["args_model"].model_validate_json(raw_json)
            
            result = await tool["func"](clean_args)
            result_str = str(result)
            
            self.callback.on_tool_success(name, result_str)
            self.state["messages"] = merge_messages(self.state["messages"], [f"Tool {name} executed successfully. Result: {result_str}"])
            
            return result_str
            
        except Exception as e:
            wrapped_err = ToolExecuteError(f"工具 {name} 运行出错")
            wrapped_err.__cause__ = e
            self.callback.on_tool_error(name, wrapped_err)
            raise wrapped_err

    async def run_concurrent_tools(self, requests: List[Dict[str, str]]) -> List[str]:
        """
        批量工具高吞吐异步并发调度引擎。
        """
        tasks = []
        for req in requests:
            tasks.append(self.run_tool(req["name"], req["args"]))
        return await asyncio.gather(*tasks)
