# 📅 Week 12: Planning + Reflection 范式

> **第十二周目标**：精通 Plan-and-Execute (规划-执行) 架构，掌握 ReWOO 规划执行解耦模式，理解 LLM-as-Critic 独立审查双模型博弈，能够使用 Reflexion 架构进行错误推导，具备在运行期动态重构任务规划的控制流设计能力。

---

## Day 78：Plan-and-Execute (规划-执行) 架构分步控制
*   **核心知识点**：
    *   **Planner（规划器）与 Executor（执行器）的解耦**：Planner 负责宏观拆解任务为 Sub-tasks，Executor 负责微观执行单个 Sub-task 并返回结果。
    *   **状态结构设计**：State 中设计专门的 `plan` 列表和 `results` 历史字典。
    *   **大模型作为计划分配器**：根据当前步骤提取任务，分发给对应 Node。
*   **Agent 核心关联**：传统的 ReAct 模式在遇到多步骤复杂任务时极易迷失方向（走一步看一步）。通过 Plan-and-Execute，Agent 能在最开始生成宏观路线图，每一轮循环只执行当前计划项，极大提升了多阶段复杂长程任务的稳定性。
*   **🎯 过关验证标准**：手写一个 Plan-and-Execute 状态图。Planner 解析复杂长句并输出一个 3 步骤的 `PlanList`。控制图按照该列表循环跳转到执行器，完成所有步骤后汇总并输出。

---

## Day 79：ReWOO (Reasoning Without Observation) 规划与执行解耦
*   **核心知识点**：
    *   **ReWOO 范式原理**：Planner 一次性输出全部计划以及各步骤所需的参数占位符（如 `Step-1: 搜索 A`，`Step-2: 总结 Step-1 的结果`），生成无观察依赖的有向计划拓扑图。
    *   **并行化加速**：一旦规划完成，独立步骤的工具调用能够并发拉起，无需等待前一步的中间 Observation 返回。
*   **Agent 核心关联**：普通的 ReAct 中，每执行一个工具都需要去调用一次大模型获取下一步行动，造成时延和 Token 暴涨。ReWOO 将“推理”和“行动”完全解耦，大幅降低了对大模型推理的调用频次，显著减少时延开销。
*   **🎯 过关验证标准**：基于 LangGraph 构建一个 ReWOO 引擎，实现输入一个包含两个独立子任务的问题时，Planner 能一次性生成带依赖的计划列表，系统自动提取参数并并发拉起对应工具，最后把 Observation 合并渲染给总结节点。

---

## Day 80：LLM-as-Critic 独立审查器与双模型博弈设计
*   **核心知识点**：
    *   **独立审查节点（Critic Node）**：引入一个与生成器独立的 LLM，使用不同的 System 约束作为评审法官。
    *   **对抗性 Prompt 提示词**：Critic 负责吹毛求疵寻找生成文本的逻辑漏洞、格式残缺和幻觉风险，给出通过（OK）或回退（REJECT）及改进建议的指标。
*   **Agent 核心关联**：模型自己评判自己的生成物很容易产生“盲点”。在 Agent 架构中引入 LLM-as-Critic 节点，形成对抗博弈，能够把逻辑严密性提升数倍，是实现 Agent 自动化代码编写和金融报告产出的核心防线。
*   **🎯 过关验证标准**：在图拓扑中绑定 `Generator` 节点与 `Critic` 节点。输入生成的英文合同，Critic 自动扫描其中的排版漏洞和缺失项，一旦检测到隐患则抛出 REJECT，路由边强制回退到 Generator 进行重新生成，直到 Critic 输出 PASS。

---

## Day 81：Reflexion 自我反思架构：从失败 Observation 中归纳纠错规则
*   **核心知识点**：
    *   **Reflexion 经典架构**：大模型生成物 $	o$ 外部环境（如测试用例、Linter）执行评估 $	o$ 若出错，大模型分析错误日志并写一篇“反思摘要（Self-Reflection）”存入记忆 $	o$ 下一轮迭代中强制大模型将该反思作为 System 约束读取。
    *   **错误经验归纳**。
*   **Agent 核心关联**：单纯的 ReAct 重试只是盲目的让模型反复尝试；Reflexion 要求模型先分析“我刚才为什么会写出这个 Bug，我下次应该避免什么”，以归纳总结出的高级经验指导下一轮生成，能够实现收敛极快的自愈。
*   **🎯 过关验证标准**：编写一个能自动执行代码并反思的 Agent。当大模型生成的 Python 代码由于 SyntaxError 或 NameError 在本地运行崩溃时，系统捕获 Traceback 错误日志送入 `Reflector` 节点，生成反思摘要，在第二轮生成中成功绕开该 Bug 正常运行。

---

## Day 82：动态计划重构（Dynamic Re-planning）分支控制
*   **核心知识点**：
    *   **运行时计划刷新**：在 Plan-and-Execute 执行中，当某个步骤发生严重偏差或返回了非预期的 Observation 时，路由到 Planner 重新规划后续的所有步骤（即动态调整未执行的 Plan 列表）。
    *   **逻辑自适应分流**。
*   **Agent 核心关联**：现实世界的工具执行反馈是充满变数的（例如：原定计划去查询 API，但发现 API 离线）。动态重构计划能让 Agent 具有“见机行事”的超强自适应弹性，避免死守着开头制定的死板计划撞墙。
*   **🎯 过关验证标准**：设计一个动态重构计划的图，在执行第 2 步（请求模拟 API）时返回 `API_OFFLINE`，路由边能识别此 Observation 并强制跳转回 Planner，Planner 自动生成一个降级新计划（改为读取本地 Mock 缓存文件）替换掉原计划列表，最终图运行成功。

---

## Day 83：语义相似度自检与输出文本防幻觉校对
*   **核心知识点**：
    *   **幻觉自检指标（NLI - Natural Language Inference）**：蕴含（Entailment）、矛盾（Contradiction）与中立（Neutral）的逻辑对齐。
    *   **基于 Embedding 距离的断言自检**。
*   **Agent 核心关联**：这是防范 Agent 基于检索 Context 生成胡编乱造（幻觉）回复的语义锁。利用蕴含模型对生成的句子与 Context 进行语义校验，能够在物理边界上卡掉 99% 的大模型幻觉输出。
*   **🎯 过关验证标准**：实现一个 `AntiHallucinationVerifier` 类。大模型生成答案后，该类自动将生成的长句拆分为独立陈述，逐个与 RAG 召回的 Context 计算逻辑蕴含关系，若判定为 Contradiction 或 Neutral，强制大模型根据 Context 进行第 2 次对齐纠偏生成。

---

## Day 84：第十二周综合实战：支持复杂多任务规划、自动纠错与反思重构的行业趋势分析 Agent
*   **实战任务**：**实现一个极其稳健的高级行业研报研究 Agent 引擎。**
    *   **要求**：
        1. 采用 Plan-and-Execute 状态图编排，Planner 对课题进行步骤拆解；
        2. 支持 ReWOO 的并行工具调用加速，并发查询多路行业数据；
        3. 引入 Day 81 的 Reflexion 架构，当提取到的财务数据指标格式不对或不齐时，Reflector 自动分析并引导修正计划；
        4. 包含 Day 80 的 Critic 节点对研报草稿进行交叉审计（从可信度、语句通顺度等），只有通过 Critic 的 PASS 评估，图才终止并输出；
        5. 包含 Day 83 的防幻觉自检，确保研报中的每一个数字都能在 context 中找到逻辑蕴含。
    *   **🎯 交付件**：Planner-Executor-Critic-Reflector 完备图拓扑代码、防幻觉自检组件类、单元测试套件、以及记录了多轮反思、计划重写和博弈评审的完整研究日志。\n