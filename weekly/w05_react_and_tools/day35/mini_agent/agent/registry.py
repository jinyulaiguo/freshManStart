"""
MiniAgent Framework v1.0 — 动态 Tool 反射注册中心

设计方案：
1. 设计意图：
   从 Day30 的 ToolRegistry 重构而来，遵循"职责单一化"原则：
   - 只负责：注册、反射解析（docstring/签名）、Pydantic 动态建模、Schema 导出、查找
   - 不负责：调用执行（交给 Dispatcher）、参数校验反馈（交给 Dispatcher）
   
   对比 Day30 的变化：
   - 新增 get_all_schemas() 批量导出，供 System Prompt 动态拼装使用
   - 新增 get_tool_model() 直接获取 Pydantic 校验模型
   - 新增 list_tools() 列出所有已注册工具名
   - 全局单例 registry 和 @tool 装饰器保持接口兼容

2. 类与函数结构：
   - ToolRegistry: 工具注册中心类
     - register(func): 反射解析并注册异步工具函数
     - get_tool_schema(name): 获取单个工具的 OpenAI Schema
     - get_all_schemas(): 批量获取所有工具的 OpenAI Schema 列表
     - get_tool_func(name): 获取绑定的本地异步函数
     - get_tool_model(name): 获取 Pydantic 动态校验模型
     - list_tools(): 列出所有已注册工具名称
     - _parse_docstring(doc): 解析 docstring 提取描述与参数说明
     - _clean_schema(schema): 递归清除冗余 title 键
   - tool(func): @tool 装饰器（绑定全局单例）

3. 数据流流向：
   - async def 函数被 @tool 装饰 → register() 捕获
   - inspect 提取函数签名 + 类型注解 + docstring
   - _parse_docstring 分离主描述与参数描述
   - pydantic.create_model 动态创建校验器
   - 规整为 OpenAI function schema 存入内部 _tools 字典
   - Dispatcher 通过 get_tool_func / get_tool_model 获取执行所需资源
   - Runner 通过 get_all_schemas 批量拉取 schema 用于 System Prompt 拼装
"""
from __future__ import annotations

import inspect
import re
from typing import Any, Callable, Dict, List, Tuple

from pydantic import BaseModel, Field, create_model


class ToolRegistry:
    """
    动态 Tool 反射注册中心。

    通过 Python 运行时反射机制，从异步函数的签名、类型注解和 docstring
    中自动提取工具元数据，动态构建 Pydantic 校验模型并导出 OpenAI 兼容的
    JSON Schema，无需手动硬编码工具的 schema 定义。

    内部存储格式：
        {
            "tool_name": {
                "func": <async function>,
                "schema": <OpenAI JSON Schema dict>,
                "model": <Pydantic BaseModel class>
            }
        }
    """

    def __init__(self) -> None:
        """初始化工具池映射字典。"""
        # 内部工具池：键为工具名，值为包含 func / schema / model 的字典
        self._tools: Dict[str, Dict[str, Any]] = {}

    def _parse_docstring(self, doc: str) -> Tuple[str, Dict[str, str]]:
        """
        解析函数的 docstring，提取工具主描述及各参数的描述文字。

        支持标准的 Google-style docstring 格式：
            工具主描述文字（多行）

            Args:
                param_name: 参数描述。
                other_param (type): 参数描述（括号注释会被忽略）。

        Args:
            doc: 原始函数 docstring 字符串。

        Returns:
            Tuple[str, Dict[str, str]]:
                - 第一个元素为工具的主功能描述（Args 之前的所有内容）
                - 第二个元素为参数名到描述的映射字典
        """
        if not doc:
            return "", {}

        doc = doc.strip()
        lines = doc.split("\n")

        # 1. 提取 Args 之前的主描述行
        main_desc_lines: List[str] = []
        for line in lines:
            if line.strip().startswith(("Args:", "Parameters:")):
                break
            main_desc_lines.append(line.strip())
        main_desc = "\n".join(main_desc_lines).strip()

        # 2. 正则提取 Args 段落内各参数的名称及说明
        # 匹配格式：  param_name: 描述  或  param_name (type): 描述
        param_descs: Dict[str, str] = {}
        pattern = re.compile(r"^\s*([\w_]+)\s*(?:\([^)]+\))?\s*:\s*(.+)$")

        in_args_section = False
        for line in lines:
            cleaned_line = line.strip()
            # 定位 Args 分割标志行
            if cleaned_line.startswith(("Args:", "Parameters:")):
                in_args_section = True
                continue
            if in_args_section:
                # 若遇到非缩进的非空行，说明已离开 Args 段落
                if not line.startswith(" ") and cleaned_line:
                    in_args_section = False
                    continue
                match = pattern.match(line)
                if match:
                    name, desc = match.groups()
                    param_descs[name.strip()] = desc.strip()

        return main_desc, param_descs

    def _clean_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        递归清理 JSON Schema 中 Pydantic 默认生成的 'title' 键。

        Pydantic 会在每个字段的 JSON Schema 中自动添加 title，这些 title
        会占用额外的 Token 并可能干扰某些 LLM 接口的参数解析，因此统一移除。

        Args:
            schema: 原始 Pydantic JSON Schema 字典。

        Returns:
            递归清洗掉所有 'title' 属性后的规范 JSON Schema 字典。
        """
        if not isinstance(schema, dict):
            return schema
        cleaned: Dict[str, Any] = {}
        for k, v in schema.items():
            if k == "title":
                # 跳过所有 title 键
                continue
            if isinstance(v, dict):
                cleaned[k] = self._clean_schema(v)
            elif isinstance(v, list):
                cleaned[k] = [
                    self._clean_schema(item) if isinstance(item, dict) else item
                    for item in v
                ]
            else:
                cleaned[k] = v
        return cleaned

    def register(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """
        将目标异步函数反射解析并注册至工具池中。

        注册流程：
        1. 校验目标函数是否为 async def（协程函数）
        2. 使用 inspect 提取函数签名、类型注解与 docstring
        3. 解析 docstring 获取主描述和各参数描述
        4. 扫描所有参数，构建 Pydantic 字段规格
        5. 调用 pydantic.create_model 动态创建校验器
        6. 导出 JSON Schema 并规整为 OpenAI function 格式
        7. 存入 _tools 字典

        Args:
            func: 目标工具异步函数（必须是 async def）。

        Returns:
            原始函数引用（保持装饰器链透明性，允许函数继续被正常调用）。

        Raises:
            TypeError: 传入非异步函数时抛出。
            ValueError: 任意参数缺少类型注解时抛出。
        """
        # 1. 强制异步协程约束校验
        if not inspect.iscoroutinefunction(func):
            raise TypeError(
                f"注册工具失败：工具函数 '{func.__name__}' 必须是异步协程函数 (async def)，"
                f"当前类型为 {type(func).__name__}。"
            )

        tool_name = func.__name__
        sig = inspect.signature(func)
        doc = inspect.getdoc(func) or ""

        # 2. 解析 docstring 提取描述信息
        main_desc, param_descs = self._parse_docstring(doc)

        # 3. 扫描所有参数，构建 Pydantic 字段规格字典
        fields_spec: Dict[str, Any] = {}
        for param_name, param in sig.parameters.items():
            # 校验参数类型注解是否存在
            if param.annotation == inspect.Parameter.empty:
                raise ValueError(
                    f"注册工具失败：函数 '{tool_name}' 的参数 '{param_name}' "
                    f"未定义显式类型注解，请添加类型注解（如 city: str）。"
                )

            desc = param_descs.get(param_name, "")

            if param.default == inspect.Parameter.empty:
                # 必填参数：无默认值，Field 使用 ... 表示必填
                fields_spec[param_name] = (param.annotation, Field(..., description=desc))
            else:
                # 选填参数：有默认值，Field 保留原始默认值
                fields_spec[param_name] = (
                    param.annotation,
                    Field(default=param.default, description=desc),
                )

        # 4. 动态构建 Pydantic 校验模型（类名：{ToolName}Input）
        model_name = f"{tool_name}Input"
        dynamic_model: type[BaseModel] = create_model(model_name, **fields_spec)

        # 5. 导出 JSON Schema 并递归清理冗余 title 键
        raw_schema = dynamic_model.model_json_schema()
        cleaned_schema = self._clean_schema(raw_schema)

        # 6. 重构为 OpenAI 原生 function 协议格式
        openai_schema = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": main_desc,
                "parameters": cleaned_schema,
            },
        }

        # 7. 存入工具池
        self._tools[tool_name] = {
            "func": func,
            "schema": openai_schema,
            "model": dynamic_model,
        }

        return func

    def get_tool_schema(self, name: str) -> Dict[str, Any]:
        """
        获取指定工具的 OpenAI 兼容 JSON Schema 定义。

        Args:
            name: 工具函数名称。

        Returns:
            OpenAI function schema 字典。

        Raises:
            KeyError: 工具名称未在注册池中注册时抛出。
        """
        if name not in self._tools:
            raise KeyError(f"工具 '{name}' 未在注册中心注册。已注册工具：{list(self._tools.keys())}")
        return self._tools[name]["schema"]

    def get_all_schemas(self) -> List[Dict[str, Any]]:
        """
        批量获取所有已注册工具的 OpenAI Schema 列表。

        用于 Runner 构建 System Prompt 时，动态拼装所有可用工具的描述。

        Returns:
            按注册顺序排列的 OpenAI function schema 列表。
        """
        return [info["schema"] for info in self._tools.values()]

    def get_tool_func(self, name: str) -> Callable[..., Any]:
        """
        获取指定工具绑定的本地异步函数。

        Args:
            name: 工具函数名称。

        Returns:
            绑定的 async def 函数对象，可直接 await 调用。

        Raises:
            KeyError: 工具名称未在注册池中注册时抛出。
        """
        if name not in self._tools:
            raise KeyError(f"工具 '{name}' 未在注册中心注册。")
        return self._tools[name]["func"]

    def get_tool_model(self, name: str) -> type[BaseModel]:
        """
        获取指定工具的 Pydantic 动态校验模型。

        Dispatcher 在执行工具前使用此模型对 LLM 输出的原始参数进行
        强类型契约校验（自动类型转换 + 必填字段检查 + 默认值补全）。

        Args:
            name: 工具函数名称。

        Returns:
            动态生成的 Pydantic BaseModel 子类。

        Raises:
            KeyError: 工具名称未在注册池中注册时抛出。
        """
        if name not in self._tools:
            raise KeyError(f"工具 '{name}' 未在注册中心注册。")
        return self._tools[name]["model"]

    def list_tools(self) -> List[str]:
        """
        列出所有已注册的工具名称。

        Returns:
            已注册工具名称的列表（按注册顺序）。
        """
        return list(self._tools.keys())

    def __contains__(self, name: str) -> bool:
        """支持 `if tool_name in registry` 的语法检查。"""
        return name in self._tools

    def __len__(self) -> int:
        """返回已注册工具数量。"""
        return len(self._tools)


# ==================== 全局注册中心单例 ====================
# 整个 Framework 使用同一个全局单例，工具通过 @tool 装饰器自动注册到此实例
registry = ToolRegistry()


def tool(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    @tool 装饰器：将异步函数自动注册到全局 ToolRegistry 单例中。

    使用方式：
        @tool
        async def get_weather(city: str) -> str:
            '''获取指定城市天气。'''
            ...

    Args:
        func: 目标工具异步函数（必须是 async def）。

    Returns:
        原始函数引用（装饰器透明，不改变函数行为）。
    """
    return registry.register(func)
