"""推薦検索は架空のカタログと履修表だけで検証する。実カタログをfixtureにしない。"""
from copy import deepcopy
import json
import tempfile
import httpx2
import pytest
import server
from recommendations import (RecommendationError, catalog_metadata, find_catalog, load_catalogs,
                             recommend_for_slot, validate_catalog)
from server import app
from test_timetable_parser import csv_bytes, timetable
from timetable_parser import parse_timetable_csv_bytes

PROFILE = "niigata-engineering-sis-2025-v1"
CONTEXT = {"profile_id": PROFILE, "academic_year": 2026, "term": 3, "weekday": 2, "period": 1}

def course(code="263G9901", schedule=None):
    return {"course_code": code, "name": "架空の推薦候補", "credits": 2, "category": "自然科学（架空区分）",
            "terms": [int(code[2])], "schedule": schedule or [{"weekday": 2, "period": 1}]}

def catalog(courses=None):
    return {"schema_version": 3, "academic_year": 2026, "profile_id": PROFILE,
            "courses": courses if courses is not None else [course()]}

def parsed():
    return parse_timetable_csv_bytes(csv_bytes(timetable()))

def test_catalog_only_results_are_explicitly_unchecked_and_slot_specific():
    data = catalog([course(), course("264G9902")])
    result = recommend_for_slot(data, CONTEXT)
    assert result["basis"] == "catalog"
    assert result["status"] == "ok"
    assert result["checks"] == {"timetable": "not_provided", "earned_credits": "not_checked",
                                "requirements": "not_checked", "enrollment": "not_checked"}
    assert [item["course_code"] for item in result["candidates"]] == ["263G9901"]
    assert recommend_for_slot(data, {**CONTEXT, "weekday": 5})["status"] == "empty"

def test_all_meetings_are_checked_even_when_the_clicked_slot_is_free():
    conflicting = course("263G9902", [{"weekday": 2, "period": 1}, {"weekday": 1, "period": 2}])
    result = recommend_for_slot(catalog([course(), conflicting]), CONTEXT, parsed())
    assert [item["course_code"] for item in result["candidates"]] == ["263G9901"]
    assert result["counts"]["excluded_overlap"] == 1
    assert result["checks"]["timetable"] == "checked"

def test_another_term_does_not_block_a_course():
    data = parsed()
    data["busy_slots"] = [{"academic_year": 2026, "term": 4, "weekday": 2, "period": 1}]
    assert recommend_for_slot(catalog(), CONTEXT, data)["status"] == "ok"

def test_occupied_slot_has_a_distinct_status_and_no_candidates():
    data = catalog([course(schedule=[{"weekday": 1, "period": 1}])])
    result = recommend_for_slot(data, {**CONTEXT, "weekday": 1}, parsed())
    assert result["status"] == "occupied"
    assert result["candidates"] == []

@pytest.mark.parametrize("change", ["unresolved", "missing_term", "missing_period"])
def test_unconfirmed_timetable_does_not_become_a_free_slot(change):
    data = parsed()
    if change == "unresolved": data["ready_for_recommendation"] = False
    elif change == "missing_term": data["display_contexts"] = [{"academic_year": 2026, "term": 4}]
    else: data["represented_periods"] = [2, 7]
    result = recommend_for_slot(catalog(), CONTEXT, data)
    assert result["status"] == "unknown"
    assert result["candidates"] == []

def test_unrepresented_other_meeting_is_excluded_without_guessing():
    data = catalog([course(schedule=[{"weekday": 2, "period": 1}, {"weekday": 3, "period": 3}])])
    result = recommend_for_slot(data, CONTEXT, parsed())
    assert result["status"] == "unknown"
    assert result["counts"]["excluded_unconfirmed"] == 1

def test_registered_course_is_excluded():
    data = parsed()
    result = recommend_for_slot(catalog([course("263G9991")]), CONTEXT, data)
    assert result["counts"]["excluded_registered"] == 1

def test_loader_only_loads_public_compact_catalog_and_skips_archives(tmp_path):
    current = tmp_path / "2026/liberal-catalog.json"
    current.parent.mkdir()
    current.write_text(json.dumps(catalog()), encoding="utf-8")
    archived = tmp_path / "2026/archive/liberal-catalog.json"
    archived.parent.mkdir()
    archived.write_text('{"schema_version":1}', encoding="utf-8")
    loaded = load_catalogs(tmp_path)
    assert loaded == [catalog()]
    assert catalog_metadata(loaded[0])["course_count"] == 1
    assert find_catalog(loaded, CONTEXT) == catalog()
    with pytest.raises(RecommendationError) as error:
        find_catalog(loaded, {**CONTEXT, "academic_year": 2027})
    assert error.value.code == "recommendation_catalog_not_found"

@pytest.mark.parametrize("kind", ["old_schema", "bool_year", "wrong_year", "unknown_category", "term_zero", "bad_term", "nonfinite", "duplicate", "missing_slot"])
def test_invalid_catalog_is_rejected(kind):
    data = catalog()
    first = data["courses"][0]
    if kind == "old_schema": data["schema_version"] = 2
    elif kind == "bool_year": data["academic_year"] = True
    elif kind == "wrong_year": data["academic_year"] = 2027
    elif kind == "unknown_category": first["category"] = "未知の分類"
    elif kind == "term_zero": first["course_code"] = "260G9901"
    elif kind == "bad_term": first["terms"] = [4]
    elif kind == "nonfinite": first["credits"] = float("inf")
    elif kind == "duplicate": data["courses"].append(deepcopy(first))
    else: first["schedule"] = []
    with pytest.raises(ValueError): validate_catalog(data)

def test_loader_errors_do_not_echo_paths_or_invalid_contents(tmp_path):
    path = tmp_path / "liberal-catalog.json"
    path.write_text("fictional-sensitive-sentinel", encoding="utf-8")
    with pytest.raises(RecommendationError) as error:
        load_catalogs(tmp_path)
    assert "fictional-sensitive-sentinel" not in str(error.value)
    assert str(tmp_path) not in str(error.value)

def test_conflicting_grade_labels_do_not_change_candidate_search():
    rows = timetable()
    raw = csv_bytes(rows)
    assert "student_grade" not in parse_timetable_csv_bytes(raw)
    rows.insert(0, ["[学年]", "3年", "", "", "", "", ""])
    assert recommend_for_slot(catalog(), CONTEXT, parse_timetable_csv_bytes(csv_bytes(rows))) == recommend_for_slot(catalog(), CONTEXT, parse_timetable_csv_bytes(raw))

@pytest.mark.parametrize("value", ["1年", "2年", "3年", "4年", "不明な学年", "GRADE", "grade", "GRADE_YEAR", "学年", "", None])
def test_grade_value_does_not_change_candidates_or_block_search(value):
    rows = timetable()
    grade_row = next(row for row in rows if "[学年]" in row)
    grade_row[grade_row.index("[学年]") + 1] = value or ""
    if value is None:
        grade_row[grade_row.index("[学年]")] = ""
    data = parse_timetable_csv_bytes(csv_bytes(rows))
    result = recommend_for_slot(catalog(), CONTEXT, data)
    assert result["status"] == "ok"
    assert result["counts"]["returned"] == 1
    assert result == recommend_for_slot(catalog(), CONTEXT, parsed())
    assert "grade" not in result["checks"]

@pytest.mark.parametrize("case", ["year_missing", "year_mismatch"])
def test_grade_independent_search_still_requires_the_timetable_period(case):
    rows = timetable()
    grade_row = next(row for row in rows if "[学年]" in row)
    grade_row[grade_row.index("[学年]") + 1] = "GRADE"
    period_row = next(row for row in rows if "[年度・学期]" in row)
    period_row[period_row.index("[年度・学期]") + 1] = "第2学期" if case == "year_missing" else "2025年度 第2学期"
    result = recommend_for_slot(catalog(), CONTEXT, parse_timetable_csv_bytes(csv_bytes(rows)))
    assert result["status"] == "unknown"
    assert result["candidates"] == []

@pytest.mark.anyio
async def test_placeholder_grade_csv_returns_candidates_without_echoing_student_metadata(client, caplog):
    rows = timetable()
    grade_row = next(row for row in rows if "[学年]" in row)
    grade_row[grade_row.index("[学年]") + 1] = "GRADE"
    response = await client.post("/api/v1/recommendations", files=multipart(raw=csv_bytes(rows)))
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["counts"]["returned"] == 1
    assert "grade" not in response.json()["checks"]
    for value in ["架空 履修学生", "T00000000", "架空所属", "GRADE"]:
        assert value not in response.text
        assert value not in caplog.text

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(server, "_recommendation_catalogs", lambda: [catalog()])
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://testserver") as value:
        yield value

def multipart(context=None, raw=None):
    parts = [(key, (None, str(value))) for key, value in (context or CONTEXT).items()]
    if raw is not None: parts.append(("file", ("fictional-timetable.csv", raw, "text/csv")))
    return parts

@pytest.mark.anyio
async def test_metadata_and_catalog_only_api(client):
    metadata = await client.get("/api/v1/recommendation-catalogs")
    assert metadata.status_code == 200
    assert "grade" not in metadata.json()["catalogs"][0]
    assert "courses" not in metadata.json()["catalogs"][0]
    response = await client.post("/api/v1/recommendations", files=multipart())
    assert response.status_code == 200
    assert response.json()["basis"] == "catalog"
    assert response.json()["counts"]["returned"] == 1
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers

@pytest.mark.anyio
async def test_timetable_api_does_not_save_echo_or_log_student_data(client, monkeypatch, caplog):
    def forbidden(*args, **kwargs): raise AssertionError("一時ファイルは使用しない")
    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", forbidden)
    response = await client.post("/api/v1/recommendations", files=multipart(raw=csv_bytes(timetable())))
    assert response.status_code == 200
    assert response.json()["basis"] == "timetable"
    assert response.json()["counts"]["returned"] == 1
    for value in ["架空 履修学生", "T00000000", "架空所属", "架空科目甲", "架空教員"]:
        assert value not in response.text
        assert value not in caplog.text

@pytest.mark.anyio
@pytest.mark.parametrize("field,value", [("term", 5), ("weekday", 0), ("period", 6), ("academic_year", "NaN")])
async def test_invalid_or_inconsistent_context_has_readable_errors(client, field, value):
    response = await client.post("/api/v1/recommendations", files=multipart({**CONTEXT, field: value}))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_recommendation_context"

@pytest.mark.anyio
@pytest.mark.parametrize("grade", [1, 4, "GRADE"])
async def test_legacy_grade_form_field_is_ignored(client, grade):
    expected = await client.post("/api/v1/recommendations", files=multipart())
    actual = await client.post("/api/v1/recommendations", files=multipart({**CONTEXT, "grade": grade}))
    assert actual.status_code == 200
    assert actual.json() == expected.json()

@pytest.mark.anyio
async def test_requests_are_isolated_and_methods_are_versioned(client):
    first = await client.post("/api/v1/recommendations", files=multipart(raw=csv_bytes(timetable())))
    missing = await client.post("/api/v1/recommendations", files=multipart({**CONTEXT, "weekday": 5}))
    third = await client.post("/api/v1/recommendations", files=multipart())
    assert first.json()["basis"] == "timetable"
    assert missing.json()["candidates"] == []
    assert third.json()["basis"] == "catalog" and third.json()["counts"]["returned"] == 1
    assert (await client.get("/api/v1/recommendations")).status_code == 405
    assert (await client.post("/api/v1/recommendation-catalogs")).status_code == 405

@pytest.mark.anyio
async def test_malformed_csv_and_missing_catalog_are_explicit(client, monkeypatch):
    response = await client.post("/api/v1/recommendations", files=multipart(raw=b"not,a,timetable"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "missing_columns"
    monkeypatch.setattr(server, "_recommendation_catalogs", lambda: [])
    response = await client.post("/api/v1/recommendations", files=multipart())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "recommendation_catalog_not_found"
