import csv
import io
import tempfile
from pathlib import Path

import httpx2
import pytest

import server
from server import MAX_FILE_BYTES, app


HEADERS = ["No.", "分野", "水準", "開講番号", "科目", "科目区分", "必選区分", "単位数", "合否"]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


def csv_bytes(rows: list[list[str]], encoding: str = "utf-8-sig") -> bytes:
    output = io.StringIO(newline="")
    csv.writer(output).writerows(rows)
    return output.getvalue().encode(encoding)


def valid_csv(grade: str = "2") -> bytes:
    return csv_bytes([
        ["[学生氏名]", "架空学生", "[在籍番号]", "T00000000", "[学生所属]", "架空所属", "[学年]", grade],
        HEADERS,
        ["1", "10", "1", "X-1", "架空科目", "英語（英語）", "必修", "2", "合"],
        ["2", "20", "2", "X-2", "架空専門科目", "専門応用科目群（選択）", "選択", "2", ""],
    ], "cp932")


def progression_csv() -> bytes:
    return csv_bytes([
        ["[学生氏名]", "架空学生", "[在籍番号]", "T00000000", "[学生所属]", "知能情報システムプログラム", "[学年]", "1"],
        HEADERS,
        ["1", "10", "1", "P-1", "総合工学概論", "英語（英語）", "必修", "4", "合"],
        ["2", "20", "2", "P-2", "架空一般科目", "自然科学（工学）", "選択", "28", "合"],
    ], "cp932")


def graduation_surplus_csv() -> bytes:
    courses = [*fourth_year_specialized_courses(),
        ("卒業研修", 2), ("卒業研究", 6), ("電気数理Ⅱ", 2),
        ("機械学習", 2), ("信号処理", 2), ("情報理論", 2),
    ]
    rows = [
        ["[学生氏名]", "架空学生", "[在籍番号]", "T00000000", "[学生所属]", "知能情報システムプログラム", "[学年]", "4"],
        HEADERS,
    ]
    rows.extend([
        [str(i), "10", "4", f"G-{i}", name, "専門応用科目群（選択必修）", "選択必修", str(credits), "合"]
        for i, (name, credits) in enumerate(courses, 1)
    ])
    rows.append([str(len(courses) + 1), "20", "4", "G-LIB", "架空教養科目", "自然科学（工学）", "選択", "36", "合"])
    return csv_bytes(rows, "cp932")


def fourth_year_specialized_courses():
    """公式科目名・単位数に架空の合格結果を付ける（実学生の成績ではない）。"""
    foundation = ["応用数理Ｅ", "電気数理Ⅰ", "応用数理Ｂ", "電磁気学", "応用数理Ｃ"]
    applied_a = [
        ("総合工学概論", 2), ("総合技術科学演習", 2), ("技術者の心がまえ", 2),
        ("知的財産概論", 1), ("情報セキュリティ概論", 1), ("国際工学概論", 1),
        ("プログラミングＡⅠ", 2), ("プログラミングＡⅡ", 2), ("情報システム基礎実習", 1),
        ("知能情報システム実験Ⅰ", 1), ("知能情報システム実験Ⅱ", 1),
        ("知能情報システム実験Ⅲ", 1), ("知能情報システム実験Ⅳ", 1), ("研究室体験実習", 1),
    ]
    applied_b = [
        ("電子情報通信概論", 1), ("知能情報システム概論", 1), ("コンピュータ基礎", 2),
        ("プログラミング基礎Ⅰ", 2), ("プログラミング基礎Ⅱ", 2),
        *[(name, 2) for name in ["情報数学", "データ構造とアルゴリズム", "電気回路", "離散数学", "論理回路", "コンピュータネットワーク", "形式言語とオートマトン", "オペレーティングシステム", "コンピュータアーキテクチャ"]],
    ]
    applied_c = [
        *[(name, 2) for name in ["職業指導（工）", "創造プロジェクト基礎", "創造プロジェクトⅠ", "創造プロジェクトⅡ", "創造研究プロジェクトⅠ", "創造研究プロジェクトⅡ", "マーケット・インターンシップ", "テクノロジー・インターンシップ"]],
        ("国際工学事情", 1),
    ]
    return [*[(name, 2) for name in foundation], *applied_a, *applied_b, *applied_c]


def fourth_year_satisfied_csv() -> bytes:
    courses = [
        *[["10", "4", f"P4-S-{i}", name, "専門応用科目群（選択）", "選択", str(credits)]
          for i, (name, credits) in enumerate(fourth_year_specialized_courses(), 1)],
        ["20", "1", "P4-05", "工学リテラシー入門(架空分野)", "大学学習法（大学学習法）", "必修", "2"],
        ["20", "1", "P4-06", "架空英語", "英語（英語）", "選択必修", "2"],
        ["20", "1", "P4-07", "架空初修外国語", "初修外国語（ドイツ語）", "選択", "2"],
        ["20", "1", "P4-08", "健康スポーツ科学実習Ⅰ", "健康・スポーツ（体育実技）", "必修", "1"],
        ["20", "1", "P4-09", "エンジニアのためのデータサイエンス入門", "情報リテラシー／自然系共通専門基礎（情報）", "必修", "2"],
        ["20", "1", "P4-10", "架空人文社会必修", "人文社会・教育科学（人文社会）", "選択", "4"],
        ["20", "1", "P4-11", "架空個性化選択必修", "新潟大学個性化科目（自由主題）", "選択", "2"],
        ["20", "1", "P4-12", "架空自然系基礎", "自然系共通専門基礎（工学）", "選択", "10"],
        ["20", "1", "P4-13", "架空自由教養", "自然科学（工学）", "選択", "7"],
    ]
    rows = [
        ["[学生氏名]", "架空学生", "[在籍番号]", "T00000000", "[学生所属]", "知能情報システムプログラム", "[学年]", "3"],
        HEADERS,
    ]
    rows.extend([
        [str(index), field, level, code, name, category, requirement_type, credits, "合"]
        for index, (field, level, code, name, category, requirement_type, credits)
        in enumerate(courses, start=1)
    ])
    return csv_bytes(rows, "cp932")


def graduation_satisfied_csv() -> bytes:
    sample = Path(__file__).resolve().parents[1] / "examples" / "graduation-sample.csv"
    return sample.read_text(encoding="utf-8").encode("cp932")


@pytest.mark.anyio
async def test_upload_returns_versioned_report_without_logging_student_data(client, caplog):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("grades.csv", valid_csv(), "text/csv")},
    )
    assert response.status_code == 200
    report = response.json()
    assert report["schema_version"] == 2
    assert report["student"]["name"] == "架空学生"
    assert report["student"]["student_number"] == "T00000000"
    assert report["summary"]["earned_credits"] == 2
    assert report["summary"]["unconfirmed_credits"] == 2
    assert "架空学生" not in caplog.text
    assert "T00000000" not in caplog.text
    assert [item["requirement_id"] for item in report["evaluations"]] == [
        "progression_year_4",
        "graduation",
    ]
    assert report["evaluations"][0]["status"] == "not_satisfied"
    assert report["evaluations"][1]["status"] == "not_satisfied"


@pytest.mark.anyio
async def test_rule_profiles_are_listed_without_student_data(client):
    response = await client.get("/api/v1/rule-profiles")
    assert response.status_code == 200
    payload = response.json()
    assert payload["default_profile_id"] == "niigata-engineering-sis-2025-v1"
    assert payload["profiles"][0]["program"] == "知能情報システムプログラム"
    assert payload["profiles"][0]["implemented_requirement_ids"] == [
        "progression_year_2",
        "progression_year_4",
        "graduation",
    ]
    assert "student" not in payload["profiles"][0]
    assert any("MVP独自方針" in note for note in payload["profiles"][0]["policy_notes"])


@pytest.mark.anyio
async def test_profile_and_residence_context_are_applied_to_evaluation(client):
    response = await client.post(
        "/api/v1/reports",
        files=[
            ("profile_id", (None, "niigata-engineering-sis-2025-v1")),
            ("residence_years", (None, "1")),
            ("file", ("grades.csv", progression_csv(), "text/csv")),
        ],
    )
    assert response.status_code == 200
    report = response.json()
    assert report["evaluation_context"] == {
        "residence_years": 1,
        "residence_years_source": "user_input",
        "student_grade_year": 1,
        "displayed_requirement_ids": ["progression_year_2", "graduation"],
    }
    assert report["evaluations"][0]["status"] == "satisfied"
    assert all(item["description"] for item in report["evaluations"][0]["conditions"])


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("grade", "expected_ids"),
    [
        ("1", ["progression_year_2", "graduation"]),
        ("2", ["progression_year_4", "graduation"]),
        ("3", ["progression_year_4", "graduation"]),
        ("4", ["graduation"]),
    ],
)
async def test_requirements_are_selected_from_csv_grade(client, grade, expected_ids):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("grades.csv", valid_csv(grade), "text/csv")},
    )
    assert response.status_code == 200
    report = response.json()
    assert report["evaluation_context"]["student_grade_year"] == int(grade)
    assert report["evaluation_context"]["residence_years"] == int(grade)
    assert report["evaluation_context"]["residence_years_source"] == "student_grade_assumption"
    assert [item["requirement_id"] for item in report["evaluations"]] == expected_ids


@pytest.mark.anyio
async def test_second_year_progression_uses_grade_as_residence_when_not_overridden(client):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("grades.csv", progression_csv(), "text/csv")},
    )
    assert response.status_code == 200
    report = response.json()
    assert report["evaluation_context"]["residence_years"] == 1
    assert report["evaluation_context"]["residence_years_source"] == "student_grade_assumption"
    assert report["evaluations"][0]["requirement_id"] == "progression_year_2"
    assert report["evaluations"][0]["status"] == "satisfied"


@pytest.mark.anyio
async def test_missing_grade_keeps_residence_unknown_and_displays_all_requirements(client):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("grades.csv", valid_csv(""), "text/csv")},
    )
    assert response.status_code == 200
    report = response.json()
    assert report["evaluation_context"]["residence_years"] is None
    assert report["evaluation_context"]["residence_years_source"] == "unavailable"
    assert report["evaluation_context"]["displayed_requirement_ids"] == [
        "progression_year_2",
        "progression_year_4",
        "graduation",
    ]


@pytest.mark.anyio
async def test_graduation_shared_surplus_is_calculated_by_upload_api(client):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("grades.csv", graduation_surplus_csv(), "text/csv")},
    )
    assert response.status_code == 200
    report = response.json()
    graduation = report["evaluations"][0]
    surplus = next(
        item for item in graduation["conditions"]
        if item["id"] == "cross_area_surplus"
    )
    assert surplus["status"] == "satisfied"
    assert surplus["confirmed_credits"] == 6
    assert surplus["source_surplus_credits"] == {
        "specialized_total": 6,
        "liberal_total": 0,
    }
    assert "配賦順序が未確認" not in surplus["description"]


@pytest.mark.anyio
async def test_fourth_year_upload_is_satisfied_when_every_condition_is_satisfied(client):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("grades.csv", fourth_year_satisfied_csv(), "text/csv")},
    )
    assert response.status_code == 200
    report = response.json()
    progression = report["evaluations"][0]
    assert progression["requirement_id"] == "progression_year_4"
    assert progression["rule_status"] == "partial"
    assert all(item["status"] == "satisfied" for item in progression["conditions"])
    humanities_required_elective = next(
        item for item in progression["conditions"]
        if item["id"] == "liberal_humanities_personalization_required_elective"
    )
    assert humanities_required_elective["confirmed_credits"] == 2
    assert progression["status"] == "satisfied"
    assert report["warnings"] == []
    assert any("MVP独自方針" in note for note in report["curriculum"]["policy_notes"])


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("complete", "satisfied"),
        ("repeat_instead_of_required", "not_satisfied"),
        ("pending_result", "unknown"),
        ("missing_credits", "unknown"),
    ],
)
async def test_graduation_required_course_check_and_overall_result_through_upload(client, scenario, expected):
    rows = list(csv.reader(io.StringIO(graduation_satisfied_csv().decode("cp932"))))
    programming_ii = next(row for row in rows[2:] if row[4] == "プログラミングＡⅡ")
    if scenario == "repeat_instead_of_required":
        programming_ii[4] = "プログラミングＡⅠ"  # コードを変えず、別コードの同名科目を作る。
    elif scenario == "pending_result":
        programming_ii[8] = ""
    elif scenario == "missing_credits":
        programming_ii[7] = ""
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("fictional-graduation.csv", csv_bytes(rows, "cp932"), "text/csv")},
    )
    assert response.status_code == 200
    report = response.json()
    assert [item["requirement_id"] for item in report["evaluations"]] == ["graduation"]
    graduation = report["evaluations"][0]
    assert graduation["status"] == expected
    assert graduation["rule_status"] == "partial"
    checks = {item["id"]: item for item in graduation["conditions"]}
    required = checks["individual_required_courses"]
    assert required["status"] == expected
    assert required["required_course_count"] == 16
    assert required["satisfied_course_count"] == (16 if scenario == "complete" else 15)
    assert graduation["caveat_ids"] == []
    if scenario in {"complete", "repeat_instead_of_required"}:
        assert report["summary"]["earned_credits"] == 124
        assert checks["specialized_applied_a"]["confirmed_credits"] == 27
        assert all(item["status"] == "satisfied" for item in graduation["conditions"] if item is not required)
    if scenario == "repeat_instead_of_required":
        assert required["missing_course_names"] == ["プログラミングＡⅡ"]
    if expected == "unknown":
        assert required["unknown_course_names"] == ["プログラミングＡⅡ"]


@pytest.mark.anyio
async def test_unknown_profile_is_rejected(client):
    response = await client.post(
        "/api/v1/reports",
        files=[
            ("profile_id", (None, "unknown-profile")),
            ("file", ("grades.csv", valid_csv(), "text/csv")),
        ],
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_rule_profile"


@pytest.mark.anyio
@pytest.mark.parametrize("value", ["-1", "101", "1e999999999999999999999999"])
async def test_invalid_residence_context_is_rejected(client, value):
    response = await client.post(
        "/api/v1/reports",
        files=[
            ("residence_years", (None, value)),
            ("file", ("grades.csv", valid_csv(), "text/csv")),
        ],
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_evaluation_context"


@pytest.mark.anyio
async def test_upload_does_not_use_spooled_temporary_files(client, monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("一時ファイルを使用してはいけません")

    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", fail_if_called)
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("grades.csv", valid_csv(), "text/csv")},
    )
    assert response.status_code == 200


@pytest.mark.anyio
async def test_missing_file_has_machine_readable_error(client):
    response = await client.post("/api/v1/reports", files={"other": (None, "value")})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_file"


@pytest.mark.anyio
async def test_multiple_files_are_rejected(client):
    response = await client.post(
        "/api/v1/reports",
        files=[
            ("file", ("first.csv", valid_csv(), "text/csv")),
            ("file", ("second.csv", valid_csv(), "text/csv")),
        ],
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "multiple_files"


@pytest.mark.anyio
async def test_empty_file_is_rejected(client):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_csv"


@pytest.mark.anyio
async def test_file_larger_than_limit_is_rejected(client):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("large.csv", b"x" * (MAX_FILE_BYTES + 1), "text/csv")},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


@pytest.mark.anyio
async def test_unsupported_encoding_is_rejected(client):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("grades.csv", b"\x81", "text/csv")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_encoding"


@pytest.mark.anyio
async def test_missing_columns_is_rejected(client):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("grades.csv", csv_bytes([["別の列"], ["値"]]), "text/csv")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "missing_columns"


@pytest.mark.anyio
async def test_file_name_and_declared_mime_are_not_trusted(client):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("not-a-csv.exe", valid_csv(), "application/octet-stream")},
    )
    assert response.status_code == 200


@pytest.mark.anyio
async def test_non_multipart_request_is_rejected(client):
    response = await client.post(
        "/api/v1/reports",
        content=valid_csv(),
        headers={"content-type": "text/csv"},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


@pytest.mark.anyio
async def test_api_routing_errors_are_machine_readable(client):
    missing = await client.get("/api/v1/missing")
    wrong_method = await client.get("/api/v1/reports")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "route_not_found"
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["code"] == "method_not_allowed"


@pytest.mark.anyio
async def test_security_headers_and_health_check(client):
    response = await client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_upload_screen_uses_versioned_api_without_browser_persistence():
    html = Path("static/index.html").read_text(encoding="utf-8")
    script = Path("static/app.js").read_text(encoding="utf-8")
    assert any(getattr(route, "name", None) == "static" for route in app.routes)
    assert 'id="upload-form"' in html
    assert 'id="profile-select"' in html
    assert 'id="residence-years"' in html
    assert "/api/v1/reports" in script
    assert "/api/v1/rule-profiles" in script
    assert "/api/report" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script


@pytest.mark.anyio
async def test_reference_screen_serves_independent_timetable_assets_with_no_store(client):
    html = (await client.get("/")).text
    for name in ["workspace-state.js", "app.js", "navigation.js", "recommendation-api.js", "recommendations.js", "timetable.js", "recommendation-search.js"]:
        assert f'src="/{name}"' in html
        response = await client.get(f"/{name}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.text == Path("static", name).read_text(encoding="utf-8")
        for storage_api in ["localStorage", "sessionStorage", "indexedDB"]:
            assert storage_api not in response.text
    assert 'aria-controls="timetable-panel"' in html
    assert 'id="timetable-file"' in html
    assert 'id="timetable-term"' in html
    assert "/api/v1/timetables" in Path("static/timetable.js").read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_unexpected_error_is_sanitized(client, monkeypatch, caplog):
    def fail_safely(_raw):
        raise RuntimeError("sensitive sentinel must not be returned or logged")

    monkeypatch.setattr(server, "parse_csv_bytes", fail_safely)
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("grades.csv", valid_csv(), "text/csv")},
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "sensitive sentinel" not in response.text
    assert "sensitive sentinel" not in caplog.text


@pytest.mark.anyio
async def test_legacy_report_does_not_read_project_csv(client):
    response = await client.get("/api/report")
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "upload_required"
