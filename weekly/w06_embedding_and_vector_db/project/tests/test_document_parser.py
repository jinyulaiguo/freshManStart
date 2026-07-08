import pytest
from weekly.w06_embedding_and_vector_db.project.document_parser import DocumentParser, MarkdownParser, HtmlParser, PlainTextParser, CodeParser
from weekly.w06_embedding_and_vector_db.project.models import RawDocument, SourceType, DocumentMetadata

def test_markdown_parser():
    parser = MarkdownParser()
    content = "# Title\n\n## Section 1\nContent 1\n\n```python\n# code block\ndef test(): pass\n```\n\n## Section 2\nContent 2"
    sections = parser.parse(content)
    
    assert len(sections) == 3
    assert sections[0].heading == "Title"
    assert sections[0].level == 1
    assert sections[1].heading == "Section 1"
    assert "code block" in sections[1].content
    assert sections[2].heading == "Section 2"
    assert sections[2].content == "Content 2"

def test_html_parser():
    parser = HtmlParser()
    content = "<html><body><h1>Main Heading</h1><p>Paragraph 1</p><h2>Sub Heading</h2><p>Paragraph 2</p></body></html>"
    sections = parser.parse(content)
    
    assert len(sections) == 2
    assert sections[0].heading == "Main Heading"
    assert "Paragraph 1" in sections[0].content
    assert sections[1].heading == "Sub Heading"
    assert "Paragraph 2" in sections[1].content

def test_plain_text_parser():
    parser = PlainTextParser()
    content = "Para 1 line 1\nPara 1 line 2\n\nPara 2 line 1"
    sections = parser.parse(content)
    
    assert len(sections) == 2
    assert sections[0].content == "Para 1 line 1\nPara 1 line 2"
    assert sections[1].content == "Para 2 line 1"

def test_code_parser():
    parser = CodeParser()
    content = '''"""Module Docstring"""\nimport os\n\nclass MyClass:\n    """Class Docstring"""\n    def method(self):\n        pass\n\ndef my_function():\n    pass\n'''
    sections = parser.parse(content, source_path="test.py")
    
    assert len(sections) == 3
    assert sections[0].heading == "module_header"
    assert sections[1].heading == "MyClass"
    assert sections[1].level == 1
    assert "MyClass" in sections[1].content
    assert sections[2].heading == "my_function"
    assert sections[2].level == 2

def test_document_parser_routing():
    doc_parser = DocumentParser()
    
    # Test Markdown raw routing
    raw_md = RawDocument(
        source_path="doc.md",
        source_type=SourceType.MARKDOWN,
        raw_content="# Title\nHello",
        file_size=15,
        metadata=DocumentMetadata(author="test_author")
    )
    parsed = doc_parser.parse(raw_md)
    
    assert parsed.title == "Title"
    assert len(parsed.sections) == 1
    assert parsed.metadata.author == "test_author"
    assert parsed.document_id.startswith("doc_doc_")
