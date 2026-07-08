"""
微引擎 1：多格式文档解析器 (DocumentParser)

设计方案：
==========
1. 设计意图：
   现实世界中的知识分散在 PDF、Markdown、HTML、纯文本、源代码等异构格式中。
   直接读取文件只能获得一大段扁平化文本，丢失了标题层级、章节结构、代码块边界等
   关键结构信息。这些结构信息的缺失将导致下游 ChunkEngine "切在语义中间"，
   产出残缺的、无法被 LLM 正确推理的知识切片。
   本模块通过统一的 BaseParser 协议和格式路由调度器，将异构文件转换为结构化的
   ParsedDocument，保留标题层级、段落边界和代码块等结构标记。

2. 关键组件结构：
   - BaseParser (Protocol):   所有格式解析器的统一接口协议
   - MarkdownParser:          基于正则解析 # 标题层级、``` 代码块、列表结构
   - HtmlParser:              剥离 <script>/<style>，提取 <h1>-<h6> 结构、<code> 块
   - PdfParser:               基于 pymupdf 提取按页文本，识别标题字号推断层级
   - PlainTextParser:         基于空行的启发式段落切分
   - CodeParser:              识别 Python def/class 定义，保留 docstring 和注释
   - DocumentParser:          顶层调度器，根据文件后缀或 SourceType 路由到具体 Parser

3. 关键数据流：
   文件路径/原始文本 → DocumentParser.parse()
     → 格式探测（后缀 + SourceType）
     → 路由到具体 Parser
     → 输出 ParsedDocument（保留结构层级）

使用方式（在项目根目录）：
    python -m weekly.w06_embedding_and_vector_db.project.document_parser
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Protocol

from weekly.w06_embedding_and_vector_db.project.models import (
    RawDocument,
    ParsedDocument,
    DocumentSection,
    DocumentMetadata,
    SourceType,
)


# ══════════════════════════════════════════════════════════════════════════════
# 板块一：BaseParser 统一接口协议
# ══════════════════════════════════════════════════════════════════════════════

class BaseParser(Protocol):
    """所有格式解析器必须实现的统一接口协议。

    任何新增的格式解析器（如 DocxParser, CsvParser 等）只需实现此协议，
    即可无缝接入 DocumentParser 调度器，无需修改调度器代码。
    """

    def parse(self, raw_content: str, source_path: str = "") -> list[DocumentSection]:
        """将原始文本解析为结构化区块列表。

        Args:
            raw_content: 原始文本内容
            source_path: 文件路径（用于推断标题等元信息）

        Returns:
            list[DocumentSection]: 保留层级的结构化区块列表
        """
        ...


# ══════════════════════════════════════════════════════════════════════════════
# 板块二：MarkdownParser — Markdown 格式解析器
# ══════════════════════════════════════════════════════════════════════════════

class MarkdownParser:
    """基于正则的 Markdown 格式结构化解析器。

    解析策略：
    1. 逐行扫描，识别 ATX 标题行（# / ## / ### ...）
    2. 以标题行为分割点，将文档切分为多个 DocumentSection
    3. 保留代码块（``` 围栏）和列表结构的原始格式
    4. 标题行的 # 数量直接映射为 level 值
    """

    # 匹配 ATX 标题行：行首的 1-6 个 # 后跟空格和标题文本
    _HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    def parse(self, raw_content: str, source_path: str = "") -> list[DocumentSection]:
        """解析 Markdown 文本为结构化区块列表。

        Args:
            raw_content: Markdown 原始文本
            source_path: 文件路径

        Returns:
            list[DocumentSection]: 以标题为分割点的结构化区块列表
        """
        if not raw_content.strip():
            return []

        sections: list[DocumentSection] = []
        lines = raw_content.split("\n")

        # 当前正在累积的区块状态
        current_heading = ""
        current_level = 0
        current_lines: list[str] = []
        in_code_block = False  # 追踪是否在 ``` 代码块内部

        for line in lines:
            # Step 1: 追踪代码块围栏状态（代码块内部的 # 不是标题）
            if line.strip().startswith("```"):
                in_code_block = not in_code_block

            # Step 2: 在代码块外部检测标题行
            if not in_code_block:
                heading_match = self._HEADING_PATTERN.match(line)
                if heading_match:
                    # 遇到新标题 → 将之前累积的内容保存为一个 Section
                    if current_lines or current_heading:
                        content = "\n".join(current_lines).strip()
                        if content or current_heading:
                            sections.append(DocumentSection(
                                heading=current_heading,
                                level=current_level,
                                content=content,
                            ))

                    # 开始新的 Section
                    current_heading = heading_match.group(2).strip()
                    current_level = len(heading_match.group(1))
                    current_lines = []
                    continue

            # Step 3: 将当前行累积到当前 Section
            current_lines.append(line)

        # Step 4: 最后一个 Section（文件末尾可能没有新标题触发保存）
        content = "\n".join(current_lines).strip()
        if content or current_heading:
            sections.append(DocumentSection(
                heading=current_heading,
                level=current_level,
                content=content,
            ))

        return sections


# ══════════════════════════════════════════════════════════════════════════════
# 板块三：HtmlParser — HTML 格式解析器
# ══════════════════════════════════════════════════════════════════════════════

class HtmlParser:
    """基于正则的 HTML 格式结构化解析器。

    解析策略：
    1. 先剥离 <script>、<style> 标签及其内部内容（防止非展示内容泄露）
    2. 提取 <h1>-<h6> 标签作为结构分割点，保留其层级信息
    3. 对剩余内容剥离 HTML 标签，还原 HTML 实体（如 &amp; → &）
    4. 保留 <code>/<pre> 块的原始内容（代码也是知识）
    """

    # 匹配 <h1>-<h6> 标签及其内容
    _HEADING_TAG_PATTERN = re.compile(
        r"<h([1-6])[^>]*>(.*?)</h\1>",
        re.DOTALL | re.IGNORECASE,
    )
    # 匹配 <script> 和 <style> 标签及其内部内容
    _SCRIPT_STYLE_PATTERN = re.compile(
        r"<(script|style)[^>]*>.*?</\1>",
        re.DOTALL | re.IGNORECASE,
    )
    # 匹配所有 HTML 标签
    _TAG_PATTERN = re.compile(r"<[^>]+>", re.DOTALL)

    def parse(self, raw_content: str, source_path: str = "") -> list[DocumentSection]:
        """解析 HTML 文本为结构化区块列表。

        Args:
            raw_content: HTML 原始文本
            source_path: 文件路径

        Returns:
            list[DocumentSection]: 以 <h1>-<h6> 为分割点的结构化区块列表
        """
        if not raw_content.strip():
            return []

        # Step 1: 剥离 script 和 style 标签
        cleaned = self._SCRIPT_STYLE_PATTERN.sub("", raw_content)

        # Step 2: 查找所有标题标签的位置和内容
        headings = []
        for match in self._HEADING_TAG_PATTERN.finditer(cleaned):
            level = int(match.group(1))
            heading_text = self._TAG_PATTERN.sub("", match.group(2)).strip()
            headings.append({
                "level": level,
                "heading": heading_text,
                "start": match.start(),
                "end": match.end(),
            })

        # Step 3: 按标题位置切分内容
        sections: list[DocumentSection] = []

        if not headings:
            # 没有标题标签 → 整个内容作为一个段落
            import html
            text = self._TAG_PATTERN.sub("", cleaned)
            text = html.unescape(text).strip()
            if text:
                sections.append(DocumentSection(
                    heading="",
                    level=0,
                    content=text,
                ))
            return sections

        # 标题前的内容（如果有）
        import html
        pre_heading_text = cleaned[:headings[0]["start"]]
        pre_text = self._TAG_PATTERN.sub("", pre_heading_text)
        pre_text = html.unescape(pre_text).strip()
        if pre_text:
            sections.append(DocumentSection(heading="", level=0, content=pre_text))

        # 每个标题到下一个标题之间的内容
        for i, h in enumerate(headings):
            # 当前标题到下一个标题（或文档末尾）之间的内容
            content_start = h["end"]
            content_end = headings[i + 1]["start"] if i + 1 < len(headings) else len(cleaned)
            raw_block = cleaned[content_start:content_end]

            # 剥离 HTML 标签并还原实体
            block_text = self._TAG_PATTERN.sub("", raw_block)
            block_text = html.unescape(block_text).strip()

            sections.append(DocumentSection(
                heading=h["heading"],
                level=h["level"],
                content=block_text,
            ))

        return sections


# ══════════════════════════════════════════════════════════════════════════════
# 板块四：PdfParser — PDF 格式解析器
# ══════════════════════════════════════════════════════════════════════════════

class PdfParser:
    """基于 pymupdf 的 PDF 格式结构化解析器。

    解析策略：
    1. 使用 pymupdf 按页提取文本（保留页码信息）
    2. 利用字号（font size）启发式推断标题层级：
       - 字号 >= 18pt → h1
       - 字号 >= 14pt → h2
       - 字号 >= 12pt → h3
       - 其余 → 正文
    3. 如果 pymupdf 不可用，降级为按页的纯文本分割

    注意：字号阈值是经验值，针对学术论文格式优化。
    """

    # 字号到标题层级的映射阈值
    _FONT_SIZE_THRESHOLDS = [
        (18.0, 1),  # >= 18pt → h1
        (14.0, 2),  # >= 14pt → h2
        (12.0, 3),  # >= 12pt → h3
    ]

    def parse(self, raw_content: str, source_path: str = "") -> list[DocumentSection]:
        """解析 PDF 文件为结构化区块列表。

        对于 PDF，raw_content 参数可以是空字符串（因为需要从文件路径读取二进制）。
        如果 raw_content 非空，则作为已提取的纯文本进行段落分割。

        Args:
            raw_content: 已提取的 PDF 文本（如果已预处理），或空字符串
            source_path: PDF 文件的物理路径

        Returns:
            list[DocumentSection]: 按页/按标题分割的结构化区块列表
        """
        # 优先尝试从文件路径用 pymupdf 提取结构化内容
        if source_path and os.path.isfile(source_path):
            try:
                return self._parse_with_pymupdf(source_path)
            except ImportError:
                # pymupdf 不可用 → 降级到纯文本处理
                pass
            except Exception as e:
                print(f"⚠️ pymupdf 解析失败 ({e})，降级为纯文本分割")

        # 降级模式：将已提取的文本按空行分段
        if raw_content.strip():
            return self._fallback_parse(raw_content)

        return []

    def _parse_with_pymupdf(self, file_path: str) -> list[DocumentSection]:
        """使用 pymupdf 提取 PDF 的结构化内容。

        Args:
            file_path: PDF 文件路径

        Returns:
            list[DocumentSection]: 结构化区块列表（按页+标题分割）
        """
        import pymupdf  # noqa: 延迟导入，仅在需要时加载

        sections: list[DocumentSection] = []
        doc = pymupdf.open(file_path)

        for page_num, page in enumerate(doc, start=1):
            # 提取文本块及其字号信息
            blocks = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)["blocks"]

            page_sections: list[DocumentSection] = []
            current_heading = ""
            current_level = 0
            current_lines: list[str] = []

            for block in blocks:
                if "lines" not in block:
                    continue

                for line in block["lines"]:
                    line_text = ""
                    max_font_size = 0.0

                    for span in line["spans"]:
                        line_text += span["text"]
                        max_font_size = max(max_font_size, span["size"])

                    line_text = line_text.strip()
                    if not line_text:
                        continue

                    # 根据字号判断是否为标题
                    detected_level = 0
                    for threshold, level in self._FONT_SIZE_THRESHOLDS:
                        if max_font_size >= threshold:
                            detected_level = level
                            break

                    if detected_level > 0 and len(line_text) < 200:
                        # 当前行是标题 → 保存之前累积的内容
                        if current_lines or current_heading:
                            content = "\n".join(current_lines).strip()
                            if content or current_heading:
                                page_sections.append(DocumentSection(
                                    heading=current_heading,
                                    level=current_level,
                                    content=content,
                                    page_number=page_num,
                                ))
                        current_heading = line_text
                        current_level = detected_level
                        current_lines = []
                    else:
                        current_lines.append(line_text)

            # 当前页最后一个 Section
            content = "\n".join(current_lines).strip()
            if content or current_heading:
                page_sections.append(DocumentSection(
                    heading=current_heading,
                    level=current_level,
                    content=content,
                    page_number=page_num,
                ))

            sections.extend(page_sections)

        doc.close()
        return sections

    def _fallback_parse(self, raw_content: str) -> list[DocumentSection]:
        """纯文本降级解析：按空行分段。

        Args:
            raw_content: 已提取的 PDF 纯文本

        Returns:
            list[DocumentSection]: 按段落分割的区块列表
        """
        paragraphs = re.split(r"\n\s*\n", raw_content)
        sections = []
        for para in paragraphs:
            text = para.strip()
            if text:
                sections.append(DocumentSection(heading="", level=0, content=text))
        return sections


# ══════════════════════════════════════════════════════════════════════════════
# 板块五：PlainTextParser — 纯文本解析器
# ══════════════════════════════════════════════════════════════════════════════

class PlainTextParser:
    """基于空行的纯文本启发式段落分割解析器。

    解析策略：
    1. 以连续空行（2 个及以上换行）作为段落分割点
    2. 每个段落成为一个独立的 DocumentSection（level=0，无标题）
    3. 合并段落内部的多余空白
    """

    def parse(self, raw_content: str, source_path: str = "") -> list[DocumentSection]:
        """解析纯文本为段落区块列表。

        Args:
            raw_content: 纯文本内容
            source_path: 文件路径

        Returns:
            list[DocumentSection]: 按段落分割的区块列表
        """
        if not raw_content.strip():
            return []

        # 按连续空行分割
        paragraphs = re.split(r"\n\s*\n", raw_content)
        sections = []
        for para in paragraphs:
            text = para.strip()
            if text:
                sections.append(DocumentSection(heading="", level=0, content=text))

        return sections


# ══════════════════════════════════════════════════════════════════════════════
# 板块六：CodeParser — 源代码解析器
# ══════════════════════════════════════════════════════════════════════════════

class CodeParser:
    """基于正则的 Python 源代码结构化解析器。

    解析策略：
    1. 识别顶层 class 定义 → level=1 区块
    2. 识别顶层 def 定义 → level=2 区块
    3. 识别文件头部的模块 docstring → level=0 区块
    4. 保留 docstring、注释和函数体（代码也是知识）
    5. 对于非 Python 代码文件，降级为按空行分段
    """

    # 匹配 Python 类定义
    _CLASS_PATTERN = re.compile(r"^class\s+(\w+)", re.MULTILINE)
    # 匹配 Python 函数定义（顶层，不缩进）
    _FUNC_PATTERN = re.compile(r"^def\s+(\w+)", re.MULTILINE)
    # 匹配 Python 装饰器行
    _DECORATOR_PATTERN = re.compile(r"^@\w+", re.MULTILINE)

    def parse(self, raw_content: str, source_path: str = "") -> list[DocumentSection]:
        """解析源代码文件为结构化区块列表。

        Args:
            raw_content: 源代码文本
            source_path: 文件路径（用于判断编程语言）

        Returns:
            list[DocumentSection]: 以 class/def 为分割点的结构化区块列表
        """
        if not raw_content.strip():
            return []

        # 判断是否为 Python 文件（根据后缀或内容特征）
        is_python = (
            source_path.endswith(".py")
            or "def " in raw_content[:500]
            or "class " in raw_content[:500]
            or "import " in raw_content[:500]
        )

        if is_python:
            return self._parse_python(raw_content)
        else:
            # 非 Python 代码 → 按空行分段
            return PlainTextParser().parse(raw_content, source_path)

    def _parse_python(self, raw_content: str) -> list[DocumentSection]:
        """解析 Python 源代码。

        Args:
            raw_content: Python 源代码文本

        Returns:
            list[DocumentSection]: 结构化区块列表
        """
        lines = raw_content.split("\n")
        sections: list[DocumentSection] = []

        # 查找所有顶层 class 和 def 的行号
        definition_points: list[dict] = []

        for i, line in enumerate(lines):
            # 只检测不缩进的（顶层）定义
            if line and not line[0].isspace():
                class_match = self._CLASS_PATTERN.match(line)
                if class_match:
                    # 检查前面是否有装饰器，如果有则包含装饰器行
                    start_line = i
                    while start_line > 0 and lines[start_line - 1].strip().startswith("@"):
                        start_line -= 1
                    definition_points.append({
                        "name": class_match.group(1),
                        "level": 1,
                        "start": start_line,
                    })
                    continue

                func_match = self._FUNC_PATTERN.match(line)
                if func_match:
                    start_line = i
                    while start_line > 0 and lines[start_line - 1].strip().startswith("@"):
                        start_line -= 1
                    definition_points.append({
                        "name": func_match.group(1),
                        "level": 2,
                        "start": start_line,
                    })

        if not definition_points:
            # 没有找到 class/def → 整个文件作为一个区块
            return [DocumentSection(heading="", level=0, content=raw_content.strip())]

        # 文件头部（第一个定义之前的内容：imports、docstring 等）
        header_content = "\n".join(lines[:definition_points[0]["start"]]).strip()
        if header_content:
            sections.append(DocumentSection(heading="module_header", level=0, content=header_content))

        # 每个定义到下一个定义之间的内容
        for i, dp in enumerate(definition_points):
            start = dp["start"]
            end = definition_points[i + 1]["start"] if i + 1 < len(definition_points) else len(lines)
            content = "\n".join(lines[start:end]).strip()
            if content:
                sections.append(DocumentSection(
                    heading=dp["name"],
                    level=dp["level"],
                    content=content,
                ))

        return sections


# ══════════════════════════════════════════════════════════════════════════════
# 板块七：DocumentParser — 顶层格式路由调度器
# ══════════════════════════════════════════════════════════════════════════════

# 文件后缀到 SourceType 的映射表
_EXTENSION_MAP: dict[str, SourceType] = {
    ".md": SourceType.MARKDOWN,
    ".markdown": SourceType.MARKDOWN,
    ".html": SourceType.HTML,
    ".htm": SourceType.HTML,
    ".pdf": SourceType.PDF,
    ".txt": SourceType.TXT,
    ".py": SourceType.CODE,
    ".js": SourceType.CODE,
    ".ts": SourceType.CODE,
    ".java": SourceType.CODE,
    ".go": SourceType.CODE,
    ".rs": SourceType.CODE,
    ".cpp": SourceType.CODE,
    ".c": SourceType.CODE,
    ".h": SourceType.CODE,
}


def _generate_document_id(source_path: str) -> str:
    """基于文件路径生成稳定的文档 ID。

    使用 SHA-256 的前 12 位十六进制字符作为 ID 前缀，
    拼接文件名（不含后缀）以保持可读性。

    Args:
        source_path: 文件路径

    Returns:
        str: 格式为 "doc_{filename}_{hash[:12]}" 的文档 ID
    """
    path_hash = hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:12]
    filename = os.path.splitext(os.path.basename(source_path))[0]
    # 清洗文件名中的特殊字符
    clean_name = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff]", "_", filename)[:30]
    return f"doc_{clean_name}_{path_hash}"


def _detect_source_type(source_path: str) -> SourceType:
    """根据文件后缀探测文档格式类型。

    Args:
        source_path: 文件路径

    Returns:
        SourceType: 探测到的格式类型，未知格式默认返回 TXT
    """
    ext = os.path.splitext(source_path)[1].lower()
    return _EXTENSION_MAP.get(ext, SourceType.TXT)


class DocumentParser:
    """多格式文档解析器 — 顶层路由调度器。

    根据文件的 SourceType 或后缀自动路由到对应的格式解析器，
    将异构文件统一转换为 ParsedDocument 结构。

    Attributes:
        _parsers: SourceType 到解析器实例的映射表
    """

    def __init__(self) -> None:
        """初始化各格式解析器实例。"""
        self._parsers: dict[SourceType, BaseParser] = {
            SourceType.MARKDOWN: MarkdownParser(),
            SourceType.HTML: HtmlParser(),
            SourceType.PDF: PdfParser(),
            SourceType.TXT: PlainTextParser(),
            SourceType.CODE: CodeParser(),
        }

    def parse(self, raw_doc: RawDocument) -> ParsedDocument:
        """解析原始文档为结构化文档。

        Args:
            raw_doc: 原始文档对象

        Returns:
            ParsedDocument: 保留结构层级的解析结果

        Raises:
            ValueError: 不支持的文档格式
        """
        # Step 1: 获取对应的格式解析器
        parser = self._parsers.get(raw_doc.source_type)
        if parser is None:
            raise ValueError(f"不支持的文档格式: {raw_doc.source_type.value}")

        # Step 2: 执行解析
        sections = parser.parse(raw_doc.raw_content, raw_doc.source_path)

        # Step 3: 生成文档 ID
        doc_id = _generate_document_id(raw_doc.source_path)

        # Step 4: 推断文档标题（取第一个 level >= 1 的标题，或使用文件名）
        title = ""
        for sec in sections:
            if sec.level >= 1 and sec.heading:
                title = sec.heading
                break
        if not title:
            title = os.path.splitext(os.path.basename(raw_doc.source_path))[0]

        # Step 5: 计算总字符数
        total_chars = sum(len(sec.content) for sec in sections)

        return ParsedDocument(
            document_id=doc_id,
            title=title,
            sections=sections,
            metadata=raw_doc.metadata,
            total_chars=total_chars,
        )

    def parse_file(self, file_path: str, metadata: DocumentMetadata | None = None) -> ParsedDocument:
        """便捷方法：直接从文件路径解析文档。

        自动探测文件格式，读取文件内容，构建 RawDocument 并解析。

        Args:
            file_path: 文件的绝对或相对路径
            metadata: 可选的文档元数据（不提供则使用默认值）

        Returns:
            ParsedDocument: 解析结果

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 不支持的文件格式
        """
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # Step 1: 探测格式
        source_type = _detect_source_type(file_path)

        # Step 2: 读取文件内容
        raw_content = ""
        if source_type != SourceType.PDF:
            # 非 PDF 格式：读取文本内容
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                raw_content = f.read()
        # PDF 格式由 PdfParser 内部通过 pymupdf 直接读取二进制文件

        # Step 3: 构建 RawDocument
        file_size = os.path.getsize(file_path)
        if metadata is None:
            metadata = DocumentMetadata(source_type=source_type)
        else:
            metadata.source_type = source_type

        raw_doc = RawDocument(
            source_path=file_path,
            source_type=source_type,
            raw_content=raw_content,
            file_size=file_size,
            metadata=metadata,
        )

        return self.parse(raw_doc)

    def parse_directory(
        self,
        dir_path: str,
        metadata: DocumentMetadata | None = None,
        recursive: bool = True,
    ) -> list[ParsedDocument]:
        """批量解析目录下的所有支持格式的文件。

        Args:
            dir_path: 目录路径
            metadata: 共享的文档元数据（每个文件的 source_type 会被自动覆盖）
            recursive: 是否递归子目录

        Returns:
            list[ParsedDocument]: 所有成功解析的文档列表
        """
        if not os.path.isdir(dir_path):
            raise NotADirectoryError(f"目录不存在: {dir_path}")

        results: list[ParsedDocument] = []
        supported_extensions = set(_EXTENSION_MAP.keys())

        for root, _dirs, files in os.walk(dir_path):
            for filename in sorted(files):
                ext = os.path.splitext(filename)[1].lower()
                if ext not in supported_extensions:
                    continue

                file_path = os.path.join(root, filename)
                try:
                    # 为每个文件创建独立的 metadata 副本
                    file_meta = metadata.model_copy() if metadata else DocumentMetadata()
                    doc = self.parse_file(file_path, file_meta)
                    results.append(doc)
                    print(f"  ✅ 解析成功: {filename} ({len(doc.sections)} sections, {doc.total_chars} chars)")
                except Exception as e:
                    print(f"  ⚠️ 解析失败: {filename} — {e}")

            if not recursive:
                break  # 不递归子目录

        return results


# ══════════════════════════════════════════════════════════════════════════════
# 主入口：解析器功能演示
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  微引擎 1：多格式文档解析器 — 功能演示")
    print("=" * 70)

    parser = DocumentParser()

    # --- 演示 1：Markdown 解析 ---
    print("\n📝 演示 1：Markdown 文档解析")
    print("-" * 50)
    md_content = """# Transformer 架构详解

## 1. 自注意力机制

Self-Attention 允许模型在处理序列中的每个位置时，
关注序列中所有其他位置的信息。

### 1.1 计算流程

```python
Q = X @ W_q
K = X @ W_k
V = X @ W_v
attention = softmax(Q @ K.T / sqrt(d_k)) @ V
```

## 2. 多头注意力

Multi-Head Attention 通过并行运行多个注意力函数，
让模型从不同表示子空间联合关注信息。
"""
    raw = RawDocument(
        source_path="/papers/transformer.md",
        source_type=SourceType.MARKDOWN,
        raw_content=md_content,
    )
    result = parser.parse(raw)
    print(f"  文档 ID: {result.document_id}")
    print(f"  标题: {result.title}")
    print(f"  区块数: {len(result.sections)}")
    for sec in result.sections:
        level_mark = "#" * sec.level if sec.level > 0 else "¶"
        print(f"    {level_mark} [{sec.heading or '正文'}] ({len(sec.content)} chars)")

    # --- 演示 2：HTML 解析 ---
    print("\n🌐 演示 2：HTML 文档解析")
    print("-" * 50)
    html_content = """<html>
<head><style>.header { color: blue; }</style></head>
<body>
<script>alert('xss');</script>
<h1>HNSW 索引原理</h1>
<p>HNSW (Hierarchical Navigable Small World) 是一种基于图的近似最近邻搜索算法。</p>
<h2>构建过程</h2>
<p>通过自底向上构建多层跳表式图结构，实现 O(log N) 的检索复杂度。</p>
<code>index.build(ef_construct=200, m=16)</code>
</body></html>"""
    raw_html = RawDocument(
        source_path="/docs/hnsw.html",
        source_type=SourceType.HTML,
        raw_content=html_content,
    )
    result_html = parser.parse(raw_html)
    print(f"  标题: {result_html.title}")
    print(f"  区块数: {len(result_html.sections)}")
    for sec in result_html.sections:
        level_mark = f"h{sec.level}" if sec.level > 0 else "¶"
        print(f"    [{level_mark}] {sec.heading or '正文'}: {sec.content[:60]}...")

    # --- 演示 3：Python 代码解析 ---
    print("\n🐍 演示 3：Python 代码解析")
    print("-" * 50)
    code_content = '''"""
Embedding 距离分析模块
"""
import numpy as np


class EmbeddingAnalyzer:
    """向量距离分析引擎"""

    def cosine_similarity(self, vec_a, vec_b):
        """计算余弦相似度"""
        dot = np.dot(vec_a, vec_b)
        return dot / (np.linalg.norm(vec_a) * np.linalg.norm(vec_b))


def main():
    """主入口函数"""
    analyzer = EmbeddingAnalyzer()
    print(analyzer.cosine_similarity([1, 0], [0, 1]))
'''
    raw_code = RawDocument(
        source_path="/src/embedding_analyzer.py",
        source_type=SourceType.CODE,
        raw_content=code_content,
    )
    result_code = parser.parse(raw_code)
    print(f"  标题: {result_code.title}")
    print(f"  区块数: {len(result_code.sections)}")
    for sec in result_code.sections:
        kind = "CLASS" if sec.level == 1 else ("FUNC" if sec.level == 2 else "HEADER")
        print(f"    [{kind}] {sec.heading or 'module'}: {len(sec.content)} chars")

    print(f"\n{'=' * 70}")
    print("  多格式文档解析器全部功能演示完成 ✅")
    print("=" * 70)
