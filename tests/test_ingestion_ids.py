from backend.services.document_parser import CHUNK_VERSION, slugify_filename
from backend.services.ingestion import make_experiment_id, resolve_chunk_version


def test_slugify_filename_cyrillic():
    slug = slugify_filename("Журнал Горный №1 2020.pdf")
    assert slug
    assert "ЖУРНАЛ" in slug or "2020" in slug
    assert slug == slugify_filename("Журнал Горный №1 2020.pdf")


def test_make_experiment_id_with_code_versioned():
    doc_meta = {"code": "CM-01-15", "filename": "CM_01_15.pdf", "file_slug": "CM-01-15"}
    assert make_experiment_id(doc_meta, 3) == f"EXP-CM-01-15-{CHUNK_VERSION}-03"


def test_make_experiment_id_without_code_versioned():
    doc_a = {
        "code": "N/A",
        "filename": "journal_a.pdf",
        "file_slug": "JOURNAL-A",
    }
    doc_b = {
        "code": "N/A",
        "filename": "journal_b.pdf",
        "file_slug": "JOURNAL-B",
    }
    id_a = make_experiment_id(doc_a, 0)
    id_b = make_experiment_id(doc_b, 0)
    assert id_a != id_b
    assert id_a == f"EXP-JOURNAL-A-{CHUNK_VERSION}-00"
    assert id_b == f"EXP-JOURNAL-B-{CHUNK_VERSION}-00"


def test_make_experiment_id_uses_chunk_version_override():
    doc_meta = {"code": "CM-01-15", "filename": "CM_01_15.pdf"}
    chunk = {"index": 1, "chunk_version": "cn_v2"}
    assert make_experiment_id(doc_meta, 1, chunk) == "EXP-CM-01-15-cn_v2-01"


def test_resolve_chunk_version_defaults():
    assert resolve_chunk_version() == CHUNK_VERSION
    assert resolve_chunk_version({"chunk_version": "cn_v9"}) == "cn_v9"


def test_two_journals_same_chunk_index_no_collision():
    journals = [
        {"code": "N/A", "filename": "Журнал 1.pdf", "file_slug": slugify_filename("Журнал 1.pdf")},
        {"code": "N/A", "filename": "Журнал 2.pdf", "file_slug": slugify_filename("Журнал 2.pdf")},
    ]
    ids = [make_experiment_id(meta, 0) for meta in journals]
    assert len(set(ids)) == 2
