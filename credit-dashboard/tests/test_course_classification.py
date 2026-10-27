"""公開科目マスターと架空CSVによるMVP分類方針の回帰テスト。"""

import copy
import csv
import io
import json

import pytest

import academic_rules
from academic_rules import (
    RuleDataError,
    load_profile_course_catalog,
    load_rule_profile,
    validate_course_catalog,
    validate_rule_profile,
)
from parser import parse_csv_bytes
from requirement_evaluator import evaluate_graduation, evaluate_second_year_progression


def parse_courses(*courses, profile=None):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["No.", "開講番号", "科目", "科目区分", "必選区分", "単位数", "合否"])
    for i, (name, category, requirement_type, credits) in enumerate(courses, 1):
        writer.writerow([i, f"FAKE-{i}", name, category, requirement_type, credits, "合"])
    return parse_csv_bytes(output.getvalue().encode("utf-8-sig"), profile=profile)


def conditions(result):
    return {item["id"]: item for item in result["conditions"]}


def test_sis_catalog_matches_independent_official_table_totals():
    catalog = load_profile_course_catalog(load_rule_profile())
    assert len(catalog["courses"]) == 83
    groups = {}
    for item in catalog["courses"]:
        key = (item["course_group"], item["requirement_code"])
        groups[key] = groups.get(key, 0) + (item["credits"] or 0)
        assert item["source_refs"]
    assert groups[("specialized_foundation", "B")] == 18
    assert groups[("specialized_applied", "A")] == 27
    assert groups[("specialized_applied", "B")] == 40
    assert groups[("specialized_applied", "C")] == 60
    assert len([item for item in catalog["courses"] if item["required_for"] == ["graduation"]]) == 16


@pytest.mark.parametrize("name", [
    "プログラミングＡⅠ", "プログラミングAI", "プログラミング A I◆",
])
def test_catalog_normalizes_width_roman_numerals_and_display_suffix(name):
    report = parse_courses((name, "専門基礎科目群（選択）", "選択", 2))
    item = report["courses"][0]
    assert item["name"] == name
    assert item["normalized_name"] == "プログラミングＡⅠ"
    assert item["curriculum_area"] == "faculty_specialized"
    assert (item["course_group"], item["requirement_code"]) == ("specialized_applied", "A")
    assert item["classification_reason_code"] == "selected_program_catalog"


def test_common_and_introductory_courses_are_specialized_not_outside_catalog():
    report = parse_courses(
        ("総合工学概論◆", "専門基礎科目群（必修）", "必修", 2),
        ("コンピュータ基礎", "専門応用科目群（選択必修）", "選択必修", 2),
        ("プログラミング基礎Ⅰ（情報電子分野）", "専門応用科目群（選択必修）", "選択必修", 2),
        ("物理工学Ⅱ", "専門基礎科目群（選択必修）", "選択必修", 2),
        ("インターンシップ", "専門応用科目群（選択）", "選択", 2),
    )
    assert [item["requirement_code"] for item in report["courses"]] == ["A", "B", "B", "B", "D"]
    assert all(item["catalog_course_id"] for item in report["courses"])
    assert report["warnings"] == []


def test_non_catalog_specialized_course_is_only_liberal_elective_and_summary_splits():
    report = parse_courses(
        ("電磁気学", "専門基礎科目群（選択必修）", "選択必修", 2),
        ("架空他分野専門科目", "専門基礎科目群（選択必修）", "選択必修", 2),
    )
    outside = report["courses"][1]
    assert outside["curriculum_area"] == "liberal_arts"
    assert outside["field"] == "対象専門科目一覧外"
    assert outside["requirement_code"] is None
    assert outside["course_group"] is None
    assert outside["classification_reason_code"] == "outside_catalog_as_liberal"
    assert len(report["summary"]["categories"]) == 2
    assert {item["major"]: item["earned_credits"] for item in report["summary"]["majors"]} == {"教養": 2, "専門": 2}
    graduation = conditions(evaluate_graduation(report))
    assert graduation["specialized_foundation_b"]["confirmed_credits"] == 2
    assert graduation["liberal_total"]["confirmed_credits"] == 2
    assert graduation["liberal_elective"]["confirmed_credits"] == 2
    assert graduation["liberal_natural_foundation"]["confirmed_credits"] == 0
    assert any("MVP方針" in message for message in report["warnings"])


def test_missing_metadata_never_becomes_other_program_liberal_course():
    report = parse_courses(("架空未知科目", "未知区分", "選択", 2))
    assert report["courses"][0]["curriculum_area"] == "unknown"


def test_known_liberal_category_is_not_overridden_by_catalog_name_collision():
    report = parse_courses(("電磁気学", "自然科学（理学）", "選択", 2))
    assert report["courses"][0]["curriculum_area"] == "liberal_arts"
    assert report["courses"][0]["field"] == "自然科学"


def test_known_other_university_label_is_visible_but_excluded_from_all_requirements():
    report = parse_courses(
        ("単位互換協定に基づき修得した他大学開設科目", "専門応用科目群（自由）", "自由", 40),
    )
    assert report["courses"][0]["curriculum_area"] == "excluded"
    assert report["summary"]["earned_credits"] == 40  # CSV上の取得と要件への算入は区別する。
    assert conditions(evaluate_second_year_progression(report))["total_credits"]["confirmed_credits"] == 0
    result = conditions(evaluate_graduation(report))
    assert result["overall_total"]["confirmed_credits"] == 0
    assert result["liberal_total"]["confirmed_credits"] == 0


def test_same_name_with_different_opening_codes_is_not_merged():
    report = parse_courses(
        ("総合工学概論", "専門応用科目群（必修）", "必修", 2),
        ("総合工学概論", "専門応用科目群（必修）", "必修", 2),
    )
    result = conditions(evaluate_second_year_progression(report))
    assert result["total_credits"]["confirmed_credits"] == 4
    assert result["designated_course_group"]["confirmed_credits"] == 4


def test_catalog_path_cannot_escape_rules():
    profile = copy.deepcopy(load_rule_profile())
    profile["classification"]["course_catalog_path"] = "../private.csv"
    with pytest.raises(RuleDataError, match="相対パス"):
        validate_rule_profile(profile)
    with pytest.raises(RuleDataError, match="rules配下"):
        load_profile_course_catalog(profile)


def test_catalog_alias_collisions_are_rejected():
    profile = load_rule_profile()
    catalog = load_profile_course_catalog(profile)
    catalog["courses"][1]["aliases"].append(catalog["courses"][0]["name"])
    with pytest.raises(RuleDataError, match="複数科目"):
        validate_course_catalog(catalog, profile)


@pytest.mark.parametrize("value", [[], [""], "工学リテラシー入門"])
def test_malformed_name_contains_selector_is_rejected(value):
    profile = copy.deepcopy(load_rule_profile())
    selector = next(
        item["selector"] for item in profile["requirements"]["graduation"]["conditions"]
        if item["id"] == "liberal_university_study"
    )
    selector["course_name_contains_any"] = value
    with pytest.raises(RuleDataError, match="course_name_contains_any"):
        validate_rule_profile(profile)


def test_other_department_profile_uses_its_own_catalog(tmp_path, monkeypatch):
    profile = copy.deepcopy(load_rule_profile())
    profile["profile_id"] = "fictional-faculty-2025"
    profile["scope"]["faculty"] = "架空学部"
    profile["classification"]["course_catalog_path"] = "fictional.json"
    catalog = load_profile_course_catalog(load_rule_profile())
    catalog["profile_id"] = profile["profile_id"]
    entry = copy.deepcopy(catalog["courses"][0])
    entry["name"], entry["aliases"] = "架空専門科目", []
    catalog["courses"] = [entry]
    (tmp_path / "fictional.json").write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(academic_rules, "RULES_ROOT", tmp_path)
    report = parse_courses(
        ("架空専門科目", "専門応用科目群（必修）", "必修", 2),
        ("プログラミングＡⅠ", "専門応用科目群（必修）", "必修", 2),
        profile=profile,
    )
    assert [item["major"] for item in report["courses"]] == ["専門", "教養"]
