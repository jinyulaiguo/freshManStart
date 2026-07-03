"""
设计方案：
- 设计意图：构建一个面向对象的工具注册与动态反射中心（基于 Day 5 动态反射模式与工厂模式）。它负责全局工具实例的集中存储，并通过 `inspect` 动态扫描并自动反射实例化注册类，实现代码的开闭原则（对扩展开放，对修改关闭）。
- 类与函数结构：
  - `ToolRegistry` 类：
    - `__init__(settings)`: 初始化注册中心，存储配置以备反射注入。
    - `register(tool)`: 强校验并注册工具，防止重名覆盖。
    - `get(name)`: 安全反射提取工具，未注册时抛出自定义的结构化 `ToolRegistrationError`。
    - `discover(module)`: 反射扫描特定模块（或包）内的所有 `BaseTool` 子类，并自动识别签名依赖完成构造注入（Constructor Injection）。
    - `list_schemas()`: 批量反射导出符合 OpenAI Function Calling 的入参 Schema 字典。
- 关键数据流向：
  - 启动阶段：传入包含工具类的 module -> 反射发现 BaseTool 子类 -> 检查构造签名并注入 `settings` -> 实例化注册至 `self._tools`。
  - 运行阶段：接收工具名字符串 -> `get()` 查找 -> 返回具体的 `BaseTool` 实例运行。
"""

import inspect
from typing import Any, Dict
from weekly.w02_pydantic_and_async.project.config.settings import AppSettings
from weekly.w02_pydantic_and_async.project.exceptions.base import ToolRegistrationError
from weekly.w02_pydantic_and_async.project.tools.base import BaseTool

class ToolRegistry:
    """系统工具注册与反射发现中心"""
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self._tools: Dict[str, BaseTool] = {}
        from weekly.w02_pydantic_and_async.project.log.factory import create_logger
        self.logger = create_logger("core.registry", settings)

    def register(self, tool: BaseTool) -> None:
        """显式注册一个已实例化的工具对象"""
        if not isinstance(tool, BaseTool):
            raise ToolRegistrationError(f"注册失败: 工具 {tool} 必须继承自 BaseTool")
        
        name = tool.name
        if name in self._tools:
            self.logger.warning(f"工具名冲突: '{name}' 已经存在于注册表中，进行覆盖")
        
        self._tools[name] = tool
        self.logger.debug(f"工具 '{name}' 注册成功: {repr(tool)}")

    def get(self, name: str) -> BaseTool:
        """根据工具名称获取工具实例。若不存在抛出 ToolRegistrationError"""
        tool = self._tools.get(name)
        if not tool:
            raise ToolRegistrationError(f"未找到工具: 名称为 '{name}' 的工具尚未注册到系统")
        return tool

    def discover(self, module: Any) -> int:
        """
        基于 Day 5 动态反射自动扫描并注册模块中的所有 BaseTool 工具类。
        """
        count = 0
        self.logger.info(f"开始扫描模块中的工具类: {module.__name__}")

        # 使用 inspect.getmembers 反射扫描所有类定义
        for class_name, cls in inspect.getmembers(module, inspect.isclass):
            # 排除 BaseTool 基类自身，过滤出所有 BaseTool 的子类
            if issubclass(cls, BaseTool) and cls is not BaseTool:
                try:
                    # 检查构造函数签名，判断是否需要注入 settings 依赖
                    sig = inspect.signature(cls.__init__)
                    init_args = {}
                    if "settings" in sig.parameters:
                        init_args["settings"] = self.settings

                    # 实例化工具对象
                    tool_instance = cls(**init_args)
                    self.register(tool_instance)
                    count += 1
                except Exception as e:
                    self.logger.error(f"反射实例化工具 '{class_name}' 失败: {e}")
                    raise ToolRegistrationError(
                        f"工具反射发现加载崩溃 (class: {class_name}): {str(e)}"
                    ) from e

        self.logger.info(f"模块工具扫描完成，成功自动加载 {count} 个工具")
        return count

    def list_schemas(self) -> Dict[str, Dict[str, Any]]:
        """批量反射导出所有工具的 JSON Schema 参数定义"""
        return {name: tool.schema() for name, tool in self._tools.items()}

    def __repr__(self) -> str:
        return f"<ToolRegistry tools={list(self._tools.keys())}>"
