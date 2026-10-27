"""公開資料の実科目や実学生の値をfixtureへコピーせず、架空セルで検証する。"""

from copy import deepcopy

import pytest

from offering_catalog import (assess_audience, assess_for_target, build_catalog, normalize_offering,
                              parse_credits, parse_meetings, parse_terms, validate_catalog,
                              build_compact_catalog, common_offerings, compact_course,
                              coverage_features, summarize_coverage)


def config():
    return {
        "institution": "新潟大学", "academic_year": 2026,
        "source": {"document_id": "fictional-source", "url": "https://example.invalid/fictional.pdf", "source_as_of": "2026-01-01"},
        "syllabus": {"search_url": "https://example.invalid/fictional-search"},
        "scope": {"excluded_categories": ["留学生基本科目"], "excluded_term_zero_policy": True},
        "target_profile": {"faculty": "架空学部", "grade": 2, "profile_id": "fictional-profile"},
    }


def row(**changes):
    cells = {"course_code": "263G9991", "name": "架空教養科目", "credits": "2", "offered_period": "第3ターム",
             "discipline_1": "10", "discipline_2": "", "discipline_3": "", "level": "03", "weekdays": "月・木",
             "periods": "3", "audience": "全学部2年以上", "capacity": "40", "remote_type": "", "teaching_type": "講義"}
    cells.update(changes)
    return {"cells": cells, "source": {"document_id": "fictional-source", "pdf_page": 8, "printed_page": 6,
                                         "table_index": 1, "table_row": 2, "heading": "自然科学（細区分：架空区分）"}}


@pytest.mark.parametrize("value,expected", [
    ("第３ターム", [3]), ("第１・２\nターム", [1, 2]), ("第3・4ターム", [3, 4]),
    ("第1学期", [1, 2]), ("第2学期", [3, 4]), ("通年", [1, 2, 3, 4]),
    ("第5ターム", None), ("未定", None), ("", None),
])
def test_periods_are_explicit_and_unknowns_are_not_guessed(value, expected):
    assert parse_terms(value) == expected


@pytest.mark.parametrize("days,periods,expected", [
    ("月・木", "３", [(1, 3), (4, 3)]),
    ("水", "１・２", [(3, 1), (3, 2)]),
    ("月・火・\n木・金", "4", [(1, 4), (2, 4), (4, 4), (5, 4)]),
    ("月・木", "3・4", None), ("月\n木", "3\n4", None),
    ("集中", "集中", None), ("指定する曜日", "5", None), ("火・集中", "5・集中", None),
    ("", "", None), ("月", "0", None),
])
def test_schedule_lists_do_not_guess_paired_days_or_intensive_times(days, periods, expected):
    slots = parse_meetings(days, periods)
    assert ([(slot["weekday"], slot["period"]) for slot in slots] if slots is not None else None) == expected


@pytest.mark.parametrize("value,expected", [("０.５", 0.5), ("2", 2), ("", None), ("0", None), ("-1", None),
                                           ("NaN", None), ("Infinity", None), ("未定", None)])
def test_unknown_or_invalid_credits_are_never_zero(value, expected):
    assert parse_credits(value) == expected


def test_normalization_preserves_category_provenance_slots_and_uncollected_descriptions():
    item = normalize_offering(row(), config())
    assert item["category"] == {"field": "自然科学", "detail": "架空区分"}
    assert item["schedule"]["slots"] == [{"term": 3, "weekday": 1, "period": 3}, {"term": 3, "weekday": 4, "period": 3}]
    assert item["data_readiness"] == {"status": "ready", "reason_codes": []}
    assert item["source_refs"][0]["printed_page"] == 6
    assert item["source_refs"][0]["url"].endswith("#page=8")
    assert item["syllabus"]["description"] is None
    assert item["syllabus"]["grading_policy"] is None
    assert item["syllabus"]["status"] == "not_collected_robots_disallow"


def test_zero_term_regular_classes_remain_in_catalog_but_are_excluded_by_mvp_policy():
    item = normalize_offering(row(course_code="260G9991", offered_period="第3・4ターム"), config())
    assert len(item["schedule"]["slots"]) == 4
    assert item["schedule"]["status"] == "known"
    assert item["data_readiness"]["status"] == "excluded"
    assert item["data_readiness"]["reason_codes"] == ["term_zero_mvp_policy"]


@pytest.mark.parametrize("changes,reason", [
    ({"offered_period": "第4ターム"}, "code_period_mismatch"),
    ({"credits": ""}, "unknown_credits"),
    ({"weekdays": "未定"}, "intensive_or_unspecified_schedule"),
    ({"weekdays": "月・木", "periods": "3・4"}, "ambiguous_or_missing_schedule"),
    ({"remote_type": "ロ"}, "asynchronous_or_unknown_delivery"),
    ({"remote_type": "イ・ロ"}, "asynchronous_or_unknown_delivery"),
])
def test_incomplete_or_inconsistent_offerings_do_not_enter_candidates(changes, reason):
    item = normalize_offering(row(**changes), config())
    assert item["data_readiness"]["status"] == "needs_review"
    assert reason in item["data_readiness"]["reason_codes"]
    assert assess_for_target(item, config()["target_profile"])["status"] == "needs_review"


def test_unknown_categories_and_international_courses_do_not_become_general_candidates():
    source = row()
    source["source"]["heading"] = "未知の科目群（細区分：架空区分）"
    assert normalize_offering(source, config())["data_readiness"]["status"] == "needs_review"
    source["source"]["heading"] = "留学生基本科目（細区分：架空区分）"
    assert normalize_offering(source, config())["data_readiness"]["status"] == "excluded"


@pytest.mark.parametrize("audience,status", [
    ("全学部", "primary_audience_match"), ("全学部２年以上", "primary_audience_match"),
    ("全学部１・２年", "primary_audience_match"), ("全学部１～３年", "primary_audience_match"),
    ("全学部３・４年", "excluded"), ("全学部初年次", "excluded"),
    ("全学部（留学生）", "excluded"), ("架空学部を除く", "excluded"),
    ("架空学部", "primary_audience_match"), ("架空学部（クラス指定）", "needs_review"),
    ("別の学部・他", "needs_review"), ("全学部（再履修用）", "needs_review"),
    ("全学部（架空学部１年を除く）", "needs_review"), ("全学部5年", "needs_review"),
])
def test_audience_assessment_preserves_conditions_and_does_not_infer_permission(audience, status):
    assert assess_audience(audience, config()["target_profile"])["status"] == status


def test_additional_audiences_are_profile_data_and_unknown_subgroups_stay_unknown():
    target = {**config()["target_profile"], "additional_primary_audiences": ["架空学部グループ・他"]}
    assert assess_audience("架空学部グループ・他", target)["status"] == "primary_audience_match"
    assert assess_audience("架空学部グループ・他（特定分野）", target)["status"] == "needs_review"


def test_catalog_keeps_distinct_offerings_with_same_name_and_can_change_target():
    first, second = row(), row(course_code="264G9992", offered_period="第4ターム", audience="別の学部2年以上")
    catalog, target, quality = build_catalog([first, second], config(), "fictional-hash")
    assert len(catalog["offerings"]) == 2
    assert len(target["candidates"]) == 1
    assert quality["candidate_term_counts"] == {"1": 0, "2": 0, "3": 1, "4": 0}
    other_config = config()
    other_config["target_profile"]["faculty"] = "別の学部"
    other_config["target_profile"]["grade"] = 1
    assert build_catalog([second], other_config, "fictional-hash")[1]["candidate_count"] == 0
    other_config["target_profile"]["grade"] = 2
    assert build_catalog([second], other_config, "fictional-hash")[1]["candidate_count"] == 1


def test_conflicting_duplicate_opening_codes_are_not_silently_merged():
    with pytest.raises(ValueError, match="複数行"):
        build_catalog([row(), row(name="架空の別科目")], config(), "fictional-hash")


def test_faculty_specialized_codes_are_not_included_via_liberal_elective_policy():
    catalog, target, quality = build_catalog([row(course_code="263T9991")], config(), "fictional-hash")
    assert catalog["offerings"] == target["candidates"] == []
    assert quality["non_g_rows_outside_scope"] == 1


def test_validator_rejects_duplicate_slots_and_missing_ready_information():
    catalog, _, _ = build_catalog([row()], config(), "fictional-hash")
    bad = deepcopy(catalog)
    bad["offerings"][0]["schedule"]["slots"].append(bad["offerings"][0]["schedule"]["slots"][0])
    with pytest.raises(ValueError, match="重複"):
        validate_catalog(bad)
    bad = deepcopy(catalog)
    bad["offerings"][0]["credits"] = None
    with pytest.raises(ValueError, match="不足"):
        validate_catalog(bad)


@pytest.mark.parametrize("audience,expected", [
    ("全学部", True), ("全学部２年以上", True), ("全学部１年", True),
    ("全学部3年", True), ("全学部4年", True), ("全学部初年次", True),
    ("架空学部", False), ("架空学部グループ・他", False), ("全学部（再履修用）", False),
    ("全学部（架空学部を優先）", False), ("全学部（架空学部を除く）", False),
])
def test_simple_pool_requires_all_faculties_and_ignores_simple_grade_conditions(audience, expected):
    cfg = config()
    cfg["target_profile"]["additional_primary_audiences"] = ["架空学部グループ・他"]
    item = normalize_offering(row(audience=audience), cfg)
    assert bool(common_offerings([item], cfg["target_profile"])) is expected


def test_compact_catalog_has_six_course_fields_that_existing_classification_can_read():
    from classification import classify_category
    cfg = config()
    full, _, _ = build_catalog([row()], cfg, "fictional-hash")
    simple, report = build_compact_catalog(full, cfg)
    assert simple["schema_version"] == 3
    assert simple["profile_id"] == "fictional-profile"
    assert "target_grade" not in simple
    course = simple["courses"][0]
    assert set(course) == {"course_code", "name", "credits", "category", "terms", "schedule"}
    assert course["category"] == "自然科学（架空区分）"
    assert classify_category(course["category"])[:3] == ("教養", "自然科学", "架空区分")
    assert course["schedule"] == [{"weekday": 1, "period": 3}, {"weekday": 4, "period": 3}]
    assert report["pool"]["covered_slots"] == report["selected"]["covered_slots"] == 2


def test_reduction_preserves_time_slots_and_categories_and_is_independent_of_input_order():
    cfg = config()
    rows = [row(), row(course_code="263G9992", weekdays="月"), row(course_code="263G9993")]
    rows[2]["source"]["heading"] = "人文社会・教育科学（細区分：架空区分）"
    full, _, _ = build_catalog(rows, cfg, "fictional-hash")
    result, report = build_compact_catalog(full, cfg)
    assert len(result["courses"]) == 2
    assert {course["category"] for course in result["courses"]} == {"自然科学（架空区分）", "人文社会・教育科学（架空区分）"}
    original_features = set().union(*(coverage_features(item) for item in full["offerings"]))
    selected_codes = {item["course_code"] for item in result["courses"]}
    selected_features = set().union(*(coverage_features(item) for item in full["offerings"] if item["course_code"] in selected_codes))
    assert original_features == selected_features
    full["offerings"].reverse()
    assert build_compact_catalog(full, cfg)[0] == result
    assert report["pool"]["missing_slots"] == report["selected"]["missing_slots"]


def test_missing_terms_and_weekdays_are_not_filled_by_another_offering():
    item = normalize_offering(row(), config())
    coverage = summarize_coverage([item])
    assert coverage["covered_slots"] == 2
    assert len(coverage["missing_slots"]) == 98
    assert coverage["matrices"]["3"][2] == [1, 0, 0, 1, 0]
    assert coverage["term_period_counts"]["3"] == [0, 0, 1, 0, 0]
    assert coverage["term_period_counts"]["4"] == [0, 0, 0, 0, 0]


def test_a_course_partly_outside_the_requested_grid_is_not_truncated():
    item = normalize_offering(row(), config())
    item["schedule"]["slots"][1]["period"] = 6
    assert common_offerings([item], config()["target_profile"]) == []


def test_different_meetings_per_term_cannot_be_flattened_into_the_compact_schedule():
    cfg = config()
    cfg["scope"]["excluded_term_zero_policy"] = False
    item = normalize_offering(row(course_code="260G9991", offered_period="第3・4ターム"), cfg)
    item["schedule"]["slots"].pop()
    with pytest.raises(ValueError, match="タームごと"):
        compact_course(item)


def test_compact_catalog_does_not_change_with_target_grade_and_empty_pool_is_valid():
    cfg = config()
    full, _, _ = build_catalog([row(audience="全学部1年")], cfg, "fictional-hash")
    simple, report = build_compact_catalog(full, cfg)
    assert len(simple["courses"]) == 1
    assert report["pool"]["covered_slots"] == 2
    for grade in [1, 2, 3, 4, None]:
        cfg["target_profile"]["grade"] = grade
        assert build_compact_catalog(full, cfg) == (simple, report)
    cfg["target_profile"].pop("grade")
    assert build_compact_catalog(full, cfg) == (simple, report)
    full["offerings"] = []
    empty, empty_report = build_compact_catalog(full, cfg)
    assert empty["courses"] == []
    assert empty_report["pool"]["covered_slots"] == 0


def test_legacy_archival_preserves_original_bytes_and_existing_archive(tmp_path):
    from scripts.build_liberal_catalog import archive_legacy
    file = tmp_path / "old.json"
    file.write_text('{"fictional": 1}', encoding="utf-8")
    archive_legacy(tmp_path, "old.json")
    assert (tmp_path / "archive/old.json").read_text() == '{"fictional": 1}'
    file.write_text('{"fictional": 2}', encoding="utf-8")
    archive_legacy(tmp_path, "old.json")
    assert (tmp_path / "archive/old.json").read_text() == '{"fictional": 1}'
    assert len(list((tmp_path / "archive").glob('old*.json'))) == 2
