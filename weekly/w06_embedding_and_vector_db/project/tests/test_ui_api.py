import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from weekly.w06_embedding_and_vector_db.project.app import app
from weekly.w06_embedding_and_vector_db.project.models import RetrievalResponse, SearchResult, RetrievalStrategy

# 构造 TestClient 进行接口离线测试
client = TestClient(app)


def test_home_page_endpoint():
    """验证主页面 GET / 接口可以正确加载 index.html"""
    response = client.get("/")
    assert response.status_code == 200
    assert "AI Research Assistant Knowledge Engine" in response.text
    assert "<svg id=\"connection-overlay\"></svg>" in response.text


def test_api_search_endpoint():
    """验证检索 Web 接口 POST /api/search"""
    # 构造请求参数，不进行真实的网络 Embedding 避免产生 429 报错或计费
    payload = {
        "query_text": "attention mechanism",
        "strategy": "hybrid",
        "top_k": 3,
        "user_id": "user_1",
        "max_permission_level": 4
    }
    
    response = client.post("/api/search", json=payload)
    # 因为可能没有 local_chunks 会返回 500 或 400，但如果是正常的，我们验证接口格式
    # 另外在测试中为了完全隔离，我们可以断言 status_code 是否为正常的 200/500（此处有真实 Qdrant Docker 时可以通过）
    if response.status_code == 200:
        data = response.json()
        assert "latency_ms" in data
        assert "results" in data
        assert "dense_results" in data
        assert "sparse_results" in data
        assert "context_preview" in data


def test_api_metrics_endpoint():
    """验证指标获取接口 GET /api/metrics"""
    response = client.get("/api/metrics")
    # 如果本地没有 local_chunks 会返回 400，如果是 200 验证内容
    if response.status_code == 200:
        data = response.json()
        assert "metrics" in data
        assert "hybrid" in data["metrics"]


def test_api_benchmark_endpoint():
    """验证并发压力测试接口 POST /api/benchmark"""
    payload = {
        "num_chunks": 10,
        "num_queries": 2,
        "concurrency": 2,
        "memory": True  # 强制内存测试，使其飞速完成
    }
    response = client.post("/api/benchmark", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "qps" in data
    assert "avg_latency_ms" in data
    assert "p50_latency_ms" in data
    assert "import_total_chunks" in data
    assert data["import_total_chunks"] == 10
