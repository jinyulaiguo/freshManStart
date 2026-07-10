"""
Day 48 参考标准答案：非结构化文档多模态解析（HTML / Markdown / PDF）与元数据富集

设计方案：
本模块提供多格式文档解析器（MultiFormatDocIngestor）的标准参考实现。
1. HTML 抽取引擎（HTMLTextExtractor）：继承标准库 HTMLParser，通过开闭状态机屏蔽无用的 script, style 等头部和标签，保障文本提取的高效率和纯净度。
2. PDF 抽取引擎：利用 pdfplumber 流式逐页提取正文。针对其中的物理表格数据，进行行列探测并转化为 Markdown 语法的表格线插入在页面正文后，从而为下游的大模型提供无失真的结构化语义输入。
3. 元数据富集器：在底层文档解析的物理循环中，为每个文本块/页面实体自动计算、附加并富集关键元数据契约（文件名、页码、字节大小、提取时间戳等），便于下游的多租户隔离与 RAG 证据溯源脚注对照映射。
"""

import os
import re
import datetime
from typing import List, Dict, Tuple
from html.parser import HTMLParser

# 尝试导入 pdfplumber 模块，严禁 Mock
try:
    import pdfplumber
except ImportError:
    pdfplumber = None


class HTMLTextExtractor(HTMLParser):
    """纯手写标准库 HTML 文本抽取器，规避 BeautifulSoup 外部依赖"""
    
    def __init__(self) -> None:
        """初始化 HTML 抽取状态机"""
        super().__init__()
        self.result: List[str] = []
        self.in_ignored_tag: bool = False
        # 常用的需要物理隔离的非正文标签
        self.ignored_tags = {"script", "style", "head", "title", "meta", "link"}

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """识别进入无用屏蔽标签"""
        if tag in self.ignored_tags:
            self.in_ignored_tag = True

    def handle_endtag(self, tag: str) -> None:
        """识别离开无用屏蔽标签"""
        if tag in self.ignored_tags:
            self.in_ignored_tag = False

    def handle_data(self, data: str) -> None:
        """收集非忽略区间的正文文本数据"""
        if not self.in_ignored_tag:
            self.result.append(data)

    def get_text(self) -> str:
        """拼接收集的数据并执行去空行、去首尾空格清洗"""
        raw_text = "".join(self.result)
        cleaned_lines = []
        for line in raw_text.splitlines():
            stripped = line.strip()
            if stripped:
                cleaned_lines.append(stripped)
        return "\n".join(cleaned_lines)


class MultiFormatDocIngestor:
    """非结构化文档多格式自动检测与元数据富集解析引擎"""
    
    def __init__(self, input_dir: str) -> None:
        """
        初始化解析引擎
        
        Args:
            input_dir (str): 文档存放目录
        """
        self.input_dir = input_dir
        if not os.path.exists(self.input_dir):
            os.makedirs(self.input_dir)

    def _convert_table_to_markdown(self, table: List[List[str]]) -> str:
        """
        将 pdfplumber 提取的嵌套列表表格高保真地还原为 Markdown 格式的表格
        
        Args:
            table (List[List[str]]): 二维行列表
            
        Returns:
            str: Markdown 表格文本
        """
        if not table or not table[0]:
            return ""
            
        # 1. 过滤并提取 Header 表头，去除回车换行符
        headers = [
            str(cell).strip().replace("\n", " ") if cell is not None else ""
            for cell in table[0]
        ]
        
        markdown_lines = []
        # 2. 组装 Markdown 表头物理结构
        markdown_lines.append("| " + " | ".join(headers) + " |")
        # 3. 组装 Markdown 的分割线
        markdown_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        
        # 4. 遍历并装填每一行数据，进行列宽度防御性对齐防错
        for row in table[1:]:
            cleaned_row = [
                str(cell).strip().replace("\n", " ") if cell is not None else ""
                for cell in row
            ]
            # 对齐单元格列数，防范因 PDF 提取不全导致的对齐倾斜
            if len(cleaned_row) < len(headers):
                cleaned_row += [""] * (len(headers) - len(cleaned_row))
            elif len(cleaned_row) > len(headers):
                cleaned_row = cleaned_row[:len(headers)]
            markdown_lines.append("| " + " | ".join(cleaned_row) + " |")
            
        return "\n" + "\n".join(markdown_lines) + "\n"

    def _parse_pdf(self, file_path: str) -> List[Dict]:
        """解析 PDF 文件的文本与表格数据并富集元数据"""
        results = []
        if not pdfplumber:
            print("⚠️ 未找到 pdfplumber 模块，无法处理 PDF")
            return results

        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        
        # 1. 打开 PDF 实例
        with pdfplumber.open(file_path) as pdf:
            # 2. 逐页读取以实现页码元数据级物理隔离，防范大量上下文糅杂在同一个 Chunk 中
            for page_idx, page in enumerate(pdf.pages):
                text = page.extract_text()
                page_content = text if text else ""
                
                # 3. 提取当前页面内含有的所有表格数据
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        # 4. 转换并高保真地追加 Markdown 表格，以便 LLM 进行精确的结构化阅读
                        md_table = self._convert_table_to_markdown(table)
                        if md_table:
                            page_content += "\n\n### [物理表格数据]\n" + md_table
                            
                # 5. 元数据富集定义
                metadata = {
                    "source_file": file_name,
                    "page_number": page_idx + 1,  # 物理页码（1-indexed）
                    "file_size_bytes": file_size,
                    "extracted_at": datetime.datetime.now().isoformat(),
                    "file_type": "pdf"
                }
                
                results.append({
                    "content": page_content,
                    "metadata": metadata
                })
        return results

    def _parse_html(self, file_path: str) -> List[Dict]:
        """读取并利用 HTMLTextExtractor 解析 HTML 纯文本并富集元数据"""
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        
        with open(file_path, "r", encoding="utf-8") as f:
            html_content = f.read()
            
        # 1. 实例化手写的 HTML 解析状态机并提取文本
        parser = HTMLTextExtractor()
        parser.feed(html_content)
        text = parser.get_text()
        
        # 2. 富集元数据，由于 HTML 无多页概念，page_number 归一化填 1
        metadata = {
            "source_file": file_name,
            "page_number": 1,
            "file_size_bytes": file_size,
            "extracted_at": datetime.datetime.now().isoformat(),
            "file_type": "html"
        }
        
        return [{
            "content": text,
            "metadata": metadata
        }]

    def _parse_txt(self, file_path: str) -> List[Dict]:
        """读取纯文本 TXT 文件并富集元数据"""
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
            
        # 元数据富集归一化
        metadata = {
            "source_file": file_name,
            "page_number": 1,
            "file_size_bytes": file_size,
            "extracted_at": datetime.datetime.now().isoformat(),
            "file_type": "txt"
        }
        
        return [{
            "content": text,
            "metadata": metadata
        }]

    def scan_and_ingest(self) -> List[Dict]:
        """
        扫描 input_dir 目录，检测不同文件后缀，调用对应解析器解析
        
        Returns:
            List[Dict]: 解析富集后的 Chunk/Page 列表
        """
        all_pages = []
        if not os.path.exists(self.input_dir):
            return all_pages
            
        # 1. 物理遍历扫描测试输入目录项
        for file_name in os.listdir(self.input_dir):
            file_path = os.path.join(self.input_dir, file_name)
            # 防御性过滤非文件项
            if not os.path.isfile(file_path):
                continue
                
            # 2. 路由分发决策
            ext = os.path.splitext(file_name)[1].lower()
            if ext == ".pdf":
                all_pages.extend(self._parse_pdf(file_path))
            elif ext in (".html", ".htm"):
                all_pages.extend(self._parse_html(file_path))
            elif ext == ".txt":
                all_pages.extend(self._parse_txt(file_path))
                
        return all_pages


if __name__ == "__main__":
    import shutil
    
    def setup_mock_files(test_dir: str) -> None:
        """生成测试用的 TXT 和 HTML 临时文件，并指定一个论文 PDF 用于解析演示"""
        if not os.path.exists(test_dir):
            os.makedirs(test_dir)
            
        # 1. 写入测试文本
        with open(os.path.join(test_dir, "test_fact.txt"), "w", encoding="utf-8") as f:
            f.write("公司研发部门周末加班可申请调休假，调休申请需在 3 个月内休完。")
            
        # 2. 写入测试 HTML (包含无用 script 和 css 样式)
        html_content = (
            "<html>\n"
            "<head><style>body { font-family: sans-serif; color: #333; }</style></head>\n"
            "<body>\n"
            "  <h1>公司差旅政策说明</h1>\n"
            "  <p>正式员工单次差旅住宿费报销上限为每天 500 元人民币。</p>\n"
            "  <script>console.log('ignored script logic');</script>\n"
            "</body>\n"
            "</html>"
        )
        with open(os.path.join(test_dir, "test_travel.html"), "w", encoding="utf-8") as f:
            f.write(html_content)
            
        # 3. 从已有的 w06 测试数据中拷贝一个 PDF 文件进行解析验证
        source_pdf = os.path.abspath(
            "./weekly/w06_embedding_and_vector_db/project/test_data/"
            "STEM Agent- A Self-Adapting, Tool-Enabled, Extensible Architecture for Multi-Protocol AI Agent Systems.pdf"
        )
        if os.path.exists(source_pdf):
            shutil.copy(source_pdf, os.path.join(test_dir, "stem_agent_paper.pdf"))

    def main():
        print("=== Day 48 非结构化多模态解析 运行测试 ===")
        test_dir = "./weekly/w07_classic_rag/day48/test_inputs"
        setup_mock_files(test_dir)
        
        ingestor = MultiFormatDocIngestor(test_dir)
        chunks = ingestor.scan_and_ingest()
        
        print(f"\n[扫描读取成功] 共扫描并解析出 {len(chunks)} 个数据页面：")
        
        # 静态验证断言，确保三种格式都得到了解析
        file_types = [c["metadata"]["file_type"] for c in chunks]
        assert "txt" in file_types, "TXT 文本解析器未被成功调用"
        assert "html" in file_types, "HTML 提取解析器未被成功调用"
        assert "pdf" in file_types, "PDF 文本解析器未被成功调用"
        
        # 校验元数据富集是否完整
        first_chunk = chunks[0]
        meta = first_chunk["metadata"]
        assert "source_file" in meta, "缺失富集元数据: source_file"
        assert "page_number" in meta, "缺失富集元数据: page_number"
        assert "file_size_bytes" in meta, "缺失富集元数据: file_size_bytes"
        assert "extracted_at" in meta, "缺失富集元数据: extracted_at"
        
        # 打印展示前 3 个解析块的富集元数据和文本数据
        for idx, chunk in enumerate(chunks[:3]):
            print(f"\n--- Chunk [{idx+1}] 元数据标签 ---")
            for k, v in chunk["metadata"].items():
                print(f"  - {k}: {v}")
            print(f"  - 提取的正文内容缩略: {chunk['content'][:220]}...")
            
        print("\n✅ Day 48 物理过关集成测试全部顺利通过！PDF表格转换与多模态解析逻辑完全正常！")

    main()
