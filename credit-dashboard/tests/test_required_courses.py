"""個別必修を単位合計で代替しないことを、公開科目名と架空成績で検証する。"""

import copy
import json

import pytest

import academic_rules
from academic_rules import (
    RuleDataError, load_profile_course_catalog, load_rule_profile,
    validate_course_catalog, validate_rule_profile,
)
from requirement_evaluator import evaluate_graduation


def required_report():
    catalog = load_profile_course_catalog(load_rule_profile())
    return {"courses": [
        {
            "name": item["name"], "normalized_name": item["name"],
            "catalog_course_id": item["id"], "course_code": f"FAKE-{i}",
            "curriculum_area": item["curriculum_area"],
            "course_group": item["course_group"], "requirement_code": item["requirement_code"],
            "credits": item["credits"], "status": "passed",
        }
        for i, item in enumerate(catalog["courses"])
        if "graduation" in item["required_for"]
    ]}


def required_result(report, profile=None):
    return next(
        item for item in evaluate_graduation(report, profile=profile)["conditions"]
        if item["id"] == "individual_required_courses"
    )


def subject(report, name="プログラミングＡⅡ"):
    return next(item for item in report["courses"] if item["name"] == name)


def test_all_sixteen_required_courses_are_checked_with_sources():
    result = required_result(required_report())
    assert result["status"] == "satisfied"
    assert result["required_course_count"] == 16
    assert result["satisfied_course_count"] == 16
    assert result["missing_course_names"] == []
    assert result["unknown_course_names"] == []
    assert len(result["course_results"]) == 16
    assert all(item["source_refs"] and item["description"] for item in result["course_results"])


def test_repeated_required_course_cannot_replace_another_required_course():
    report = required_report()
    missing = subject(report)
    report["courses"].remove(missing)
    duplicate = {**subject(report, "プログラミングＡⅠ"), "course_code": "FAKE-RETAKE"}
    report["courses"].append(duplicate)
    graduation = evaluate_graduation(report)
    applied_a = next(item for item in graduation["conditions"] if item["id"] == "specialized_applied_a")
    result = next(item for item in graduation["conditions"] if item["id"] == "individual_required_courses")
    assert applied_a["confirmed_credits"] == 27
    assert applied_a["status"] == "satisfied"
    assert result["status"] == "not_satisfied"
    assert result["satisfied_course_count"] == 15
    assert result["missing_course_names"] == ["プログラミングＡⅡ"]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"status": "unconfirmed"}, "unknown"),
        ({"status": "passed", "credits": None}, "unknown"),
        ({"curriculum_area": "unknown", "requirement_code": None}, "unknown"),
        ({"status": "failed"}, "not_satisfied"),
        ({"credits": 0}, "not_satisfied"),
        ({"credits": 1}, "not_satisfied"),
        ({"curriculum_area": "liberal_arts"}, "not_satisfied"),
        ({"curriculum_area": "excluded"}, "not_satisfied"),
    ],
)
def test_missing_unconfirmed_and_excluded_required_courses_are_distinguished(changes, expected):
    report = required_report()
    subject(report).update(changes)
    result = required_result(report)
    assert result["status"] == expected
    row = next(item for item in result["course_results"] if item["name"] == "プログラミングＡⅡ")
    assert row["status"] == expected
    names = result["unknown_course_names"] if expected == "unknown" else result["missing_course_names"]
    assert names == ["プログラミングＡⅡ"]


def test_unknown_result_is_resolved_by_a_separate_valid_pass():
    report = required_report()
    uncertain = {**subject(report), "course_code": "FAKE-PENDING", "status": "unconfirmed"}
    report["courses"].append(uncertain)
    result = required_result(report)
    assert result["status"] == "satisfied"
    assert result["satisfied_course_count"] == 16


def test_two_partial_credit_rows_do_not_count_as_one_full_required_course():
    report = required_report()
    partial = subject(report)
    partial["credits"] = 1
    report["courses"].append({**partial, "course_code": "FAKE-PARTIAL-2"})
    assert required_result(report)["missing_course_names"] == ["プログラミングＡⅡ"]


def test_conflicting_opening_code_cannot_satisfy_two_required_courses():
    report = required_report()
    subject(report)["course_code"] = subject(report, "プログラミングＡⅠ")["course_code"]
    result = required_result(report)
    assert result["status"] == "unknown"
    assert set(result["unknown_course_names"]) == {"プログラミングＡⅠ", "プログラミングＡⅡ"}


def test_required_results_do_not_depend_on_course_order():
    report = required_report()
    original = required_result(report)
    report["courses"].reverse()
    assert required_result(report) == original


def test_width_and_roman_variants_use_the_same_required_course():
    report = required_report()
    item = subject(report)
    item["name"] = item["normalized_name"] = "プログラミング A II◆"
    assert required_result(report)["status"] == "satisfied"


def test_required_check_uses_selected_profile_catalog_not_fixed_course_names(tmp_path, monkeypatch):
    profile = copy.deepcopy(load_rule_profile())
    profile["profile_id"] = "fictional-required-profile"
    profile["classification"]["course_catalog_path"] = "required.json"
    catalog = load_profile_course_catalog(load_rule_profile())
    catalog["profile_id"] = profile["profile_id"]
    catalog["courses"] = [copy.deepcopy(catalog["courses"][0])]
    catalog["courses"][0]["name"] = "架空必修科目"
    (tmp_path / "required.json").write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(academic_rules, "RULES_ROOT", tmp_path)
    report = required_report_for_name("架空必修科目")
    result = required_result(report, profile)
    assert result["required_course_count"] == 1
    assert result["status"] == "satisfied"


def required_report_for_name(name):
    return {"courses": [{
        "name": name, "credits": 2, "status": "passed",
        "curriculum_area": "faculty_specialized", "requirement_code": "A",
    }]}


def test_required_check_cannot_be_configured_without_catalog():
    profile = copy.deepcopy(load_rule_profile())
    profile["classification"].pop("course_catalog_path")
    with pytest.raises(RuleDataError, match="科目マスター"):
        validate_rule_profile(profile)


def test_empty_required_list_cannot_be_accepted_as_satisfied():
    profile = load_rule_profile()
    catalog = load_profile_course_catalog(profile)
    for item in catalog["courses"]:
        item["required_for"] = []
    with pytest.raises(RuleDataError, match="一覧が空"):
        validate_course_catalog(catalog, profile)


@pytest.mark.parametrize("credits", [None, 0])
def test_required_catalog_entries_need_positive_known_credits(credits):
    profile = load_rule_profile()
    catalog = load_profile_course_catalog(profile)
    catalog["courses"][0]["credits"] = credits
    with pytest.raises(RuleDataError, match="必修科目"):
        validate_course_catalog(catalog, profile)
