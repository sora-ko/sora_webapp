import csv
import io
from pathlib import Path

import httpx2
import pytest

from server import app


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "examples" / "first-year-sample.csv"
GRADUATION_SAMPLE_PATH = SAMPLE_PATH.with_name("graduation-sample-original-format.csv")
SIMPLIFIED_GRADUATION_SAMPLE_PATH = SAMPLE_PATH.with_name("graduation-sample.csv")
ORIGINAL_HEADERS = [
    "No.", "分野", "水準", "開講番号", "科目", "担当教員 ",
    "科目区分", "必選区分", "単位数", "得点", "評語", "合否", "GP",
    "修得年度", "修得学期", "読替前科目", "読替後科目", "報告日", "試験種別",
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_graduation_sample_preserves_original_csv_format():
    raw = GRADUATION_SAMPLE_PATH.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    assert b"\r\n" in raw
    assert b"\r" not in raw.replace(b"\r\n", b"")
    assert b"\n" not in raw.replace(b"\r\n", b"")

    rows = list(csv.reader(io.StringIO(raw.decode("cp932"), newline="")))
    assert len(rows) > 5
    assert all(len(row) == 19 for row in rows)
    assert rows[0][:4] == ["[学生氏名]", "架空 卒業生", "[在籍番号]", "T00000000"]
    assert rows[1][:4] == [
        "[学生所属]", "工学部 工学科 知能情報システムプログラム", "[学年]", "4年",
    ]
    assert rows[2][:2] == ["[年度・学期]", "2028年度 第2学期"]
    assert not any(rows[0][4:] + rows[1][4:] + rows[2][2:])
    assert rows[3] == [""] * 19
    assert rows[4] == ORIGINAL_HEADERS
    assert rows[5][0] == "1"
    assert all(row[11] == "合" for row in rows[5:])


@pytest.mark.anyio
async def test_original_format_graduation_sample_is_satisfied_and_matches_simplified_sample():
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/reports",
            files={"file": (GRADUATION_SAMPLE_PATH.name, GRADUATION_SAMPLE_PATH.read_bytes(), "text/csv")},
        )
        simplified_response = await client.post(
            "/api/v1/reports",
            files={
                "file": (
                    SIMPLIFIED_GRADUATION_SAMPLE_PATH.name,
                    SIMPLIFIED_GRADUATION_SAMPLE_PATH.read_bytes(),
                    "text/csv",
                ),
            },
        )

    assert response.status_code == simplified_response.status_code == 200
    report = response.json()
    assert report["student"] == {
        "name": "架空 卒業生",
        "student_number": "T00000000",
        "affiliation": "工学部 工学科 知能情報システムプログラム",
        "grade": "4年",
    }
    assert report["summary"]["earned_credits"] == 124
    assert {
        item["major"]: item["earned_credits"] for item in report["summary"]["majors"]
    } == {"教養": 36, "専門": 88}
    assert [item["requirement_id"] for item in report["evaluations"]] == ["graduation"]
    graduation = report["evaluations"][0]
    assert graduation["status"] == "satisfied"
    assert all(item["status"] == "satisfied" for item in graduation["conditions"])
    checks = {item["id"]: item for item in graduation["conditions"]}
    assert checks["individual_required_courses"]["satisfied_course_count"] == 16
    assert checks["individual_required_courses"]["required_course_count"] == 16
    assert report["warnings"] == []
    assert report["courses"][0]["row_number"] == 6
    for key in ("summary", "evaluations", "evaluation_context"):
        assert report[key] == simplified_response.json()[key]


@pytest.mark.anyio
async def test_first_year_sample_remains_uploadable_with_documented_result():
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/reports",
            files={"file": (SAMPLE_PATH.name, SAMPLE_PATH.read_bytes(), "text/csv")},
        )

    assert response.status_code == 200
    report = response.json()

    assert report["student"] == {
        "name": "架空 一郎",
        "student_number": "T00000000",
        "affiliation": "工学部 工学科 知能情報システムプログラム",
        "grade": "1年",
    }
    graduation = report["evaluations"][1]
    graduation_conditions = {
        item["id"]: item
        for item in graduation["conditions"]
    }
    assert graduation_conditions[
        "liberal_humanities_personalization_required_elective"
    ]["confirmed_credits"] == 2
    assert graduation_conditions[
        "liberal_humanities_personalization_required_elective"
    ]["status"] == "satisfied"
    assert graduation_conditions["liberal_natural_foundation"]["confirmed_credits"] == 13
    assert graduation_conditions["liberal_elective"]["confirmed_credits"] == 3
    assert report["summary"]["earned_credits"] == 34
    assert report["warnings"] == []
    assert report["evaluation_context"] == {
        "residence_years": 1,
        "residence_years_source": "student_grade_assumption",
        "student_grade_year": 1,
        "displayed_requirement_ids": ["progression_year_2", "graduation"],
    }
    assert [item["requirement_id"] for item in report["evaluations"]] == [
        "progression_year_2",
        "graduation",
    ]
    progression = report["evaluations"][0]
    assert progression["status"] == "satisfied"
    assert {
        item["id"]: item["confirmed_credits"]
        for item in progression["conditions"]
        if "confirmed_credits" in item
    } == {
        "total_credits": 32,
        "designated_course_group": 4,
    }
