"""
设计方案：
1. 设计意图：构建一个动态 Tool 反射注册中心，支持通过 `@tool` 装饰器自动捕获 Python 异步工具函数，反射其函数签名与 docstring，并动态构建 Pydantic 校验模型，最终导出 OpenAI 兼容的 JSON Schema 协议定义。
2. 类与函数结构：
   - ToolRegistry: 工具注册中心类。
     - __init__(self): 初始化工具池映射。
     - register(self, func): 捕获装饰函数，执行反射解析与动态 Pydantic 建模。
     - get_tool_schema(self, name: str) -> dict: 获取指定工具的规范 JSON Schema。
     - get_tool_func(self, name: str): 获取绑定的本地异步函数。
     - _parse_docstring(self, doc: str) -> tuple[str, dict[str, str]]: 辅助解析 docstring，提取函数总体描述与各参数描述。
     - _clean_schema(self, schema: dict) -> dict: 递归清除 JSON Schema 中冗余的 title 键。
   - tool: 装饰器函数，用于绑定全局注册中心实例。
3. 数据流流向：
   - 当异步函数被 `@tool` 装饰时，进入 register 阶段。
   - 使用 inspect 检查函数签名，校验类型注解的存在性。
   - 解析 docstring 提取工具的主描述及参数对应的描述文字。
   - 根据参数的“类型、默认值、描述说明”，利用 pydantic.create_model 创建运行时校验器。
   - 提取校验器的 model_json_schema()，并重构成 OpenAI 格式，存储至工具池中。
"""
import inspect
import re
from typing import Callable, Any, Dict, Tuple
from pydantic import create_model, Field, BaseModel

class ToolRegistry:
    def __init__(self):
        # 存储格式：{tool_name: {"func": func, "schema": schema_dict, "model": pydantic_model}}
        self._tools: Dict[str, Dict[str, Any]] = {}

    def _parse_docstring(self, doc: str) -> Tuple[str, Dict[str, str]]:
        """
        解析函数的 docstring，提取工具主描述及各参数的描述文字。
        支持格式举例：
        \"\"\"
        这是工具的主要描述文字。
        
        Args:
            city: 目标城市名称。
            days: 预测的天数。
        \"\"\"
        """
        if not doc:
            return "", {}
            
        doc = doc.strip()
        lines = doc.split("\n")
        
        # 提取主描述（以空行为分界，或 Args 之前的所有第一行/多行内容）
        main_desc_lines = []
        for line in lines:
            if line.strip().startswith(("Args:", "Parameters:", "Args", "Parameters")):
                break
            main_desc_lines.append(line.strip())
        main_desc = "\n".join(main_desc_lines).strip()
        
        # 提取参数描述
        param_descs = {}
        # 匹配类似于: "    param_name: 描述内容" 或 "    param_name (type): 描述内容"
        pattern = re.compile(r"^\s*([\w_]+)\s*(?:\([^)]+\))?\s*:\s*(.+)$")
        
        in_args_section = False
        for line in lines:
            cleaned_line = line.strip()
            if cleaned_line.startswith(("Args:", "Parameters:", "Args", "Parameters")):
                in_args_section = True
                continue
            if in_args_section:
                # 如果遇到空行或新的顶级缩进（不以空格开头且包含冒号），判定退出参数部分
                if not line.startswith(" ") and cleaned_line:
                    in_args_section = False
                    continue
                match = pattern.match(line)
                if match:
                    name, desc = match.groups()
                    param_descs[name.strip()] = desc.strip()
                    
        return main_desc, param_descs

    def _clean_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """递归清理 JSON Schema 中的 'title' 键，防止干扰模型"""
        if not isinstance(schema, dict):
            return schema
        cleaned = {}
        for k, v in schema.items():
            if k == "title":
                continue
            if isinstance(v, dict):
                cleaned[k] = self._clean_schema(v)
            elif isinstance(v, list):
                cleaned[k] = [self._clean_schema(item) if isinstance(item, dict) else item for item in v]
            else:
                cleaned[k] = v
        return cleaned

    def register(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """
        将目标异步函数反射解析并注册至工具池中。
        """
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"注册工具失败：工具函数 '{func.__name__}' 必须是异步协程函数 (async def)")
            
        tool_name = func.__name__
        sig = inspect.signature(func)
        doc = inspect.getdoc(func) or ""
        
        # 1. 解析 docstring
        main_desc, param_descs = self._parse_docstring(doc)
        
        # 2. 扫描函数参数并构造 Pydantic 字段契约
        fields_spec = {}
        for param_name, param in sig.parameters.items():
            # 校验参数是否标明了类型注解
            if param.annotation == inspect.Parameter.empty:
                raise ValueError(
                    f"注册工具失败：函数 '{tool_name}' 的参数 '{param_name}' 未定义显式类型注解。"
                )
                
            desc = param_descs.get(param_name, "")
            
            # 判断可选性与设置默认值
            if param.default == inspect.Parameter.empty:
                # 必填字段
                fields_spec[param_name] = (param.annotation, Field(..., description=desc))
            else:
                # 选填字段，赋予默认值
                fields_spec[param_name] = (param.annotation, Field(default=param.default, description=desc))
                
        # 3. 动态构建 Pydantic 校验模型
        model_name = f"{tool_name}Input"
        dynamic_model = create_model(model_name, **fields_spec)
        
        # 4. 导出并规整 JSON Schema 结构
        raw_schema = dynamic_model.model_json_schema()
        cleaned_schema = self._clean_schema(raw_schema)
        
        openai_schema = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": main_desc,
                "parameters": cleaned_schema
            }
        }
        
        # 5. 存储至池中
        self._tools[tool_name] = {
            "func": func,
            "schema": openai_schema,
            "model": dynamic_model
        }
        
        return func

    def get_tool_schema(self, name: str) -> Dict[str, Any]:
        """获取指定工具的 OpenAI 兼容 JSON Schema 定义"""
        if name not in self._tools:
            raise KeyError(f"工具 '{name}' 未在注册中心注册。")
        return self._tools[name]["schema"]

    def get_tool_func(self, name: str) -> Callable[..., Any]:
        """获取指定工具绑定的异步函数"""
        if name not in self._tools:
            raise KeyError(f"工具 '{name}' 未在注册中心注册。")
        return self._tools[name]["func"]

# 初始化全局注册中心单例
registry = ToolRegistry()

def tool(func: Callable[..., Any]) -> Callable[..., Any]:
    """工具绑定装饰器包装"""
    return registry.register(func)

if __name__ == "__main__":
    print("=" * 60)
    print("运行 ToolRegistry 动态反射与建模测试与演示...")
    print("=" * 60)
    
    # 模拟成功的注册
    @tool
    async def get_weather(city: str, days: int = 1) -> str:
        """
        获取目标城市未来数天的天气状况。
        
        Args:
            city: 目标城市名称，例如 "北京" 或 "Shanghai"。
            days: 天气预报天数，可选 1-7 天。
        """
        return f"{city}未来 {days} 天为晴天。"

    # 获取并打印生成的 OpenAI 规范 Schema
    schema = registry.get_tool_schema("get_weather")
    print("\n🎉 成功捕获工具并反射生成 Schema:")
    import json
    print(json.dumps(schema, indent=2, ensure_ascii=False))
    
    # 测试强类型校验拦截功能：缺失参数注解报错
    print("\n开始测试强类型注解校验拦截机制...")
    try:
        @tool
        async def invalid_tool(query, limit: int = 10):
            """模拟缺失类型注解的错误工具"""
            pass
    except ValueError as e:
        print(f"🚨 拦截异常成功: {e}")
        
    print("=" * 60)
