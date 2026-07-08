import pytest
from weekly.w06_embedding_and_vector_db.project.sparse_retriever import SparseRetriever, _tokenize
from weekly.w06_embedding_and_vector_db.project.models import Chunk

def test_tokenize():
    # English tokenization
    en_tokens = _tokenize("The HNSW algorithm is fast.")
    assert "hnsw" in en_tokens
    assert "algorithm" in en_tokens
    assert "fast" in en_tokens
    
    # Chinese tokenization
    zh_tokens = _tokenize("自注意力机制是核心。")
    assert "自注意力" in zh_tokens or "注意力" in zh_tokens or "机制" in zh_tokens

def test_sparse_retriever_search():
    chunks = [
        Chunk(chunk_id="c1", document_id="d1", content="HNSW has parameters like ef_construct and M.", title="HNSW"),
        Chunk(chunk_id="c2", document_id="d1", content="BM25 is a sparse retrieval method.", title="BM25"),
        Chunk(chunk_id="c3", document_id="d2", content="Dense retrieval relies on embeddings.", title="Dense"),
    ]
    
    retriever = SparseRetriever()
    retriever.build_index(chunks)
    
    # Keyword search
    res = retriever.search("ef_construct parameters", top_k=2)
    assert len(res) >= 1
    assert res[0].chunk_id == "c1"
    assert res[0].strategy == "sparse"
    
    # Match BM25
    res_bm25 = retriever.search("sparse retrieval", top_k=2)
    assert len(res_bm25) >= 1
    assert res_bm25[0].chunk_id == "c2"
