"""不足単位の探索。学生CSV・カタログは全て架空値で検証する。"""
from copy import deepcopy
import tempfile

import httpx2
import pytest

import server
from academic_rules import load_rule_profile
from classification import classify_course
from parser import parse_csv_bytes
from recommendation_search import search_recommendations
from recommendations import RecommendationError
from test_api import HEADERS, csv_bytes, graduation_surplus_csv
from test_recommendations import catalog, course as offering, parsed


PROFILE = load_rule_profile()
CONTEXT = {"profile_id": PROFILE["profile_id"], "academic_year": 2026, "term": 3}


def earned(name, credits, category="自然科学（架空区分）", status="passed", code=None):
    return {**classify_course(name, category, "", profile=PROFILE), "name": name, "credits": credits,
            "status": status, "course_code": code}


def search(courses=None, candidates=None, timetable=None, profile=None):
    return search_recommendations(catalog(candidates), CONTEXT, {"courses": courses or []},
                                  timetable if timetable is not None else parsed(), profile or PROFILE)


def complete_liberal(*, natural=10, humanities=4, personalization=2, specialized=88):
    courses = [earned("工学リテラシー入門（架空分野）", 2, "大学学習法（架空）"),
               earned("架空英語", 2, "英語（英語）"),
               earned("架空外国語", 2, "初修外国語（架空）"),
               earned("健康スポーツ科学実習Ⅰ", 1, "健康・スポーツ（架空）"),
               earned("エンジニアのためのデータサイエンス入門", 2, "情報リテラシー（架空）"),
               earned("架空人文", humanities, "人文社会・教育科学（架空）"),
               earned("架空個性化", personalization, "新潟大学個性化科目（架空）"),
               earned("架空自然", natural), earned("架空選択", 11, "英語（架空選択）")]
    # 専門側はこの探索の対象外。合計枠の入力としてだけ架空の取得単位を用意する。
    courses.append({"name": "架空専門合計", "credits": specialized, "status": "passed",
                    "curriculum_area": "faculty_specialized", "course_group": "specialized_applied",
                    "requirement_code": "C", "field": "専門応用科目群"})
    return courses


def candidate(name="架空候補", category="自然科学（架空区分）", credits=2, code="263G9901", schedule=None):
    return {**offering(code, schedule), "name": name, "category": category, "credits": credits}


def benefit(result, condition_id):
    return next(item for item in result["candidates"][0]["benefits"] if item["condition_id"] == condition_id)


def test_search_uses_all_meetings_and_excludes_acquired_registered_and_other_terms():
    candidates = [candidate(), candidate("架空修得済み", code="263G9902"),
                  candidate(code="263G9903", schedule=[{"weekday": 2, "period": 1}, {"weekday": 1, "period": 2}]),
                  candidate(code="263G9991"), candidate(code="264G9904")]
    result = search([earned("架空修得済み", 2, code="253G9900")], candidates)
    assert [item["course_code"] for item in result["candidates"]] == ["263G9901"]
    assert result["counts"]["excluded_earned"] == 1
    assert result["counts"]["excluded_overlap"] == 1
    assert result["counts"]["excluded_registered"] == 1
    assert result["counts"]["catalog_in_term"] == 4
    assert {"weekday": 1, "period": 1} not in result["free_slots"]
    assert {"weekday": 2, "period": 1} in result["free_slots"]


@pytest.mark.parametrize("status,credits,expected", [("passed", 2, 0), ("failed", 2, 1), ("unconfirmed", 2, 0), ("unconfirmed", None, 0)])
def test_only_passed_valid_credits_are_earned_and_pending_matches_require_review(status, credits, expected):
    result = search([earned("架空候補", credits, status=status)], [candidate()])
    assert len(result["candidates"]) == expected
    if status == "unconfirmed":
        assert len(result["review_candidates"]) == 1
        assert result["review_candidates"][0]["review_reasons"] == ["matching_earned_course_unconfirmed"]
        assert result["status"] == "unknown"


def test_code_match_excludes_earned_even_if_name_changes_and_explicit_aliases_are_used():
    assert search([earned("別の架空表示名", 2, code="263G9901")], [candidate()])["counts"]["excluded_earned"] == 1
    profile = deepcopy(PROFILE)
    profile["classification"]["course_name_aliases"]["架空の別名"] = "架空候補"
    assert search([earned("架空の別名", 2)], [candidate()], profile=profile)["counts"]["excluded_earned"] == 1
    assert search([earned("架空候補Ⅱ", 2)], [candidate()])["counts"]["excluded_earned"] == 0


def test_natural_requirement_is_filled_before_elective_without_double_counting():
    result = search(complete_liberal(natural=8), [candidate()])
    assert result["status"] == "ok"
    assert benefit(result, "liberal_natural_foundation")["reduced_credits"] == 2
    assert benefit(result, "liberal_natural_foundation")["after_shortfall"] == 0
    assert "liberal_elective" not in {item["condition_id"] for item in result["candidates"][0]["benefits"]}
    assert benefit(result, "liberal_total")["reduced_credits"] == 2


@pytest.mark.parametrize("earned_name,candidate_name", [("架空科目Ⅱ", "架空科目II"), ("架空 科目", "架空科目"), ("架空Ａ科目", "架空A科目")])
def test_earned_name_matching_handles_only_established_typographic_differences(earned_name, candidate_name):
    assert search([earned(earned_name, 2)], [candidate(candidate_name)])["counts"]["excluded_earned"] == 1
    assert search([earned("架空科目Ⅰ", 2)], [candidate("架空科目Ⅱ")])["counts"]["excluded_earned"] == 0


def test_personalization_can_fill_humanities_elective_requirement():
    result = search(complete_liberal(personalization=0), [candidate(category="新潟大学個性化科目（架空）")])
    assert benefit(result, "liberal_humanities_personalization_required_elective")["after_shortfall"] == 0
    assert "liberal_humanities_social_required" not in {item["condition_id"] for item in result["candidates"][0]["benefits"]}


@pytest.mark.parametrize("credits,required_reduction,elective_reduction", [(1, 1, 0), (2, 2, 0), (3, 2, 1), (4, 2, 2), (1.5, 1.5, 0)])
def test_humanities_credit_boundary_and_overflow_allocation(credits, required_reduction, elective_reduction):
    result = search(complete_liberal(humanities=2, personalization=0), [candidate(category="人文社会・教育科学（架空）", credits=credits)])
    assert benefit(result, "liberal_humanities_social_required")["reduced_credits"] == required_reduction
    effects = {item["condition_id"]: item for item in result["candidates"][0]["benefits"]}
    assert effects.get("liberal_humanities_personalization_required_elective", {}).get("reduced_credits", 0) == elective_reduction
    assert required_reduction + elective_reduction <= credits


def test_liberal_shortage_candidate_also_reports_shared_surplus_and_total_effects():
    result = search(complete_liberal(natural=8, specialized=82), [candidate(credits=4)])
    assert benefit(result, "cross_area_surplus")["before_shortfall"] == 6
    assert benefit(result, "cross_area_surplus")["after_shortfall"] == 4
    assert benefit(result, "overall_total")["reduced_credits"] == 4
    assert "liberal_english" not in {item["condition_id"] for item in result["candidates"][0]["benefits"]}


@pytest.mark.parametrize("specialized,extra_liberal", [(60, 6), (60, 0), (82, 0), (88, 0)])
def test_fulfilled_liberal_requirements_stop_recommendations_despite_specialized_or_shared_shortage(specialized, extra_liberal):
    courses = complete_liberal(specialized=specialized)
    if extra_liberal:
        courses.append(earned("架空の追加教養", extra_liberal, "英語（架空）"))
    result = search(courses, [candidate()])
    assert result["status"] == "empty"
    assert result["candidates"] == result["review_candidates"] == []
    assert any(message["code"] == "liberal_requirements_satisfied" for message in result["messages"])


def test_liberal_total_alone_does_not_hide_missing_required_category():
    courses = complete_liberal(natural=8)
    courses.append(earned("架空の追加教養", 6, "英語（架空）"))
    result = search(courses, [candidate()])
    assert next(item for item in result["baseline"] if item["id"] == "liberal_total")["status"] == "satisfied"
    assert result["status"] == "ok"
    assert benefit(result, "liberal_natural_foundation")["reduced_credits"] == 2


def test_overall_only_improvement_is_not_a_reason_to_recommend_when_another_liberal_bucket_is_missing():
    courses = complete_liberal(personalization=0, specialized=60)
    courses.append(earned("架空の追加教養", 8, "英語（架空）"))
    result = search(courses, [candidate()])
    assert result["candidates"] == result["review_candidates"] == []
    assert result["counts"]["excluded_no_benefit"] == 1


def test_unknown_liberal_requirement_is_not_treated_as_fulfilled():
    courses = complete_liberal()
    next(item for item in courses if item["name"] == "架空自然")["status"] = "unconfirmed"
    courses.append(earned("架空の追加教養", 10, "英語（架空）"))
    result = search(courses, [candidate()])
    assert result["status"] == "unknown"
    assert result["candidates"] == []
    assert result["review_candidates"]
    assert not any(message["code"] == "liberal_requirements_satisfied" for message in result["messages"])


def test_uncertain_specialized_credits_do_not_create_review_candidates_when_liberal_is_fulfilled():
    courses = complete_liberal(specialized=60)
    courses.append({"name": "架空の未確定専門", "credits": None, "status": "unconfirmed",
                    "curriculum_area": "faculty_specialized", "course_group": "specialized_applied", "requirement_code": "C"})
    result = search(courses, [candidate()])
    assert result["status"] == "empty"
    assert result["candidates"] == result["review_candidates"] == []
    assert result["checks"]["requirements"] == "checked"
    assert any(item["status"] == "unknown" for item in result["baseline"])


def test_fulfilled_liberal_with_unresolved_timetable_does_not_assume_free_time():
    timetable = parsed()
    timetable["ready_for_recommendation"] = False
    result = search(complete_liberal(), [candidate()], timetable)
    assert result["status"] == "empty"
    assert result["free_slots"] == []
    assert result["checks"]["timetable"] == "needs_review"
    assert result["candidates"] == result["review_candidates"] == []


def test_no_benefit_when_requirements_are_fulfilled_and_actual_report_is_not_modified():
    courses = complete_liberal()
    snapshot = deepcopy(courses)
    timetable = parsed()
    timetable["represented_periods"] = list(range(1, 6))
    result = search(courses, [candidate()], timetable)
    assert result["status"] == "empty"
    assert result["candidates"] == result["review_candidates"] == []
    assert result["counts"]["excluded_no_benefit"] == 0
    assert courses == snapshot
    report = parse_csv_bytes(graduation_surplus_csv(), profile=PROFILE)
    assert search(report["courses"], [candidate()], timetable)["status"] == "empty"


def test_unknown_credits_do_not_turn_into_confirmed_shortages():
    courses = [earned("結果未確定の架空自然科目", None, status="unconfirmed")]
    result = search(courses, [candidate()])
    assert result["candidates"] == []
    assert result["review_candidates"][0]["uncertain_benefits"]
    assert result["status"] == "unknown"
    assert result["checks"]["requirements"] == "needs_review"


@pytest.mark.parametrize("change", ["unresolved", "period_missing", "unrepresented_meeting"])
def test_unknown_timetable_is_not_assumed_free(change):
    timetable = parsed()
    if change == "unresolved": timetable["ready_for_recommendation"] = False
    elif change == "period_missing": timetable["display_contexts"] = []
    else: timetable["represented_periods"] = [2]
    result = search([], [candidate()], timetable)
    assert result["status"] == "unknown"
    assert result["candidates"] == result["review_candidates"] == []


def test_candidates_are_simulated_independently_including_alternative_offerings():
    candidates = [candidate(code="263G9902"), candidate(code="263G9901")]
    result = search(complete_liberal(natural=8), candidates)
    assert [item["course_code"] for item in result["candidates"]] == ["263G9901", "263G9902"]
    for item in result["candidates"]:
        effect = next(effect for effect in item["benefits"] if effect["condition_id"] == "liberal_natural_foundation")
        assert effect["before_shortfall"] == 2 and effect["after_shortfall"] == 0


def test_other_profile_condition_ids_are_supported_without_grade_dependencies():
    profile = deepcopy(PROFILE)
    profile["requirements"]["graduation"]["conditions"] = [{"id": "different_natural_requirement", "label": "架空の別要件",
        "kind": "minimum_credits", "minimum": 3, "selector": {"curriculum_areas": ["liberal_arts"], "fields": ["自然科学"]}}]
    result = search([], [candidate()], profile=profile)
    assert benefit(result, "different_natural_requirement")["after_shortfall"] == 1
    profile["requirements"].pop("graduation")
    with pytest.raises(RecommendationError) as error: search([], [candidate()], profile=profile)
    assert error.value.code == "recommendation_rules_unsupported"


def test_blocked_rule_profiles_only_return_review_candidates():
    profile = deepcopy(PROFILE)
    profile["requirements"]["graduation"]["status"] = "blocked"
    result = search([], [candidate()], profile=profile)
    assert result["candidates"] == []
    assert result["review_candidates"] and result["status"] == "unknown"


def grades_csv(status="合", grade="2", category="英語（英語）", name="既存の架空科目"):
    return csv_bytes([["[学生氏名]", "架空照合学生", "[在籍番号]", "S00000000", "[学生所属]", "架空所属", "[学年]", grade],
                      HEADERS, ["1", "10", "1", "FAKE-PREVIOUS", name, category, "選択", "2", status]])


def multipart(context=None, grades=None, timetable=None):
    from test_timetable_parser import csv_bytes as timetable_bytes, timetable as timetable_rows
    return [(key, (None, str(value))) for key, value in (context or CONTEXT).items()] + [
        ("grades_file", ("fictional-grades.csv", grades if grades is not None else grades_csv(), "text/csv")),
        ("timetable_file", ("fictional-timetable.csv", timetable if timetable is not None else timetable_bytes(timetable_rows()), "text/csv"))]


@pytest.fixture
def anyio_backend(): return "asyncio"


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(server, "_recommendation_catalogs", lambda: [catalog([candidate()])])
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=server.app), base_url="http://testserver") as value:
        yield value


@pytest.mark.anyio
async def test_new_api_uses_both_original_csvs_without_saving_logging_or_echoing(client, monkeypatch, caplog):
    def forbidden(*args, **kwargs): raise AssertionError("一時ファイルは使わない")
    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", forbidden)
    response = await client.post("/api/v1/recommendation-searches", files=multipart())
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["candidates"][0]["benefits"]
    assert response.headers["cache-control"] == "no-store" and "set-cookie" not in response.headers
    for value in ["架空照合学生", "S00000000", "架空所属", "既存の架空科目", "架空 履修学生", "T00000000", "架空科目甲"]:
        assert value not in response.text and value not in caplog.text
    assert (await client.get("/api/v1/recommendation-searches")).status_code == 405


@pytest.mark.anyio
async def test_only_shortage_search_stops_for_completed_liberal_and_keeps_other_apis_unchanged(client):
    liberal_courses = complete_liberal()[:-1]
    raw = csv_bytes([HEADERS, *[
        [str(index), "10", "1", f"FAKE-LIB-{index}", item["name"], f'{item["field"]}（架空）', "選択", str(item["credits"]), "合"]
        for index, item in enumerate(liberal_courses, 1)
    ]])
    response = await client.post("/api/v1/recommendation-searches", files=multipart(grades=raw))
    assert response.status_code == 200
    assert response.json()["status"] == "empty"
    assert response.json()["candidates"] == response.json()["review_candidates"] == []
    assert any(item["code"] == "liberal_requirements_satisfied" for item in response.json()["messages"])
    # 成績集計では、専門や総計の不足を引き続きそのまま返す。
    report = await client.post("/api/v1/reports", files={"file": ("fictional.csv", raw, "text/csv")})
    graduation = next(item for item in report.json()["evaluations"] if item["requirement_id"] == "graduation")
    assert next(item for item in graduation["conditions"] if item["id"] == "specialized_total")["status"] == "not_satisfied"
    assert next(item for item in graduation["conditions"] if item["id"] == "overall_total")["status"] == "not_satisfied"
    # 時限指定APIは、教養の充足にかかわらず開講候補を閲覧できる。
    context = {**CONTEXT, "weekday": 2, "period": 1}
    timetable_file = next(part for part in multipart() if part[0] == "timetable_file")[1]
    slot = await client.post("/api/v1/recommendations", files=[
        *[(key, (None, str(value))) for key, value in context.items()], ("file", timetable_file)])
    assert slot.status_code == 200 and slot.json()["status"] == "ok"
    assert slot.json()["counts"]["returned"] == 1
    assert slot.json()["checks"]["earned_credits"] == "not_checked"


@pytest.mark.anyio
@pytest.mark.parametrize("grade", ["1", "2", "3", "4", "GRADE", ""])
async def test_search_does_not_change_with_grade(client, grade):
    expected = await client.post("/api/v1/recommendation-searches", files=multipart(grades=grades_csv()))
    actual = await client.post("/api/v1/recommendation-searches", files=multipart(grades=grades_csv(grade=grade)))
    assert actual.status_code == 200 and actual.json() == expected.json()


@pytest.mark.anyio
@pytest.mark.parametrize("which", ["grades_file", "timetable_file"])
async def test_missing_duplicate_empty_and_oversized_files_are_rejected(client, which):
    parts = multipart()
    missing = [part for part in parts if part[0] != which]
    response = await client.post("/api/v1/recommendation-searches", files=missing)
    assert response.status_code == 400 and response.json()["error"]["code"] == "missing_file"
    assert response.json()["error"]["details"]["field"] == which
    part = next(part for part in parts if part[0] == which)
    response = await client.post("/api/v1/recommendation-searches", files=parts + [part])
    assert response.status_code == 400 and response.json()["error"]["code"] == "multiple_files"
    for raw, status, code in [(b"", 422, "invalid_csv"), (b"x" * (server.MAX_FILE_BYTES + 1), 413, "file_too_large")]:
        response = await client.post("/api/v1/recommendation-searches", files=missing + [(which, ("fake.csv", raw, "text/csv"))])
        assert response.status_code == status and response.json()["error"]["code"] == code


@pytest.mark.anyio
@pytest.mark.parametrize("which", ["grades", "timetable"])
async def test_malformed_csv_errors_identify_input_without_echoing_it(client, which):
    response = await client.post("/api/v1/recommendation-searches", files=multipart(**{which: b"fictional-sensitive-sentinel"}))
    assert response.status_code == 422
    assert response.json()["error"]["details"]["field"] == ("grades_file" if which == "grades" else "timetable_file")
    assert "fictional-sensitive-sentinel" not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize("change", [{"term": 5}, {"term": "３"}, {"academic_year": -1}, {"academic_year": "NaN"}])
async def test_invalid_context_is_rejected(client, change):
    response = await client.post("/api/v1/recommendation-searches", files=multipart(context={**CONTEXT, **change}))
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_recommendation_context"
