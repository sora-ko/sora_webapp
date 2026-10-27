"""履修照会の時間割CSVをメモリ上で読み取る。ファイルI/Oやログ出力は行わない。"""

from __future__ import annotations

import csv
import io
import re
import unicodedata

from parser import CsvFormatError


DAY_NAMES = "月火水木金土日"
DAY_COLUMNS = {
    name + suffix: number
    for number, name in enumerate(DAY_NAMES, 1)
    for suffix in ("", "曜", "曜日")
}
OPENING_CODE = re.compile(r"[0-9]{3}[A-Z][0-9]{4}")
PERIOD = re.compile(r"(?:第)?([1-9][0-9]?)(?:時限|限)?")


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def parse_opening_code(value: str) -> dict:
    """利用者指定の20YY・ターム体系。0の除外は公式規則ではなくMVP方針。"""
    code = _normalized(value)
    if not OPENING_CODE.fullmatch(code) or code[2] not in "01234":
        raise CsvFormatError("開講番号の形式を解釈できません", code="invalid_value")
    term = int(code[2])
    return {
        "course_code": code,
        "academic_year": 2000 + int(code[:2]),
        "term": term or None,
        "excluded_by_term_zero_policy": term == 0,
    }


def _warning(warnings: list, code: str, row: int, message: str) -> None:
    warnings.append({"code": code, "row_number": row, "message": message})


def _context(rows: list[list[str]], warnings: list) -> dict:
    context = {"academic_year": None, "semester": None, "term": None}
    seen = False
    for row_number, row in enumerate(rows, 1):
        for index, cell in enumerate(row[:-1]):
            if _normalized(cell) != "[年度・学期]":
                continue
            value = _normalized(row[index + 1])
            year = re.search(r"(?<![0-9])(20[0-9]{2})\s*年度", value)
            semester = re.search(r"第?\s*([12])\s*学期", value)
            term = re.search(r"第?\s*([1-4])\s*ターム", value)
            candidate = {
                "academic_year": int(year[1]) if year else None,
                "semester": int(semester[1]) if semester else None,
                "term": int(term[1]) if term else None,
            }
            if seen and candidate != context:
                raise CsvFormatError("年度・学期の情報が重複し、一致しません", code="invalid_value")
            context, seen = candidate, True
            if value and (not year or not (semester or term)):
                _warning(warnings, "context_not_fully_readable", row_number,
                         "年度・学期の一部を読み取れません。対象年度・タームの確認が必要です。")
    return context


def parse_timetable_csv_bytes(raw: bytes) -> dict:
    """時間割の縦軸・横軸と開講番号だけを取得し、学生情報や授業名を返さない。"""
    if not raw:
        raise CsvFormatError("履修表CSVが空です")
    for encoding in ("utf-8-sig", "cp932"):
        try:
            content = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise CsvFormatError("文字コードを判定できません（UTF-8/CP932に対応）",
                             code="unsupported_encoding")
    if "\0" in content:
        raise CsvFormatError("履修表CSVに不正な文字が含まれています")
    try:
        rows = list(csv.reader(io.StringIO(content, newline=""), strict=True))
    except csv.Error as error:
        raise CsvFormatError("履修表CSVの構文が不正です") from error
    rows = [[_normalized(value) for value in row] for row in rows]
    header_index = next((i for i, row in enumerate(rows)
                         if sum(value in DAY_COLUMNS for value in row[1:]) >= 2), None)
    if header_index is None:
        raise CsvFormatError("曜日の見出しが見つかりません", code="missing_columns")
    header = rows[header_index]
    if any(value not in DAY_COLUMNS for value in header[1:]):
        raise CsvFormatError("曜日の見出しに未対応の列があります", code="missing_columns")
    weekdays = {column: DAY_COLUMNS[value] for column, value in enumerate(header[1:], 1)}
    if len(set(weekdays.values())) != len(weekdays):
        raise CsvFormatError("曜日の見出しが重複しています")

    warnings = []
    context = _context(rows[:header_index], warnings)
    blocks = []
    footer = []
    current = None
    footer_started = False
    periods = set()
    for row_number, cells in enumerate(rows[header_index + 1:], header_index + 2):
        if len(cells) > len(header) and any(cells[len(header):]):
            raise CsvFormatError(f"{row_number}行目: 見出しより多い列に値があります")
        cells = cells[:len(header)] + [""] * max(0, len(header) - len(cells))
        match = PERIOD.fullmatch(cells[0])
        if match:
            period = int(match[1])
            if footer_started or period in periods:
                raise CsvFormatError(f"{row_number}行目: 時限の配置が不正または重複しています")
            periods.add(period)
            current = {"period": period, "rows": []}
            blocks.append(current)
        elif cells[0]:
            footer_started = True
            current = None
        if current is not None:
            current["rows"].append((row_number, cells))
        elif any(cells):
            footer.append((row_number, cells))

    if not blocks:
        raise CsvFormatError("履修表に時限の行がありません", code="missing_columns")

    courses = {}
    excluded = set()
    unresolved = []
    busy = set()
    context_conflict = False

    def register(value, row_number, weekday=None, period=None):
        nonlocal context_conflict
        try:
            opening = parse_opening_code(value)
        except CsvFormatError as error:
            raise CsvFormatError(f"{row_number}行目: 開講番号の形式を解釈できません",
                                 code="invalid_value") from error
        code = opening["course_code"]
        if opening["excluded_by_term_zero_policy"]:
            excluded.add(code)
            return
        if weekday is None or period is None:
            unresolved.append({"course_code": code, "row_number": row_number,
                               "reason_code": "regular_course_outside_grid"})
            _warning(warnings, "regular_course_outside_grid", row_number,
                     "時間割外の通常科目に曜日・時限がありません。空き時間の判定を保留します。")
            return
        item = courses.setdefault(code, {
            "course_code": code, "academic_year": opening["academic_year"],
            "term": opening["term"], "slots": [],
        })
        slot = {"weekday": weekday, "period": period}
        if slot not in item["slots"]:
            item["slots"].append(slot)
        busy.add((opening["academic_year"], opening["term"], weekday, period))
        year_mismatch = context["academic_year"] is not None and context["academic_year"] != opening["academic_year"]
        term_mismatch = context["term"] is not None and context["term"] != opening["term"]
        semester_mismatch = context["semester"] is not None and (
            (opening["term"] - 1) // 2 + 1 != context["semester"]
        )
        if year_mismatch or term_mismatch or semester_mismatch:
            context_conflict = True
            _warning(warnings, "opening_context_mismatch", row_number,
                     "開講番号の年度・タームと履修表の年度・学期が一致しません。確認が必要です。")

    for block in blocks:
        body = block["rows"][:]
        while body and not any(body[-1][1][1:]):
            body.pop()
        # この出力形式では、1枠の科目を開講番号＋付随情報2行の計3行で表す。
        # 時限ごとの科目数・全体行数は固定せず、空欄の付随行は省略されても扱える。
        for offset in range(0, len(body), 3):
            group = body[offset:offset + 3]
            row_number, cells = group[0]
            for column, weekday in weekdays.items():
                value = cells[column]
                details = [row[column] for _, row in group[1:]]
                if any(OPENING_CODE.fullmatch(detail) for detail in details):
                    raise CsvFormatError(f"{row_number}行目: 科目ブロックの配置が未対応です")
                # この出力形式の「未登録」は空枠の表示。ただし付随情報があれば未解決にする。
                if value in {"", "未登録"}:
                    if any(details):
                        unresolved.append({"course_code": None, "row_number": row_number,
                                           "weekday": weekday, "period": block["period"],
                                           "reason_code": "missing_course_code"})
                        _warning(warnings, "missing_course_code", row_number,
                                 "科目情報に開講番号がありません。空き時間の判定を保留します。")
                    continue
                register(value, row_number, weekday, block["period"])

    for row_number, cells in footer:
        for value in cells[1:]:
            if OPENING_CODE.fullmatch(value):
                register(value, row_number)
            elif re.match(r"[0-9]{3}[A-Z]", value):
                raise CsvFormatError(f"{row_number}行目: 開講番号の形式を解釈できません",
                                     code="invalid_value")

    for item in courses.values():
        item["slots"].sort(key=lambda slot: (slot["weekday"], slot["period"]))
    display_contexts = {(item["academic_year"], item["term"]) for item in courses.values()}
    if context["academic_year"] is not None:
        if context["term"] is not None:
            display_contexts.add((context["academic_year"], context["term"]))
        elif context["semester"] is not None:
            first_term = 2 * context["semester"] - 1
            display_contexts.update((context["academic_year"], term)
                                    for term in (first_term, first_term + 1))
    result = {
        "schema_version": 1,
        "format": "niigata-rsrefer-grid",
        "context": context,
        "display_contexts": [{"academic_year": year, "term": term}
                             for year, term in sorted(display_contexts)],
        "represented_weekdays": sorted(weekdays.values()),
        "represented_periods": sorted(periods),
        "courses": sorted(courses.values(), key=lambda item: item["course_code"]),
        "busy_slots": [
            {"academic_year": year, "term": term, "weekday": day, "period": period}
            for year, term, day, period in sorted(busy)
        ],
        "excluded_term_zero_course_count": len(excluded),
        "policy_notes": ([
            "利用者指定のMVP方針で開講番号の3桁目が0の科目を除外しています。"
            "0には通常の曜限を持つ授業もあるため、除外した科目との時間重複は確認しません。"
        ] if excluded else []),
        "unresolved_courses": unresolved,
        "ready_for_recommendation": not unresolved and not context_conflict and not warnings,
        "warnings": warnings,
    }
    return result
