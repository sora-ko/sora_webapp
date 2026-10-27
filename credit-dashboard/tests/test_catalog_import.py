"""PDF依存は遅延読込し、架空の罫線セルだけで抽出の完全性を検証する。"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from catalog_import import FIELD_NAMES, HEADERS, extract_offering_rows


def fake_document(monkeypatch, *, text="263G9991", header=None, missing=False):
    values = {"course_code": "263G9991", "name": "架空科目", "credits": "2"}
    row = [values.get(field, "") for field in FIELD_NAMES]
    class Page:
        def find_tables(self):
            return [] if missing else [SimpleNamespace(extract=lambda: [header or HEADERS, row], bbox=(0, 50, 100, 100))]

        def crop(self, _bbox):
            return SimpleNamespace(extract_text=lambda: "自然科学（細区分：架空区分）")

        def extract_text(self):
            return text

        def close(self):
            pass

    class Document:
        pages = [Page()]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setitem(__import__("sys").modules, "pdfplumber",
                        SimpleNamespace(__version__="fictional", open=lambda path: Document()))
    return {"expected_pdf_pages": 1, "main_table_pdf_pages": [1, 1], "printed_page_offset": 0,
            "document_id": "fictional-source"}


def test_pdf_cell_extraction_keeps_source_and_independently_matches_text(monkeypatch):
    config = fake_document(monkeypatch)
    records, audit = extract_offering_rows(Path("fictional-not-read.pdf"), config)
    assert len(records) == 1
    assert records[0]["cells"]["name"] == "架空科目"
    assert records[0]["source"]["pdf_page"] == 1
    assert records[0]["source"]["table_row"] == 2
    assert audit["coverage_matches"] is True


def test_pdf_text_code_missing_from_table_is_not_silently_ignored(monkeypatch):
    config = fake_document(monkeypatch, text="263G9991 263G9992")
    _, audit = extract_offering_rows(Path("fictional-not-read.pdf"), config)
    assert audit["coverage_matches"] is False
    assert audit["pages"][0]["missing_codes"] == ["263G9992"]


def test_unrecognized_table_with_codes_fails_coverage_instead_of_becoming_empty_catalog(monkeypatch):
    config = fake_document(monkeypatch, missing=True)
    records, audit = extract_offering_rows(Path("fictional-not-read.pdf"), config)
    assert records == []
    assert audit["coverage_matches"] is False


def test_changed_table_header_requires_review(monkeypatch):
    config = fake_document(monkeypatch, header=HEADERS[:4] + ["未知の列"] + HEADERS[5:])
    with pytest.raises(ValueError, match="見出し"):
        extract_offering_rows(Path("fictional-not-read.pdf"), config)


def test_changed_pdf_version_does_not_reuse_old_page_mapping(monkeypatch):
    config = fake_document(monkeypatch)
    config["expected_pdf_pages"] = 2
    with pytest.raises(ValueError, match="ページ数"):
        extract_offering_rows(Path("fictional-not-read.pdf"), config)
