import copy
import json
from pathlib import Path

import pytest

from academic_rules import (
    RuleDataError,
    RuleProfileNotFoundError,
    discover_rule_profiles,
    load_rule_profile,
    load_rule_profile_by_id,
    public_rule_profile,
    validate_course_catalog,
    validate_rule_profile,
)
from classification import CURRICULUM_PROFILE, REQUIREMENT_TYPE_CODES, normalize_course_name


def condition_by_id(profile, requirement_id, condition_id):
    return next(
        condition
        for condition in profile["requirements"][requirement_id]["conditions"]
        if condition["id"] == condition_id
    )


def test_default_profile_is_discoverable_and_drives_classification():
    profile = load_rule_profile()
    discovered = discover_rule_profiles()
    assert [item["profile_id"] for item in discovered] == [profile["profile_id"]]
    assert CURRICULUM_PROFILE["rules_version"] == profile["profile_id"]
    assert CURRICULUM_PROFILE["admission_year"] == 2025
    assert REQUIREMENT_TYPE_CODES == {"必修": "A", "選択必修": "B", "選択": "C", "特殊選択": "D", "自由": "E"}


def test_profile_can_be_selected_by_stable_id():
    profile = load_rule_profile()
    selected = load_rule_profile_by_id(profile["profile_id"])
    assert selected["scope"] == profile["scope"]
    public = public_rule_profile(selected)
    assert public["profile_id"] == profile["profile_id"]
    assert {item["requirement_id"] for item in public["requirements"]} == {
        "progression_year_2",
        "progression_year_4",
        "graduation",
    }


def test_unknown_profile_id_is_rejected_without_path_lookup():
    with pytest.raises(RuleProfileNotFoundError, match="未対応"):
        load_rule_profile_by_id("../../student-data")


def test_json_schema_files_and_profile_schema_reference_are_valid_json():
    profile_path = Path("rules/niigata/engineering/smart-information-systems/2025/profile.json")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    referenced_schema = (profile_path.parent / profile["$schema"]).resolve()
    assert referenced_schema == Path("rules/profile.schema.json").resolve()
    assert json.loads(referenced_schema.read_text(encoding="utf-8"))["$schema"].endswith("2020-12/schema")
    assert json.loads(Path("rules/course-catalog.schema.json").read_text(encoding="utf-8"))["type"] == "object"


def test_transcribed_credit_boundaries_are_present():
    profile = load_rule_profile()
    assert profile["requirements"]["progression_year_4"]["status"] == "partial"
    assert profile["requirements"]["graduation"]["status"] == "partial"
    assert condition_by_id(profile, "progression_year_2", "total_credits")["minimum"] == 32
    assert condition_by_id(profile, "progression_year_2", "designated_course_group")["minimum"] == 4
    assert condition_by_id(profile, "progression_year_4", "overall_total")["minimum"] == 104
    assert condition_by_id(profile, "progression_year_4", "specialized_total")["minimum"] == 66
    assert condition_by_id(profile, "graduation", "overall_total")["minimum"] == 124
    assert condition_by_id(profile, "graduation", "specialized_total")["minimum"] == 82
    assert condition_by_id(profile, "graduation", "liberal_total")["minimum"] == 36
    assert condition_by_id(profile, "graduation", "cross_area_surplus") == {
        "id": "cross_area_surplus",
        "label": "専門または教養の超過単位",
        "kind": "shared_surplus_minimum",
        "minimum": 6,
        "selector": {"curriculum_areas": ["liberal_arts", "faculty_specialized"]},
        "source_condition_ids": ["specialized_total", "liberal_total"],
    }
    questions = {item["id"]: item for item in profile["open_questions"]}
    assert questions["cross_area_allocation_order"]["status"] == "resolved"
    assert questions["graduation_e_credit_treatment"]["status"] == "resolved"


def test_duplicate_condition_id_is_rejected():
    profile = copy.deepcopy(load_rule_profile())
    conditions = profile["requirements"]["progression_year_2"]["conditions"]
    conditions.append(copy.deepcopy(conditions[0]))
    with pytest.raises(RuleDataError, match="重複したid"):
        validate_rule_profile(profile)


def test_specialized_prefixes_are_required_per_profile():
    profile = copy.deepcopy(load_rule_profile())
    profile["classification"]["faculty_specialized_prefixes"] = []
    with pytest.raises(RuleDataError, match="専門系科目区分"):
        validate_rule_profile(profile)


def test_course_name_display_suffixes_are_profile_driven():
    profile = load_rule_profile()
    assert normalize_course_name("総合工学概論◆", profile) == "総合工学概論"
    assert normalize_course_name("総合工学概論", profile) == "総合工学概論"
    assert normalize_course_name("健康スポーツ科学実習 I", profile) == "健康スポーツ科学実習Ⅰ"


def test_unknown_blocking_question_is_rejected():
    profile = copy.deepcopy(load_rule_profile())
    profile["requirements"]["graduation"]["blocking_open_question_ids"].append("missing-question")
    with pytest.raises(RuleDataError, match="未知の要確認事項"):
        validate_rule_profile(profile)


def test_unknown_allocation_condition_is_rejected():
    profile = copy.deepcopy(load_rule_profile())
    rule = profile["requirements"]["progression_year_4"]["allocation_rules"][0]
    rule["to_condition_id"] = "missing-condition"
    with pytest.raises(RuleDataError, match="未知の条件"):
        validate_rule_profile(profile)


def test_shared_surplus_unknown_or_forward_condition_is_rejected():
    profile = copy.deepcopy(load_rule_profile())
    shared = condition_by_id(profile, "graduation", "cross_area_surplus")
    shared["source_condition_ids"] = ["missing-condition"]
    with pytest.raises(RuleDataError, match="未知の条件"):
        validate_rule_profile(profile)

    profile = copy.deepcopy(load_rule_profile())
    conditions = profile["requirements"]["graduation"]["conditions"]
    shared = condition_by_id(profile, "graduation", "cross_area_surplus")
    conditions.remove(shared)
    conditions.insert(0, shared)
    with pytest.raises(RuleDataError, match="先に定義された条件"):
        validate_rule_profile(profile)


def test_empty_composite_selector_is_rejected():
    profile = copy.deepcopy(load_rule_profile())
    condition_by_id(
        profile,
        "progression_year_4",
        "specialized_applied_b",
    )["selector"]["any_of"] = []

    with pytest.raises(RuleDataError, match="any_of は1件以上"):
        validate_rule_profile(profile)


def fictional_catalog(profile):
    return {
        "schema_version": 1,
        "catalog_id": "fictional-catalog",
        "profile_id": profile["profile_id"],
        "evidence_status": "needs_confirmation",
        "courses": [
            {
                "id": "fictional-course-1",
                "course_code": None,
                "name": "架空科目",
                "curriculum_area": "faculty_specialized",
                "course_group": "specialized_foundation",
                "requirement_code": "B",
                "credits": 2,
                "standard_years": [1],
                "terms": [],
                "aliases": [],
                "required_for": ["progression_year_2", "graduation"],
                "source_refs": [
                    {
                        "document_id": "student_handbook_2025",
                        "printed_pages": [1],
                        "pdf_pages": [5],
                    }
                ],
            }
        ],
    }


def test_fictional_course_catalog_structure_is_accepted():
    profile = load_rule_profile()
    catalog = fictional_catalog(profile)
    assert validate_course_catalog(catalog, profile)["catalog_id"] == "fictional-catalog"


def test_course_catalog_cannot_reference_unknown_requirement():
    profile = load_rule_profile()
    catalog = fictional_catalog(profile)
    catalog["courses"][0]["required_for"] = ["unknown-requirement"]
    with pytest.raises(RuleDataError, match="未知の要件"):
        validate_course_catalog(catalog, profile)
