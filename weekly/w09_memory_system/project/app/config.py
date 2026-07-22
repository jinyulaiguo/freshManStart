"""
Project Config and LLM Client Provider.

设计方案说明：
1. **设计意图**：
   本模块用于加载项目的基础环境变量（如 MINIMAX_API_KEY），并为所有微引擎提供统一且正确加载的环境路径。
   通过动态计算，本模块将主工作区根目录加入 sys.path，保证了 `weekly.w04_prompt_and_http.utils` 的安全导入。
2. **核心结构**：
   - sys.path 动态补全：确保跨运行路径下，工程包 of freshManStart 的统一寻址。
   - `get_llm_client()`: 提供单例形式 of LLMClient，用于各大微引擎发起真实的 API 访问。
"""

import os
import sys

# 步骤 1: 动态计算主工作区根目录，并将其插入 sys.path，实现公共 utils 模块的无缝导入
current_dir = os.path.dirname(os.path.abspath(__file__))
# current_dir 是 weekly/w09_memory_system/project/app
# 向上四级即为 /Users/zhouyi/03.AI/03.freshManStart
project_root = os.path.abspath(os.path.join(current_dir, "../../../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 步骤 2: 安全导入 Week 4 的环境变量加载工具与 LLM 客户端
try:
    from weekly.w04_prompt_and_http.utils import load_env_file, LLMClient
except ImportError as e:
    raise RuntimeError(
        f"导入公共大模型请求工具类失败，请检查工作区 sys.path 设置。当前项目根目录: {project_root}。错误原因: {e}"
    )

# 步骤 3: 物理触发一次环境变量加载
load_env_file()

# 步骤 4: 定义单例的 LLM 客户端对象
_global_client = None

def get_llm_client() -> LLMClient:
    """获取全局唯一的大模型客户端单例。

    Returns:
        LLMClient 实例。

    Raises:
        ValueError: 当环境变量中未配置 MINIMAX_API_KEY 时。
    """
    global _global_client
    if _global_client is None:
        # 防御性实例化，若缺失 Key 会在 LLMClient 初始化中报错抛出
        _global_client = LLMClient()
    return _global_client
