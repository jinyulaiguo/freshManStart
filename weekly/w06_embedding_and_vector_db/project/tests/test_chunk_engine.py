import pytest
from weekly.w06_embedding_and_vector_db.project.chunk_engine import ChunkEngine, FixedTokenChunker, SemanticChunker, CodeChunker, _estimate_tokens
from weekly.w06_embedding_and_vector_db.project.models import CleanedDocument, CleanedSection, DocumentMetadata

def test_token_estimation():
    assert _estimate_tokens("Hello World") == 3  # 11 chars / 4 = 2.75 -> 3 tokens
    assert _estimate_tokens("你好，世界") == 3     # 5 chars / 1.5 = 3.33 -> 3 tokens

def test_fixed_token_chunker():
    chunker = FixedTokenChunker(max_tokens=20, overlap_tokens=5)
    text = "This is paragraph one.\n\nThis is paragraph two.\n\nThis is paragraph three."
    chunks = chunker.chunk(text)
    
    assert len(chunks) > 0
    for chunk in chunks:
        assert _estimate_tokens(chunk) <= 20

def test_code_chunker():
    chunker = CodeChunker(max_tokens=10)
    code = "def first():\n    pass\n\ndef second():\n    pass\n"
    chunks = chunker.chunk(code)
    
    assert len(chunks) == 2
    assert "def first()" in chunks[0]
    assert "def second()" in chunks[1]

def test_chunk_engine():
    engine = ChunkEngine(max_tokens=30, min_tokens=10)
    
    doc = CleanedDocument(
        document_id="doc_test_456",
        title="Test Chunk Document",
        metadata=DocumentMetadata(author="author_chunk", category="test_category", permission_level=3),
        sections=[
            CleanedSection(heading="Section 1", level=1, content="This is a section content that needs chunking. We want to test how the engine processes it."),
            CleanedSection(heading="Code Section", level=2, content="def sample_code():\n    return 42\n")
        ]
    )
    
    chunks = engine.chunk_document(doc)
    
    assert len(chunks) >= 2
    assert chunks[0].document_id == "doc_test_456"
    assert chunks[0].author == "author_chunk"
    assert chunks[0].category == "test_category"
    assert chunks[0].permission_level == 3
    assert chunks[0].hash.startswith("sha256:")
