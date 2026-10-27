"""架空CSVだけをメモリ上で加工し、稼働中のlocalhost APIを確認する。

実在する学生CSVを受け取る引数は設けない。CSVや応答本文は保存しない。
実行: .venv/bin/python scripts/check_localhost_uploads.py
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
HEADERS = [
    "No.", "分野", "水準", "開講番号", "科目", "担当教員 ",
    "科目区分", "必選区分", "単位数", "得点", "評語", "合否", "GP",
    "修得年度", "修得学期", "読替前科目", "読替後科目", "報告日", "試験種別",
]
P2 = "progression_year_2"
P4 = "progression_year_4"
GRAD = "graduation"


@dataclass
class Case:
    name: str
    raw: bytes
    expected: dict
    http_status: int = 200


def encode(rows: list[list[str]], encoding="cp932", ending="\r\n") -> bytes:
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator=ending).writerows(rows)
    return output.getvalue().encode(encoding)


def example_rows(filename: str, encoding: str) -> list[list[str]]:
    """既存の架空サンプルを前置き4行・19列へ揃える。"""
    raw = (ROOT / "examples" / filename).read_bytes()
    rows = list(csv.reader(io.StringIO(raw.decode(encoding), newline="")))
    index = next(i for i, row in enumerate(rows) if "No." in row)
    values = {}
    for row in rows[:index]:
        for i, cell in enumerate(row[:-1]):
            if cell in {"[学生氏名]", "[在籍番号]", "[学生所属]", "[学年]"}:
                values[cell] = row[i + 1]

    def pad(row):
        return row + [""] * (19 - len(row))

    result = [
        pad(["[学生氏名]", values["[学生氏名]"], "[在籍番号]", values["[在籍番号]"]]),
        pad(["[学生所属]", values["[学生所属]"], "[学年]", values["[学年]"]]),
        pad(["[年度・学期]", "2028年度 第2学期"]),
        [""] * 19,
        HEADERS.copy(),
    ]
    for row in rows[index + 1:]:
        record = dict(zip(rows[index], row))
        result.append([record.get(header, "") for header in HEADERS])
    return result


def change(rows, name, **fields):
    row = next(row for row in rows[5:] if row[HEADERS.index("科目")] == name)
    for header, value in fields.items():
        row[HEADERS.index(header)] = str(value)


def add_course(rows, name, category, credits):
    number = max(int(row[0]) for row in rows[5:]) + 1
    record = {
        "No.": str(number), "開講番号": f"VIRTUAL-{number}", "科目": name,
        "科目区分": category, "必選区分": "選択", "単位数": str(credits), "合否": "合",
    }
    rows.append([record.get(header, "") for header in HEADERS])


def build_cases() -> list[Case]:
    first = example_rows("first-year-sample.csv", "utf-8")
    graduate = example_rows("graduation-sample-original-format.csv", "cp932")
    cases = []

    def add(name, rows, requirements, earned=None, conditions=None, **extra):
        expected = {"requirements": requirements, **extra}
        if earned is not None:
            expected["earned_credits"] = earned
        if conditions:
            expected["conditions"] = conditions
        cases.append(Case(name, encode(rows), expected))

    add("year1_progression_32", first, {P2: "satisfied", GRAD: "not_satisfied"}, 34,
        {P2: {"total_credits": {"confirmed_credits": 32}}, GRAD: {
            "liberal_humanities_personalization_required_elective": {"confirmed_credits": 2},
            "liberal_natural_foundation": {"confirmed_credits": 13},
            "liberal_elective": {"confirmed_credits": 3},
        }})
    for amount, status in [(2, "not_satisfied"), (4, "satisfied")]:
        rows = copy.deepcopy(first)
        change(rows, "架空自由教養", 単位数=amount)
        add(f"year1_progression_{29 + amount}", rows, {P2: status, GRAD: "not_satisfied"},
            31 + amount, {P2: {"total_credits": {"confirmed_credits": 29 + amount}}})

    for grade, progression_status in [(2, "not_satisfied"), (3, "satisfied")]:
        rows = copy.deepcopy(graduate)
        rows[1][3] = f"{grade}年"
        add(f"year{grade}_requirements", rows, {P4: progression_status, GRAD: "not_satisfied"}, 124,
            {P4: {"minimum_residence": {"confirmed_years": grade}}}, residence_years=grade)

    add("year4_graduation_124", graduate, {GRAD: "satisfied"}, 124, {GRAD: {
        "individual_required_courses": {"satisfied_course_count": 16, "required_course_count": 16},
        "liberal_total": {"confirmed_credits": 36},
        "specialized_total": {"confirmed_credits": 88},
        "liberal_elective": {"confirmed_credits": 11},
        "cross_area_surplus": {"confirmed_credits": 6},
    }}, warning_count=0, condition_counts={GRAD: 20})
    for amount, status in [(1, "not_satisfied"), (3, "satisfied")]:
        rows = copy.deepcopy(graduate)
        change(rows, "職業指導（工）", 単位数=amount)
        add(f"graduation_{122 + amount}", rows, {GRAD: status}, 122 + amount, {GRAD: {
            "overall_total": {"confirmed_credits": 122 + amount},
            "individual_required_courses": {"status": "satisfied"},
        }})

    for name, fields, status, credits in [
        ("required_replaced_by_repeat", {"科目": "プログラミングＡⅠ"}, "not_satisfied", 124),
        ("required_failed", {"合否": "否"}, "not_satisfied", 122),
        ("required_result_pending", {"合否": ""}, "unknown", 122),
        ("required_credits_unknown", {"単位数": ""}, "unknown", 122),
    ]:
        rows = copy.deepcopy(graduate)
        change(rows, "プログラミングＡⅡ", **fields)
        add(name, rows, {GRAD: status}, credits, {GRAD: {
            "individual_required_courses": {"status": status, "satisfied_course_count": 15},
        }})

    rows = copy.deepcopy(graduate)
    rows[1][3] = ""
    add("grade_missing", rows, {P2: "unknown", P4: "unknown", GRAD: "unknown"}, 124,
        residence_years=None)

    rows = copy.deepcopy(graduate)
    change(rows, "架空個性化選択必修", 科目区分="人文社会・教育科学（人文社会）")
    add("humanities_instead_of_personalization", rows, {GRAD: "satisfied"}, 124, {GRAD: {
        "liberal_humanities_social_required": {"confirmed_credits": 6},
        "liberal_humanities_personalization_required_elective": {"confirmed_credits": 2},
        "liberal_elective": {"confirmed_credits": 11},
    }})
    rows = copy.deepcopy(graduate)
    change(rows, "架空自然系基礎", 科目区分="自然科学（工学）")
    add("natural_science_fills_required_elective", rows, {GRAD: "satisfied"}, 124, {GRAD: {
        "liberal_natural_foundation": {"confirmed_credits": 21},
        "liberal_elective": {"confirmed_credits": 11},
    }})
    rows = copy.deepcopy(graduate)
    change(rows, "架空自然系基礎", 単位数=6)
    add_course(rows, "架空情報選択", "情報リテラシー／自然系共通専門基礎（情報）", 4)
    add("information_foundation_science_combined", rows, {GRAD: "satisfied"}, 124, {GRAD: {
        "liberal_natural_foundation": {"confirmed_credits": 21},
        "liberal_elective": {"confirmed_credits": 11},
    }})
    rows = copy.deepcopy(graduate)
    change(rows, "架空自然系基礎", 単位数=8)
    change(rows, "架空自由教養", 科目区分="新潟大学個性化科目（自由主題）", 単位数=9)
    change(rows, "架空自然科学追加", 科目区分="新潟大学個性化科目（自由主題）")
    add("data_science_not_double_counted", rows, {GRAD: "not_satisfied"}, 124, {GRAD: {
        "liberal_information_literacy": {"status": "satisfied", "confirmed_credits": 2},
        "liberal_natural_foundation": {"status": "not_satisfied", "confirmed_credits": 8},
    }})

    rows = copy.deepcopy(graduate)
    for name in ("職業指導（工）", "創造プロジェクト基礎", "創造プロジェクトⅠ"):
        change(rows, name, 単位数=1)
    change(rows, "架空自由教養", 単位数=10)
    add("surplus_split_between_both_areas", rows, {GRAD: "satisfied"}, 124, {GRAD: {
        "cross_area_surplus": {"confirmed_credits": 6, "source_surplus_credits": {
            "specialized_total": 3, "liberal_total": 3,
        }},
    }})

    rows = copy.deepcopy(graduate)
    change(rows, "職業指導（工）", 科目区分="架空未定義区分")
    add("unknown_classification_affects_result", rows, {GRAD: "unknown"}, 124, warning_count=1,
        courses={"P4-S-34": {"major": "不明", "classification_status": "unknown"}})
    rows = copy.deepcopy(graduate)
    add_course(rows, "架空追加未分類科目", "架空未定義区分", 2)
    add("unknown_extra_does_not_cancel_satisfaction", rows, {GRAD: "satisfied"}, 126,
        warning_count=1)
    rows = copy.deepcopy(graduate)
    change(rows, "職業指導（工）", 科目="架空別プログラム専門科目")
    add("outside_catalog_goes_to_liberal_elective", rows, {GRAD: "satisfied"}, 124,
        {GRAD: {"specialized_total": {"confirmed_credits": 86},
                "liberal_total": {"confirmed_credits": 38}}}, warning_count=1,
        courses={"P4-S-34": {"major": "教養", "classification_reason_code": "outside_catalog_as_liberal"}})
    rows = copy.deepcopy(graduate)
    change(rows, "職業指導（工）", 科目="単位互換協定に基づき修得した他大学開設科目")
    add("recognized_external_credit_excluded", rows, {GRAD: "not_satisfied"}, 124,
        {GRAD: {"overall_total": {"confirmed_credits": 122}}}, warning_count=1,
        courses={"P4-S-34": {"major": "対象外", "curriculum_area": "excluded"}})

    for encoding, ending, name in [
        ("utf-8-sig", "\r\n", "utf8_bom_crlf"),
        ("utf-8", "\n", "utf8_without_bom_lf"),
    ]:
        cases.append(Case(name, encode(graduate, encoding, ending),
                          {"requirements": {GRAD: "satisfied"}, "earned_credits": 124}))
    rows = copy.deepcopy(graduate)
    rows[4:] = [list(reversed(row)) for row in rows[4:]]
    add("reordered_columns", rows, {GRAD: "satisfied"}, 124)
    rows = copy.deepcopy(graduate)
    for number in range(25):
        add_course(rows, f"架空追加教養{number + 1}", "自然科学（工学）", 1)
    add("more_than_80_course_rows", rows, {GRAD: "satisfied"}, 149, course_count=83)

    invalid = []
    invalid.append(("empty_csv", b"", 422, "invalid_csv"))
    rows = copy.deepcopy(graduate)
    result_index = HEADERS.index("合否")
    for row in rows[4:]:
        del row[result_index]
    invalid.append(("missing_required_column", encode(rows), 422, "missing_columns"))
    rows = copy.deepcopy(graduate)
    change(rows, "職業指導（工）", 単位数="not-a-number")
    invalid.append(("invalid_credits", encode(rows), 422, "invalid_value"))
    rows = copy.deepcopy(graduate)
    rows[6][0] = rows[5][0]
    invalid.append(("duplicate_course_number", encode(rows), 422, "invalid_csv"))
    invalid.append(("unsupported_encoding", b"\x81", 415, "unsupported_encoding"))
    invalid.append(("file_over_5_mib", b"x" * (5 * 1024 * 1024 + 1), 413, "file_too_large"))
    for name, raw, status, code in invalid:
        cases.append(Case(name, raw, {"error_code": code}, status))
    return cases


def public_result(report: dict) -> dict:
    """検証用の形にする。学生情報や科目名は結果ログへ出力しない。"""
    if "error" in report:
        return {"error_code": report["error"]["code"]}
    evaluations = report["evaluations"]
    return {
        "requirements": {item["requirement_id"]: item["status"] for item in evaluations},
        "condition_counts": {item["requirement_id"]: len(item["conditions"]) for item in evaluations},
        "conditions": {item["requirement_id"]: {
            condition["id"]: condition for condition in item["conditions"]
        } for item in evaluations},
        "earned_credits": report["summary"]["earned_credits"],
        "course_count": report["summary"]["course_count"],
        "residence_years": report["evaluation_context"]["residence_years"],
        "warning_count": len(report["warnings"]),
        "courses": {item["code"]: item for item in report["courses"]},
    }


def verify(actual, expected, path="response"):
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise AssertionError(f"{path}: 応答の型が異なります")
        for key, value in expected.items():
            if key not in actual:
                raise AssertionError(f"{path}.{key}: 必要な項目がありません")
            verify(actual[key], value, f"{path}.{key}")
    elif actual != expected:
        # 応答の値を例外へ含めず、差があった項目だけを報告する。
        raise AssertionError(f"{path}: 期待値と一致しません")


def check_case(case: Case, status: int, report: dict):
    if status != case.http_status:
        raise AssertionError(f"HTTPステータス: 期待{case.http_status} / 実際{status}")
    actual = public_result(report)
    verify(actual, case.expected)
    if status != 200:
        if not report["error"].get("message"):
            raise AssertionError("入力エラーの表示メッセージがありません")
        return
    if status == 200:
        # 対象要件が増減していないことも確認する（部分一致だけにしない）。
        verify(actual["requirements"], case.expected["requirements"])
        if set(actual["requirements"]) != set(case.expected["requirements"]):
            raise AssertionError("学年別の表示対象要件が一致しません")
        for evaluation in report["evaluations"]:
            if not evaluation.get("title") or not evaluation.get("description"):
                raise AssertionError("総合判定の画面表示用テキストがありません")
            for condition in evaluation["conditions"]:
                if condition["status"] not in {"satisfied", "not_satisfied", "unknown"}:
                    raise AssertionError("条件の画面表示用ステータスが不正です")
                if not condition.get("label") or not condition.get("description"):
                    raise AssertionError("条件の画面表示用テキストがありません")
            if evaluation["rule_status"] != "blocked" and all(
                condition["status"] == "satisfied" for condition in evaluation["conditions"]
            ) and evaluation["status"] != "satisfied":
                raise AssertionError("全条件充足なのに総合判定が充足になっていません")


def run(base_url: str) -> int:
    parsed = urlsplit(base_url)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise ValueError("送信先はローカルのHTTPルートURLだけを指定できます")
    base_url = base_url.rstrip("/")
    opener = build_opener(ProxyHandler({}))
    asset_checks = {}
    for url_path, local_file in [("/", "static/index.html"), ("/app.js", "static/app.js"),
                                 ("/navigation.js", "static/navigation.js"),
                                 ("/recommendation-api.js", "static/recommendation-api.js"),
                                 ("/recommendations.js", "static/recommendations.js"),
                                 ("/timetable.js", "static/timetable.js"),
                                 ("/styles.css", "static/styles.css")]:
        with opener.open(base_url + url_path, timeout=15) as response:
            served = response.read()
        asset_checks[local_file] = (
            hashlib.sha256(served).digest() == hashlib.sha256((ROOT / local_file).read_bytes()).digest()
        )
    if not all(asset_checks.values()):
        raise AssertionError("配信中の画面ファイルが作業中のコードと異なります。再ビルドを確認してください")
    print(json.dumps({"served_assets_match_workspace": asset_checks}, ensure_ascii=False), flush=True)

    failures = 0
    cases = build_cases()
    for case in cases:
        boundary = "credit-dashboard-check-" + uuid4().hex
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{case.name}.csv\"\r\nContent-Type: text/csv\r\n\r\n"
        ).encode("ascii") + case.raw + f"\r\n--{boundary}--\r\n".encode("ascii")
        request = Request(base_url + "/api/v1/reports", data=body,
                          headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            try:
                response = opener.open(request, timeout=15)
            except HTTPError as error:
                response = error
            with response:
                status = response.status
                report = json.loads(response.read())
            check_case(case, status, report)
            summary = public_result(report)
            print(json.dumps({"case": case.name, "passed": True, "http_status": status,
                              "display_statuses": summary.get("requirements"),
                              "error_code": summary.get("error_code")}, ensure_ascii=False), flush=True)
        except AssertionError as error:
            failures += 1
            print(json.dumps({"case": case.name, "passed": False, "check": str(error)},
                             ensure_ascii=False), flush=True)
        except Exception:
            failures += 1
            print(json.dumps({"case": case.name, "passed": False,
                              "check": "接続または応答の解析に失敗しました（本文は非表示）"},
                             ensure_ascii=False), flush=True)
    print(json.dumps({"total": len(cases), "passed": len(cases) - failures,
                      "failed": failures, "csv_saved": False}, ensure_ascii=False), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        sys.exit(run(args.base_url))
    except (ValueError, AssertionError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print("localhostに接続できません。アプリを起動し、接続権限を確認してください。", file=sys.stderr)
        sys.exit(1)
