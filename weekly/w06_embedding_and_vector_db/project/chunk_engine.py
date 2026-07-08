"""
微引擎 3：智能切片引擎 (ChunkEngine)

设计方案：
==========
1. 设计意图：
   Day 40 的滑动窗口分块只按字符长度切割，完全不感知语义边界。
   一段完整的代码示例可能被从中间切断，一个论证链条可能被拆到两个 Chunk，
   导致检索到的 Chunk 本身就是残缺的、无法被 LLM 正确推理的。
   本引擎提供三种切片策略：
   - FixedTokenChunker: 按 token 数切分（通用兜底）
   - SemanticChunker: 利用标题层级 + 段落空行作为语义边界优先切分
   - CodeChunker: 以函数/类定义为自然切分边界
   并在每个 Chunk 上注入完整的溯源元数据（document_id、section_path、hash 等）。

2. 关键组件结构：
   - _estimate_tokens(): Token 数估算函数（无 tiktoken 依赖）
   - _compute_chunk_hash(): SHA-256 内容指纹生成
   - FixedTokenChunker: 按 token 数 + overlap 的固定切分
   - SemanticChunker: 感知标题层级和段落边界的语义切分
   - CodeChunker: 感知 def/class 定义的代码切分
   - ChunkEngine: 顶层调度器，根据 Section 的内容特征自动选择切分策略

3. 关键数据流：
   CleanedDocument → ChunkEngine.chunk_document()
     → 遍历每个 CleanedSection
     → 根据内容特征选择 Chunker
     → 生成 Chunk 列表（含完整元数据和 SHA-256 哈希）
     → 输出 list[Chunk]

使用方式（在项目根目录）：
    python -m weekly.w06_embedding_and_vector_db.project.chunk_engine
"""
from __future__ import annotations

import hashlib
import re

from weekly.w06_embedding_and_vector_db.project.models import (
    Chunk,
    CleanedDocument,
    CleanedSection,
)


# ══════════════════════════════════════════════════════════════════════════════
# 板块一：公共辅助函数
# ══════════════════════════════════════════════════════════════════════════════

def _estimate_tokens(text: str) -> int:
    """估算文本的 token 数量（无需 tiktoken 依赖）。

    采用经验规则：
    - 英文：平均 1 token ≈ 4 个字符（基于 GPT tokenizer 的统计特征）
    - 中文：平均 1 token ≈ 1.5 个字符（一个汉字约 1-2 tokens）
    - 混合文本：分别统计中英文字符后加权求和

    Args:
        text: 待估算的文本

    Returns:
        int: 估算的 token 数量（向上取整）
    """
    if not text:
        return 0

    # 统计中文字符数（CJK 统一表意字符区间）
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))
    # 非中文字符数
    non_cjk_chars = len(text) - cjk_chars

    # 加权估算：中文部分 / 1.5 + 英文部分 / 4
    cjk_tokens = cjk_chars / 1.5
    non_cjk_tokens = non_cjk_chars / 4.0

    return max(1, int(cjk_tokens + non_cjk_tokens + 0.5))


def _compute_chunk_hash(content: str) -> str:
    """计算 Chunk 内容的 SHA-256 指纹哈希。

    用于全局去重：相同内容的 Chunk 具有相同的 hash，
    EmbeddingPipeline 可据此跳过重复向量化。

    Args:
        content: Chunk 文本内容

    Returns:
        str: "sha256:" 前缀的十六进制哈希值
    """
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _is_code_content(content: str) -> bool:
    """判断内容是否主要是代码。

    Args:
        content: 待判断的文本内容

    Returns:
        bool: True 表示该内容主要是代码
    """
    if not content or len(content) < 20:
        return False

    lines = content.split("\n")
    if len(lines) < 2:
        return False

    # 指标 1：缩进行占比
    indented = sum(1 for l in lines if l and l[0] in " \t")
    indent_ratio = indented / len(lines)

    # 指标 2：是否包含代码关键字
    has_keywords = bool(re.search(
        r"^\s*(def |class |import |from |if |for |while |return |async )",
        content,
        re.MULTILINE,
    ))

    return indent_ratio > 0.3 and has_keywords


# ══════════════════════════════════════════════════════════════════════════════
# 板块二：FixedTokenChunker — 固定 Token 数切分器
# ══════════════════════════════════════════════════════════════════════════════

class FixedTokenChunker:
    """按固定 token 数量进行切分的通用兜底切分器。

    支持 overlap（重叠窗口），确保切分边界处的上下文不丢失。
    切分单位是"段落"（以双换行分隔），避免在句子中间切断。

    Attributes:
        max_tokens: 单个 Chunk 的最大 token 数
        overlap_tokens: 相邻 Chunk 之间的重叠 token 数
    """

    def __init__(self, max_tokens: int = 256, overlap_tokens: int = 50) -> None:
        """初始化切分参数。

        Args:
            max_tokens: 单个 Chunk 的最大 token 数（默认 256）
            overlap_tokens: 相邻 Chunk 重叠 token 数（默认 50）

        Raises:
            ValueError: max_tokens <= 0 或 overlap_tokens >= max_tokens
        """
        if max_tokens <= 0:
            raise ValueError(f"max_tokens 必须大于 0，收到: {max_tokens}")
        if overlap_tokens >= max_tokens:
            raise ValueError(
                f"overlap_tokens ({overlap_tokens}) 必须小于 max_tokens ({max_tokens})"
            )
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    def chunk(self, text: str) -> list[str]:
        """将文本按固定 token 数切分。

        优先在段落边界（双换行）处切分。如果单个段落超过 max_tokens，
        则在句号/句尾处进行二次切分。

        Args:
            text: 待切分的文本

        Returns:
            list[str]: 切分后的文本片段列表
        """
        if not text.strip():
            return []

        # 如果整个文本在 token 限制内，直接返回
        if _estimate_tokens(text) <= self.max_tokens:
            return [text.strip()]

        # Step 1: 按段落分割（双换行或单换行）
        paragraphs = re.split(r"\n\s*\n", text)
        if len(paragraphs) == 1:
            # 没有段落分隔符 → 按句子分割
            paragraphs = re.split(r"(?<=[。！？.!?])\s*", text)

        # Step 2: 贪心合并段落，直到达到 token 上限
        chunks: list[str] = []
        current_parts: list[str] = []
        current_tokens = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_tokens = _estimate_tokens(para)

            # 如果单个段落就超过 max_tokens，对其进行字符级切分
            if para_tokens > self.max_tokens:
                # 先保存之前累积的内容
                if current_parts:
                    chunks.append("\n\n".join(current_parts))
                    current_parts = []
                    current_tokens = 0

                # 对长段落进行字符级切分
                sub_chunks = self._split_long_paragraph(para)
                chunks.extend(sub_chunks)
                continue

            # 加入当前段落后是否超限
            if current_tokens + para_tokens > self.max_tokens and current_parts:
                # 超限 → 保存当前累积内容，开始新的 chunk
                chunks.append("\n\n".join(current_parts))

                # Overlap：保留最后几个段落作为下一个 chunk 的开头
                overlap_parts: list[str] = []
                overlap_tokens_count = 0
                for part in reversed(current_parts):
                    part_tokens = _estimate_tokens(part)
                    if overlap_tokens_count + part_tokens > self.overlap_tokens:
                        break
                    overlap_parts.insert(0, part)
                    overlap_tokens_count += part_tokens

                current_parts = overlap_parts
                current_tokens = overlap_tokens_count

            current_parts.append(para)
            current_tokens += para_tokens

        # 最后一个 chunk
        if current_parts:
            chunks.append("\n\n".join(current_parts))

        return chunks

    def _split_long_paragraph(self, text: str) -> list[str]:
        """对超长段落进行字符级切分。

        Args:
            text: 超长段落文本

        Returns:
            list[str]: 切分后的片段列表
        """
        # 按字符数估算切分点（max_tokens * 4 字符）
        max_chars = self.max_tokens * 3  # 偏保守
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + max_chars, len(text))
            # 尝试在句号、换行处切分
            if end < len(text):
                for sep in ["。", ".", "\n", "！", "？", "!", "?", "，", ","]:
                    last_sep = text.rfind(sep, start, end)
                    if last_sep > start + max_chars // 2:
                        end = last_sep + 1
                        break
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start = end
        return chunks


# ══════════════════════════════════════════════════════════════════════════════
# 板块三：SemanticChunker — 语义边界感知切分器
# ══════════════════════════════════════════════════════════════════════════════

class SemanticChunker:
    """利用标题层级和段落空行作为语义边界信号的切分器。

    切分策略：
    1. 以 CleanedDocument 的 Section 为基本切分单位
    2. 如果单个 Section 超过 max_tokens → 委托 FixedTokenChunker 二次切分
    3. 如果多个短 Section 合计不超过 max_tokens → 合并为一个 Chunk

    Attributes:
        max_tokens: 单个 Chunk 的最大 token 数
        min_tokens: 合并短 Section 的最小 token 阈值
        _fixed_chunker: 用于二次切分的 FixedTokenChunker 实例
    """

    def __init__(
        self,
        max_tokens: int = 256,
        min_tokens: int = 50,
        overlap_tokens: int = 30,
    ) -> None:
        """初始化语义切分参数。

        Args:
            max_tokens: 单个 Chunk 的最大 token 数
            min_tokens: 短 Section 合并的最小阈值
            overlap_tokens: 二次切分时的重叠 token 数
        """
        self.max_tokens = max_tokens
        self.min_tokens = min_tokens
        self._fixed_chunker = FixedTokenChunker(
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )

    def chunk_sections(self, sections: list[CleanedSection]) -> list[dict]:
        """对 Section 列表进行语义感知切分。

        返回的每个切片包含文本内容和来源 Section 的元信息。

        Args:
            sections: CleanedSection 列表

        Returns:
            list[dict]: 每个元素包含 "content", "heading", "section_path", "page_number"
        """
        if not sections:
            return []

        chunks: list[dict] = []

        # 构建每个 Section 的完整路径（层级面包屑）
        heading_stack: list[str] = []

        # 累积短 Section 的缓冲区
        merge_buffer: list[dict] = []
        merge_tokens = 0

        for section in sections:
            # 更新标题路径栈
            if section.heading and section.level > 0:
                # 弹出同级或下级的标题
                while len(heading_stack) >= section.level:
                    heading_stack.pop()
                heading_stack.append(section.heading)

            section_path = " > ".join(heading_stack) if heading_stack else ""
            section_tokens = _estimate_tokens(section.content)

            section_info = {
                "content": section.content,
                "heading": section.heading,
                "section_path": section_path,
                "page_number": section.page_number,
            }

            if section_tokens == 0:
                continue

            # Case 1: 单个 Section 超过 max_tokens → 二次切分
            if section_tokens > self.max_tokens:
                # 先清空合并缓冲区
                if merge_buffer:
                    chunks.append(self._merge_buffer(merge_buffer))
                    merge_buffer = []
                    merge_tokens = 0

                # 委托 FixedTokenChunker 切分长 Section
                sub_texts = self._fixed_chunker.chunk(section.content)
                for sub_text in sub_texts:
                    chunks.append({
                        "content": sub_text,
                        "heading": section.heading,
                        "section_path": section_path,
                        "page_number": section.page_number,
                    })
                continue

            # Case 2: 短 Section → 尝试与前面的短 Section 合并
            if merge_tokens + section_tokens <= self.max_tokens:
                merge_buffer.append(section_info)
                merge_tokens += section_tokens
            else:
                # 合并缓冲区已满 → 输出并重新开始
                if merge_buffer:
                    chunks.append(self._merge_buffer(merge_buffer))
                merge_buffer = [section_info]
                merge_tokens = section_tokens

        # 清空最后的缓冲区
        if merge_buffer:
            chunks.append(self._merge_buffer(merge_buffer))

        return chunks

    def _merge_buffer(self, buffer: list[dict]) -> dict:
        """将合并缓冲区中的多个短 Section 合并为一个 Chunk。

        Args:
            buffer: 待合并的 Section 信息列表

        Returns:
            dict: 合并后的 Chunk 信息
        """
        if len(buffer) == 1:
            return buffer[0]

        # 合并文本内容
        combined_content = "\n\n".join(item["content"] for item in buffer if item["content"])
        # 使用第一个有标题的 Section 的信息
        heading = ""
        section_path = ""
        page_number = 0
        for item in buffer:
            if item["heading"]:
                heading = item["heading"]
                section_path = item["section_path"]
                page_number = item["page_number"]
                break
        if not heading and buffer:
            section_path = buffer[0].get("section_path", "")
            page_number = buffer[0].get("page_number", 0)

        return {
            "content": combined_content,
            "heading": heading,
            "section_path": section_path,
            "page_number": page_number,
        }


# ══════════════════════════════════════════════════════════════════════════════
# 板块四：CodeChunker — 代码定义边界切分器
# ══════════════════════════════════════════════════════════════════════════════

class CodeChunker:
    """以函数/类定义为自然切分边界的代码切分器。

    切分策略：
    1. 识别顶层 class/def 定义行
    2. 每个定义（包含其完整函数体）成为一个独立 Chunk
    3. 如果单个函数体超过 max_tokens → 委托 FixedTokenChunker 二次切分

    Attributes:
        max_tokens: 单个 Chunk 的最大 token 数
        _fixed_chunker: 用于二次切分的 FixedTokenChunker 实例
    """

    # 匹配顶层定义行（不缩进）
    _DEFINITION_PATTERN = re.compile(r"^(class|def)\s+(\w+)", re.MULTILINE)

    def __init__(self, max_tokens: int = 256) -> None:
        """初始化代码切分参数。"""
        self.max_tokens = max_tokens
        overlap = min(30, max_tokens // 4) if max_tokens > 4 else 0
        self._fixed_chunker = FixedTokenChunker(max_tokens=max_tokens, overlap_tokens=overlap)

    def chunk(self, text: str) -> list[str]:
        """将代码文本按定义边界切分。

        Args:
            text: 源代码文本

        Returns:
            list[str]: 切分后的代码片段列表
        """
        if not text.strip():
            return []

        if _estimate_tokens(text) <= self.max_tokens:
            return [text.strip()]

        lines = text.split("\n")
        # 查找所有顶层定义的行号
        definition_lines: list[int] = []

        for i, line in enumerate(lines):
            if line and not line[0].isspace():
                if self._DEFINITION_PATTERN.match(line):
                    # 包含装饰器
                    start = i
                    while start > 0 and lines[start - 1].strip().startswith("@"):
                        start -= 1
                    if not definition_lines or definition_lines[-1] != start:
                        definition_lines.append(start)

        if not definition_lines:
            return self._fixed_chunker.chunk(text)

        chunks: list[str] = []

        # 文件头部
        if definition_lines[0] > 0:
            header = "\n".join(lines[:definition_lines[0]]).strip()
            if header:
                if _estimate_tokens(header) > self.max_tokens:
                    chunks.extend(self._fixed_chunker.chunk(header))
                else:
                    chunks.append(header)

        # 每个定义到下一个定义
        for i, start in enumerate(definition_lines):
            end = definition_lines[i + 1] if i + 1 < len(definition_lines) else len(lines)
            block = "\n".join(lines[start:end]).strip()
            if not block:
                continue
            if _estimate_tokens(block) > self.max_tokens:
                chunks.extend(self._fixed_chunker.chunk(block))
            else:
                chunks.append(block)

        return chunks


# ══════════════════════════════════════════════════════════════════════════════
# 板块五：ChunkEngine — 顶层切片调度器
# ══════════════════════════════════════════════════════════════════════════════

class ChunkEngine:
    """智能切片引擎 — 顶层调度器。

    根据 CleanedDocument 中每个 Section 的内容特征，自动选择最合适的
    切分策略（语义 / 代码 / 固定），并为每个 Chunk 注入完整的溯源元数据。

    Attributes:
        max_tokens: 单个 Chunk 的最大 token 数
        overlap_tokens: 相邻 Chunk 的重叠 token 数
        _semantic_chunker: 语义切分器实例
        _code_chunker: 代码切分器实例
        _fixed_chunker: 固定切分器实例
    """

    def __init__(
        self,
        max_tokens: int = 256,
        overlap_tokens: int = 50,
        min_tokens: int = 50,
    ) -> None:
        """初始化切片引擎参数。

        Args:
            max_tokens: 单个 Chunk 最大 token 数（默认 256）
            overlap_tokens: 重叠 token 数（默认 50）
            min_tokens: 短 Section 合并阈值（默认 50）
        """
        self.max_tokens = max_tokens
        # Ensure overlap_tokens is strictly less than max_tokens
        safe_overlap = min(overlap_tokens, max_tokens - 1) if max_tokens > 1 else 0
        self.overlap_tokens = safe_overlap
        self._semantic_chunker = SemanticChunker(
            max_tokens=max_tokens,
            min_tokens=min_tokens,
            overlap_tokens=safe_overlap,
        )
        self._code_chunker = CodeChunker(max_tokens=max_tokens)
        self._fixed_chunker = FixedTokenChunker(
            max_tokens=max_tokens,
            overlap_tokens=safe_overlap,
        )

    def chunk_document(self, cleaned_doc: CleanedDocument) -> list[Chunk]:
        """对 CleanedDocument 执行智能切片。

        流程：
        1. 将 Section 列表分为"代码类"和"文本类"两组
        2. 文本类 Section → SemanticChunker（语义边界切分）
        3. 代码类 Section → CodeChunker（定义边界切分）
        4. 为所有 Chunk 注入元数据和 SHA-256 哈希

        Args:
            cleaned_doc: 清洗后的文档

        Returns:
            list[Chunk]: 携带完整元数据的知识切片列表
        """
        all_chunks: list[Chunk] = []
        chunk_index = 0

        # 分离代码 Section 和文本 Section
        text_sections: list[CleanedSection] = []
        code_sections: list[CleanedSection] = []

        for section in cleaned_doc.sections:
            if _is_code_content(section.content):
                code_sections.append(section)
            else:
                text_sections.append(section)

        # === 处理文本 Section ===
        if text_sections:
            text_chunk_infos = self._semantic_chunker.chunk_sections(text_sections)
            for info in text_chunk_infos:
                content = info["content"]
                if not content.strip():
                    continue

                chunk = self._build_chunk(
                    document_id=cleaned_doc.document_id,
                    content=content,
                    chunk_index=chunk_index,
                    heading=info.get("heading", ""),
                    section_path=info.get("section_path", ""),
                    page_number=info.get("page_number", 0),
                    metadata=cleaned_doc.metadata,
                )
                all_chunks.append(chunk)
                chunk_index += 1

        # === 处理代码 Section ===
        # 构建标题路径栈（复用 SemanticChunker 的逻辑）
        heading_stack: list[str] = []
        for section in code_sections:
            if section.heading and section.level > 0:
                while len(heading_stack) >= section.level:
                    heading_stack.pop()
                heading_stack.append(section.heading)

            section_path = " > ".join(heading_stack) if heading_stack else ""

            code_texts = self._code_chunker.chunk(section.content)
            for ct in code_texts:
                if not ct.strip():
                    continue
                chunk = self._build_chunk(
                    document_id=cleaned_doc.document_id,
                    content=ct,
                    chunk_index=chunk_index,
                    heading=section.heading,
                    section_path=section_path,
                    page_number=section.page_number,
                    metadata=cleaned_doc.metadata,
                )
                all_chunks.append(chunk)
                chunk_index += 1

        return all_chunks

    def _build_chunk(
        self,
        document_id: str,
        content: str,
        chunk_index: int,
        heading: str,
        section_path: str,
        page_number: int,
        metadata,
    ) -> Chunk:
        """构建一个携带完整元数据的 Chunk 对象。

        Args:
            document_id: 文档 ID
            content: 切片文本内容
            chunk_index: 切片序号
            heading: 所属章节标题
            section_path: 完整章节路径
            page_number: 页码
            metadata: 文档元数据

        Returns:
            Chunk: 完整的知识切片对象
        """
        chunk_id = f"{document_id}_chunk_{chunk_index:04d}"
        token_length = _estimate_tokens(content)
        char_length = len(content)
        content_hash = _compute_chunk_hash(content)

        return Chunk(
            chunk_id=chunk_id,
            document_id=document_id,
            content=content,
            chunk_index=chunk_index,
            title=heading,
            section_path=section_path,
            source_path=getattr(metadata, "source_type", "unknown"),
            author=metadata.author if hasattr(metadata, "author") else "unknown",
            created_time=metadata.created_time if hasattr(metadata, "created_time") else "",
            page_number=page_number,
            token_length=token_length,
            char_length=char_length,
            hash=content_hash,
            category=metadata.category if hasattr(metadata, "category") else "general",
            permission_level=metadata.permission_level if hasattr(metadata, "permission_level") else 1,
            user_id=metadata.user_id if hasattr(metadata, "user_id") else "default",
        )


# ══════════════════════════════════════════════════════════════════════════════
# 主入口：切片引擎功能演示
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from weekly.w06_embedding_and_vector_db.project.models import DocumentMetadata

    print("=" * 70)
    print("  微引擎 3：智能切片引擎 — 功能演示")
    print("=" * 70)

    engine = ChunkEngine(max_tokens=100, overlap_tokens=20, min_tokens=30)

    # 构建测试 CleanedDocument
    test_doc = CleanedDocument(
        document_id="doc_transformer_abc123",
        title="Transformer 架构详解",
        metadata=DocumentMetadata(
            author="Vaswani",
            category="transformer",
            permission_level=2,
            user_id="researcher_001",
        ),
        sections=[
            CleanedSection(
                heading="自注意力机制",
                level=1,
                content=(
                    "Self-Attention 允许模型在处理序列中的每个位置时，"
                    "关注序列中所有其他位置的信息。这是 Transformer 架构的核心创新。"
                    "通过计算 Query、Key、Value 三个矩阵的点积注意力，"
                    "模型能够动态地为不同位置分配不同的注意力权重。"
                ),
                original_length=120,
                cleaned_length=110,
            ),
            CleanedSection(
                heading="计算流程",
                level=2,
                content=(
                    "注意力计算公式为 Attention(Q,K,V) = softmax(QK^T / sqrt(d_k)) V。"
                    "其中 d_k 是 Key 向量的维度，用于缩放防止点积值过大。"
                    "softmax 函数将注意力分数归一化为概率分布。"
                    "最终输出是 Value 向量的加权和。"
                ),
                original_length=100,
                cleaned_length=95,
            ),
            CleanedSection(
                heading="多头注意力",
                level=2,
                content=(
                    "Multi-Head Attention 通过并行运行 h 个注意力头，"
                    "让模型从不同的表示子空间联合关注信息。"
                    "每个头独立计算 Q、K、V 映射，最后拼接并线性变换。"
                    "这使得模型能够同时关注不同位置、不同距离的依赖关系。"
                    "在 Transformer 原始论文中使用了 8 个注意力头。"
                ),
                original_length=150,
                cleaned_length=140,
            ),
            CleanedSection(
                heading="位置编码",
                level=1,
                content="使用正弦和余弦函数的不同频率来编码位置信息。",
                original_length=25,
                cleaned_length=25,
            ),
        ],
    )

    chunks = engine.chunk_document(test_doc)

    print(f"\n  文档: {test_doc.title} (ID: {test_doc.document_id})")
    print(f"  Section 数: {len(test_doc.sections)}")
    print(f"  生成 Chunk 数: {len(chunks)}")

    for chunk in chunks:
        print(f"\n  --- Chunk {chunk.chunk_index} ---")
        print(f"  ID: {chunk.chunk_id}")
        print(f"  标题: {chunk.title or '(无)'}")
        print(f"  路径: {chunk.section_path or '(根)'}")
        print(f"  Token 数: {chunk.token_length}")
        print(f"  字符数: {chunk.char_length}")
        print(f"  Hash: {chunk.hash[:30]}...")
        print(f"  作者: {chunk.author}, 权限: {chunk.permission_level}")
        print(f"  内容: {chunk.content[:80]}{'...' if len(chunk.content) > 80 else ''}")

    # --- 验证 Hash 唯一性 ---
    hashes = [c.hash for c in chunks]
    unique_hashes = set(hashes)
    print(f"\n  Hash 唯一性校验: {len(unique_hashes)}/{len(hashes)} unique")
    assert len(unique_hashes) == len(hashes), "发现重复 Hash！"

    print(f"\n{'=' * 70}")
    print("  智能切片引擎功能演示完成 ✅")
    print("=" * 70)
