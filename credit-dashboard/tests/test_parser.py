import csv
import copy
import io
import unittest

from parser import CsvFormatError, parse_csv_bytes
from academic_rules import load_rule_profile


HEADERS = ["No.", "分野", "水準", "開講番号", "科目", "科目区分", "必選区分", "単位数", "合否"]


def csv_bytes(rows: list[list[str]], encoding: str = "utf-8-sig") -> bytes:
    output = io.StringIO(newline="")
    csv.writer(output).writerows(rows)
    return output.getvalue().encode(encoding)


class ParserTests(unittest.TestCase):
    def test_category_totals_and_requested_classification(self):
        rows = [
            ["[学生氏名]", "架空学生", "[学年]", "2"],
            HEADERS,
            ["1", "10", "1", "L-1", "情報科目", "情報リテラシー／自然系共通専門基礎", "選択必修", "2", "合"],
            ["2", "20", "2", "S-1", "電磁気学", "専門基礎科目群（選択必修）", "選択必修", "2", "合"],
            ["3", "20", "2", "S-2", "データベース", "専門応用科目群（選択）", "選択", "1.5", ""],
        ]
        report = parse_csv_bytes(csv_bytes(rows, "cp932"))
        self.assertEqual((report["summary"]["course_count"], report["summary"]["earned_credits"]), (3, 4))
        self.assertEqual((report["summary"]["unconfirmed_count"], report["summary"]["unconfirmed_credits"]), (1, 1.5))
        self.assertEqual(
            {x["major"]: x["earned_credits"] for x in report["summary"]["majors"]},
            {"教養": 2, "専門": 2},
        )
        information = next(x for x in report["summary"]["categories"] if x["field"].startswith("情報リテラシー"))
        self.assertEqual((information["major"], information["earned_credits"]), ("教養", 2))
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["curriculum"]["admission_year"], 2025)

    def test_blank_units_and_failure_are_not_earned(self):
        rows = [
            ["[学生氏名]", "テスト学生", "[学年]", "2"], HEADERS,
            ["1", "41", "3", "A", "合格・単位未確定", "自然科学（理学）", "選択", "", "合"],
            ["2", "41", "3", "B", "不合格", "自然科学（工学）", "選択", "2", "否"],
            ["3", "10", "4", "C", "データベース", "専門応用科目群（選択）", "選択", "1.5", ""],
        ]
        report = parse_csv_bytes(csv_bytes(rows))
        self.assertEqual(report["student"]["name"], "テスト学生")
        self.assertEqual(report["student"]["grade"], "2")
        self.assertEqual(report["summary"]["earned_credits"], 0)
        self.assertEqual(report["summary"]["passed_count"], 0)
        self.assertEqual(report["summary"]["unconfirmed_count"], 2)
        self.assertEqual(report["summary"]["unknown_credit_count"], 1)
        self.assertEqual(report["summary"]["unconfirmed_credits"], 1.5)
        self.assertEqual(report["courses"][0]["credits"], None)
        self.assertEqual(report["courses"][0]["status"], "unconfirmed")
        self.assertEqual(report["courses"][1]["status"], "failed")
        self.assertEqual(report["courses"][2]["major"], "専門")

    def test_invalid_credits_explain_row(self):
        with self.assertRaisesRegex(CsvFormatError, "2行目: 単位数") as context:
            parse_csv_bytes(csv_bytes([HEADERS, ["1", "", "", "A", "科目", "英語", "選択", "abc", "合"]]))
        self.assertEqual(context.exception.code, "invalid_value")

    def test_course_row_count_is_not_fixed(self):
        courses = [
            [str(number), "10", "1", f"X-{number}", f"架空科目{number}", "英語（英語）", "選択", "1", "合"]
            for number in range(1, 81)
        ]
        report = parse_csv_bytes(csv_bytes([HEADERS, *courses]))
        self.assertEqual(report["summary"]["course_count"], 80)
        self.assertEqual(report["summary"]["earned_credits"], 80)

    def test_unknown_category_is_not_assumed_to_be_liberal_arts(self):
        report = parse_csv_bytes(csv_bytes([
            HEADERS,
            ["1", "", "", "X", "架空科目", "未定義区分", "選択", "2", "合"],
        ]))
        self.assertEqual(report["courses"][0]["major"], "不明")
        self.assertEqual(report["courses"][0]["curriculum_area"], "unknown")
        self.assertEqual(report["courses"][0]["classification_status"], "unknown")
        self.assertTrue(report["warnings"])

    def test_selected_profile_drives_curriculum_and_category_prefixes(self):
        profile = copy.deepcopy(load_rule_profile())
        profile["profile_id"] = "fictional-program-2030-v1"
        profile["scope"]["program"] = "架空情報プログラム"
        profile["scope"]["admission_year"] = 2030
        profile["classification"]["liberal_category_prefixes"] = ["架空教養"]
        profile["classification"]["faculty_specialized_prefixes"] = ["架空専門"]
        profile["classification"].pop("course_catalog_path")
        profile["classification"]["specialized_groups"] = [
            {"id": "foundation", "source_prefix": "架空専門基礎", "normalized_value": "specialized_foundation"}
        ]
        report = parse_csv_bytes(csv_bytes([
            HEADERS,
            ["1", "", "", "F-1", "架空科目", "架空専門基礎", "必修", "2", "合"],
        ]), profile=profile)
        self.assertEqual(report["curriculum"]["rules_version"], "fictional-program-2030-v1")
        self.assertEqual(report["curriculum"]["program"], "架空情報プログラム")
        self.assertEqual(report["courses"][0]["curriculum_area"], "faculty_specialized")
        self.assertEqual(report["courses"][0]["course_group"], "specialized_foundation")

    def test_course_name_keeps_source_and_adds_profile_normalized_value(self):
        report = parse_csv_bytes(csv_bytes([
            HEADERS,
            ["1", "10", "1", "X-1", "総合工学概論◆", "英語（英語）", "必修", "2", "合"],
            ["2", "10", "1", "X-2", "健康スポーツ科学実習 I", "健康・スポーツ（体育実技）", "必修", "1", "合"],
        ]))
        self.assertEqual(report["courses"][0]["name"], "総合工学概論◆")
        self.assertEqual(report["courses"][0]["normalized_name"], "総合工学概論")
        self.assertEqual(report["courses"][1]["normalized_name"], "健康スポーツ科学実習Ⅰ")


if __name__ == "__main__":
    unittest.main()
