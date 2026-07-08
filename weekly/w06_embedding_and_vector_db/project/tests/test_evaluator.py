import pytest
from weekly.w06_embedding_and_vector_db.project.evaluator import RetrievalEvaluator
from weekly.w06_embedding_and_vector_db.project.models import EvalSample, SearchResult, RetrievalStrategy

def test_retrieval_evaluator_metrics():
    evaluator = RetrievalEvaluator(default_k=5)
    
    retrieved = ["c1", "c2", "c3", "c4", "c5"]
    relevant = ["c2", "c4", "c6"]
    
    # Recall@5 = 2 / 3
    assert evaluator.recall_at_k(retrieved, relevant, k=5) == pytest.approx(2/3)
    
    # Precision@5 = 2 / 5
    assert evaluator.precision_at_k(retrieved, relevant, k=5) == pytest.approx(2/5)
    
    # MRR (first relevant is at rank 2: "c2") -> 1 / 2
    assert evaluator.reciprocal_rank(retrieved, relevant) == pytest.approx(0.5)
    
    # NDCG@5 calculation
    ndcg = evaluator.ndcg_at_k(retrieved, relevant, k=5)
    assert ndcg > 0.0
    assert ndcg <= 1.0

def test_evaluator_evaluate_batch():
    evaluator = RetrievalEvaluator(default_k=3)
    
    samples = [
        EvalSample(question="Q1", expected_chunk_ids=["c1", "c2"]),
        EvalSample(question="Q2", expected_chunk_ids=["c3"]),
    ]
    results = [
        [
            SearchResult(chunk_id="c1", content="", score=0.9, rank=1),
            SearchResult(chunk_id="c2", content="", score=0.8, rank=2)
        ],
        [
            SearchResult(chunk_id="x1", content="", score=0.9, rank=1),
            SearchResult(chunk_id="c3", content="", score=0.8, rank=2)
        ]
    ]
    
    metrics = evaluator.evaluate_batch(samples, results, k=3, strategy=RetrievalStrategy.HYBRID)
    
    assert metrics.k == 3
    assert metrics.num_samples == 2
    assert metrics.recall_at_k == pytest.approx((1.0 + 1.0) / 2) # Sample 1 has c1, c2 (2/2); Sample 2 has c3 (1/1)
    assert metrics.precision_at_k == pytest.approx(((2/3) + (1/3)) / 2)
    assert metrics.mrr == pytest.approx((1.0 + 0.5) / 2)
