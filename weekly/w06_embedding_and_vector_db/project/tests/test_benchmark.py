import pytest
import asyncio
from weekly.w06_embedding_and_vector_db.project.benchmark import BenchmarkRunner
from weekly.w06_embedding_and_vector_db.project.models import BenchmarkReport


def test_synthetic_data_generation():
    """验证合成数据生成器能够正确生产 Chunk 数据契约"""
    runner = BenchmarkRunner(use_memory_store=True, mock_embedding=True)
    chunks = runner.generate_synthetic_chunks(25)
    
    assert len(chunks) == 25
    assert chunks[0].chunk_id == "bench_chunk_000000"
    assert chunks[24].chunk_id == "bench_chunk_000024"
    
    # 验证字段合法性与多样性
    assert chunks[0].token_length > 0
    assert chunks[0].char_length > 0
    assert chunks[0].permission_level in [1, 2, 3, 4]
    assert len(chunks[0].hash) == 64  # sha256 hex


@pytest.mark.asyncio
async def test_full_benchmark_flow():
    """对压测的全生命周期进行微型测试，验证统计计算是否能够流畅跑通"""
    runner = BenchmarkRunner(use_memory_store=True, mock_embedding=True)
    
    # 缩减规模进行极速跑通测试，保证不拖慢测试时间，也不发生 OOM
    report = await runner.run_full_benchmark(
        num_chunks=20,
        num_queries=5,
        concurrency=2
    )
    
    assert isinstance(report, BenchmarkReport)
    assert report.import_total_chunks == 20
    assert report.query_count == 5
    
    # 吞吐与延迟必须是合理的数值
    assert report.import_tps >= 0.0
    assert report.embedding_tps >= 0.0
    assert report.qdrant_write_tps >= 0.0
    assert report.qps >= 0.0
    assert report.p50_latency_ms >= 0.0
    assert report.p95_latency_ms >= 0.0
    assert report.p99_latency_ms >= 0.0
    assert report.avg_latency_ms >= 0.0
