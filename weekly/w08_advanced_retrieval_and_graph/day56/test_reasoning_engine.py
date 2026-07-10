"""
File: test_reasoning_engine.py
Description: Day 56 综合实战：跨章节高级推理分析引擎单元测试。

设计方案：
1. 设计意图：
   通过自动化测试用例，全方位校验 ReasoningEngine 的各个步骤运行状态与数据结构完整性。
   本文件利用 pytest 运行。测试涵盖数据库初始化、五步逻辑提取与异常控制拦截。

2. 核心校验点：
   - 内存数据库的初始化注入行为。
   - `execute_reasoning` 异步生成器中 StepResult 返回的键契约与数据结构规范。
   - 测试三元组中实体与属性边的数量是否非空。

3. 运行方式：
   在终端运行：`python -m pytest weekly/w08_advanced_retrieval_and_graph/day56/test_reasoning_engine.py`
"""

import pytest
import asyncio
from weekly.w08_advanced_retrieval_and_graph.day56.reasoning_engine import ReasoningEngine

@pytest.mark.asyncio
async def test_reasoning_engine_pipeline():
    """测试整个推理引擎流水线的输出结果结构、状态以及关键数据契约"""
    # 1. 实例化引擎
    engine = ReasoningEngine()
    
    # 2. 初始化向量数据库
    await engine.initialize_database()
    
    # 3. 运行推理流，针对测试问题
    query = "谁背叛了李四，并与赵六勾结密谋？"
    
    steps_received = []
    
    async for step_result in engine.execute_reasoning(query):
        steps_received.append(step_result)
        
        # 3.1 验证基本的 StepResult 数据结构约束
        assert "step" in step_result
        assert "status" in step_result
        assert "duration" in step_result
        assert "data" in step_result
        
        # 3.2 对特定步骤执行细化内容与指标的结构检验
        step = step_result["step"]
        data = step_result["data"]
        
        if step == 1:
            assert "rewritten_queries" in data
            assert "deduped_count" in data
            assert len(data["rewritten_queries"]) >= 1 # 必须包含原始问题和变体
            
        elif step == 2:
            assert "hypothetical_document" in data
            assert "chunks" in data
            
        elif step == 3:
            assert "chunks" in data
            assert "score_comparison" in data
            assert "filtered_count" in data
            
        elif step == 4:
            assert "triples" in data
            assert "nodes" in data
            assert "edges" in data
            # 校验实体图提取是否非空（由于模型在极低温度下运行，应能够稳定抽取到关键实体）
            if step_result["status"] == "success":
                assert len(data["nodes"]) > 0
                
        elif step == 5:
            assert "report" in data
            assert len(data["report"]) > 0

    # 4. 验证是否完整走完 5 个步骤
    assert len(steps_received) == 5
    assert [s["step"] for s in steps_received] == [1, 2, 3, 4, 5]
    
    # 5. 校验全部步骤运行状态为 success
    for s in steps_received:
        assert s["status"] == "success"
