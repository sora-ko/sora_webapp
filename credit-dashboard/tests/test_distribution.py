"""クローンへ配布するファイルの範囲と、確認用データの非個人性を検証する。"""

import csv
import json
from pathlib import Path
import shutil
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED_FILES = (
    "data/recommendations/2026/liberal-catalog.json",
    "data/recommendations/2026/README.md",
    "examples/first-year-sample.csv",
    "examples/graduation-sample.csv",
    "examples/graduation-sample-original-format.csv",
)


def test_shared_catalog_contains_only_public_course_fields():
    catalog = json.loads((PROJECT_ROOT / SHARED_FILES[0]).read_text(encoding="utf-8"))
    if set(catalog) != {"schema_version", "academic_year", "profile_id", "courses"}:
        pytest.fail("配布カタログの項目を確認してください。", pytrace=False)
    if not catalog["courses"]:
        pytest.fail("初回起動用の公開科目データが必要です。", pytrace=False)
    for course in catalog["courses"]:
        if set(course) != {"course_code", "name", "credits", "category", "terms", "schedule"}:
            pytest.fail("配布カタログに教員・学生情報などの項目を追加しないでください。", pytrace=False)
        if any(set(slot) != {"weekday", "period"} for slot in course["schedule"]):
            pytest.fail("公開時間割には曜日・時限だけを含めてください。", pytrace=False)


@pytest.mark.parametrize("relative_path", SHARED_FILES[2:])
def test_shared_csv_uses_explicitly_fictional_student_and_teacher(relative_path):
    encoding = "cp932" if "original-format" in relative_path else "utf-8-sig"
    with (PROJECT_ROOT / relative_path).open(encoding=encoding, newline="") as source:
        rows = list(csv.reader(source))
    metadata = {
        cell: row[index + 1].strip()
        for row in rows
        for index, cell in enumerate(row[:-1])
        if cell in {"[学生氏名]", "[在籍番号]"}
    }
    if "架空" not in metadata.get("[学生氏名]", "") or metadata.get("[在籍番号]") != "T00000000":
        pytest.fail("配布CSVは架空の氏名と確認用の在籍番号を使用してください。", pytrace=False)
    for index, row in enumerate(rows):
        teacher_columns = [column for column, cell in enumerate(row) if "教員" in cell and "架空" not in cell]
        if not teacher_columns:
            continue
        for course in rows[index + 1:]:
            for column in teacher_columns:
                teacher = course[column].strip() if len(course) > column else ""
                if teacher and "架空" not in teacher:
                    pytest.fail("配布CSVの教員欄には架空の値だけを使用してください。", pytrace=False)
        break


def test_gitignore_shares_only_reviewed_data_and_synthetic_samples():
    if not shutil.which("git"):
        pytest.skip("Gitを使える環境で除外規則を検証する。")
    repository = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=False,
    )
    if repository.returncode != 0:
        pytest.skip("Git作業コピーで除外規則を検証する。")
    private_files = (
        "data/student.csv",
        "data/student.json",
        "student.csv",
        "student.CSV",
        "examples/student.csv",
        "examples/nested/student.csv",
        "data/recommendations/2026/student.json",
        "data/recommendations/2026/raw-rows.json",
        "data/recommendations/2026/extraction-audit.json",
        "data/recommendations/2026/sources/course-offerings.pdf",
        "data/recommendations/2026/archive/liberal-catalog.json",
        "data/recommendations/2027/liberal-catalog.json",
        "handoff/credit-dashboard-handoff-2026-10-27.zip",
    )
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        input="\n".join((*SHARED_FILES, *private_files)) + "\n",
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
    )
    assert set(result.stdout.splitlines()) == set(private_files)
    assert all((PROJECT_ROOT / path).is_file() for path in SHARED_FILES)
