"""公開の開講一覧PDF専用アダプター。学生CSVの解析器から分離する。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import unicodedata


HEADERS = ["開講番号", "分野1", "分野2", "分野3", "水準", "科目名", "単位", "開講時期",
           "代表教員", "代表教員の所属", "定員", "主聴講対象学部等", "遠隔授業科目", "曜日", "時限", "授業形態"]
FIELD_NAMES = ["course_code", "discipline_1", "discipline_2", "discipline_3", "level", "name", "credits",
               "offered_period", "instructor", "instructor_affiliation", "capacity", "audience", "remote_type",
               "weekdays", "periods", "teaching_type"]
G_CODE = re.compile(r"[0-9]{3}G[0-9]{4}")


def compact(value: str | None) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or ""))


def extract_offering_rows(pdf_path: Path, source: dict, *, progress=None) -> tuple[list[dict], dict]:
    """罫線のセル単位で抽出し、本文中のG番号と独立照合して欠落を検出する。"""
    try:
        import pdfplumber
    except ImportError as error:
        raise RuntimeError("カタログ生成には requirements-catalog.txt の依存が必要です") from error
    records = []
    pages = []
    with pdfplumber.open(pdf_path) as document:
        if len(document.pages) != source["expected_pdf_pages"]:
            raise ValueError("公式PDFのページ数が変わっています。版と抽出範囲を再確認してください")
        first, last = source["main_table_pdf_pages"]
        for number in range(first, last + 1):
            page = document.pages[number - 1]
            page_records = []
            for table_index, table in enumerate(page.find_tables(), 1):
                rows = table.extract()
                if not rows or compact(rows[0][0]) != "開講番号":
                    continue
                if [compact(cell) for cell in rows[0]] != HEADERS:
                    raise ValueError(f"PDF{number}ページ: 表の見出しが対応形式と異なります")
                left, top, right, _ = table.bbox
                heading = page.crop((left, max(0, top - 30), right, top)).extract_text() or ""
                for row_index, row in enumerate(rows[1:], 2):
                    if not any(compact(value) for value in row):
                        continue
                    if len(row) != len(FIELD_NAMES):
                        raise ValueError(f"PDF{number}ページ: 列数が一致しません")
                    page_records.append({
                        "source": {"document_id": source["document_id"], "pdf_page": number,
                                   "printed_page": number + source["printed_page_offset"],
                                   "table_index": table_index, "table_row": row_index, "heading": heading},
                        "cells": dict(zip(FIELD_NAMES, (value or "" for value in row))),
                    })
            text_codes = Counter(G_CODE.findall(compact(page.extract_text())))
            table_codes = Counter(compact(item["cells"]["course_code"]) for item in page_records
                                  if G_CODE.fullmatch(compact(item["cells"]["course_code"])))
            pages.append({"pdf_page": number, "rows": len(page_records), "g_code_count": sum(table_codes.values()),
                          "coverage_matches": text_codes == table_codes,
                          "missing_codes": list((text_codes - table_codes).elements()),
                          "extra_codes": list((table_codes - text_codes).elements())})
            records.extend(page_records)
            page.close()
            if progress and (number % 10 == 0 or number == last):
                progress(number, last, len(records))
    return records, {"pdfplumber_version": pdfplumber.__version__, "pages": pages,
                     "coverage_matches": all(page["coverage_matches"] for page in pages),
                     "extracted_rows": len(records)}
