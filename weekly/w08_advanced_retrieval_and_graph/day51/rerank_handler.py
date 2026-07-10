"""
Day 51 参考答案：重排序模型（Rerank）与交叉编码器（Cross-Encoder）

设计方案：
1. 设计意图：
   提供本地重排序模型与 API 级大模型重排评分的双方案实现。
   解决多路向量检索召回结果中夹带的“字面相似、逻辑无关”的噪音，
   通过全自注意力（Cross-Attention）交互打分来精准甄别，过滤并截断低相关度（score < 0.3）的 Chunks。

2. 核心结构：
   - 方案 A（本地模型重排）：`LocalCrossEncoderReranker`
     动态导入 `sentence_transformers` 并调用本地模型 predict。通过 NumPy 数组打分并进行浮点转换。
   - 方案 B（API 降级重排）：`APILightweightReranker`
     并发调用 `LLMClient` 获取 0.0-1.0 之间的相关性标量打分，做防错数据异常拦截。
   - `if __name__ == "__main__":` 调试主入口：演示两种方案对 5 个不同相关性 Chunk 进行重排的真实效果。

3. 物理隔离规范：
   - 方案 A 与方案 B 属于彻底物理隔离的不同代码板块，拥有独立的依赖加载和流程控制逻辑。
   - 方案 A 的 sentence-transformers 导入为延迟导入，防止无依赖环境导入模块时整体报错。
"""

import asyncio
from typing import List, Dict, Any, Tuple

# 导入真实大模型客户端，作为方案 B 打分器及降级备用
from weekly.w04_prompt_and_http.utils import LLMClient

# =====================================================================
# 【方案 A 板块】本地 Cross-Encoder 重排方案 (物理彻底隔离)
# =====================================================================

class LocalCrossEncoderReranker:
    """本地交叉编码器重排器：加载本地模型权重进行高性能全交互注意力打分"""

    def __init__(self, model_name: str = "BAAI/bge-reranker-base"):
        """初始化本地重排器
        
        Args:
            model_name: HuggingFace 权重路径，默认使用轻量级 base 版本
        """
        self.model_name = model_name
        self.model = None

    def rerank(self, query: str, chunks: List[Dict[str, Any]], threshold: float = 0.3) -> List[Dict[str, Any]]:
        """利用本地交叉编码器计算相关度分数，截断并降序排列
        
        Args:
            query: 用户的原始问题
            chunks: 粗筛召回的 Chunk 列表，每个字典格式为 {"doc_id": str, "text": str}
            threshold: 过滤截断阈值，低于该分数的 Chunk 将被物理丢弃
            
        Returns:
            排好序且过滤掉噪音后的 Chunk 列表，每个字典新增 "score" 键
            
        Raises:
            ImportError: 当未安装 sentence-transformers 时延迟触发
        """
        if not chunks:
            return []

        # 1. 延迟加载 CrossEncoder 模型，防止无 sentence-transformers 依赖时导入失败崩溃
        if self.model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as e:
                raise ImportError(
                    "未安装 'sentence-transformers' 依赖包，请运行 `pip install sentence-transformers` 或转为使用方案 B。"
                ) from e
            self.model = CrossEncoder(self.model_name)

        # 2. 组装交叉编码输入对：[ [Query, Doc1_Text], [Query, Doc2_Text], ... ]
        pairs = [[query, chunk["text"]] for chunk in chunks]

        # 3. 运行本地 Transformer 自注意力推理，获取标量分数列表 (NumPy 数组)
        scores = self.model.predict(pairs)

        # 4. 组装结果，执行阈值过滤与排序
        reranked_list = []
        for chunk, score in zip(chunks, scores):
            chunk_copy = chunk.copy()
            # 必须强制转换为标准 python 浮点数，NumPy 的 float32 类型在序列化时容易引发类型异常
            chunk_copy["score"] = float(score)

            # 过滤丢弃低于阈值的无用噪声
            if chunk_copy["score"] >= threshold:
                reranked_list.append(chunk_copy)

        # 5. 依据相关度评分执行降序排列
        reranked_list.sort(key=lambda x: x["score"], reverse=True)
        return reranked_list


# =====================================================================
# 【方案 B 板块】API 轻量级语义评估重排方案 (物理彻底隔离，无共享依赖)
# =====================================================================

class APILightweightReranker:
    """API 轻量级重排器：利用大模型对 Chunk 进行语义相关性判断打分，作为无本地算力时的降级选择"""

    def __init__(self, llm_client: LLMClient):
        """初始化 API 重排器
        
        Args:
            llm_client: 已经加载了环境变量的真实大模型客户端实例
        """
        self.llm_client = llm_client

    async def _score_single_chunk(self, query: str, chunk_text: str) -> float:
        """调用大模型为单个 (Query, Doc) 对打分 (0.0 - 1.0)
        
        Args:
            query: 用户提问
            chunk_text: 待评分的文档块内容
            
        Returns:
            0.0 到 1.0 之间的浮点数分数
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个高精度的文本相关性评估助手。\n"
                    "你的任务是接收用户的问题（Query）和一段参考文档片段（Document），评估该文档片段对回答用户提问的相关度，并输出一个 0.0 到 1.0 之间的分数。\n"
                    "打分梯度标准如下：\n"
                    "- 0.9 到 1.0: 极度相关，完美且直接回答了问题，包含核心技术手段。\n"
                    "- 0.5 到 0.8: 中度相关，提供了核心概念或背景原理，可辅助间接推导。\n"
                    "- 0.1 到 0.4: 弱度相关，只字面含有重合词汇但偏离了用户真实解决意图。\n"
                    "- 0.0: 完全不相关。\n"
                    "输出限制：\n"
                    "1. 仅输出一个 0.0 到 1.0 之间的浮点数（如 0.85），严禁包含任何序号、思考标签（如 <think>）或解释性废话。\n"
                    "2. 如果评估失败或无法判断，直接输出 0.0。"
                )
            },
            {
                "role": "user",
                "content": f"用户问题：{query}\n\n参考文档：{chunk_text}"
            }
        ]

        try:
            # 限制 max_tokens 为 10，并使用低温度 0.1 保证打分确定性，减少时延
            res = await self.llm_client.request_llm(
                messages=messages,
                temperature=0.1,
                max_tokens=10
            )
            
            # 清洗大模型输出
            cleaned = res.strip()
            # 过滤反引号 markdown 块
            if cleaned.startswith("`") or cleaned.endswith("`"):
                cleaned = cleaned.replace("`", "")
            
            # 如果大模型吐出额外汉字，在此只提取首个可能的浮点数
            import re
            match = re.search(r"\d+(\.\d+)?", cleaned)
            if match:
                score = float(match.group())
            else:
                score = float(cleaned)
                
            return max(0.0, min(score, 1.0))
        except Exception:
            # 异常防爆降级打分归零
            return 0.0

    async def rerank(self, query: str, chunks: List[Dict[str, Any]], threshold: float = 0.3) -> List[Dict[str, Any]]:
        """并发调用大模型接口对所有 Chunk 打分，过滤并降序重排
        
        Args:
            query: 用户的原始问题
            chunks: 粗筛召回的 Chunk 列表
            threshold: 过滤截断阈值
            
        Returns:
            排好序且过滤噪音后的 Chunk 列表
        """
        if not chunks:
            return []

        # 1. 异步并发发起所有 Chunk 的 API 打分请求，避免串行网络 Block
        tasks = [self._score_single_chunk(query, chunk["text"]) for chunk in chunks]
        scores = await asyncio.gather(*tasks)

        # 2. 组装结果并执行阈值降噪截断
        reranked_list = []
        for chunk, score in zip(chunks, scores):
            chunk_copy = chunk.copy()
            chunk_copy["score"] = score
            
            if score >= threshold:
                reranked_list.append(chunk_copy)

        # 3. 按相关度打分降序排列
        reranked_list.sort(key=lambda x: x["score"], reverse=True)
        return reranked_list


# =====================================================================
# 🛠️ 模拟粗筛数据与调试运行入口
# =====================================================================

MOCK_COARSE_CHUNKS = [
    {
        "doc_id": "doc_001",
        "text": "Python 异步 asyncio 库利用单线程事件循环（Event Loop）和非阻塞 I/O 多路复用，是处理高并发网络请求与长连接的黄金方案。但由于单线程限制，它不适合含有密集 CPU 计算的任务，也无法利用多核 CPU。"
    },
    {
        "doc_id": "doc_002",
        "text": "CPython 解释器的垃圾回收机制采用引用计数为主、标记清除与分代回收为辅的策略。当垃圾回收器（GC）运行时，会带来短暂的 Stop-The-World 开销，影响响应式高并发接口的首字时延。"
    },
    {
        "doc_id": "doc_003",
        "text": "对于 CPU 密集型任务，为了实现真正的物理多核并发，Python 工程师应当使用 multiprocessing 进程池（ProcessPoolExecutor）调度。它通过创建多个独立的 OS 进程规避了全局解释器锁（GIL）的阻塞。"
    },
    {
        "doc_id": "doc_004",
        "text": "线程是操作系统能够进行运算调度的最小单位。在 CPython 中，因为全局解释器锁（GIL）的存在，同一时刻只允许一个线程执行 Python 字节码，故多线程不能实现 CPU 密集型并发优化。"
    },
    {
        "doc_id": "doc_005",
        "text": "高性能并发编程需要关注 CPU 缓存行对齐、虚假共享以及非阻塞同步队列。在 C++ 和 Rust 中，常通过 std::atomic 或 atomic-queue 来消除由于线程竞争带来的吞吐量下降瓶颈。"
    }
]


async def main():
    """本地手动调试主入口"""
    print("=== 开始 Day 51 Rerank 重排过滤器本地调试 (标准答案) ===\n")
    
    query = "Python 并发如何优化以消除 CPU 瓶颈？"
    print(f"原始 Query: '{query}'\n")
    print("--- 粗筛阶段 Top-5 Chunks 原始分布 ---")
    for i, c in enumerate(MOCK_COARSE_CHUNKS):
        print(f"[{i+1}] ({c['doc_id']}): {c['text'][:60]}...")
    
    # 1. 尝试执行方案 A (本地 Cross-Encoder)
    try:
        print("\n[方案 A] 正在初始化本地 CrossEncoder (需加载本地模型权重)...")
        local_reranker = LocalCrossEncoderReranker()
        
        # 执行重排
        reranked_a = local_reranker.rerank(query, MOCK_COARSE_CHUNKS, threshold=0.3)
        print("\n[方案 A] 本地重排与截断成功！结果按得分排序：")
        for i, c in enumerate(reranked_a):
            print(f"[{i+1}] ({c['doc_id']}) 得分: {c['score']:.4f} -> {c['text'][:60]}...")
            
    except Exception as e:
        print(f"\n⚠️ 方案 A 本地模型加载失败 (这在未配置 CUDA/Mac MPS 环境或权重未下载时属正常预期): {e}")
        print("💡 正在自动降级执行 [方案 B] 大模型 API 语义打分重排...")

        # 2. 自动降级执行方案 B (API 语义打分重排)
        try:
            llm = LLMClient()
            api_reranker = APILightweightReranker(llm)
            
            reranked_b = await api_reranker.rerank(query, MOCK_COARSE_CHUNKS, threshold=0.3)
            print("\n[方案 B] API 降级重排与噪声截断成功！结果按评分排序：")
            for i, c in enumerate(reranked_b):
                print(f"[{i+1}] ({c['doc_id']}) 得分: {c['score']:.4f} -> {c['text'][:60]}...")
        except Exception as api_err:
            print(f"\n❌ [方案 B] API 重排降级链路同样运行失败: {api_err}")


if __name__ == "__main__":
    asyncio.run(main())
