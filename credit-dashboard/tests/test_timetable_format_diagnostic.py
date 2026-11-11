"""構造診断がセル値を出力せず、形式差を検出できることを架空値だけで確認する。"""

import csv
import importlib.util
import io
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "timetable_format_diagnostic", Path(__file__).resolve().parents[1] / "scripts" / "check_timetable_format.py"
)
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


def fictional_csv(*, delimiter=",", encoding="utf-8"):
    stream = io.StringIO(newline="")
    csv.writer(stream, delimiter=delimiter, quoting=csv.QUOTE_ALL).writerows([
        ["[氏名]", '架空 PRIVATE_VALUE_DO_NOT_PRINT, "仮名"\r\n架空の続き'],
        ["", "月曜日", "火曜日"],
        ["1限", "263T9999", ""],
    ])
    return stream.getvalue().encode(encoding)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp932", "utf-16"])
def test_reports_structural_counts_without_decoding_or_parsing_values(encoding, monkeypatch):
    def forbid_csv_reader(*args, **kwargs):
        raise AssertionError("構造診断で元セルをCSV解析してはいけません")

    monkeypatch.setattr(csv, "reader", forbid_csv_reader)
    result = diagnostic.diagnose(fictional_csv(encoding=encoding))
    assert result["input_status"] == "structure_examined"
    assert result["values_decoded"] is False
    assert result["cell_values_parsed"] is False
    assert result["readers"]["comma_strict"]["readable"] is True
    assert result["readers"]["comma_strict"]["records_read"] == 3
    text = json.dumps(result, ensure_ascii=False)
    for value in ["PRIVATE_VALUE_DO_NOT_PRINT", "架空", "氏名", "263T9999"]:
        assert value not in text


@pytest.mark.parametrize("delimiter,reader", [("\t", "tab_strict"), (";", "semicolon_strict")])
def test_distinguishes_delimiters_without_normalizing_the_source(delimiter, reader):
    raw = fictional_csv(delimiter=delimiter)
    original = bytes(raw)
    result = diagnostic.diagnose(raw)
    assert raw == original
    assert result["readers"]["comma_strict"]["readable"] is False
    assert result["readers"][reader]["readable"] is True
    assert result["readers"][reader]["max_columns"] == 3


def test_reports_quote_error_position_and_scans_outside_quote_padding():
    raw = '"[氏名]","架空 PRIVATE_VALUE_DO_NOT_PRINT" ,""\r\n'.encode()
    result = diagnostic.diagnose(raw)
    assert result["readers"]["comma_strict"]["error_kind"] == "characters_after_quote"
    assert result["readers"]["comma_strict"]["physical_error_line"] == 1
    assert result["readers"]["comma_with_quote_padding"]["readable"] is True
    assert result["readers"]["comma_with_quote_padding"]["padding_regions"] == 1
    assert "PRIVATE_VALUE_DO_NOT_PRINT" not in json.dumps(result)


def test_does_not_treat_nonpadding_after_quote_as_export_padding():
    result = diagnostic.diagnose(b'"fictional" invalid\r\n')
    assert result["readers"]["comma_with_quote_padding"]["readable"] is False
    assert result["readers"]["comma_with_quote_padding"]["error_kind"] == "characters_after_quote"


def test_empty_or_too_large_input_is_not_parsed():
    assert diagnostic.diagnose(b"")["input_status"] == "empty"
    result = diagnostic.diagnose(b"X" * (diagnostic.MAX_BYTES + 1))
    assert result["input_status"] == "too_large"
    assert result["readers"] == {}
