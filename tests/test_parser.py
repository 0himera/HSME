import os

from backend.services.document_parser import (
    CHUNK_VERSION,
    DocumentParser,
    assemble_chunks_from_blocks,
    format_table_rows,
    is_code_like,
    split_table_with_repeated_headers,
)


def test_is_code_like_detects_python_block():
    code = "import os\ndef main():\n    print('x')\n"
    assert is_code_like(code) is True


def test_is_code_like_keeps_technical_prose():
    text = "Плотность тока 300 А/м2 при pH = 2.0 и температуре 55°C."
    assert is_code_like(text) is False


def test_split_table_with_repeated_headers():
    header = [["Параметр", "Значение"]]
    body = [[f"row-{i}", str(i) * 80] for i in range(40)]
    parts = split_table_with_repeated_headers(header, body, soft_limit=400, hard_limit=800)
    assert len(parts) >= 2
    header_line = format_table_rows(header)
    for text, part_idx in parts:
        assert text.startswith(header_line)
        assert part_idx >= 1


def test_assemble_chunks_section_aware_and_skips_code():
    blocks = [
        {"type": "heading", "text": "1 Введение", "level": 1, "block_id": "h1"},
        {"type": "text", "text": "Описание процесса электроэкстракции никеля.", "block_id": "t1"},
        {"type": "heading", "text": "1.1 Условия", "level": 2, "block_id": "h2"},
        {
            "type": "code",
            "text": "import numpy as np\nx = np.array([1, 2, 3])\nprint(x)\n",
            "block_id": "c1",
        },
        {
            "type": "text",
            "text": "Рабочая плотность тока составляет 200-300 А/м2 в сульфатном электролите.",
            "block_id": "t2",
        },
    ]
    chunks = assemble_chunks_from_blocks(blocks)
    assert chunks
    assert all(c["chunk_version"] == CHUNK_VERSION for c in chunks)
    joined = "\n".join(c["text"] for c in chunks)
    assert "import numpy" not in joined
    assert any("1 Введение" in c["text"] or c["section"] == "1 Введение" for c in chunks)
    # Subsection chunk should carry parent path context.
    sub = [c for c in chunks if c["section"] == "1.1 Условия"]
    assert sub
    assert "1 Введение" in sub[0]["section_path"]
    assert "1 Введение" in sub[0]["text"]


def test_assemble_chunks_oversized_table_duplicates_header():
    header = ["Материал", "Извлечение"]
    rows = [header] + [[f"M{i}", f"{i}% " + ("x" * 60)] for i in range(50)]
    blocks = [{"type": "table", "rows": rows, "block_id": "tbl1"}]
    chunks = assemble_chunks_from_blocks(blocks, soft_limit=500, hard_limit=900)
    table_chunks = [c for c in chunks if c["content_type"] == "table"]
    assert len(table_chunks) >= 2
    header_line = "| Материал | Извлечение |"
    for c in table_chunks:
        assert header_line in c["text"]
        assert c["table_header"] is not None


def test_document_parser_docx():
    parser = DocumentParser()
    file_path = (
        "data/Задача 2. Научный клубок/Источники информации/Обзоры/"
        "Электроэкстракция никеля. Влияние состава электролита.docx"
    )
    if not os.path.exists(file_path):
        return

    result = parser.parse_file(file_path)
    assert result is not None
    assert result["format"] == "docx"
    assert result["chunk_version"] == CHUNK_VERSION
    assert "электроэкстракция никеля" in result["title"].lower()
    assert "ОИП-09-2023" in result["code"]
    assert result["year"] == 2023
    assert len(result["chunks"]) > 0
    first = result["chunks"][0]
    assert first["chunk_version"] == CHUNK_VERSION
    assert "content_type" in first
    assert "section_path" in first


def test_document_parser_pdf():
    parser = DocumentParser()
    file_path = (
        "data/Задача 2. Научный клубок/Источники информации/Обзоры/"
        "ТИ-5-2017. Кучное выщелачивание в условиях холодного климата.pdf"
    )
    if not os.path.exists(file_path):
        return

    result = parser.parse_file(file_path)
    assert result is not None
    assert result["format"] == "pdf"
    assert result["chunk_version"] == CHUNK_VERSION
    assert "ТИ-05-2017" in result["code"]
    assert result["year"] == 2017
    assert len(result["chunks"]) > 0
    assert all(c.get("chunk_version") == CHUNK_VERSION for c in result["chunks"])
