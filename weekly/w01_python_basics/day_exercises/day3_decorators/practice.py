"""
Day 3: 函数进阶与装饰器（工业级实战版）

本文件包含以下两个核心实战内容：
1. @agent_tool: 自动提取函数签名并生成 Tool Schema 的装饰器，且在运行时进行强类型验证。
2. @retry_with_backoff: 兼容同步与异步协程的指数退避重试装饰器，支持特定异常捕获。
"""

import asyncio
import inspect
import time
import typing
import sys
from functools import wraps

# 兼容 Python 3.10+ 的 Union 联合类型定义（如 int | str）
UnionTypes = (typing.Union,)
if sys.version_info >= (3, 10):
    import types
    UnionTypes += (types.UnionType,)

# Python 类型提示到 Standard JSON Schema 类型映射表
TYPE_MAPPING = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


# ==========================================
# 🛠️ 任务 1：@agent_tool 装饰器实现
# ==========================================
def agent_tool(func: typing.Callable) -> typing.Callable:
    """大模型工具定义与类型安全校验装饰器。
    
    1. 在加载时，反射解析函数签名，动态生成 __tool_schema__ 属性。
    2. 在运行时，强校验传入的实参是否符合类型提示声明，不符则抛出 TypeError。
    """
    sig = inspect.signature(func)
    
    # 1. 动态反射提取 Schema
    properties = {}
    required = []
    
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
            
        param_type = param.annotation
        
        # 解析 JSON Schema 的类型名称
        # 如果是 Union，取第一个非 None 类型进行简易映射；如果无法映射则兜底 "string"
        origin = getattr(param_type, "__origin__", None)
        if origin in UnionTypes:
            args = typing.get_args(param_type)
            # 过滤掉 NoneType
            non_none_args = [a for a in args if a is not type(None)]
            main_type = non_none_args[0] if non_none_args else str
            schema_type = TYPE_MAPPING.get(main_type, "string")
        else:
            schema_type = TYPE_MAPPING.get(param_type, "string")
            
        param_schema = {"type": schema_type}
        
        # 提取参数默认值
        if param.default is not inspect.Parameter.empty:
            param_schema["default"] = param.default
        else:
            required.append(name)
            
        properties[name] = param_schema

    schema = {
        "name": func.__name__,
        "description": func.__doc__.strip() if func.__doc__ else "No description provided.",
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required
        }
    }

    # 2. 构建包装函数，执行运行时校验
    @wraps(func)
    def wrapper(*args, **kwargs):
        # 绑定传入的实际参数并填充默认值
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()
        
        for name, value in bound_args.arguments.items():
            param = sig.parameters.get(name)
            if not param or param.annotation is inspect.Parameter.empty:
                continue
                
            expected_type = param.annotation
            origin = getattr(expected_type, "__origin__", None)
            
            # 解析出所有允许的真实类型
            if origin in UnionTypes:
                allowed_types = typing.get_args(expected_type)
            elif expected_type is float:
                allowed_types = (float, int)  # 工业实践中，float 允许传入 int
            else:
                allowed_types = (expected_type,)
                
            # 运行时类型校验
            is_valid = False
            for allowed_type in allowed_types:
                if allowed_type is type(None):
                    if value is None:
                        is_valid = True
                        break
                elif isinstance(allowed_type, type) and isinstance(value, allowed_type):
                    is_valid = True
                    break
                    
            if not is_valid:
                raise TypeError(
                    f"Parameter '{name}' in tool '{func.__name__}' expects type '{expected_type}', "
                    f"but received '{type(value).__name__}' (value: {value!r})"
                )
                
        return func(*args, **kwargs)
        
    # 绑定 schema 到包装后的可调用对象
    wrapper.__tool_schema__ = schema
    return wrapper


# ==========================================
# 🛡️ 任务 2：@retry_with_backoff 装饰器实现
# ==========================================
def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 10.0,
    retry_exceptions: typing.Tuple[typing.Type[Exception], ...] = (Exception,),
) -> typing.Callable:
    """带指数退避的重试装饰器，自动兼容同步函数与异步协程。
    
    参数:
        max_retries: 最大尝试次数。
        initial_delay: 首次失败后的等待时间（秒）。
        backoff_factor: 每次失败后延迟时间的指数递增因子。
        max_delay: 最大重试延迟上限（秒）。
        retry_exceptions: 需要触发重试的异常类型元组，其他异常将直接抛出。
    """
    def decorator(func: typing.Callable) -> typing.Callable:
        # 1. 异步通道
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                delay = initial_delay
                for attempt in range(1, max_retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except retry_exceptions as e:
                        if attempt == max_retries:
                            raise e
                        print(
                            f"[Retry Warning] Async {func.__name__} raised {e.__class__.__name__}. "
                            f"Attempt {attempt}/{max_retries} failed. Retrying in {delay:.2f}s..."
                        )
                        await asyncio.sleep(delay)
                        delay = min(delay * backoff_factor, max_delay)
            return async_wrapper
            
        # 2. 同步通道
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                delay = initial_delay
                for attempt in range(1, max_retries + 1):
                    try:
                        return func(*args, **kwargs)
                    except retry_exceptions as e:
                        if attempt == max_retries:
                            raise e
                        print(
                            f"[Retry Warning] Sync {func.__name__} raised {e.__class__.__name__}. "
                            f"Attempt {attempt}/{max_retries} failed. Retrying in {delay:.2f}s..."
                        )
                        time.sleep(delay)
                        delay = min(delay * backoff_factor, max_delay)
            return sync_wrapper
            
    return decorator


# ==========================================
# 🌟 演示与自验证运行入口
# ==========================================
@agent_tool
def get_user_info(user_id: int, include_details: bool = False, nickname: typing.Optional[str] = None):
    """根据用户ID获取用户信息，支持高级配置参数。"""
    return {
        "user_id": user_id,
        "include_details": include_details,
        "nickname": nickname,
        "status": "active"
    }


@retry_with_backoff(max_retries=3, initial_delay=0.5, retry_exceptions=(ConnectionError, TimeoutError))
async def mock_async_api_call(url: str, should_fail: bool = True):
    """模拟大模型 API 异步调用，展示重试机制。"""
    print(f"  [API Call] Requesting: {url} ...")
    if should_fail:
        raise ConnectionError("Network handshake timeout.")
    return {"status": "success", "content": "hello world"}


if __name__ == "__main__":
    print("--- [1. @agent_tool 反射 Schema 演示] ---")
    import json
    print(json.dumps(get_user_info.__tool_schema__, indent=2, ensure_ascii=False))

    print("\n--- [2. @agent_tool 运行时类型强验证校验] ---")
    try:
        # 正常调用
        print("正常调用结果:", get_user_info(12345, include_details=True, nickname="PythonMaster"))
        
        # 异常调用：故意传递错误的类型 user_id = "abc" (期望为 int)
        print("尝试传入错误类型参数...")
        get_user_info("abc")  # 这行应该抛出 TypeError
    except TypeError as type_err:
        print(f"成功拦截类型错误: {type_err}")

    print("\n--- [3. @retry_with_backoff 指数退避异步重试演示] ---")
    try:
        # 执行会失败的异步 API 调用，观察重试日志
        asyncio.run(mock_async_api_call("https://api.openai.com/v1/chat/completions"))
    except ConnectionError as conn_err:
        print(f"最终重试耗尽抛出异常: {conn_err}")
