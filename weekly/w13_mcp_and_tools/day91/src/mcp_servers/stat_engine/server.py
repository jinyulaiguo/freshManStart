import asyncio
import base64
import io
import matplotlib.pyplot as plt
from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, Field
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
from src.infrastructure.observability import get_logger

logger = get_logger("stat_engine_mcp")

mcp = FastMCP("stat_engine", dependencies=["mcp", "pydantic", "matplotlib"])

class PlotInput(BaseModel):
    data_points: list[float] = Field(..., description="要进行方差和直方图分析的浮点数一维数组。")
    title: str = Field("Research Data Analysis", description="图表的标题。")

@mcp.tool()
async def generate_histogram(input: PlotInput, ctx: Context) -> str:
    """
    长耗时数据分析与图表生成引擎。
    执行过程中会频繁回传 Progress，并在计算结束后抛出包含多模态 Base64 图像的数据。
    """
    logger.info("Starting heavy data analysis", data_size=len(input.data_points))
    
    total_steps = 10
    for i in range(total_steps):
        # 模拟 CPU 密集型任务
        await asyncio.sleep(0.3)
        # 向 Client 发送 Progress 进度事件
        await ctx.session.send_progress_notification(
            progressToken=ctx.request_context.meta.progressToken if ctx.request_context and ctx.request_context.meta else f"sim_token_{i}",
            progress=i,
            total=total_steps
        )
        logger.debug(f"Progress: {i}/{total_steps}")
        
    # 生成 Matplotlib 图表
    plt.figure(figsize=(6, 4))
    plt.hist(input.data_points, bins=10, color="#D97757", edgecolor="#141413") # 遵循温润知性配色
    plt.title(input.title, fontname="DejaVu Sans")
    plt.xlabel("Value")
    plt.ylabel("Frequency")
    plt.grid(axis='y', alpha=0.3)
    
    # 存入字节流
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close()
    buf.seek(0)
    
    # 编码为 Base64
    b64_data = base64.b64encode(buf.read()).decode("utf-8")
    
    # 在 FastMCP 中，可以通过特殊的标记或让 Client 识别这是图片。
    # 为了简化，我们按照 MCP 约定的结构化文本返回，让前端解析。
    # (实际上 FastMCP 支持返回 Image 对象，但在 Tool 中通常以 Markdown 或 Base64 传递)
    return f"![{input.title}](data:image/png;base64,{b64_data})\n\n分析完成。总数据量: {len(input.data_points)}"

if __name__ == "__main__":
    mcp.run(transport="stdio")
