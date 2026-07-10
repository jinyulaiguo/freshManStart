"""
Day 43 参考标准答案：固定大小 vs 递归字符分块算法

设计方案：
本模块提供两种分块（Chunking）机制的具体实现，旨在定量对比不同切片算法在面对带有特定程序结构（如 Python 异步协程）的技术长文本时的表现。

类与函数结构：
- FixedSizeTextSplitter: 
  通过单纯的按固定偏移量 `self.chunk_size` 步进切片，无视任何分隔符。
- RecursiveCharacterTextSplitter: 
  使用多级分隔符降级匹配并采用 Overlap 回溯合并逻辑。
  - _split_text(): 递归函数，按给定的优先级分隔符（如 \\n\\n, \\n, 空格）将文本逐步拆分成原子串，且在原子片段中保留分隔符以维护原文本完整性。
  - _merge_splits(): 长度控制与重叠拼接引擎。合并原子片段并在超限时回溯寻找 overlap_parts 初始化下一个块。
- verify_function_integrity():
  利用正则动态提取测试文本中的函数体定义，在生成的分块列表中遍历校验该函数是否被完整包含在单一的 Chunk 中，以评估切片算法的语义保留度。

数据流向：
1. 原始文本输入。
2. 递归细分：逐级应用分隔符切割，超出 chunk_size 的段落会被拆散到句子或单词级别，直至所有子片段长度合规或无分隔符可用。
3. 顺序流式合并：遍历原子片段进行累加。遇到超限时，输出当前累加块；并利用 `chunk_overlap` 参数从当前块末尾反向回溯收集小片段作为下一个块的前置缓冲。
4. 验证引擎检验并输出报告。
"""

import re
from typing import List

# 包含 Python 异步函数定义的测试技术文档
TEST_DOCUMENT = """
这是一个关于异步编程的技术文档。
在 Python 中，我们使用 asyncio 库来进行非阻塞并发编程。下面是一个典型的异步 API 调用函数：

async def fetch_user_data(user_id: int) -> dict:
    # 模拟网络延迟，让出 CPU 执行权
    await asyncio.sleep(0.5)
    # 模拟从数据库或外部 API 获取数据
    data = {
        "id": user_id,
        "name": f"User_{user_id}",
        "role": "engineer",
        "status": "active"
    }
    return data

上面的函数展示了如何定义一个协程。协程在 await 时会被挂起，从而允许事件循环在等待期间执行其他任务。

接着，我们还需要编写一个用于批量处理用户数据的入口函数：

async def batch_process_users(user_ids: list[int]) -> list[dict]:
    # 使用 asyncio.gather 来并发执行多个协程，提升 I/O 密集型任务的并发效率
    tasks = [fetch_user_data(uid) for uid in user_ids]
    results = await asyncio.gather(*tasks)
    return results

最后，通过 asyncio.run() 启动整个异步事件循环，将 batch_process_users 挂载到主线程上运行。
"""


class FixedSizeTextSplitter:
    """固定大小分块器，通过单纯的字符位移强行分块，不考虑文本的语义或结构边界"""
    
    def __init__(self, chunk_size: int = 150):
        """
        初始化固定大小分块器
        
        Args:
            chunk_size (int): 每一个文本块的硬性字符上限数。默认为 150。
        """
        self.chunk_size = chunk_size

    def split_text(self, text: str) -> List[str]:
        """
        将文本按固定字数进行物理截断切片
        
        Args:
            text (str): 待切片的长文本
            
        Returns:
            List[str]: 切分后的分块列表
        """
        if not text:
            return []
            
        chunks = []
        # 以 chunk_size 为步长，在文本上做固定长度的滑窗切片
        for i in range(0, len(text), self.chunk_size):
            chunks.append(text[i : i + self.chunk_size])
        return chunks


class RecursiveCharacterTextSplitter:
    """递归字符分块器，通过多级天然分隔符递归回退，保障语义完整度，并引入重叠区域平滑边缘信息"""
    
    def __init__(self, chunk_size: int = 150, chunk_overlap: int = 30, separators: List[str] = None):
        """
        初始化递归字符分块器
        
        Args:
            chunk_size (int): 每个分块的字符数上限
            chunk_overlap (int): 邻接块之间的重叠字符长度
            separators (List[str]): 分隔符递减降级列表，默认值为 ["\\n\\n", "\\n", " ", ""]
            
        Raises:
            ValueError: 当 chunk_overlap >= chunk_size 时抛出，此时重叠大小无意义或会导致算法死循环
        """
        if chunk_overlap >= chunk_size:
            raise ValueError(f"重叠大小 chunk_overlap ({chunk_overlap}) 必须小于分块大小 chunk_size ({chunk_size})")
            
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", " ", ""]

    def split_text(self, text: str) -> List[str]:
        """
        实现递归切分与 Overlap 平滑合并的核心入口
        
        Args:
            text (str): 待切片的长文本
            
        Returns:
            List[str]: 满足语义聚拢与重叠平滑的分块列表
        """
        if not text:
            return []
            
        # 步骤 1：调用内部递归拆分，提取出所有基本的原子片段（splits）
        splits = self._split_text(text, self.separators)
        
        # 步骤 2：对原子片段进行顺序流式合并与 overlap 滑动控制
        return self._merge_splits(splits)

    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        """
        递归地将文本切分为原子片段，每个片段不超过 chunk_size (除非分隔符耗尽且无法再分)
        
        Args:
            text (str): 需要切分的子文本
            separators (List[str]): 当前可用的分隔符降级列表
            
        Returns:
            List[str]: 包含文本内容和分隔符片段的细分列表
        """
        # 边界条件：如果当前文本长度已经满足限制，直接作为单个片叶子节点返回
        if len(text) <= self.chunk_size:
            return [text]
            
        # 边界条件：如果分隔符列表已经用完，做最后的兜底字符切割
        if not separators:
            return [text[i : i + self.chunk_size] for i in range(0, len(text), self.chunk_size)]
            
        # 提取当前层级优先级最高的分隔符
        separator = separators[0]
        
        # 如果当前分隔符不在文本中，降级采用下一个分隔符进行递归
        if separator not in text:
            return self._split_text(text, separators[1:])
            
        # 空格特殊处理以防止死循环
        if separator == "":
            return list(text)
            
        # 进行切分，由于我们要保留分隔符，不能直接抛弃它，因此要在合并时还原
        parts = text.split(separator)
        splits = []
        
        # 遍历切片，针对非空文本段继续向下递归切割，并在其后追加当前的分隔符
        for i, part in enumerate(parts):
            if part:
                # 递归降级处理子文本片段，传入除当前分隔符外的剩余分隔符列表
                splits.extend(self._split_text(part, separators[1:]))
            if i < len(parts) - 1:
                # 还原切分处的原有分隔符，作为独立的原子标记保留在列表中
                splits.append(separator)
                
        return splits

    def _merge_splits(self, splits: List[str]) -> List[str]:
        """
        采用流式合并机制将原子片段拼装成块，满足大小限制和 Overlap 要求
        
        Args:
            splits (List[str]): 包含文本段和连接符的原子片段列表
            
        Returns:
            List[str]: 合并完毕的最终分块列表
        """
        chunks = []
        current_chunk = []
        current_len = 0
        
        for part in splits:
            part_len = len(part)
            
            # 如果某单个原子片段本身就已经超出了 chunk_size (例如极长无空格字符串)
            # 我们必须将其作为单块输出以防丢失数据
            if part_len > self.chunk_size:
                if current_chunk:
                    chunks.append("".join(current_chunk))
                    current_chunk = []
                    current_len = 0
                chunks.append(part)
                continue
                
            # 控制流分支 1：当前块还有容量接纳该片段
            if current_len + part_len <= self.chunk_size:
                current_chunk.append(part)
                current_len += part_len
            # 控制流分支 2：加入后会导致超限，执行输出并回溯计算 overlap 重叠部分
            else:
                if current_chunk:
                    chunks.append("".join(current_chunk))
                    
                # 回溯区段累加：从当前块的尾部逆向遍历，收集累加长度在 chunk_overlap 之内的片段
                overlap_parts = []
                overlap_len = 0
                for p in reversed(current_chunk):
                    if overlap_len + len(p) <= self.chunk_overlap:
                        overlap_parts.insert(0, p)
                        overlap_len += len(p)
                    else:
                        # 超过重叠限制，停止收集
                        break
                        
                # 将下一个 chunk 初始化为回溯提取出来的重叠部分
                current_chunk = overlap_parts
                current_len = overlap_len
                
                # 追加当前导致超限的 part 进新块
                current_chunk.append(part)
                current_len += part_len
                
        # 循环结束，输出最终残留未被处理的块
        if current_chunk:
            chunks.append("".join(current_chunk))
            
        return chunks


def verify_function_integrity(chunks: List[str], function_name: str) -> bool:
    """
    静态校验特定的 Python 函数定义是否完整地包含在某一个 Chunk 块中
    
    Args:
        chunks (List[str]): 已经切分出来的 Chunk 列表
        function_name (str): 需要查找的函数定义关键字（例如 'async def fetch_user_data'）
        
    Returns:
        bool: 如果该函数的完整定义被 100% 完整保留在同一个 Chunk 中，返回 True；
              若被劈裂在不同的 Chunk 之间，返回 False。
              
    Raises:
        ValueError: 当在原始测试文档中无法通过正则解析出该函数体时抛出
    """
    # 提取测试文档中该函数的完整原始定义体
    # 正则提取自 async def [name] 开始，到其内最后的 return [name] 行结束
    pattern = rf"(async\s+def\s+{function_name}.*?return\s+\w+)"
    match = re.search(pattern, TEST_DOCUMENT, re.DOTALL)
    if not match:
        raise ValueError(f"测试文档中未定义名为 '{function_name}' 的函数")
        
    full_function_body = match.group(1).strip()
    
    # 遍历切片后的 chunks，查找是否有一个 chunk 能够作为超集完整容纳整个函数体字符串
    for chunk in chunks:
        if full_function_body in chunk:
            return True
            
    return False


if __name__ == "__main__":
    print("=== Day 43 固定大小 vs 递归字符分块 运行演示 ===")
    
    chunk_size = 300
    chunk_overlap = 60
    
    # 1. 测试固定大小分块
    print(f"\n--- 试验 1: 固定大小切片 (限制大小: {chunk_size} 字符) ---")
    fixed_splitter = FixedSizeTextSplitter(chunk_size=chunk_size)
    fixed_chunks = fixed_splitter.split_text(TEST_DOCUMENT)
    
    print(f"成功切分为 {len(fixed_chunks)} 个块:")
    for idx, chunk in enumerate(fixed_chunks):
        # 打印部分预览，展示其被物理切开的切面
        preview = repr(chunk.replace('\n', '\\n'))[:60]
        print(f"  Chunk [{idx}] (长度 {len(chunk)}): {preview}...")
        
    fixed_integrity = verify_function_integrity(fixed_chunks, "fetch_user_data")
    print(f"-> fetch_user_data 函数体是否被暴力截断: {'没有截断 (完美保留)' if fixed_integrity else '发生暴力截断 (撕裂分块)'}")
    
    # 2. 测试递归字符分块
    print(f"\n--- 试验 2: 递归字符语义分块 (限制大小: {chunk_size}, 重叠: {chunk_overlap} 字符) ---")
    rec_splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    rec_chunks = rec_splitter.split_text(TEST_DOCUMENT)
    
    print(f"成功切分为 {len(rec_chunks)} 个块:")
    for idx, chunk in enumerate(rec_chunks):
        preview = repr(chunk.replace('\n', '\\n'))[:60]
        print(f"  Chunk [{idx}] (长度 {len(chunk)}): {preview}...")
        
    rec_integrity = verify_function_integrity(rec_chunks, "fetch_user_data")
    print(f"-> fetch_user_data 函数体是否被暴力截断: {'没有截断 (完美保留)' if rec_integrity else '发生暴力截断 (撕裂分块)'}")
    
    print("\n[工程验证结论]")
    if not fixed_integrity and rec_integrity:
        print("物理验证成功！固定大小分块在 {chunk_size} 限制下破坏了 Python 异步函数的自然结构边界，而递归字符切分成功通过 \\n 契约将整个协程体保留在单一的 Chunk 中，守护了语义完整度。")
