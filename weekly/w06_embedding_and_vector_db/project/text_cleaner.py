"""
微引擎 2：文本清洗管道 (TextCleaner)

设计方案：
==========
1. 设计意图：
   复用 Day 40 已交付的 CleanTextPipeline 作为底层清洗引擎，在其上构建面向
   ParsedDocument → CleanedDocument 的结构化适配层。
   Day 40 原版将全部文本铲平为纯文本后再滑动窗口分块，会丢失标题、代码块、
   表格等结构标记。本适配层的关键升级在于：
   - 对每个 DocumentSection 独立执行清洗（保留章节边界）
   - 保留代码块内容不做清洗（代码是知识的一部分）
   - 计算每个 Section 的噪声比例（noise_ratio）
   - 支持全文档级噪声统计

2. 关键组件结构：
   - TextCleaner: 结构化文本清洗适配器
     - clean_section(): 单个 Section 级别的清洗
     - clean_document(): ParsedDocument → CleanedDocument 的全文档清洗
     - _should_preserve(): 判断 Section 是否应跳过清洗（如代码块）

3. 关键数据流：
   ParsedDocument → TextCleaner.clean_document()
     → 遍历每个 DocumentSection
     → 对非代码块 Section 调用 CleanTextPipeline.clean()
     → 计算 noise_ratio
     → 输出 CleanedDocument

使用方式（在项目根目录）：
    python -m weekly.w06_embedding_and_vector_db.project.text_cleaner
"""
from __future__ import annotations

import re

from weekly.w06_embedding_and_vector_db.day40.text_clean_pipeline import CleanTextPipeline
from weekly.w06_embedding_and_vector_db.project.models import (
    ParsedDocument,
    CleanedDocument,
    CleanedSection,
    DocumentSection,
)


# ══════════════════════════════════════════════════════════════════════════════
# 板块一：TextCleaner — 结构化文本清洗适配器
# ══════════════════════════════════════════════════════════════════════════════

class TextCleaner:
    """面向 ParsedDocument 的结构化文本清洗管道。

    相比 Day 40 原版 CleanTextPipeline 的升级点：
    1. 输入从原始字符串升级为 ParsedDocument 结构体
    2. 对每个 Section 独立清洗，保留章节边界
    3. 代码块内容跳过清洗（保留原始格式）
    4. 输出带噪声统计的 CleanedDocument

    Attributes:
        _pipeline: Day 40 的底层清洗引擎实例
        _preserve_code: 是否跳过代码块的清洗
        _min_section_length: Section 清洗后的最小有效长度（低于此值视为无效丢弃）
    """

    def __init__(
        self,
        remove_html: bool = True,
        normalize_whitespace: bool = True,
        strip_control_chars: bool = True,
        preserve_code: bool = True,
        min_section_length: int = 10,
    ) -> None:
        """初始化清洗管道参数。

        Args:
            remove_html: 是否剥离 HTML 标签（传递给 Day 40 CleanTextPipeline）
            normalize_whitespace: 是否合并多余空白
            strip_control_chars: 是否过滤控制字符
            preserve_code: 是否跳过代码块内容的清洗
            min_section_length: Section 最小有效字符数
        """
        # 实例化 Day 40 底层清洗引擎
        self._pipeline = CleanTextPipeline(
            remove_html=remove_html,
            normalize_whitespace=normalize_whitespace,
            strip_control_chars=strip_control_chars,
        )
        self._preserve_code = preserve_code
        self._min_section_length = min_section_length

    def _should_preserve(self, section: DocumentSection) -> bool:
        """判断 Section 是否应跳过清洗（保留原始格式）。

        代码块和模块头部（imports、docstring）不应被清洗引擎处理，
        否则会破坏代码的缩进和语法结构。

        Args:
            section: 待判断的文档区块

        Returns:
            bool: True 表示应跳过清洗
        """
        if not self._preserve_code:
            return False

        # 代码类标题标记
        code_headings = {"module_header"}
        if section.heading in code_headings:
            return True

        # 检查内容是否主要是代码（包含大量缩进行或 def/class 关键字）
        content = section.content
        if not content:
            return False

        lines = content.split("\n")
        if len(lines) < 2:
            return False

        # 统计缩进行比例（代码通常有大量缩进行）
        indented_lines = sum(1 for line in lines if line and line[0] in " \t")
        indent_ratio = indented_lines / len(lines)

        # 检查是否包含 Python 定义关键字
        has_code_keywords = bool(re.search(
            r"^\s*(def |class |import |from |if __name__)",
            content,
            re.MULTILINE,
        ))

        # 如果缩进行占比 > 40% 且包含代码关键字，视为代码块
        return indent_ratio > 0.4 and has_code_keywords

    def clean_section(self, section: DocumentSection) -> CleanedSection:
        """对单个 DocumentSection 执行清洗。

        Args:
            section: 原始文档区块

        Returns:
            CleanedSection: 清洗后的区块（含噪声统计）
        """
        original_length = len(section.content)

        # 判断是否需要跳过清洗
        if self._should_preserve(section):
            # 代码块：保留原始内容，noise_ratio = 0
            return CleanedSection(
                heading=section.heading,
                level=section.level,
                content=section.content,
                original_length=original_length,
                cleaned_length=original_length,
                noise_ratio=0.0,
                page_number=section.page_number,
            )

        # 调用 Day 40 底层清洗引擎
        cleaned_text = self._pipeline.clean(section.content)
        cleaned_length = len(cleaned_text)

        # 计算噪声比例
        noise_ratio = 0.0
        if original_length > 0:
            noise_ratio = round(1.0 - (cleaned_length / original_length), 4)
            # 防止负值（清洗后文本因 HTML 实体还原可能变长）
            noise_ratio = max(0.0, noise_ratio)

        return CleanedSection(
            heading=section.heading,
            level=section.level,
            content=cleaned_text,
            original_length=original_length,
            cleaned_length=cleaned_length,
            noise_ratio=noise_ratio,
            page_number=section.page_number,
        )

    def clean_document(self, parsed_doc: ParsedDocument) -> CleanedDocument:
        """对 ParsedDocument 执行全文档清洗。

        遍历所有 Section 依次清洗，过滤掉清洗后过短的无效 Section，
        并计算全文档平均噪声比例。

        Args:
            parsed_doc: 解析后的结构化文档

        Returns:
            CleanedDocument: 清洗后的文档（含全局噪声统计）
        """
        cleaned_sections: list[CleanedSection] = []
        total_original = 0
        total_cleaned = 0

        for section in parsed_doc.sections:
            cleaned = self.clean_section(section)

            # 过滤掉清洗后过短的无效 Section
            if cleaned.cleaned_length >= self._min_section_length or cleaned.heading:
                cleaned_sections.append(cleaned)

            total_original += cleaned.original_length
            total_cleaned += cleaned.cleaned_length

        # 计算全文档平均噪声比例
        total_noise_ratio = 0.0
        if total_original > 0:
            total_noise_ratio = round(1.0 - (total_cleaned / total_original), 4)
            total_noise_ratio = max(0.0, total_noise_ratio)

        return CleanedDocument(
            document_id=parsed_doc.document_id,
            title=parsed_doc.title,
            sections=cleaned_sections,
            metadata=parsed_doc.metadata,
            total_noise_ratio=total_noise_ratio,
        )


# ══════════════════════════════════════════════════════════════════════════════
# 主入口：清洗管道功能演示
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  微引擎 2：文本清洗管道 — 功能演示")
    print("=" * 70)

    cleaner = TextCleaner()

    # 构建一个包含 HTML 噪声的 ParsedDocument
    test_doc = ParsedDocument(
        document_id="doc_test_001",
        title="测试文档",
        sections=[
            DocumentSection(
                heading="简介",
                level=1,
                content=(
                    "<p>这是一段包含 <b>HTML 标签</b> 和 &amp; 实体的文本。</p>\n"
                    "<script>alert('xss');</script>\n"
                    "正常的段落内容在这里。\x00\x01 包含控制字符。\n\n\n"
                    "多余的空行已经被清除。"
                ),
            ),
            DocumentSection(
                heading="代码示例",
                level=2,
                content=(
                    "def hello_world():\n"
                    "    \"\"\"示例函数\"\"\"\n"
                    "    print('Hello, World!')\n"
                    "\n"
                    "if __name__ == '__main__':\n"
                    "    hello_world()\n"
                ),
            ),
            DocumentSection(
                heading="",
                level=0,
                content="短文本",  # 将被 min_section_length 过滤
            ),
        ],
    )

    result = cleaner.clean_document(test_doc)

    print(f"\n  文档 ID: {result.document_id}")
    print(f"  全文档噪声比例: {result.total_noise_ratio:.2%}")
    print(f"  有效区块数: {len(result.sections)}")

    for i, sec in enumerate(result.sections):
        print(f"\n  --- 区块 {i + 1} ---")
        print(f"  标题: {sec.heading or '(无标题)'}")
        print(f"  原始长度: {sec.original_length} → 清洗后: {sec.cleaned_length}")
        print(f"  噪声比例: {sec.noise_ratio:.2%}")
        print(f"  内容预览: {sec.content[:80]}{'...' if len(sec.content) > 80 else ''}")

    print(f"\n{'=' * 70}")
    print("  文本清洗管道功能演示完成 ✅")
    print("=" * 70)
