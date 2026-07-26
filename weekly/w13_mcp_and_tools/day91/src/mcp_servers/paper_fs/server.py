import os
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

# 创建具有独立职责的 FileSystem MCP
mcp = FastMCP("paper_fs", dependencies=["mcp", "pydantic"])

# 在生产环境中，应当严格限制研究助手能访问的根目录
RESEARCH_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../research_papers"))
os.makedirs(RESEARCH_ROOT, exist_ok=True)

class ReadPaperInput(BaseModel):
    filename: str = Field(..., description="文献的文件名，例如 'attention_is_all_you_need.pdf'")

@mcp.tool()
async def read_paper(input: ReadPaperInput) -> str:
    """
    【受限操作】从科研文献库读取指定的学术论文或实验记录。
    系统自带沙箱防御，绝对禁止路径穿越读取 /etc 或其他敏感文件。
    """
    target_path = os.path.abspath(os.path.join(RESEARCH_ROOT, input.filename))
    
    # 防御性契约：防止路径穿越
    if not target_path.startswith(RESEARCH_ROOT):
        raise ValueError("Security Error: Path traversal attempt blocked.")
    
    if not os.path.exists(target_path):
        return f"文献未找到: {input.filename}。请检查文献库。"
        
    with open(target_path, "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    mcp.run(transport="stdio")
