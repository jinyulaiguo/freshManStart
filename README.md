# 🧠 AI Agent 驾驭工程 · 26 周学习之旅

> 从 Python 零基础到生产级 AI Agent 工程师的完整学习记录。
>
> 核心公式：**Agent = Model + Harness**

---

## 📅 学习路线总览

| 阶段 | 时间 | 主题 | 里程碑 |
|------|------|------|--------|
| 阶段一 | W1 – W5 | Python & LLM 地基 | ✅ 不依赖框架的最小可运行 Agent |
| 阶段二 | W6 – W9 | 知识与记忆系统 | ✅ 具备 RAG + Memory 的知识型 Agent |
| 阶段三 | W10 – W15 | 框架与核心工程 | ✅ LangGraph + Planning + 自动化评测 |
| 阶段四 | W16 – W18 | 生产工程化 | ✅ 可部署的生产级 Agent（监控 + 容灾） |
| 阶段五 | W19 – W21 | 多 Agent 系统与协议 | ✅ 多 Agent 协作系统 |
| 阶段六 | W22 – W24 | Harness Engineering | ✅ Harness 三层防护完整覆盖 |
| 阶段七 | W25 – W26 | 毕业冲刺 | ✅ 完整作品集 + 面试材料就绪 |

详细的周度知识地图见 [docs/knowledge_map.md](docs/knowledge_map.md)。

---

## 📁 目录结构

```
03.freshManStart/
│
├── README.md                        ← 你现在看的这个文件
│
├── docs/                            # 📄 规划文档区（只读参考）
│   ├── agent_learning_plan.md       # 26 周总体学习计划
│   ├── knowledge_map.md             # 周度知识地图
│   ├── week_1_basics_and_oop.md     # W1 日计划
│   └── week_2_pydantic_and_async.md # W2 日计划
│
├── weekly/                          # 🧪 周练习区（练兵场）
│   ├── w01_python_basics/
│   │   ├── day_exercises/           # 每天的小练习
│   │   │   ├── day1_data_structures/
│   │   │   │   ├── practice.py
│   │   │   │   └── notes.md
│   │   │   ├── day2_control_flow_regex/
│   │   │   ├── day3_decorators/
│   │   │   ├── day4_oop_magic/
│   │   │   └── day5_protocol_reflection/
│   │   ├── deliverable/             # 本周交付作品（Day6-7 综合实战）
│   │   │   ├── main.py
│   │   │   └── README.md
│   │   └── README.md                # 本周学习总结
│   │
│   ├── w02_pydantic_async/
│   │   ├── day_exercises/
│   │   ├── deliverable/
│   │   └── README.md
│   │
│   ├── ...                          # w03 ~ w26 同理
│   └── w26_interview_prep/
│
├── project/                         # 🚀 主线项目（主战场）：AI 研究助手
│   ├── src/
│   │   ├── agent/                   # Agent 核心逻辑（W10 起建）
│   │   ├── tools/                   # 工具集（W5 起建）
│   │   ├── rag/                     # 检索增强模块（W7 起建）
│   │   ├── memory/                  # 记忆模块（W9 起建）
│   │   ├── harness/                 # Harness 控制层（W22 起建）
│   │   │   ├── specs/
│   │   │   ├── rules/
│   │   │   └── sandbox/
│   │   └── utils/                   # 通用工具函数
│   ├── eval/                        # 评测体系（W15 起建）
│   ├── deploy/                      # 部署配置（W18 起建）
│   ├── tests/                       # 单元测试
│   ├── pyproject.toml
│   └── README.md
│
└── reading/                         # 📖 源码阅读笔记
    ├── langchain_tool_decorator.md
    ├── langgraph_state_graph.md
    └── ...
```

### 核心分区原则

| 分区 | 定位 | 代码质量要求 | 是否持续迭代 |
|------|------|-------------|-------------|
| `weekly/` | 练兵场：15+ 个独立小作品 + 每日练习 | 允许粗糙，重在验证学习 | 写完不改，保留为学习证据 |
| `project/` | 主战场：唯一的面试级主线项目 | 逐步打磨到生产级 | 从 W6 持续迭代到 W25 |
| `reading/` | 源码笔记：框架源码阅读记录 | 按主题命名，方便检索 | 学到新框架时持续补充 |
| `docs/` | 规划文档：学习计划与知识地图 | 只读参考，一般不修改 | 仅在计划调整时更新 |

### `weekly/` 与 `project/` 的关系

两者不是割裂的。流程是：**先在 `weekly/` 里实验探索 → 验证可行 → 把成熟代码"毕业"到 `project/` 中**。

```
weekly/w07 学会了 RAG 分块策略
    ↓ 验证可行后搬过去
project/src/rag/ 正式实现 RAG 模块
```

### `project/src/` 的模块对应 Agent 能力模型

```
Agent = 大脑(agent/)   → 决策与编排
      + 四肢(tools/)   → 执行具体动作
      + 记忆(memory/)  → 短期 + 长期记忆
      + 知识(rag/)     → 外部文档检索
      + 缰绳(harness/) → 安全约束控制
```

各模块按需创建，不提前建空文件夹：

| 模块 | 首次创建 | 后续迭代 |
|------|---------|---------|
| `tools/` | W5 | W13 MCP 标准化 |
| `rag/` | W7 | W8 GraphRAG 升级 |
| `memory/` | W9 | W14 压缩优化 |
| `agent/` | W10 | W12 加 Planning，W21 加 Supervisor |
| `eval/` | W15 | W24 回归测试 |
| `deploy/` | W18 | W25 最终打磨 |
| `harness/` | W22 | W23-W24 三层补全 |

---

## 📝 Git 提交规范

### Commit Message 格式

```
<类型>(范围): 简要描述
```

**类型定义**：

| 类型 | 用途 | 示例 |
|------|------|------|
| `learn` | 周练习代码 | `learn(w01/day3): 实现带参数装饰器 @retry(times=3)` |
| `feat` | 主线项目新增功能 | `feat(project/rag): 实现 PDF 分块与向量化入库` |
| `refactor` | 主线项目重构 | `refactor(project/agent): 迁移 ReAct 循环到 LangGraph` |
| `eval` | 评测相关 | `eval(project): 新增 50 条 Golden Dataset 测试用例` |
| `docs` | 文档/笔记 | `docs(reading): LangChain @tool 装饰器源码阅读笔记` |
| `fix` | 修复 | `fix(project/tools): 修复搜索工具超时未捕获的异常` |

### Commit 粒度

**按"知识点完成"提交，不按天。** 每完成一个可独立运行的知识点验证，就提交一次。一天可能 2–5 个 commit。

```bash
# ✅ 好的粒度
git commit -m "learn(w01/day1): 实现嵌套字典安全提取函数"
git commit -m "learn(w01/day1): 添加字典推导式与 KeyError 处理练习"

# ❌ 不好的粒度
git commit -m "update"
git commit -m "Day 1 所有代码"
```

### 筛选技巧

```bash
# 查看第一周所有练习
git log --oneline --grep="learn(w01"

# 查看主线项目的完整演进史
git log --oneline --grep="feat(project"

# 查看所有源码阅读笔记
git log --oneline --grep="docs(reading"
```

---

## 🏷️ Tag 标签策略

### 周标签

每周日完成后打一个周标签：

```bash
git tag -a week-01 -m "W01: Python 基础与面向对象"
git tag -a week-02 -m "W02: Pydantic 与异步编程"
# ...
git tag -a week-26 -m "W26: 面试冲刺"
```

### 里程碑标签

在 6 个关键节点打里程碑标签，与普通周标签区分：

```bash
git tag -a milestone-1-minimal-agent  -m "里程碑一：不依赖框架的最小可运行 Agent"       # W5 结束
git tag -a milestone-2-rag-memory     -m "里程碑二：具备 RAG + Memory 的知识型 Agent"   # W9 结束
git tag -a milestone-3-framework-eval -m "里程碑三：LangGraph + Planning + 自动化评测"  # W15 结束
git tag -a milestone-4-production     -m "里程碑四：可部署的生产级 Agent（监控+容灾）"   # W18 结束
git tag -a milestone-5-multi-agent    -m "里程碑五：多 Agent 协作系统"                  # W21 结束
git tag -a milestone-6-harness        -m "里程碑六：Harness 三层防护完整覆盖"           # W24 结束
```

### 他人学习时的使用方式

```bash
# 想从头跟学第一周？
git checkout week-01

# 想看最小 Agent 怎么写的？
git checkout milestone-1-minimal-agent

# 想看从最小 Agent 到加了 RAG 之间发生了什么？
git log milestone-1-minimal-agent..milestone-2-rag-memory --oneline

# 想看第 12 周学了什么？
git log week-11..week-12 --oneline
```

---

## 🌿 分支策略

主线使用单一 `main` 分支，保持线性历史：

```
main: ──○──○──○──○──○──○──○──○──○──○──○──○──
       W1        W5▲       W9▲        W15▲
                  │         │           │
            milestone-1  milestone-2  milestone-3
```

唯一例外：当实验性改动可能搞崩主线项目时，临时开分支：

```bash
git checkout -b experiment/w10-langgraph-migration
# 实验成功后合并回 main
git checkout main
git merge experiment/w10-langgraph-migration
git branch -d experiment/w10-langgraph-migration
```

---

## 📋 每周 README 模板

每个 `weekly/wXX_xxx/README.md` 建议使用以下模板：

```markdown
# WXX - 本周主题

## 本周目标
（从 knowledge_map.md 复制对应行）

## 完成情况
- [x] Day X: xxx ✅
- [x] Day X: xxx ✅
- [ ] Day X: xxx 🔄 进行中

## 踩坑记录
（记录卡了很久的问题和最终解决方案）

## 关键收获
（用自己的话总结 1-3 个核心理解）

## 交付作品
（简要说明本周交付的独立作品及运行方式）
```

---

## 🚫 .gitignore 配置

请在第一天就配好以下规则：

```gitignore
# 环境与密钥
.env
*.pyc
__pycache__/
.venv/
venv/

# 向量数据库本地存储
chroma_db/
*.index

# 大文件
*.pdf
*.csv

# IDE
.vscode/
.idea/

# 评测报告临时产物
eval/reports/*.json

# 系统文件
.DS_Store
Thumbs.db
```
