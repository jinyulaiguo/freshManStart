import pytest
import asyncio
from weekly.w06_embedding_and_vector_db.project.embedding_pipeline import EmbeddingPipeline
from weekly.w06_embedding_and_vector_db.project.models import Chunk

@pytest.mark.asyncio
async def test_embedding_pipeline_integration():
    # Make sure we use a real API request to embo-01
    pipeline = EmbeddingPipeline(max_concurrent_requests=2, batch_size=2)
    
    chunks = [
        Chunk(
            chunk_id="test_c1",
            document_id="test_d1",
            content="This is a test chunk for testing the embedding pipeline integration.",
            hash="sha256:test1"
        ),
        Chunk(
            chunk_id="test_c2",
            document_id="test_d1",
            content="This is a test chunk for testing the embedding pipeline integration.",
            hash="sha256:test1" # duplicate hash to test deduplication
        ),
        Chunk(
            chunk_id="test_c3",
            document_id="test_d2",
            content="Here is another distinct chunk to represent a separate semantic unit.",
            hash="sha256:test2"
        )
    ]
    
    results = await pipeline.embed_chunks(chunks)
    
    assert len(results) == 3
    assert len(results[0].vector) > 0
    assert results[0].vector == results[1].vector # Deduplication maps to same vector
    assert results[0].vector != results[2].vector
