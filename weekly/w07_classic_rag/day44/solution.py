"""
Day 44 参考标准答案：基于语义相似度突变点的语义分块 (Semantic Chunking)

设计方案：
本模块提供基于高维向量空间余弦距离变化的自适应切片机制。该算法不依赖硬性的字数截断，
而是从高维语义空间的突变中寻找句子间的话题分水岭，保证每个分块都是高度内聚的“语义事实”。

类与函数结构：
- SemanticTextSplitter: 自适应语义切片器。
  - _calculate_cosine_distance(): 手写向量空间余弦距离计算（1.0 - 余弦相似度），规避第三方库依赖。
  - split_text(): 主控制流方法，执行“单句拆分 -> 批量向量化 -> 距离突变定位 -> 物理切分合并”的数据流逻辑。

关键数据流：
1. 原始长文本传入，利用正则表达式拆分为纯净句子集合。
2. 批量请求真实的 MiniMax 向量模型，获取每句的高维浮点表征。
3. 顺序滑窗计算相邻两句之间的余弦距离。
4. 计算距离集合的均值（Mean）与标准差（Std），设定过滤临界值：threshold = mean + step * std。
5. 遍历距离判定线，当相邻距离大于阈值时（相似度暴跌），截断并输出前置块，并初始化新块。
6. 输出完全隔离不同话题的 Chunk 集合。
"""

import re
import math
import asyncio
from typing import List

# 导入 w06 中封装好的真实 EmbeddingClient 网络客户端，严禁使用 Mock
from weekly.w06_embedding_and_vector_db.utils import EmbeddingClient

# 测试文本：前半部分讨论量子计算核心原理，后半部分骤然转换为中餐红烧肉的制作工序
TEST_DOCUMENT = (
    "量子计算是一种遵循量子力学规律调控量子信息单元进行计算的新型计算模式。"
    "在传统计算机中，信息以0或1的二进制位表示，而量子计算机利用量子叠加原理，其基本信息单元是量子比特。"
    "量子比特可以同时处于0和1的叠加态，这使得量子计算机在并行处理海量数据时展现出传统芯片无法企及的指数级加速能力。"
    "此外，量子纠缠是量子计算的另一大核心基石，处于纠缠态 of 两个粒子即便相隔万里也能实现瞬间的状态感应与协同。"
    
    # 话题突变点
    "红烧肉是一道深受人们喜爱的经典中餐家常菜，其肥而不腻的关键在于火候的精准把控。"
    "制作红烧肉时，通常需要选用五花三层的精品五花肉，先将其切成麻将牌大小的方块。"
    "五花肉块需要在冷水锅中下入，加入姜片与料酒大火焯水，以彻底去除血水和肉腥味。"
    "接着在锅中放入适量冰糖，用小火慢慢熬制出红褐色的糖色，这是给红烧肉上亮丽酱红色的灵魂步骤。"
    "最后加入八角、桂皮和热水，转为小火慢炖一个小时，使油脂在微沸中慢慢溢出，达到入口即化的酥烂口感。"
)


class SemanticTextSplitter:
    """基于句子间 Embedding 相似度突变点的自适应语义切分器"""
    
    def __init__(self, threshold_step: float = 1.0):
        """
        初始化语义分块器
        
        Args:
            threshold_step (float): 统计学阈值系数，即 均值 + threshold_step * 标准差
        """
        self.threshold_step = threshold_step
        # 实例化网络向量请求工具
        self.embedding_client = EmbeddingClient()

    def _calculate_cosine_distance(self, v1: List[float], v2: List[float]) -> float:
        """
        计算两个向量的余弦距离 (1.0 - 余弦相似度)
        
        Args:
            v1 (List[float]): 向量 A
            v2 (List[float]): 向量 B
            
        Returns:
            float: 余弦距离，值越接近 0.0 表示语义越相似，值越接近 1.0-2.0 表示语义差异越大
        """
        # 计算点积与各自模长，使用纯 Python 逻辑以保持算法自包含与物理隔离
        dot_product = sum(a * b for a, b in zip(v1, v2))
        norm_a = math.sqrt(sum(a * a for a in v1))
        norm_b = math.sqrt(sum(b * b for b in v2))
        
        # 边界防错设计：若存在全零异常向量，直接判定为最大语义距离
        if norm_a == 0 or norm_b == 0:
            return 1.0
            
        cosine_similarity = dot_product / (norm_a * norm_b)
        
        # 限制相似度范围，防止由于浮点精度损失引起的越界
        cosine_similarity = max(-1.0, min(cosine_similarity, 1.0))
        return 1.0 - cosine_similarity

    async def split_text(self, text: str) -> List[str]:
        """
        将文本按语义变化边界切分为多个 Chunk
        
        Args:
            text (str): 输入长文本
            
        Returns:
            List[str]: 语义聚拢的分块列表
        """
        # 1. 拆分成句子列表，利用正则匹配句号、感叹号、问号或换行，并洗掉冗余空格与空项
        sentences = [s.strip() for s in re.split(r"(?<=[。！？\n])", text) if s.strip()]
        if len(sentences) <= 1:
            return sentences

        # 2. 批量并发请求真实 Embedding 向量（不进行单个轮询以优化网络 I/O 时延）
        #    根据 Rule 12 使用真实网络客户端，且使用 db 写入用途参数
        print(f"[SemanticSplitter] 正在向量化 {len(sentences)} 个文本单句...")
        embeddings = await self.embedding_client.embed_texts(sentences, embed_type="db")
        
        # 3. 滑动计算相邻句子之间的语义距离
        distances = []
        for i in range(len(sentences) - 1):
            dist = self._calculate_cosine_distance(embeddings[i], embeddings[i + 1])
            distances.append(dist)
            
        # 4. 手动计算均值与标准差以判定动态阈值（拒绝外部 numpy 依赖以巩固手写算法底座）
        n = len(distances)
        mean_distance = sum(distances) / n
        variance = sum((d - mean_distance) ** 2 for d in distances) / n
        std_distance = math.sqrt(variance)
        
        # 5. 设定突变阀值：均值 + 1.0 倍标准差
        threshold = mean_distance + self.threshold_step * std_distance
        
        print(f"[SemanticSplitter] 句子距离分析:")
        print(f"  - 均值 (Mean): {mean_distance:.4f}")
        print(f"  - 标准差 (Std): {std_distance:.4f}")
        print(f"  - 突变分割阈值 (Threshold): {threshold:.4f}")
        
        # 6. 在距离大于阈值的相邻点执行物理切分，将句子合并成最终的 chunks
        chunks = []
        current_chunk_sentences = [sentences[0]]
        
        for i, dist in enumerate(distances):
            print(f"  - 句对 [{i} ↔ {i+1}] 语义跨距: {dist:.4f} {'[!!! 触发话题切换切分点]' if dist > threshold else ''}")
            
            # 分支判定：当距离大于阈值，说明在此发生了话题转折（相似度暴跌）
            if dist > threshold:
                # 截断并拼装输出前置分块
                chunks.append("".join(current_chunk_sentences))
                # 用下一个句子启动新分块
                current_chunk_sentences = [sentences[i + 1]]
            else:
                # 语义相近，追加到当前构建块中
                current_chunk_sentences.append(sentences[i + 1])
                
        # 循环结束，输出最终的尾部累加块
        if current_chunk_sentences:
            chunks.append("".join(current_chunk_sentences))
            
        return chunks


if __name__ == "__main__":
    async def main():
        print("=== Day 44 基于语义相似度突变的自适应切片 运行演示 ===")
        
        splitter = SemanticTextSplitter(threshold_step=1.0)
        chunks = await splitter.split_text(TEST_DOCUMENT)
        
        print(f"\n[切片输出结果] 成功生成了 {len(chunks)} 个语义内聚块：")
        for idx, chunk in enumerate(chunks):
            print(f"\n--- Chunk [{idx}] (长度: {len(chunk)} 字符) ---")
            print(chunk)
            
        # 静态验证断言：预期应当切分为 2 个 chunk (量子计算段与红烧肉段)
        assert len(chunks) == 2, f"切片异常，预期 2 个，实际切分出 {len(chunks)} 个"
        print("\n✅ 物理过关验证通过！文本在“量子纠缠...”与“红烧肉是一道...”的话题边界处成功被语义分块器自动切断！")

    asyncio.run(main())
