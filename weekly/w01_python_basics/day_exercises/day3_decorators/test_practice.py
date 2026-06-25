import unittest
import asyncio
import time
import typing
from weekly.w01_python_basics.day_exercises.day3_decorators.practice import agent_tool, retry_with_backoff


class TestAgentToolDecorator(unittest.TestCase):
    """测试 @agent_tool 装饰器"""

    def test_schema_generation(self):
        """测试 @agent_tool 生成的 Schema 是否满足要求"""
        @agent_tool
        def complex_tool(
            api_key: str,
            timeout: int = 10,
            threshold: float = 0.5,
            debug_mode: bool = False,
            metadata: typing.Optional[dict] = None
        ):
            """这是一个用于测试的复杂 Agent 工具，包含各种不同类型的参数。"""
            return "ok"

        schema = complex_tool.__tool_schema__
        
        # 1. 验证基础结构
        self.assertEqual(schema["name"], "complex_tool")
        self.assertEqual(schema["description"], "这是一个用于测试的复杂 Agent 工具，包含各种不同类型的参数。")
        self.assertEqual(schema["parameters"]["type"], "object")
        
        # 2. 验证必填字段
        # api_key 没有默认值，应该在 required 列表中；其他的有默认值，不应该在 required 中
        self.assertIn("api_key", schema["parameters"]["required"])
        self.assertNotIn("timeout", schema["parameters"]["required"])
        self.assertNotIn("threshold", schema["parameters"]["required"])
        
        # 3. 验证参数类型映射
        properties = schema["parameters"]["properties"]
        self.assertEqual(properties["api_key"]["type"], "string")
        self.assertEqual(properties["timeout"]["type"], "integer")
        self.assertEqual(properties["threshold"]["type"], "number")
        self.assertEqual(properties["debug_mode"]["type"], "boolean")
        self.assertEqual(properties["metadata"]["type"], "object")
        
        # 4. 验证默认值
        self.assertEqual(properties["timeout"]["default"], 10)
        self.assertEqual(properties["threshold"]["default"], 0.5)
        self.assertEqual(properties["debug_mode"]["default"], False)

    def test_runtime_type_validation_success(self):
        """测试正常类型参数调用是否成功"""
        @agent_tool
        def add_task(title: str, priority: int, tags: list):
            return f"Task '{title}' added with priority {priority}."

        # 传递完全正确类型的参数
        result = add_task("Finish homework", 1, ["study", "today"])
        self.assertEqual(result, "Task 'Finish homework' added with priority 1.")
        
        # 测试 float 参数接受 int 的情况（工业实践中 float 类型可兼容 int 输入）
        @agent_tool
        def set_temperature(temp: float):
            return temp
            
        self.assertEqual(set_temperature(25.5), 25.5)
        self.assertEqual(set_temperature(25), 25)  # 25 是 int，但在 float 期望中应校验通过

    def test_runtime_type_validation_failure(self):
        """测试非正常类型参数是否抛出 TypeError 阻断执行"""
        @agent_tool
        def send_alert(message: str, code: int):
            return "Alert Sent"

        # 1. 校验第一个参数传入错误类型 (传入了 int 类型的 123，期望 str)
        with self.assertRaises(TypeError) as context:
            send_alert(123, 500)
        self.assertIn("Parameter 'message'", str(context.exception))
        
        # 2. 校验第二个参数传入错误类型 (传入了 str 类型的 '500'，期望 int)
        with self.assertRaises(TypeError) as context:
            send_alert("System crash", "500")
        self.assertIn("Parameter 'code'", str(context.exception))

    def test_union_and_optional_types(self):
        """测试 Union 与 Optional 类型的安全校验"""
        @agent_tool
        def format_payload(data: dict, prefix: typing.Optional[str] = None):
            return f"{prefix}: {data}" if prefix else str(data)

        # 1. 传递有效的类型（None 或者是 str）
        self.assertEqual(format_payload({"id": 1}, prefix="Data"), "Data: {'id': 1}")
        self.assertEqual(format_payload({"id": 1}, prefix=None), "{'id': 1}")

        # 2. 传递无效的类型（如传入列表作为 prefix，期望 Optional[str]）
        with self.assertRaises(TypeError):
            format_payload({"id": 1}, prefix=[1, 2, 3])


class TestRetryDecorator(unittest.IsolatedAsyncioTestCase):
    """测试 @retry_with_backoff 装饰器 (支持异步环境测试)"""

    def test_sync_retry_success_after_failure(self):
        """测试同步重试：函数在前几次抛出异常，但在重试限制次数内成功"""
        call_count = 0

        @retry_with_backoff(max_retries=3, initial_delay=0.01, retry_exceptions=(ValueError,))
        def unstable_sync_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary connection error")
            return "success"

        result = unstable_sync_func()
        self.assertEqual(result, "success")
        self.assertEqual(call_count, 3)

    def test_sync_retry_exhausted(self):
        """测试同步重试：重试次数耗尽后抛出最后一次的异常"""
        call_count = 0

        @retry_with_backoff(max_retries=3, initial_delay=0.01, retry_exceptions=(IOError,))
        def broken_sync_func():
            nonlocal call_count
            call_count += 1
            raise IOError("Persistent disk full error")

        with self.assertRaises(IOError):
            broken_sync_func()
        self.assertEqual(call_count, 3)

    def test_sync_no_retry_on_unspecified_exceptions(self):
        """测试同步重试：如果抛出了未指定在 retry_exceptions 里的异常，应立刻抛出且不进行重试"""
        call_count = 0

        @retry_with_backoff(max_retries=5, initial_delay=0.01, retry_exceptions=(ConnectionError,))
        def buggy_func():
            nonlocal call_count
            call_count += 1
            raise KeyError("Key not found")  # 抛出 KeyError，但指定重试异常是 ConnectionError

        with self.assertRaises(KeyError):
            buggy_func()
        # 应只调用一次，直接退出
        self.assertEqual(call_count, 1)

    async def test_async_retry_success(self):
        """测试异步重试：异步函数在重试次数内成功恢复"""
        call_count = 0

        @retry_with_backoff(max_retries=4, initial_delay=0.01, retry_exceptions=(TimeoutError,))
        async def unstable_async_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TimeoutError("API Request Timeout")
            return "async success"

        result = await unstable_async_func()
        self.assertEqual(result, "async success")
        self.assertEqual(call_count, 3)

    async def test_async_retry_exhausted(self):
        """测试异步重试：次数耗尽，正确抛出异常"""
        call_count = 0

        @retry_with_backoff(max_retries=3, initial_delay=0.01, retry_exceptions=(RuntimeError,))
        async def broken_async_func():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Database connection lost permanently")

        with self.assertRaises(RuntimeError):
            await broken_async_func()
        self.assertEqual(call_count, 3)

    def test_metadata_preservation(self):
        """测试装饰器是否利用 functools.wraps 成功保留了函数元数据"""
        @retry_with_backoff(max_retries=2, initial_delay=0.01)
        def my_test_worker(x: int):
            """这是一个工作者函数的 Docstring。"""
            return x

        self.assertEqual(my_test_worker.__name__, "my_test_worker")
        self.assertEqual(my_test_worker.__doc__, "这是一个工作者函数的 Docstring。")
        self.assertEqual(my_test_worker(10), 10)


if __name__ == "__main__":
    unittest.main()
