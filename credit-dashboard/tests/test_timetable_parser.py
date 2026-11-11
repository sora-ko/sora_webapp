import csv
import io
import json
import tempfile
from unittest.mock import patch

import httpx2
import pytest

from parser import CsvFormatError
from server import app
from timetable_parser import _normalize_quoted_field_padding, parse_opening_code, parse_timetable_csv_bytes


def csv_bytes(rows, encoding="cp932", ending="\r\n"):
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator=ending).writerows(rows)
    return output.getvalue().encode(encoding)


def timetable(grade_info=True):
    rows = []
    if grade_info:
        rows.extend([
            ["[氏名]", "架空 履修学生", "", "", "[在籍番号]", "T00000000", ""],
            ["[所属]", "架空所属", "", "", "[学年]", "2年", ""],
            ["[年度・学期]", "2026年度 第2学期", "[期限]", "架空期限", "[件数]", "架空件数", ""],
            [""] * 7,
            ["", "", "", "[最終更新日時：架空日時]", "", "", ""],
            [""] * 7,
        ])
    rows.extend([
        ["", "月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日"],
        ["1限", "263G9991", "未登録", "", "263G9991", "", ""],
        ["", "架空科目甲", "", "", "架空科目甲", "", ""],
        ["", "架空教員", "", "", "架空教員", "", ""],
        ["", "264G9992", "", "", "", "", ""],
        ["", "架空科目乙", "", "", "", "", ""],
        ["", "架空教員", "", "", "", "", ""],
        ["2限", "263G9991", "", "", "", "", ""],
        ["", "架空科目甲", "", "", "", "", ""],
        ["", "架空教員", "", "", "", "", ""],
        ["7限", "", "", "", "", "", ""],
        [""] * 7,
        [""] * 7,
        [""] * 7,
        ["集中講義", "260T9999", "", "", "", "", ""],
        ["実習", "", "", "", "", "", ""],
        ["その他", "", "", "", "", "", ""],
    ])
    return rows


def course_row(rows):
    return next(row for row in rows if row[0] == "1限")


@pytest.mark.parametrize("encoding,ending", [
    ("cp932", "\r\n"), ("utf-8", "\n"), ("utf-8-sig", "\r\n"),
])
def test_grid_extracts_terms_days_and_variable_period_blocks(encoding, ending):
    report = parse_timetable_csv_bytes(csv_bytes(timetable(), encoding, ending))
    assert report["context"] == {"academic_year": 2026, "semester": 2, "term": None}
    assert report["courses"] == [
        {"course_code": "263G9991", "academic_year": 2026, "term": 3,
         "slots": [{"weekday": 1, "period": 1}, {"weekday": 1, "period": 2},
                   {"weekday": 4, "period": 1}]},
        {"course_code": "264G9992", "academic_year": 2026, "term": 4,
         "slots": [{"weekday": 1, "period": 1}]},
    ]
    assert len(report["busy_slots"]) == 4
    assert report["excluded_term_zero_course_count"] == 1
    assert report["policy_notes"]
    assert report["ready_for_recommendation"] is True
    assert report["warnings"] == []


def test_student_and_course_descriptions_are_not_returned_or_logged(caplog):
    report = parse_timetable_csv_bytes(csv_bytes(timetable()))
    serialized = json.dumps(report, ensure_ascii=False)
    for value in ["架空 履修学生", "T00000000", "架空所属", "架空科目甲", "架空教員", "架空日時"]:
        assert value not in serialized
        assert value not in caplog.text


@pytest.mark.parametrize("encoding", ["cp932", "utf-8-sig"])
@pytest.mark.parametrize("quoting", [csv.QUOTE_MINIMAL, csv.QUOTE_ALL])
@pytest.mark.parametrize("with_intensive", [False, True])
def test_fictional_identity_and_teacher_quotes_do_not_change_timetable(encoding, quoting, with_intensive):
    rows = timetable() if with_intensive else timetable()[:-3]
    expected = parse_timetable_csv_bytes(csv_bytes(rows, encoding))
    rows[0][1] = '架空,氏名 "仮名"\r\n架空の続き'
    rows[1][1] = '架空所属,架空学科 "架空プログラム"'
    for row in rows:
        row[:] = ['架空教員, "仮名"\n架空の続き' if value == '架空教員' else value for value in row]
    stream = io.StringIO(newline="")
    csv.writer(stream, quoting=quoting).writerows(rows)
    assert parse_timetable_csv_bytes(stream.getvalue().encode(encoding)) == expected


@pytest.mark.parametrize("padding", [" ", "\t", " \t "])
@pytest.mark.parametrize("encoding", ["cp932", "utf-8-sig"])
@pytest.mark.parametrize("with_intensive", [False, True])
@pytest.mark.parametrize("ending", ["\r\n", "\r", "mixed"], ids=["crlf", "cr", "mixed_newlines"])
def test_original_export_padding_after_quoted_fields_is_accepted(padding, encoding, with_intensive, ending):
    rows = timetable() if with_intensive else timetable()[:-3]
    rows[0][1] = '架空,氏名 "仮名"\r\n架空の続き'
    stream = io.StringIO(newline="")
    for index, row in enumerate(rows):
        terminator = "\r" if ending == "\r" or (ending == "mixed" and index % 2) else "\r\n"
        csv.writer(stream, quoting=csv.QUOTE_ALL, lineterminator=terminator).writerow(row)
    canonical = stream.getvalue()
    padded = canonical.replace('"1限",', '"1限"' + padding + ',', 1)
    padded = padded.replace('"[氏名]",', '"[氏名]"' + padding + ',', 1)
    padded = padded[:-len(terminator)] + padding + padded[-len(terminator):]
    assert parse_timetable_csv_bytes(padded.encode(encoding)) == parse_timetable_csv_bytes(canonical.encode(encoding))


@pytest.mark.parametrize("content", [
    '"  架空,セル内の空白  ","別の架空値"\r\n',
    '"架空の引用符"" ,\r\n 改行""  ","次"\r\n',
    '"架空""", "引用符が先頭にない値"\r\n',
])
def test_padding_normalization_preserves_quoted_contents(content):
    assert _normalize_quoted_field_padding(content) == content


@pytest.mark.parametrize("suffix", ['余分な文字', ' "余分な引用符"', '\t余分な文字'])
def test_padding_normalization_does_not_accept_nonpadding_after_quotes(suffix):
    raw = ('"[氏名]","FICTIONAL_DO_NOT_ECHO"' + suffix + '\r\n').encode()
    with pytest.raises(CsvFormatError) as error:
        parse_timetable_csv_bytes(raw)
    assert error.value.code == "invalid_csv"
    assert "FICTIONAL_DO_NOT_ECHO" not in str(error.value)


@pytest.mark.parametrize("raw,hint", [
    ('"[氏名]","FICTIONAL_DO_NOT_ECHO\r\n'.encode(), "閉じ"),
    ('"[氏名]","FICTIONAL_DO_NOT_ECHO"後続文字\r\n'.encode(), "引用符の直後"),
    (('[氏名],"' + 'X' * (csv.field_size_limit() + 1) + '"\r\n').encode(), "上限"),
], ids=["unclosed_quote", "characters_after_quote", "field_limit"])
def test_csv_syntax_errors_explain_location_and_kind_without_echoing_values(raw, hint, caplog):
    with pytest.raises(CsvFormatError) as error:
        parse_timetable_csv_bytes(raw)
    assert error.value.code == "invalid_csv"
    assert "1行目" in str(error.value)
    assert hint in str(error.value)
    assert "FICTIONAL_DO_NOT_ECHO" not in str(error.value)
    assert "FICTIONAL_DO_NOT_ECHO" not in caplog.text


@pytest.mark.parametrize("position", ["grid", "footer"])
def test_term_zero_is_excluded_from_occupied_times_even_inside_grid(position):
    rows = timetable()
    if position == "grid":
        course_row(rows)[2] = "260G9998"
    report = parse_timetable_csv_bytes(csv_bytes(rows))
    assert report["excluded_term_zero_course_count"] == (2 if position == "grid" else 1)
    assert all(item["course_code"][2] != "0" for item in report["courses"])
    assert all(slot["weekday"] != 2 for slot in report["busy_slots"])


def test_regular_course_in_footer_is_not_assigned_to_previous_period():
    rows = timetable()
    rows[-1][2] = "263G9997"
    report = parse_timetable_csv_bytes(csv_bytes(rows))
    assert report["unresolved_courses"][0]["reason_code"] == "regular_course_outside_grid"
    assert report["ready_for_recommendation"] is False
    assert all(slot["weekday"] != 2 for slot in report["busy_slots"])


def test_missing_code_is_unresolved_instead_of_free_time():
    rows = timetable()
    row_index = rows.index(course_row(rows))
    rows[row_index + 1][2] = "架空番号欠落科目"
    report = parse_timetable_csv_bytes(csv_bytes(rows))
    assert report["ready_for_recommendation"] is False
    assert report["unresolved_courses"][0]["reason_code"] == "missing_course_code"


@pytest.mark.parametrize("value", ["263G999X", "265G9991", "個人情報を含む不正な値"])
def test_invalid_code_error_does_not_echo_input(value):
    rows = timetable()
    course_row(rows)[1] = value
    with pytest.raises(CsvFormatError) as error:
        parse_timetable_csv_bytes(csv_bytes(rows))
    assert error.value.code == "invalid_value"
    assert value not in str(error.value)


def test_weekday_column_order_is_not_fixed():
    original = timetable(False)
    expected = parse_timetable_csv_bytes(csv_bytes(original))
    reordered = [row[:1] + list(reversed(row[1:])) for row in original]
    assert parse_timetable_csv_bytes(csv_bytes(reordered)) == expected


def test_fullwidth_numbers_and_codes_are_normalized():
    rows = timetable()
    first = course_row(rows)
    first[0] = "１限"
    first[1] = "２６３Ｇ９９９１"
    assert parse_timetable_csv_bytes(csv_bytes(rows))["ready_for_recommendation"] is True


@pytest.mark.parametrize("code", ["253G9991", "261G9991"])
def test_year_or_semester_mismatch_blocks_recommendation(code):
    rows = timetable()
    course_row(rows)[1] = code
    report = parse_timetable_csv_bytes(csv_bytes(rows))
    assert report["ready_for_recommendation"] is False
    assert any(item["code"] == "opening_context_mismatch" for item in report["warnings"])


def test_no_metadata_is_not_replaced_by_guessed_context():
    report = parse_timetable_csv_bytes(csv_bytes(timetable(False)))
    assert report["context"] == {"academic_year": None, "semester": None, "term": None}
    assert report["courses"][0]["academic_year"] == 2026


@pytest.mark.parametrize("period,expected", [
    ("2026年度 第1学期", [1, 2]),
    ("2026年度 第2学期", [3, 4]),
    ("2026年度 第3ターム", [3]),
])
def test_empty_timetable_still_has_display_contexts_from_explicit_metadata(period, expected):
    report = parse_timetable_csv_bytes(csv_bytes([
        ["[年度・学期]", period, ""],
        ["", "月曜日", "水曜日"],
        ["1限", "未登録", ""], ["", "", ""], ["", "", ""],
    ]))
    assert report["courses"] == []
    assert report["display_contexts"] == [{"academic_year": 2026, "term": term} for term in expected]


def test_without_metadata_display_contexts_only_include_observed_terms():
    rows = timetable(False)
    rows[4][1] = "263G9991"
    report = parse_timetable_csv_bytes(csv_bytes(rows))
    assert report["display_contexts"] == [{"academic_year": 2026, "term": 3}]


def test_without_metadata_or_courses_no_display_context_is_guessed():
    report = parse_timetable_csv_bytes(csv_bytes([
        ["", "月曜日", "水曜日"], ["1限", "", ""], ["", "", ""], ["", "", ""],
    ]))
    assert report["display_contexts"] == []


def test_conflicting_contexts_are_preserved_for_display_without_marking_them_safe():
    rows = timetable()
    course_row(rows)[1] = "253G9991"
    report = parse_timetable_csv_bytes(csv_bytes(rows))
    assert report["display_contexts"] == [
        {"academic_year": 2025, "term": 3},
        {"academic_year": 2026, "term": 3},
        {"academic_year": 2026, "term": 4},
    ]
    assert report["ready_for_recommendation"] is False


def test_duplicate_slots_are_deduplicated():
    rows = timetable(False)
    rows[4][1] = "263G9991"
    report = parse_timetable_csv_bytes(csv_bytes(rows))
    assert len(report["courses"]) == 1
    assert len(report["busy_slots"]) == 3


def test_more_rows_than_sample_are_read_to_end():
    rows = timetable(False)
    footer = next(i for i, row in enumerate(rows) if row[0] == "集中講義")
    rows[footer:footer] = [
        ["8限", "", "", "263G9996", "", "", ""],
        ["", "", "", "架空追加科目", "", "", ""],
        ["", "", "", "架空教員", "", "", ""],
    ]
    report = parse_timetable_csv_bytes(csv_bytes(rows))
    assert any(slot["weekday"] == 3 and slot["period"] == 8 for slot in report["busy_slots"])


@pytest.mark.parametrize("rows", [
    [["曜日なし", "値"]],
    [["", "月曜日", "月曜日"]],
    [["", "月曜日", "火曜日", "未知の列"]],
])
def test_invalid_weekday_header_is_rejected(rows):
    with pytest.raises(CsvFormatError):
        parse_timetable_csv_bytes(csv_bytes(rows))


def test_nonempty_extra_column_is_rejected():
    rows = timetable(False)
    rows[1].append("架空の余分な値")
    with pytest.raises(CsvFormatError):
        parse_timetable_csv_bytes(csv_bytes(rows))


def test_duplicate_period_is_rejected():
    rows = timetable(False)
    next(row for row in rows if row[0] == "2限")[0] = "1限"
    with pytest.raises(CsvFormatError):
        parse_timetable_csv_bytes(csv_bytes(rows))


@pytest.mark.parametrize("raw", [b"", b"\x81", b"\0"])
def test_empty_unsupported_or_null_content_is_rejected(raw):
    with pytest.raises(CsvFormatError):
        parse_timetable_csv_bytes(raw)


def test_parser_does_not_use_file_io():
    raw = csv_bytes(timetable())
    with patch("builtins.open", side_effect=AssertionError("ファイルI/Oは禁止")):
        assert parse_timetable_csv_bytes(raw)["ready_for_recommendation"] is True


def test_opening_code_rule_is_explicit():
    assert parse_opening_code("263G9991") == {
        "course_code": "263G9991", "academic_year": 2026, "term": 3,
        "excluded_by_term_zero_policy": False,
    }
    assert parse_opening_code("260G9991")["excluded_by_term_zero_policy"] is True


def test_unknown_empty_marker_is_not_silently_treated_as_free():
    rows = timetable()
    course_row(rows)[2] = "空き"
    with pytest.raises(CsvFormatError):
        parse_timetable_csv_bytes(csv_bytes(rows))


def test_header_without_period_axes_is_not_a_confirmed_empty_timetable():
    with pytest.raises(CsvFormatError) as error:
        parse_timetable_csv_bytes(csv_bytes([["", "月曜日", "火曜日"]]))
    assert error.value.code == "missing_columns"


def test_axes_without_courses_are_explicit_empty_slots_with_limited_coverage():
    report = parse_timetable_csv_bytes(csv_bytes([
        ["", "月曜日", "水曜日"], ["1限", "未登録", ""], ["", "", ""], ["", "", ""],
    ]))
    assert report["courses"] == []
    assert report["busy_slots"] == []
    assert report["represented_weekdays"] == [1, 3]
    assert report["represented_periods"] == [1]


def test_code_on_wrong_attribute_row_is_rejected_instead_of_moving_it_to_a_slot():
    rows = timetable()
    first_index = rows.index(course_row(rows))
    rows[first_index + 1][2] = "263G9995"
    with pytest.raises(CsvFormatError):
        parse_timetable_csv_bytes(csv_bytes(rows))


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_timetable_upload_api_returns_slots_without_student_data_or_temporary_files(caplog, monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("一時ファイルを使用してはいけません")

    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", fail_if_called)
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/v1/timetables", files={
            "file": ("fictional-timetable.csv", csv_bytes(timetable()), "text/csv"),
        })
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["ready_for_recommendation"] is True
    assert response.json()["excluded_term_zero_course_count"] == 1
    for value in ["架空 履修学生", "T00000000", "架空所属", "架空科目甲", "架空教員"]:
        assert value not in response.text
        assert value not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("use_session", [False, True], ids=["stateless", "session"])
async def test_fictional_quoted_timetable_and_syntax_errors_through_both_apis(use_session, monkeypatch, caplog):
    from session_store import SessionStore

    store = SessionStore()
    monkeypatch.setattr(app.state, "session_store", store)
    rows = timetable()
    marker = '架空,秘密にしない仮名 "引用符"\r\nFICTIONAL_DO_NOT_ECHO'
    rows[0][1] = marker
    rows[1][1] = '架空,所属 "仮学科"'
    for row in rows:
        row[:] = [marker if value == '架空教員' else value for value in row]
    stream = io.StringIO(newline="")
    csv.writer(stream, quoting=csv.QUOTE_ALL).writerows(rows)
    original_format = stream.getvalue().replace('"1限",', '"1限" ,', 1).encode("cp932")
    path = "/api/v1/session/timetables" if use_session else "/api/v1/timetables"
    headers = {"X-Session-Request": "1"} if use_session else {}
    try:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                      base_url="https://timetable.test", headers=headers) as client:
            mutation = {}
            if use_session:
                created = await client.post("/api/v1/session")
                assert created.status_code == 200
                mutation = {"X-CSRF-Token": created.json()["csrf_token"], "X-Session-Revision": "0"}
            response = await client.post(path, headers=mutation, files={
                "file": ("fictional-timetable.csv", original_format, "text/csv"),
            })
            assert response.status_code == 200
            parsed = response.json()["timetable"] if use_session else response.json()
            assert parsed["ready_for_recommendation"] is True
            assert parsed["excluded_term_zero_course_count"] == 1
            if use_session:
                mutation["X-Session-Revision"] = str(response.json()["revision"])
            bad = '"[氏名]","FICTIONAL_DO_NOT_ECHO"余分な文字\r\n'.encode()
            rejected = await client.post(path, headers=mutation, files={
                "file": ("fictional-invalid.csv", bad, "text/csv"),
            })
            assert rejected.status_code == 422
            assert rejected.json()["error"]["code"] == "invalid_csv"
            assert "1行目" in rejected.json()["error"]["message"]
            assert "引用符の直後" in rejected.json()["error"]["message"]
            assert rejected.headers["cache-control"] == "no-store"
            for body in [response.text, rejected.text, caplog.text]:
                assert "FICTIONAL_DO_NOT_ECHO" not in body
            if use_session:
                restored = await client.get("/api/v1/session/workspace")
                assert restored.json()["timetable"] is None
    finally:
        store.clear()


@pytest.mark.anyio
@pytest.mark.parametrize("raw,status,code", [
    (b"\x81", 415, "unsupported_encoding"),
    (b"not,a,timetable\r\n", 422, "missing_columns"),
])
async def test_timetable_upload_api_errors_are_versioned_and_readable(raw, status, code):
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/v1/timetables", files={"file": ("fictional.csv", raw, "text/csv")})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"]


@pytest.mark.anyio
async def test_timetable_upload_api_requires_file():
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/v1/timetables", files={"other": (None, "fictional")})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_file"


@pytest.mark.anyio
async def test_timetable_upload_api_rejects_wrong_method():
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/v1/timetables")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
