"""
Day 40 参考答案 — 非结构化文本数据清洗、规范化与字段分流

设计方案：
==========
1. 设计意图：
   本文件是 Day 40 的标准参考答案实现。针对在 RAG 系统中，非结构化文本（如网页 HTML）常包含大量的
   网页标签、控制字符、乱码与冗余空行，对文本的 Embedding 高维空间向量表征产生严重干扰（表征污染）的痛点，
   本类实现了一个高效的文本清洗与分块分流流水线 `CleanTextPipeline`。
   通过正则表达式过滤非文本实体、HTML 编码反转义、基于 Overlap 的滑动窗口分块，并采用 SHA-256 算法生成
   唯一的内容指纹哈希，用作后续数据在数据库中去重与更新的唯一依据。

2. 关键组件结构：
   - CleanTextPipeline: 清洗与切片主控类
     - clean(): 彻底剔除 `<script>` 和 `<style>` 内的样式与逻辑代码、剥离常规 HTML 标记、还原转义字符、合并冗余多重空行/空白、清除系统控制字符。
     - split_into_chunks(): 防御性校验输入参数，应用字符游标实现重叠滑动切割，并自动为各 Chunk 注入唯一 SHA-256 哈希防重指纹。
     - process(): 串联并执行以上步骤。

3. 关键数据流向与 Benchmark 验证：
   - 实例化 `CleanTextPipeline`。
   - 准备一段包含嵌入式样式表、恶意 JS 脚本、HTML 嵌套标记、控制字符（`\x00` 等）、多重空白及回车的复杂测试文本。
   - 运行管道，以 `chunk_size=120`, `chunk_overlap=30` 进行切割。
   - 打印清晰的分块详情报表，包括哈希、长度、内容，并通过断言（Assert）验证管道的完备性。

使用方式（在项目根目录）：
    python -m weekly.w06_embedding_and_vector_db.day40.text_clean_pipeline
"""
from __future__ import annotations

import re
import html
import hashlib
import sys


# ══════════════════════════════════════════════════════════════════════════════
# 板块一：CleanTextPipeline 完整实现
# ══════════════════════════════════════════════════════════════════════════════

class CleanTextPipeline:
    """非结构化文本清洗与指纹分块分流管道类（标准版）"""

    def __init__(
        self,
        remove_html: bool = True,
        normalize_whitespace: bool = True,
        strip_control_chars: bool = True
    ) -> None:
        """初始化管道清洗规则参数。"""
        self.remove_html = remove_html
        self.normalize_whitespace = normalize_whitespace
        self.strip_control_chars = strip_control_chars

    def clean(self, text: str) -> str:
        """对原始文本进行正则物理降噪、HTML 还原与多换行合并，输出干净可用的纯净语义长文本。

        Args:
            text: 待处理的原始脏文本

        Returns:
            str: 格式规整的干净纯文本
        """
        # Step 0: 空值防御
        if not text:
            return ""

        # Step 1: 处理 HTML 标签与内容净化（防止泄露非展示内容）
        if self.remove_html:
            # 剥离脚本标签及其内部代码
            text = re.sub(r"<(script|style).*?>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
            # 剥离 HTML 注释块
            text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
            # 物理剥离常规标签，保留正文
            text = re.sub(r"<.*?>", "", text, flags=re.DOTALL)
            # 将 HTML 编码实体（如 &nbsp;, &lt;, &gt;, &quot;）还原为正常的可读字符
            text = html.unescape(text)

        # Step 2: 剔除系统不可见控制字符，防止 API 传输或存储抛错
        if self.strip_control_chars:
            # 过滤 ASCII 值在 \x00-\x1f 之间的系统控制字符（保留换行符 \n、制表符 \t 等常规排版符）
            # ASCII 127 (\x7f) 表示 DEL 控制符，一并清除
            text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]", "", text)

        # Step 3: 空白字符与换行符归一化合并，保持段落结构但排除杂乱格式
        if self.normalize_whitespace:
            # 将多重连续的新行/回车符（\n、\r\n 等）合并为单一换行符
            text = re.sub(r"\n+", "\n", text)
            # 将多重连续的空格、制表符、垂直制表符等合并为单空格
            text = re.sub(r"[ \t\r\f\v]+", " ", text)
            # 排除文本整体首尾的多余空白
            text = text.strip()

        return text

    def split_into_chunks(
        self,
        clean_text: str,
        chunk_size: int = 200,
        chunk_overlap: int = 50
    ) -> list[dict]:
        """使用带重叠度（Overlap）的滑动窗口物理切分长文本，并生成 SHA-256 排重指纹。

        Args:
            clean_text: 已完成 clean 规范化处理的纯净文本
            chunk_size: 每个分块的最大字符长度限制
            chunk_overlap: 相邻分块的重叠语义字符跨度

        Returns:
            list[dict]: 每一个 Chunk 构成的元数据字典列表
        """
        # Step 1: 防御性参数校验
        if chunk_size <= 0:
            raise ValueError(f"分块大小 chunk_size ({chunk_size}) 必须大于 0")
        if chunk_overlap < 0:
            raise ValueError(f"分块重叠度 chunk_overlap ({chunk_overlap}) 必须大于或等于 0")
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"重叠跨度限制：chunk_overlap ({chunk_overlap}) 必须小于分块大小 chunk_size ({chunk_size})，"
                f"否则会导致滑动游标退化，陷入无限死循环！"
            )

        chunks: list[dict] = []
        text_len = len(clean_text)
        
        # Step 2: 依据 Overlap 计算滑动步长
        step = chunk_size - chunk_overlap
        start = 0

        # Step 3: 滑动窗口切割
        while start < text_len:
            # 截取固定区间的子文本
            end = start + chunk_size
            chunk_content = clean_text[start:end].strip()

            # 仅当文本非空时加入，排除空文本块
            if chunk_content:
                # 使用 SHA-256 算法生成该 Chunk 文本内容的唯一排重哈希指纹
                sha256 = hashlib.sha256(chunk_content.encode("utf-8")).hexdigest()
                
                chunks.append({
                    "content": chunk_content,
                    "length": len(chunk_content),
                    "sha256": sha256
                })

            # 如果当前块的终点已经覆盖了整个文本末尾，必须强行跳出，防止产生冗余边界碎块
            if end >= text_len:
                break

            # 游标向后移动指定步长
            start += step

        return chunks

    def process(
        self,
        raw_text: str,
        chunk_size: int = 200,
        chunk_overlap: int = 50
    ) -> list[dict]:
        """一键执行非结构化文本的清洗降噪，并滑动切割产生带有哈希排重的分流文本块。

        Args:
            raw_text: 原始未经处理的杂乱文本数据
            chunk_size: 分块大小
            chunk_overlap: 重叠字符跨度

        Returns:
            list[dict]: 加工后的规范化文本块字典列表
        """
        # 1. 物理层数据清洗归一化
        cleaned = self.clean(raw_text)
        # 2. 逻辑层滑动窗口切片指纹构建
        return self.split_into_chunks(cleaned, chunk_size, chunk_overlap)


# ══════════════════════════════════════════════════════════════════════════════
# 板块二：过关测试与断言校验入口
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("======================================================================")
    print("🏆 Day 40 过关验证：非结构化网页文本清洗降噪与 SHA-256 滑动窗口分块分流")
    print("======================================================================")
    
    # 实例化管道实例
    pipeline = CleanTextPipeline()

    # 1. 构造混杂了多重网页标记、嵌套代码、多换行、系统控制符的复杂脏文本
    dirty_html = (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        "   <meta charset='UTF-8'>\n"
        "   <style>\n"
        "      body { background-color: #fff; font-family: sans-serif; }\n"
        "      .noise { display: none; }\n"
        "   </style>\n"
        "</head>\n"
        "<body>\n"
        "   <div id='container'>\n"
        "       <h1>AI &nbsp; 导师 &lt;高级课程&gt;</h1>\n"
        "       <script type='text/javascript'>\n"
        "          window.leakData = 'sensitive';\n"
        "          console.log('malicious script execute!');\n"
        "       </script>\n"
        "       <!-- 网页开发调试注释，Embedding 不应学习此内容 -->\n"
        "       <p>深度学习与自然语言处理（NLP）是人工智能领域最璀璨的明珠。\r\n\r\n"
        "       在构建 Agent 知识底座时，如果直接输入未经清洗的脏语料，"
        "       会严重扭曲向量空间的夹角计算方向。\x00\x07系统噪音已被探测到。</p>\n"
        "       \n"
        "       <p>清洗流水线的作用是将非结构化文本，   剥离其样式标签，  \t  合并冗余空白，"
        "       使数据在滑动窗口下按期望的 Chunk 大小滑动切分，并生成哈希防重指纹。</p>\n"
        "   </div>\n"
        "</body>\n"
        "</html>"
    )

    print("原始脏 HTML/文本数据快照（包含未执行 JS 脚本、CSS 样式块与换行乱码）：")
    print("-" * 70)
    print(dirty_html[:300] + "\n...[省略后面部分]...")
    print("-" * 70)

    try:
        # 2. 执行流水线处理：每块 100 字符，重叠度 25 字符
        chunk_size = 100
        chunk_overlap = 25
        
        chunks = pipeline.process(dirty_html, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        
        # 3. 打印精美清洗后分块排重数据表
        print(f"\n✅ 数据处理完毕，顺利切割出 {len(chunks)} 个规范化语义 Chunk：")
        print("=" * 80)
        print(f"| 序号 | 字符数 | SHA-256 指纹 (前10位) | 语义文本内容快照 |")
        print("-" * 80)
        for i, ck in enumerate(chunks, 1):
            content_snap = ck["content"].replace("\n", "\\n")
            print(f"|  {i:02d}  |  {ck['length']:3d}   | {ck['sha256'][:10]}... | '{content_snap[:35]}...' |")
        print("=" * 80)

        # 4. 严苛的防错设计与语义质量断言（Assertion Testing）
        print("\n⏳ 正在执行防御性质量指标断言校验...")
        
        # 校验 1：HTML 剥离完整度校验
        for ck in chunks:
            assert "<script" not in ck["content"].lower(), "❌ 质量校验失败：残留 JavaScript 代码块！"
            assert "<style" not in ck["content"].lower(), "❌ 质量校验失败：残留 CSS 样式配置块！"
            assert "<div" not in ck["content"].lower(), "❌ 质量校验失败：残留 HTML div 容器标签！"
            assert "</" not in ck["content"], "❌ 质量校验失败：残留 HTML 关闭闭合标签！"
            assert "&nbsp;" not in ck["content"], "❌ 质量校验失败：残留转义序列 &nbsp; 实体！"
        
        # 验证网页实体字符解码成功，且未被 HTML 标签正则误杀
        assert "<高级课程>" in chunks[0]["content"], "❌ 质量校验失败：网页实体字符未正确反序列化还原！"

        # 校验 2：系统控制字符剔除校验
        for ck in chunks:
            assert "\x00" not in ck["content"], "❌ 质量校验失败：残留 NULL 物理截断符 \\x00！"
            assert "\x07" not in ck["content"], "❌ 质量校验失败：残留 BELL 控制符 \\x07！"

        # 校验 3：多空白归一化校验
        for ck in chunks:
            assert "  " not in ck["content"], "❌ 质量校验失败：残留两个以上的多重冗余连续空格！"
            assert "\t" not in ck["content"], "❌ 质量校验失败：残留制表符 \\t！"
            assert "\r" not in ck["content"], "❌ 质量校验失败：残留回车符 \\r！"
            assert "\n\n" not in ck["content"], "❌ 质量校验失败：残留两重以上的空行换行！"

        # 校验 4：滑动窗口 Overlap 连贯性校验
        # 块 1 的末尾内容应该与块 2 的开头存在交集（语义承接）
        if len(chunks) >= 2:
            chunk_1_content = chunks[0]["content"]
            chunk_2_content = chunks[1]["content"]
            
            # 因为有 strip 首尾空格，所以取 overlap 前后的一段子集作相似匹配，若包含则通过
            overlap_anchor = chunk_1_content[-(chunk_overlap - 5):]
            assert overlap_anchor in chunk_2_content, "❌ 质量校验失败：滑动窗口 Overlap 连贯性丢失！"

        # 校验 5：SHA-256 排重指纹校验
        all_hashes = [ck["sha256"] for ck in chunks]
        assert len(all_hashes) == len(set(all_hashes)), "❌ 质量校验失败：生成的 SHA-256 指纹发生冲突碰撞！"
        
        print("✅ 所有的质量指标校验断言 100% 通过！文本规范化极佳。")
        print("🏁 Day 40 过关压测测试结束！")
        print("======================================================================")

    except AssertionError as ae:
        print("\n❌ 拦截到质量校验断言报错：")
        print(ae)
        sys.exit(1)
    except Exception as e:
        print("\n💥 运行过程中抛出意外异常:")
        import traceback
        traceback.print_exc()
        sys.exit(1)
