from backend.services.document_parser import slugify_filename
from backend.services.ingestion import make_experiment_id


def test_slugify_filename_cyrillic():
    slug = slugify_filename("Журнал Горный №1 2020.pdf")
    assert slug
    assert "ЖУРНАЛ" in slug or "2020" in slug
    assert slug == slugify_filename("Журнал Горный №1 2020.pdf")


def test_make_experiment_id_with_code():
    doc_meta = {"code": "CM-01-15", "filename": "CM_01_15.pdf", "file_slug": "CM-01-15"}
    assert make_experiment_id(doc_meta, 3) == "EXP-CM-01-15-03"


def test_make_experiment_id_without_code():
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
    assert id_a == "EXP-JOURNAL-A-00"
    assert id_b == "EXP-JOURNAL-B-00"


def test_two_journals_same_chunk_index_no_collision():
    journals = [
        {"code": "N/A", "filename": "Журнал 1.pdf", "file_slug": slugify_filename("Журнал 1.pdf")},
        {"code": "N/A", "filename": "Журнал 2.pdf", "file_slug": slugify_filename("Журнал 2.pdf")},
    ]
    ids = [make_experiment_id(meta, 0) for meta in journals]
    assert len(set(ids)) == 2
