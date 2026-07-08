import pytest
from weekly.w06_embedding_and_vector_db.project.text_cleaner import TextCleaner
from weekly.w06_embedding_and_vector_db.project.models import ParsedDocument, DocumentSection, DocumentMetadata

def test_text_cleaner_clean_section():
    cleaner = TextCleaner(min_section_length=5)
    
    # Standard text section cleaning
    sec_normal = DocumentSection(heading="Normal", level=1, content="<p>Hello <b>World</b></p>\x00\n\nNew Line")
    cleaned_normal = cleaner.clean_section(sec_normal)
    assert "Hello World" in cleaned_normal.content
    assert "New Line" in cleaned_normal.content
    assert cleaned_normal.noise_ratio > 0
    assert cleaned_normal.original_length > cleaned_normal.cleaned_length
    
    # Code section preserving
    sec_code = DocumentSection(
        heading="Code Block",
        level=2,
        content="def hello_world():\n    # This is a comment\n    print('Hello, <p>World</p>')\n"
    )
    cleaned_code = cleaner.clean_section(sec_code)
    # The HTML tags inside code block shouldn't be stripped because it was classified as code
    assert "<p>World</p>" in cleaned_code.content
    assert cleaned_code.noise_ratio == 0.0

def test_text_cleaner_clean_document():
    cleaner = TextCleaner(min_section_length=10)
    
    doc = ParsedDocument(
        document_id="doc_test_123",
        title="Test Document",
        metadata=DocumentMetadata(author="clean_tester"),
        sections=[
            DocumentSection(heading="Intro", level=1, content="<p>This is a long introductory text that is clean.</p>"),
            DocumentSection(heading="Short", level=2, content="Tiny"), # Cleaned length < 10, will be filtered if no heading, but wait, does cleaner filter it if it has a heading?
            # In text_cleaner.py: if cleaned.cleaned_length >= self._min_section_length or cleaned.heading:
            # Let's test one without a heading that is short
            DocumentSection(heading="", level=0, content="Short"), # Cleaned length < 10 and no heading
        ]
    )
    
    cleaned_doc = cleaner.clean_document(doc)
    
    # The one with heading 'Short' is preserved because it has a heading, but the empty heading 'Short' should be filtered.
    headings = [s.heading for s in cleaned_doc.sections]
    assert "Intro" in headings
    assert "Short" in headings
    assert "" not in headings
    assert len(cleaned_doc.sections) == 2
