import os
from backend.document_parser import DocumentParser

def test_document_parser_docx():
    parser = DocumentParser()
    file_path = "data/Задача 2. Научный клубок/Источники информации/Обзоры/Электроэкстракция никеля. Влияние состава электролита.docx"
    
    assert os.path.exists(file_path), f"Test file not found at {file_path}"
    
    result = parser.parse_file(file_path)
    assert result is not None
    assert result["format"] == "docx"
    assert "электроэкстракция никеля" in result["title"].lower()
    assert "ОИП-09-2023" in result["code"]
    assert result["year"] == 2023
    assert len(result["chunks"]) > 0
    
    # Check chunks contents
    first_chunk = result["chunks"][0]["text"]
    assert len(first_chunk) > 0
    print(f"\n[Test DOCX] Title: {result['title']}")
    print(f"[Test DOCX] Code: {result['code']}, Year: {result['year']}")
    print(f"[Test DOCX] Authors: {result['authors']}")
    print(f"[Test DOCX] Chunks parsed: {len(result['chunks'])}")

def test_document_parser_pdf():
    parser = DocumentParser()
    file_path = "data/Задача 2. Научный клубок/Источники информации/Обзоры/ТИ-5-2017. Кучное выщелачивание в условиях холодного климата.pdf"
    
    assert os.path.exists(file_path), f"Test file not found at {file_path}"
    
    result = parser.parse_file(file_path)
    assert result is not None
    assert result["format"] == "pdf"
    assert "ТИ-05-2017" in result["code"]
    assert result["year"] == 2017
    assert len(result["chunks"]) > 0
    print(f"\n[Test PDF] Title: {result['title']}")
    print(f"[Test PDF] Code: {result['code']}, Year: {result['year']}")
    print(f"[Test PDF] Chunks parsed: {len(result['chunks'])}")

if __name__ == "__main__":
    test_document_parser_docx()
    test_document_parser_pdf()
