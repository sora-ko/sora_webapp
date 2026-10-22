"""大学の確定成績CSVを、画面やAPIで使えるデータに変換する。"""

from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation
from pathlib import Path

from classification import CURRICULUM_PROFILE, classify_category, classify_specialized


REQUIRED_COLUMNS = {"No.", "科目", "科目区分", "単位数", "合否"}
STUDENT_FIELDS = {
    "[学生氏名]": ("name", "NAME"),
    "[在籍番号]": ("student_number", "NUMBER"),
    "[学生所属]": ("affiliation", "BELONG"),
    "[学年]": ("grade", "GRADE"),
}


class CsvFormatError(ValueError):
    """CSVの形式や値を安全に解釈できないときに送出する。"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_csv",
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _number(value: str, row_number: int) -> Decimal | None:
    if not value.strip():
        return None
    try:
        number = Decimal(value.strip())
    except InvalidOperation as exc:
        raise CsvFormatError(
            f"{row_number}行目: 単位数が数値ではありません",
            code="invalid_value",
        ) from exc
    if not number.is_finite() or number < 0:
        raise CsvFormatError(
            f"{row_number}行目: 単位数が不正です",
            code="invalid_value",
        )
    return number


def _json_number(number: Decimal | None) -> int | float | None:
    if number is None:
        return None
    return int(number) if number == number.to_integral_value() else float(number)


def _student_info(preamble: list[list[str]]) -> dict[str, str | None]:
    student: dict[str, str | None] = {key: None for key, _ in STUDENT_FIELDS.values()}
    for row in preamble:
        for i, cell in enumerate(row[:-1]):
            field = STUDENT_FIELDS.get(cell.strip())
            if field:
                key, placeholder = field
                value = row[i + 1].strip()
                if value and value.upper() != placeholder:
                    student[key] = value
    return student


def parse_csv_bytes(raw: bytes) -> dict:
    """成績CSVのバイト列を読み込み、正規化・集計する。"""
    if not raw:
        raise CsvFormatError("CSVが空です")
    for encoding in ("utf-8-sig", "cp932"):
        try:
            content = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise CsvFormatError(
            "文字コードを判定できません（UTF-8/CP932に対応）",
            code="unsupported_encoding",
        )

    try:
        rows = list(csv.reader(io.StringIO(content, newline=""), strict=True))
    except csv.Error as exc:
        raise CsvFormatError("CSVの構文が不正です") from exc
    header_index = next(
        (
            i
            for i, row in enumerate(rows)
            if REQUIRED_COLUMNS.issubset({cell.strip() for cell in row})
        ),
        None,
    )
    if header_index is None:
        raise CsvFormatError(
            "科目表の見出し（No.、科目、科目区分、単位数、合否）がありません",
            code="missing_columns",
            details={"columns": sorted(REQUIRED_COLUMNS)},
        )
    headers = [cell.strip() for cell in rows[header_index]]
    if len(headers) != len(set(headers)):
        raise CsvFormatError("科目表の見出しに重複があります")

    courses = []
    warnings = []
    categories = {}
    majors = {
        name: {"major": name, "earned_credits": Decimal(0),
               "unconfirmed_credits": Decimal(0), "course_count": 0}
        for name in ("教養", "専門", "不明")
    }
    seen_numbers = set()
    earned = Decimal(0)
    unconfirmed = Decimal(0)
    passed_count = 0
    unconfirmed_count = 0
    unknown_credit_count = 0

    for row_number, cells in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any(cell.strip() for cell in cells):
            continue
        if len(cells) > len(headers) and any(cell.strip() for cell in cells[len(headers):]):
            raise CsvFormatError(f"{row_number}行目: 見出しより多い列に値があります")
        record = dict(zip(headers, cells + [""] * max(0, len(headers) - len(cells))))
        no = record.get("No.", "").strip()
        if not no.isdecimal():
            warnings.append(f"{row_number}行目: 科目番号がないため集計対象から除外しました")
            continue
        if no in seen_numbers:
            raise CsvFormatError(f"{row_number}行目: No. {no} が重複しています")
        seen_numbers.add(no)
        category = record["科目区分"].strip()
        if not category:
            raise CsvFormatError(f"{row_number}行目: 科目区分が空欄です")
        if not record["科目"].strip():
            raise CsvFormatError(f"{row_number}行目: 科目名が空欄です")
        credits = _number(record["単位数"], row_number)
        source_result = record["合否"].strip()
        status = (
            "passed"
            if source_result == "合" and credits is not None
            else "failed"
            if source_result == "否"
            else "unconfirmed"
        )
        if source_result not in ("", "合", "否"):
            warnings.append(f"{row_number}行目: 未知の合否を未確定として扱いました")
        major, field, detail, curriculum_area, classification_status = classify_category(category)
        requirement_type = record.get("必選区分", "").strip()
        course_group, requirement_code = classify_specialized(category, requirement_type)
        if classification_status == "unknown":
            warnings.append(f"{row_number}行目: 未知の科目区分のため分類できませんでした")
        course = {
            "no": int(no),
            "sequence": int(no),
            "row_number": row_number,
            "code": record.get("開講番号", "").strip() or None,
            "course_code": record.get("開講番号", "").strip() or None,
            "name": record["科目"].strip(),
            "source_category": category,
            "major": major,
            "curriculum_area": curriculum_area,
            "course_group": course_group,
            "requirement_code": requirement_code,
            "classification_status": classification_status,
            "field": field,
            "detail": detail,
            "requirement_type": requirement_type or None,
            "field_codes": [x.strip() for x in record.get("分野", "").split(",") if x.strip()],
            "level": record.get("水準", "").strip() or None,
            "credits": _json_number(credits),
            "status": status,
            "result": status,
            "source_result": source_result or None,
            "year": record.get("修得年度", "").strip() or None,
            "earned_year": record.get("修得年度", "").strip() or None,
            "term": record.get("修得学期", "").strip() or None,
            "earned_term": record.get("修得学期", "").strip() or None,
        }
        courses.append(course)

        bucket = categories.setdefault(category, {
            "source_category": category, "major": major, "field": field,
            "detail": detail, "earned_credits": Decimal(0),
            "unconfirmed_credits": Decimal(0), "course_count": 0,
            "passed_count": 0, "unconfirmed_count": 0,
        })
        bucket["course_count"] += 1
        majors[major]["course_count"] += 1
        if credits is None:
            unknown_credit_count += 1
            warning = f"{row_number}行目: 単位数が未確定です"
            if source_result == "合":
                warning += "（取得済みには含めません）"
            warnings.append(warning)
        if status == "passed":
            passed_count += 1
            bucket["passed_count"] += 1
            if credits is not None:
                earned += credits
                bucket["earned_credits"] += credits
                majors[major]["earned_credits"] += credits
        elif status == "unconfirmed":
            unconfirmed_count += 1
            bucket["unconfirmed_count"] += 1
            if credits is not None:
                unconfirmed += credits
                bucket["unconfirmed_credits"] += credits
                majors[major]["unconfirmed_credits"] += credits

    def public_bucket(bucket: dict) -> dict:
        return {
            k: _json_number(v) if isinstance(v, Decimal) else v
            for k, v in bucket.items()
        }

    return {
        "schema_version": 2,
        "curriculum": CURRICULUM_PROFILE.copy(),
        "student": _student_info(rows[:header_index]),
        "summary": {
            "course_count": len(courses),
            "passed_count": passed_count,
            "unconfirmed_count": unconfirmed_count,
            "unknown_credit_count": unknown_credit_count,
            "earned_credits": _json_number(earned),
            "unconfirmed_credits": _json_number(unconfirmed),
            "majors": [
                public_bucket(majors[k])
                for k in ("教養", "専門", "不明")
                if k != "不明" or majors[k]["course_count"]
            ],
            "categories": [public_bucket(v) for v in categories.values()],
        },
        "courses": courses,
        "warnings": warnings,
        "evaluations": [],
    }


def parse_csv(path: str | Path) -> dict:
    """パスで指定された成績CSVを読み込む互換用インターフェース。"""
    return parse_csv_bytes(Path(path).read_bytes())
