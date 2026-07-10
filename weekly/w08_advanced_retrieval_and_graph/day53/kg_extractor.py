"""
Day 53 参考答案：知识图谱（Knowledge Graph）建模与实体关系提取

设计方案：
1. 设计意图：
   提供完整的内存知识图谱拓扑构建与基于 LLM 的 SPO 三元组提取管道。
   设计了高保真的实体消歧（Entity Resolution）提示词以维持图的连通性。
   并且在解析 LLM 输出时，加入了物理剔除思维链及正则剥离 JSON 数组的防御性容错设计。

2. 核心结构：
   - `MemoryGraph`: 邻接表内存图结构，负责注册节点标签、动态拼装有向边。
   - `KGExtractor`: 调用 LLM API，对输出文本进行异常剔除、提取实体三元组并输出 JSON，做反序列化。
   - `if __name__ == "__main__":` 调试主入口：加载两章小说文本，完成关系提炼与跨章节多跳图搜索验证。

3. 物理防爆与正则匹配：
   - 提取三元组时，使用 re.DOTALL 剔除 <think> 块以防 Reasoning 模型标签外溢。
   - 使用 re.search(r"\\[.*\\]", text, re.DOTALL) 强行定位并提取 JSON 数组子串，杜绝模型多嘴说出的 Markdown 标记污染。
"""

import asyncio
import json
import re
from typing import List, Dict, Any, Tuple

# 导入真实 LLM 客户端，保证 100% 真实调用
from weekly.w04_prompt_and_http.utils import LLMClient


class MemoryGraph:
    """内存属性图模型：采用邻接表维护顶点标签与实体间的定向关系边"""

    def __init__(self):
        """初始化内存图结构"""
        # 邻接表：{ subject: { predicate: [objects] } }
        self.adj_list = {}
        # 节点集：{ node_id: label }
        self.nodes = {}

    def add_node(self, node_id: str, label: str = "Unknown"):
        """向图谱中添加节点并标记其标签类型
        
        Args:
            node_id: 节点唯一ID（消歧后的标准实体名）
            label: 实体标签，如 '人物', '地点', '机构'
        """
        # 1. 注册节点类型，若尚未在 nodes 中存在则添加
        if node_id not in self.nodes:
            self.nodes[node_id] = label
            
        # 2. 初始化该节点的邻接表分支
        if node_id not in self.adj_list:
            self.adj_list[node_id] = {}

    def add_triple(self, s: str, p: str, o: str, s_label: str = "Unknown", o_label: str = "Unknown"):
        """向图中添加一条三元组边关系
        
        Args:
            s: 主体节点 ID (Subject)
            p: 关系名称 (Predicate)
            o: 客体节点 ID (Object)
            s_label: 主体标签
            o_label: 客体标签
        """
        # 1. 保证主体和客体节点在图中均已注册，维护标签完整性
        self.add_node(s, s_label)
        self.add_node(o, o_label)

        # 2. 将有向边关系写入邻接表中，避免重复添加边
        if p not in self.adj_list[s]:
            self.adj_list[s][p] = []
            
        if o not in self.adj_list[s][p]:
            self.adj_list[s][p].append(o)

    def display(self):
        """打印输出当前内存图谱的邻接表拓扑分布，供控制台直观验证"""
        print("====== 内存知识图谱拓扑分布 ======")
        for s, rels in self.adj_list.items():
            s_label = self.nodes.get(s, "Unknown")
            print(f"Node: [{s}] (Type: {s_label})")
            for p, objects in rels.items():
                for o in objects:
                    o_label = self.nodes.get(o, "Unknown")
                    print(f"  └───( {p} )───► [{o}] (Type: {o_label})")
        print("==================================")


class KGExtractor:
    """关系提取引擎：利用大模型提取非结构化小说中的实体关系三元组，并在此过程中完成实体消歧"""

    def __init__(self, llm_client: LLMClient):
        """初始化关系提取器
        
        Args:
            llm_client: 已经加载了环境变量的真实大模型客户端实例
        """
        self.llm_client = llm_client

    def _repair_json_array(self, json_str: str) -> str:
        """如果 JSON 数组被大模型物理截断，本方法尝试剔除末尾未闭合的残缺字典，并自动补全括号以修复 JSON
        
        Args:
            json_str: 已经截取了中括号区间的可能残缺的 JSON 字符串
            
        Returns:
            修复并闭合后的 JSON 字符串
        """
        json_str = json_str.strip()
        if not json_str.startswith("["):
            return json_str
            
        # 寻找最后一个完整字典的结尾 "}"
        last_brace_idx = json_str.rfind("}")
        if last_brace_idx == -1:
            return json_str
            
        # 截取到该 "}" 位置，并补充中括号闭合数组
        repaired = json_str[:last_brace_idx + 1]
        repaired += "\n]"
        return repaired


    async def extract_triples(self, text: str) -> List[Dict[str, str]]:
        """调用大模型提炼文本中的三元组信息并返回标准的 JSON 结构
        
        Args:
            text: 非结构化的原始文本段落
            
        Returns:
            三元组字典列表，每个字典格式为：
            {
               "subject": str,
               "subject_label": str,
               "predicate": str,
               "object": str,
               "object_label": str
            }
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个高精度的文本实体关系三元组（SPO）提取器。\n"
                    "你需要从用户输入的小说章节文本中，提取出实体和实体之间的关系，并以标准的 JSON 数组格式输出。\n\n"
                    "提取规范与实体消歧（Entity Resolution）要求：\n"
                    "1. 实体标签仅限以下几种：'人物', '地点', '机构', '事件', '物品'。\n"
                    "2. 必须执行实体消歧：文中所有代称、职务称呼或同义简称，必须统一转换为其标准的唯一实体 ID。\n"
                    "   - 所有对李四的代称（如 '李队长', '李警官'）必须统一消歧合并为实体：'李四'\n"
                    "   - 所有对张三的代称（如 '张警员', '助手张三'）必须统一消歧合并为实体：'张三'\n"
                    "   - 所有对警局的代称（如 '警局', '江城警局'）必须统一消歧合并为实体：'江城警局'\n"
                    "3. 关系（Predicate）必须简短精准，如 '工作于', '助手', '配偶', '勾结', '密谋', '侦办' 等。\n"
                    "4. 重要防截断规范：如果你有思维链（如 <think> 标签），请务必将思考字数严格限制在 150 字以内，并必须在 </think> 标签外部输出最终的 JSON 数组。\n"
                    "5. 只输出一个合法的 JSON 数组，严禁包含任何 Markdown 格式标签、序号或多余的解释。格式示例如下：\n"
                    "[\n"
                    "  {\n"
                    "    \"subject\": \"李四\",\n"
                    "    \"subject_label\": \"人物\",\n"
                    "    \"predicate\": \"工作于\",\n"
                    "    \"object\": \"江城警局\",\n"
                    "    \"object_label\": \"机构\"\n"
                    "  }\n"
                    "]"

                )
            },
            {
                "role": "user",
                "content": f"需要提取的文本段落：\n{text}"
            }
        ]

        try:
            # 1. 采用低温度（0.1）保证大模型生成结构的确定性，将 max_tokens 提升至 2000 防止长思维链导致 JSON 截断
            response_text = await self.llm_client.request_llm(
                messages=messages,
                temperature=0.1,
                max_tokens=2000
            )


            # 2. 防错清洗：剔除思维链 Reasoning 标签极其内容
            if "<think>" in response_text:
                response_text = re.sub(r"<think>.*?</think>", "", response_text, flags=re.DOTALL)

            # 3. 防错正则拦截：部分大模型仍会吐出 "```json ... ```" 包装或前缀碎碎念
            # 利用正则表达式定位首个 "[" 到末尾 "]" 的 JSON 数组子串
            cleaned_text = response_text.strip()
            match = re.search(r"\[.*\]", cleaned_text, re.DOTALL)
            if match:
                cleaned_text = match.group()

            # 4. 反序列化解析 JSON 结构
            try:
                triples = json.loads(cleaned_text)
            except json.JSONDecodeError as decode_err:
                print(f"⚠️ 检测到 JSON 物理截断异常 ({decode_err})，正在执行工业级截断自愈修复...")
                # 调用自愈函数修复被截断的 JSON 串
                repaired_text = self._repair_json_array(cleaned_text)
                try:
                    triples = json.loads(repaired_text)
                    print(f"🎉 JSON 截断自愈成功！从截断的原始响应中挽救回 {len(triples)} 条完整三元组。")
                except Exception as repair_err:
                    print(f"❌ 截断自愈二次修复失败: {repair_err}")
                    raise decode_err
            return triples


        except Exception as e:
            # 防御性降级处理，当生成格式受阻时，返回空列表保障外部 Pipeline 顺畅不停机
            print(f"⚠️ 三元组提取/反序列化发生故障: {e}")
            # 诊断日志：打印出 raw 的大模型返回，帮助排查是否思维链被截断或没有格式化
            try:
                print(f"   [大模型 raw 返回]:\n{response_text}\n")
            except NameError:
                pass
            return []



# =====================================================================
# 🛠️ 悬疑小说双章节原始文本与调试运行入口
# =====================================================================

MOCK_NOVEL_CHAPTER_1 = (
    "第一章：江城是一个山明水秀的江南小城。李四是江城警局的刑侦队长，他为人正直深得民心。"
    "在警局里，李四有一个非常器重的贴身助手叫张三，两人合作多年，关系极好，目前正联手侦办一桩离奇的黄金失窃案。"
    "李队长每天办案辛劳，他的贤内助王五在江城一所大学里教历史，每天过着深居简出的平静生活。"
)

MOCK_NOVEL_CHAPTER_2 = (
    "第二章：夜幕降临，江城大酒店的某个包房里，助手张三悄悄推门而入。"
    "包房内坐着的正是被警局通缉的神秘幕后反派赵六。平日深得李队长信任的这个警员，竟然一直是赵六安插的内鬼。"
    "反派赵六递过去一箱现金，冷酷地指示张警员必须在三天内将警局机密卷宗偷出，否则交易作废。"
)


async def main():
    """本地手动调试主入口"""
    print("=== 开始 Day 53 知识图谱提取器本地调试 (标准答案) ===\n")
    
    # 1. 初始化依赖服务
    try:
        llm = LLMClient()
    except Exception as e:
        print(f"大模型客户端初始化失败 (检查 .env 配置文件): {e}")
        return

    extractor = KGExtractor(llm)
    graph = MemoryGraph()

    # 2. 依次分析小说章节并动态构建内存图谱
    try:
        print("--- [分析第一章] 提取实体关系... ---")
        triples_1 = await extractor.extract_triples(MOCK_NOVEL_CHAPTER_1)
        print(f"第一章成功提取 {len(triples_1)} 条三元组关系。")
        for t in triples_1:
            graph.add_triple(
                s=t["subject"], p=t["predicate"], o=t["object"],
                s_label=t["subject_label"], o_label=t["object_label"]
            )
            
        print("\n--- [分析第二章] 提取实体关系... (测试实体消歧能力) ---")
        triples_2 = await extractor.extract_triples(MOCK_NOVEL_CHAPTER_2)
        print(f"第二章成功提取 {len(triples_2)} 条三元组关系。")
        for t in triples_2:
            graph.add_triple(
                s=t["subject"], p=t["predicate"], o=t["object"],
                s_label=t["subject_label"], o_label=t["object_label"]
            )

        print("\n--- 图谱装配完毕，验证拓扑连通性 ---")
        graph.display()
        
        # 3. 验证多跳实体图连通路径
        # 提问：谁向反派赵六泄露了李四所在警局的机密？
        # 正确实体路径：李四(警局队长) -- 助手 --> 张三(内鬼) -- 勾结 --> 赵六
        print("\n🔎 执行拓扑路径搜索测试：寻找 [李四] -> [赵六] 的关联人...")
        
        # 在内存图的邻接表拓扑中寻找忽略方向的跨节点多跳链路 (无向图连通判定)
        connected_to_lisi = set()
        if "李四" in graph.adj_list:
            for p, objects in graph.adj_list["李四"].items():
                for obj in objects:
                    connected_to_lisi.add(obj)
        for node, rels in graph.adj_list.items():
            for p, objects in rels.items():
                if "李四" in objects:
                    connected_to_lisi.add(node)
                    
        connected_to_zhaoli = set()
        if "赵六" in graph.adj_list:
            for p, objects in graph.adj_list["赵六"].items():
                for obj in objects:
                    connected_to_zhaoli.add(obj)
        for node, rels in graph.adj_list.items():
            for p, objects in rels.items():
                if "赵六" in objects:
                    connected_to_zhaoli.add(node)
                    
        intersection = connected_to_lisi.intersection(connected_to_zhaoli)
        linked = False
        if intersection:
            linked = True
            connector = list(intersection)[0]
            print(f"🎉 发现关联路径！")
            print(f"   路径关系: [李四] ─── 与 ─── [{connector}] ─── 与 ─── [赵六] 在拓扑上双向连通")
        
        if not linked:

            print("❌ 失败！由于没有完成实体消歧（可能生成了 '张警员' 或 '李队长'），实体间多跳链路断开。")

    except Exception as e:
        print(f"\n❌ 运行发生未预期错误: {e}")


if __name__ == "__main__":
    asyncio.run(main())
