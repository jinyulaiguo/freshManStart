import pytest
from weekly.w06_embedding_and_vector_db.project.vector_store import QdrantVectorStore
from weekly.w06_embedding_and_vector_db.project.models import Chunk, ChunkWithVector, MetadataFilter

def test_qdrant_vector_store_memory_mode():
    store = QdrantVectorStore(location=":memory:")
    assert store.is_memory_mode is True
    
    col_name = "test_collection"
    store.create_collection(col_name, dimension=4)
    store.create_payload_indexes(col_name)
    
    cvs = [
        ChunkWithVector(
            chunk=Chunk(
                chunk_id="chunk_1", document_id="doc_1", content="Public block",
                category="NLP", permission_level=1, user_id="tester", created_time="2026-07-01T00:00:00Z"
            ),
            vector=[1.0, 0.0, 0.0, 0.0]
        ),
        ChunkWithVector(
            chunk=Chunk(
                chunk_id="chunk_2", document_id="doc_1", content="Confidential block",
                category="NLP", permission_level=3, user_id="tester", created_time="2026-07-02T00:00:00Z"
            ),
            vector=[0.9, 0.1, 0.0, 0.0]
        )
    ]
    
    store.upsert_chunks(col_name, cvs)
    
    # 1. Search without filters
    res = store.search_dense(col_name, query_vector=[1.0, 0.0, 0.0, 0.0], limit=5)
    assert len(res) == 2
    
    # 2. Search with permission filter: level 2 (should hide chunk_2)
    f1 = MetadataFilter(user_id="tester", max_permission_level=2)
    res_filtered = store.search_dense(col_name, query_vector=[1.0, 0.0, 0.0, 0.0], limit=5, filters=f1)
    assert len(res_filtered) == 1
    assert res_filtered[0].chunk_id == "chunk_1"
    
    # 3. Search with category filter
    f2 = MetadataFilter(categories=["ComputerVision"])
    res_category = store.search_dense(col_name, query_vector=[1.0, 0.0, 0.0, 0.0], limit=5, filters=f2)
    assert len(res_category) == 0
    
    # 4. Search with time filters
    f3 = MetadataFilter(created_after="2026-07-01T12:00:00Z")
    res_time = store.search_dense(col_name, query_vector=[1.0, 0.0, 0.0, 0.0], limit=5, filters=f3)
    assert len(res_time) == 1
    assert res_time[0].chunk_id == "chunk_2"
    
    # 5. Delete by doc id
    store.delete_by_document_id(col_name, "doc_1")
    res_after_delete = store.search_dense(col_name, query_vector=[1.0, 0.0, 0.0, 0.0], limit=5)
    assert len(res_after_delete) == 0
    
    # 6. Cleanup
    store.delete_collection(col_name)
