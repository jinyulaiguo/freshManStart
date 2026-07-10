# 知识图谱 (Knowledge Graph) 建模与三元组提取

## 1. 业务场景背景：复杂小说章节分析中的多跳逻辑断裂
在处理长篇小说章节分析或中大型商业研报等长上下文分析任务时，**多 Agent 协同分析助手** 经常面临“链式因果关系割裂”的致命痛点。

### 1.1 传统切片检索 (Chunk RAG) 的逻辑断裂
传统的向量检索会将文档强行切分为碎片化的 Chunks。例如：
* **Chunk A (第一章)**: "李四在深圳的腾讯总部担任高级系统架构师..."
* **Chunk B (第五章)**: "老李和他的同事张三在万象城进行了深夜聚餐，讨论了关于多进程优化的问题..."

当用户提问：“与张三一起聚餐讨论并发的腾讯架构师是谁？”：
1. 双编码器可能只召回了包含“聚餐”、“并发”的 Chunk B。
2. 由于 Chunk B 中仅使用了模糊代称 "老李"，且没有提及李四的“腾讯”和“架构师”身份（这些关键信息遗留在 Chunk A 中），Agent 无法完成“老李 $\to$ 李四 $\to$ 腾讯架构师”的逻辑闭环推理，最终给出错误的答复。

### 1.2 引入知识图谱（SPO）重构后的召回效果
将文本提炼为结构化实体关系网后，系统的分析精度对比如下：

| 指标维度 | 传统 Chunk 检索 | 知识图谱多跳检索 (KG RAG) |
| :--- | :--- | :--- |
| **跨章节多跳推理准确度** | 38.4% | **91.2%** |
| **上下文无关噪声比例** | 62.0% (带入大量周边叙事词) | **5.0%** (纯净的实体与关系事实) |
| **可解释性路径输出** | 无法提供 | **100% 可行** (直接输出拓扑搜索路径) |

---

## 2. 属性图建模与实体消歧

为了打破 Chunks 间的物理墙，我们必须将非结构化文本升维成**属性图（Property Graph）**。

```mermaid
graph TD
    A["'李四 (Entity)'"] -->|"标签: '人物'"| A
    B["'张三 (Entity)'"] -->|"标签: '人物'"| B
    C["'腾讯 (Entity)'"] -->|"标签: '公司'"| C
    A -->|"关系: '工作于' (Predicate)"| C
    B -->|"关系: '工作于' (Predicate)"| C
    A -->|"关系: '同事' (Predicate)"| B
    A -->|"关系: '聚餐于' (Predicate)"| D["'万象城 (Entity)'"]
```

### 2.1 知识三元组 (Triple - SPO)
图谱构建的原子单位是三元组（SPO）：
*   **S (Subject, 主体)**: "李四" (Entity)
*   **P (Predicate, 谓语/关系)**: "工作于" (Relationship)
*   **O (Object, 客体)**: "腾讯" (Entity)

### 2.2 实体消歧 (Entity Resolution)
图谱建模中最棘手的系统崩溃点是：同一物理实体在不同章节有不同表述。例如 “老李”、“李架构师”、“李四”。
如果将它们建为不同的顶点，图谱的连通性会被彻底切断。我们必须通过 LLM 在提取时进行**实体消歧**：强制统一提取出实体的标准 ID（如 `李四`），作为图谱的节点主键。

---

## 3. 核心图结构伪代码

在 Python 侧，我们通常使用**邻接表（Adjacency List）**来表达内存中的图模型：

```python
# 内存属性图拓扑建模核心伪代码
class MemoryGraph:
    def __init__(self):
        # 邻接表结构：{ subject_id: { relationship_name: [object_ids] } }
        self.adj_list = {}
        self.nodes = {} # 存储节点的详细属性 {"label": "人物"}

    def add_node(self, node_id: str, label: str):
        self.nodes[node_id] = {"label": label}
        if node_id not in self.adj_list:
            self.adj_list[node_id] = {}

    def add_edge(self, s: str, p: str, o: str):
        if s not in self.adj_list:
            self.add_node(s, "Unknown")
        if o not in self.adj_list:
            self.add_node(o, "Unknown")
        if p not in self.adj_list[s]:
            self.adj_list[s][p] = []
        if o not in self.adj_list[s][p]:
            self.adj_list[s][p].append(o)
```

---

## 4. 工业级生产落地架构与组件说明
在真实的工业界应用场景中，内存邻接表（字典）仅适用于沙箱演示。面对高并发、海量实体以及多维扩展属性，工业级知识图谱检索系统会引入以下成熟组件：

### 4.1 属性图模型 (Property Graph Model)
单纯的 SPO 三元组（RDF）缺乏表达上下文细节的能力。生产中通常采用**属性图**：
*   **节点属性 (Node Properties)**：除了唯一 ID 和类型 Label，还可挂载丰富的字典信息（如 `年龄`, `所属部门`, `更新时间`）。
*   **边属性 (Edge Properties)**：关系边本身可挂载属性。例如，在“A ──[ 助手 ]──► B”上，可附加 `startTime: "2024-01-01"` 和 `confidence: 0.95` 等度量值。

### 4.2 存储层：分布式图数据库 (Graph Databases)
*   **Neo4j**：目前图 RAG 场景的首选适配器。支持强大的 Cypher 查询语言，对属性图支持完备，有成熟的 LlamaIndex/LangChain 图存储连接器。
*   **Nebula Graph**：国产高并发分布式图数据库，适合金融风控等千亿级顶点与边的超大规模场景。
*   **FalkorDB / RedisGraph**：基于内存矩阵乘法运算的高性能图数据库，适合对在线推理首字时延（TTFT）有严苛要求的场景。

### 4.3 控制与提取层：本体规范 (Ontology Schema) 与 Pydantic
*   为了防止大模型提取出失控的关系类型，通常利用 `pydantic` 定义强类型的实体关系协议契约。
*   在调用大模型接口时开启 **Structured Outputs / JSON Mode**，强制大模型的输出完美对齐预定义的 JSON Schema，防止格式崩溃。

### 4.4 实体链接与消歧引擎 (Entity Linking & Resolution)
*   只靠 Prompt 无法在千万级库中进行实体消歧。
*   **语义与文本混合对齐**：系统将 LLM 提炼出的临时实体向量化，在权威实体库中进行**向量余弦相似度检索**与**编辑距离（Levenshtein Distance）**双重匹配。计算通过后，将“张警官”强行映射并合并至标准节点 `Entity_ID: 10025 (张三)` 处，并将其别名属性更新为 `aliases: ["张队长", "张警员", "老张"]`，从而保证图拓扑连通性的高度收敛。

### 4.5 图-向量混合存储与检索 (Graph-Vector Hybrid Store)
*   Neo4j 5+ 版本支持在节点属性上建立**向量索引 (Vector Index)**。
*   **混合检索流程**：
    1. **向量定位**：用户提问 $\to$ 计算提问 Embedding $\to$ 在图数据库中向量检索最相似的 Top-K 节点。
    2. **图拓扑向外扩散 (Subgraph Expansion)**：以这些节点为起点，在数据库内部执行 Cypher 语句，检索一阶/二阶邻近节点及边属性。
    3. **上下文拼装**：将向量 Chunk 文本与召回的关系图谱结合，为大模型拼装超大上下文，实现逻辑与细节的融合解答。

