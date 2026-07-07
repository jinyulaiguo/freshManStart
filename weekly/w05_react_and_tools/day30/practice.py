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
            
        # TODO: 1. 利用 inspect 模块提取函数签名与 docstring
        # TODO: 2. 检验每个参数是否标明了类型注解，无类型注解则抛出 ValueError 强拦截
        # TODO: 3. 解析 docstring，提取函数主描述与每个参数的 description
        # TODO: 4. 利用 pydantic.create_model 动态拼装入参校验模型
        # TODO: 5. 提取 json schema 并清洗重组为符合 OpenAI 规范的 {"type": "function", "function": {...}} 字典
        # TODO: 6. 存储至 self._tools 中
        
        raise NotImplementedError("TODO: 请先在 register 中实现反射签名提取与 Pydantic 动态参数建模")

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
    print("运行 ToolRegistry 动态反射与建模调试模板...")
    print("=" * 60)
    
    try:
        # 定义一个合法的异步测试函数
        @tool
        async def calculate_distance(origin: str, destination: str, mode: str = "driving") -> str:
            """
            计算两个地点之间的距离和预计耗时。
            
            Args:
                origin: 出发地名称，如 "北京南站"。
                destination: 目的地名称，如 "天安门广场"。
                mode: 交通出行方式，可选 "driving", "walking", "transit"。
            """
            return f"从 {origin} 到 {destination} 的 {mode} 距离为 15 公里。"
            
        # 打印生成的 JSON Schema
        schema = registry.get_tool_schema("calculate_distance")
        print("\n🎉 成功生成标准 OpenAI Tool Schema 定义：")
        import pprint
        pprint.pprint(schema)
        
    except NotImplementedError as e:
        print(f"\n❌ 拦截到 TODO 占位：\n{e}")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        
    print("=" * 60)
