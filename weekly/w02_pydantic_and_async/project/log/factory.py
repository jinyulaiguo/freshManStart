"""
设计方案：
- 设计意图：构建一个带有继承链、多 Handler 分发的生产级日志系统。支持控制台美化输出（带高亮）和文件日志结构化（JSON 行格式）输出，保证系统在运行时可追溯每一条流转记录。
- 类与函数结构：
  - `StructuredJsonFormatter` 类：继承自 `logging.Formatter`，用于将 LogRecord 字典转化为单行 JSON 字符串。
  - `create_logger(module_name: str, settings: AppSettings)` 函数：根据模块名字空间（形如 "tool_runner.module"）动态创建或获取已创建的 Logger，并自动绑定对应的 ConsoleHandler 与 FileHandler，避免 Handlers 重复挂载。
- 关键数据流向：
  - 代码中触发 `logger.info()` -> 日志记录传入子 Logger -> 继承链向上传递至 `tool_runner` 根 Logger -> 分发至 Console Handler（输出彩色格式至终端）和 File Handler（输出 JSON 格式至 tool_runner.log 磁盘文件）。
"""

import json
import logging
import sys
from typing import Any
from weekly.w02_pydantic_and_async.project.config.settings import AppSettings

class StructuredJsonFormatter(logging.Formatter):
    """自定义 JSON 结构化日志 Formatter（生产级审计记录）"""
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno
        }
        # 如果包含异常堆栈，合并写入日志
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False)

def create_logger(module_name: str, settings: AppSettings) -> logging.Logger:
    """
    生产级日志工厂方法，构建以 tool_runner 为顶级域的 Logger 继承树。
    """
    # 统一命名空间
    full_name = f"tool_runner.{module_name}" if module_name else "tool_runner"
    logger = logging.getLogger(full_name)
    
    # 根域级别由配置动态决定
    logger.setLevel(settings.log_level.upper())
    
    # 获取顶级 logger 引用，用于挂载通用 Handler
    root_project_logger = logging.getLogger("tool_runner")
    root_project_logger.setLevel(settings.log_level.upper())
    
    # 如果顶级 Logger 尚未挂载任何 Handler，则初始化 Handlers (防止重复挂载导致日志重复打印)
    if not root_project_logger.handlers:
        root_project_logger.propagate = True
        
        # 1. 控制台 Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(settings.log_level.upper())
        console_formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | [%(name)s] -> %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(console_formatter)
        root_project_logger.addHandler(console_handler)
        
        # 2. 文件 Handler (JSON 格式写入本地磁盘文件)
        if settings.log_to_file:
            file_handler = logging.FileHandler(settings.log_file_path, encoding="utf-8")
            file_handler.setLevel(settings.log_level.upper())
            json_formatter = StructuredJsonFormatter(datefmt="%Y-%m-%d %H:%M:%S")
            file_handler.setFormatter(json_formatter)
            root_project_logger.addHandler(file_handler)

    return logger
