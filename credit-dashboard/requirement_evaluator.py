"""正規化済み成績と規則データを使う学務要件評価器。"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from academic_rules import RuleDataError, catalog_name_key, load_profile_course_catalog, load_rule_profile
from classification import normalize_course_name


RESULTS = {"satisfied", "not_satisfied", "unknown"}
SUPPORTED_REQUIREMENT_IDS = (
    "progression_year_2",
    "progression_year_4",
    "graduation",
)
MAX_RESIDENCE_YEARS = Decimal("100")


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, bool):
        raise ValueError("真偽値を単位数または年数として扱うことはできません")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("単位数または年数が数値ではありません") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("単位数または年数は有限の0以上である必要があります")
    return number


def _json_number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _result_from_lower_bound(
    earned: Decimal,
    minimum: Decimal,
    has_uncertain_candidate: bool,
) -> tuple[str, str]:
    if earned >= minimum:
        return "satisfied", "minimum_reached"
    if has_uncertain_candidate:
        return "unknown", "uncertain_courses_may_affect_result"
    return "not_satisfied", "confirmed_credits_below_minimum"


def _selector_match(course: dict[str, Any], selector: dict[str, Any]) -> str:
    """selectorへの該当をinclude/exclude/uncertainで返す。"""
    if course.get("curriculum_area") == "excluded":
        return "exclude"
    alternatives = selector.get("any_of")
    if alternatives:
        common_selector = {
            key: value for key, value in selector.items() if key != "any_of"
        }
        common_match = _selector_match(course, common_selector)
        if common_match != "include":
            return common_match
        alternative_matches = [
            _selector_match(course, alternative) for alternative in alternatives
        ]
        if "include" in alternative_matches:
            return "include"
        if "uncertain" in alternative_matches:
            return "uncertain"
        return "exclude"

    selected_areas = set(selector.get("curriculum_areas", []))
    area = course.get("curriculum_area")
    if selected_areas:
        if area == "unknown" or area is None:
            return "uncertain"
        if area not in selected_areas:
            return "exclude"

    selected_fields = set(selector.get("fields", []))
    if selected_fields:
        field = course.get("field")
        if field is None:
            return "uncertain"
        if field not in selected_fields:
            return "exclude"

    normalized_name = course.get("normalized_name") or course.get("name")
    selected_names = set(selector.get("course_names", []))
    if selected_names and normalized_name not in selected_names:
        return "exclude"
    fragments = selector.get("course_name_contains_any", [])
    if fragments and not any(fragment in (normalized_name or "") for fragment in fragments):
        return "exclude"
    if normalized_name in set(selector.get("excluded_course_names", [])):
        return "exclude"

    selected_groups = set()
    if selector.get("course_group"):
        selected_groups.add(selector["course_group"])
    selected_groups.update(selector.get("course_groups", []))
    if selected_groups:
        group = course.get("course_group")
        if group is None:
            return "uncertain" if area in {"faculty_specialized", "unknown", None} else "exclude"
        if group not in selected_groups:
            return "exclude"

    selected_codes = set(selector.get("requirement_codes", []))
    code = course.get("requirement_code")
    if selected_codes:
        if code is None:
            return "uncertain" if area in {"faculty_specialized", "unknown", None} else "exclude"
        if code not in selected_codes:
            return "exclude"

    selected_types = set(selector.get("requirement_types", []))
    requirement_type = course.get("requirement_type")
    if selected_types:
        if requirement_type is None:
            return "uncertain"
        if requirement_type not in selected_types:
            return "exclude"

    excluded_codes = set(selector.get("excluded_requirement_codes", []))
    if code in excluded_codes:
        return "exclude"
    if excluded_codes and area == "faculty_specialized" and code is None:
        return "uncertain"
    if selector.get("credit_caps") and area == "faculty_specialized" and code is None:
        return "uncertain"
    return "include"


def _evaluate_credit_condition(
    condition: dict[str, Any],
    courses: list[dict[str, Any]],
) -> dict[str, Any]:
    minimum = _decimal(condition["minimum"])
    selector = condition["selector"]
    earned = Decimal(0)
    earned_by_code: dict[str | None, Decimal] = {}
    uncertain = False
    counted_course_ids: set[str] = set()

    for course in courses:
        match = _selector_match(course, selector)
        if match == "exclude" or course.get("status") == "failed":
            continue
        if match == "uncertain" or course.get("status") != "passed":
            uncertain = True
            continue
        credits = course.get("credits")
        if credits is None:
            uncertain = True
            continue
        identity = str(course.get("course_code") or course.get("code") or f"name:{course.get('name')}")
        if identity in counted_course_ids:
            uncertain = True
            continue
        counted_course_ids.add(identity)
        course_credits = _decimal(credits)
        earned_by_code[course.get("requirement_code")] = (
            earned_by_code.get(course.get("requirement_code"), Decimal(0)) + course_credits
        )

    credit_caps = {
        code: _decimal(maximum)
        for code, maximum in selector.get("credit_caps", {}).items()
    }
    for code, credits in earned_by_code.items():
        earned += min(credits, credit_caps[code]) if code in credit_caps else credits

    status, reason_code = _result_from_lower_bound(earned, minimum, uncertain)
    return {
        "id": condition["id"],
        "label": condition.get("label", condition["id"]),
        "status": status,
        "reason_code": reason_code,
        "minimum_credits": _json_number(minimum),
        "confirmed_credits": _json_number(earned),
        "confirmed_credit_shortfall": _json_number(max(minimum - earned, Decimal(0))),
        "has_uncertain_candidate": uncertain,
        "applied_credit_caps": {
            code: _json_number(maximum) for code, maximum in credit_caps.items()
        },
    }


def _evaluate_named_course_condition(
    condition: dict[str, Any],
    courses: list[dict[str, Any]],
) -> dict[str, Any]:
    minimum = _decimal(condition["minimum"])
    earned = Decimal(0)
    uncertain = False
    matched_names: list[str] = []
    counted_course_ids: set[str] = set()

    for course in courses:
        normalized_name = course.get("normalized_name") or course.get("name")
        match = _selector_match(course, condition["selector"])
        if match == "exclude" or course.get("status") == "failed":
            continue
        if match == "uncertain" or course.get("status") != "passed" or course.get("credits") is None:
            uncertain = True
            continue
        identity = str(course.get("course_code") or course.get("code") or f"name:{normalized_name}")
        if identity in counted_course_ids:
            uncertain = True
            continue
        counted_course_ids.add(identity)
        earned += _decimal(course["credits"])
        matched_names.append(normalized_name)

    status, reason_code = _result_from_lower_bound(earned, minimum, uncertain)
    return {
        "id": condition["id"],
        "label": condition.get("label", condition["id"]),
        "status": status,
        "reason_code": reason_code,
        "minimum_credits": _json_number(minimum),
        "confirmed_credits": _json_number(earned),
        "confirmed_credit_shortfall": _json_number(max(minimum - earned, Decimal(0))),
        "has_uncertain_candidate": uncertain,
        "matched_course_names": matched_names,
    }


def _evaluate_shared_surplus_condition(
    condition: dict[str, Any],
    evaluated_conditions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """区分別最低単位を超えた確認済み単位の合計を評価する。"""
    minimum = _decimal(condition["minimum"])
    confirmed_surplus = Decimal(0)
    uncertain = False
    source_surplus: dict[str, int | float] = {}

    for source_id in condition["source_condition_ids"]:
        source = evaluated_conditions[source_id]
        confirmed = _decimal(source["confirmed_credits"])
        source_minimum = _decimal(source["minimum_credits"])
        surplus = max(confirmed - source_minimum, Decimal(0))
        source_surplus[source_id] = _json_number(surplus)
        confirmed_surplus += surplus
        if source["status"] == "unknown" or source.get("has_uncertain_candidate"):
            uncertain = True

    status, reason_code = _result_from_lower_bound(
        confirmed_surplus,
        minimum,
        uncertain,
    )
    return {
        "id": condition["id"],
        "label": condition.get("label", condition["id"]),
        "status": status,
        "reason_code": reason_code,
        "minimum_credits": _json_number(minimum),
        "confirmed_credits": _json_number(confirmed_surplus),
        "confirmed_credit_shortfall": _json_number(
            max(minimum - confirmed_surplus, Decimal(0))
        ),
        "has_uncertain_candidate": uncertain,
        "source_surplus_credits": source_surplus,
    }


def _evaluate_required_courses_condition(
    condition: dict[str, Any],
    courses: list[dict[str, Any]],
    requirement_id: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    """必修を科目ごとに確認する。取得単位への配賦・再加算はしない。"""
    catalog = load_profile_course_catalog(profile)
    if catalog is None:
        raise RuleDataError("個別必修の評価には科目マスターが必要です")
    required = [
        item for item in catalog["courses"]
        if requirement_id in item.get("required_for", [])
    ]
    if not required:
        raise RuleDataError("個別必修の評価対象一覧が空です")
    # 同一の開講番号が異なる科目を示す入力から、複数必修の充足を確定しない。
    names_by_code: dict[str, set[str]] = {}
    for course in courses:
        code = course.get("course_code") or course.get("code")
        if code:
            name = course.get("normalized_name") or course.get("name") or ""
            names_by_code.setdefault(str(code), set()).add(
                catalog_name_key(normalize_course_name(name, profile))
            )

    results = []
    for required_course in required:
        names = {
            catalog_name_key(name)
            for name in [required_course["name"], *required_course.get("aliases", [])]
        }
        minimum = _decimal(required_course["credits"])
        confirmed = Decimal(0)
        uncertain = False
        for course in courses:
            name = course.get("normalized_name") or course.get("name") or ""
            name_key = catalog_name_key(normalize_course_name(name, profile))
            if name_key not in names:
                continue
            match = _selector_match(course, condition["selector"])
            if match == "exclude" or course.get("status") == "failed":
                continue
            code = course.get("course_code") or course.get("code")
            conflicting_code = code and len(names_by_code[str(code)]) > 1
            if (match == "uncertain" or conflicting_code
                    or course.get("status") != "passed" or course.get("credits") is None):
                uncertain = True
                continue
            # 同名の別コード科目は全体単位では別々に数えるが、この必修を
            # 修得したかの確認では、1回の有効な修得を確認できればよい。
            confirmed = max(confirmed, _decimal(course["credits"]))
        status, reason = _result_from_lower_bound(confirmed, minimum, uncertain)
        result = {
            "catalog_course_id": required_course["id"],
            "name": required_course["name"],
            "status": status,
            "reason_code": reason,
            "minimum_credits": _json_number(minimum),
            "confirmed_credits": _json_number(confirmed),
            "confirmed_credit_shortfall": _json_number(max(minimum - confirmed, Decimal(0))),
            "has_uncertain_candidate": uncertain,
            "source_refs": required_course["source_refs"],
        }
        result["description"] = _condition_description(result)
        results.append(result)

    status = _overall_status(results)
    return {
        "id": condition["id"],
        "label": condition.get("label", condition["id"]),
        "status": status,
        "reason_code": {
            "satisfied": "all_required_courses_passed",
            "not_satisfied": "required_courses_missing",
            "unknown": "required_course_results_uncertain",
        }[status],
        "required_course_count": len(results),
        "satisfied_course_count": sum(item["status"] == "satisfied" for item in results),
        "missing_course_names": [item["name"] for item in results if item["status"] == "not_satisfied"],
        "unknown_course_names": [item["name"] for item in results if item["status"] == "unknown"],
        "course_results": results,
    }


def _evaluate_residual_credit_condition(
    condition: dict[str, Any],
    courses: list[dict[str, Any]],
    evaluated_conditions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """先に満たす分類別最低単位を差し引いた、重複しない残余単位を評価する。"""
    total = _evaluate_credit_condition(condition, courses)
    total_credits = _decimal(total["confirmed_credits"])
    allocated = Decimal(0)
    allocated_by_condition: dict[str, int | float] = {}
    uncertain = bool(total["has_uncertain_candidate"])
    for dependency_id in condition["subtract_condition_ids"]:
        dependency = evaluated_conditions.get(dependency_id)
        if dependency is None or dependency.get("confirmed_credits") is None:
            uncertain = True
            continue
        confirmed = _decimal(dependency["confirmed_credits"])
        minimum = _decimal(dependency["minimum_credits"])
        dependency_allocation = min(confirmed, minimum)
        allocated += dependency_allocation
        allocated_by_condition[dependency_id] = _json_number(dependency_allocation)
        if dependency["status"] == "unknown":
            uncertain = True

    residual = max(total_credits - allocated, Decimal(0))
    minimum = _decimal(condition["minimum"])
    status, reason_code = _result_from_lower_bound(residual, minimum, uncertain)
    return {
        "id": condition["id"],
        "label": condition.get("label", condition["id"]),
        "status": status,
        "reason_code": reason_code,
        "minimum_credits": _json_number(minimum),
        "confirmed_credits": _json_number(residual),
        "confirmed_credit_shortfall": _json_number(max(minimum - residual, Decimal(0))),
        "has_uncertain_candidate": uncertain,
        "applied_credit_caps": total.get("applied_credit_caps", {}),
        "confirmed_area_credits": _json_number(total_credits),
        "allocated_to_prior_conditions": _json_number(allocated),
        "allocated_by_condition": allocated_by_condition,
    }


def _evaluate_residence_condition(
    condition: dict[str, Any],
    residence_years: int | float | None,
    residence_years_source: str,
) -> dict[str, Any]:
    minimum = _decimal(condition["minimum"])
    if residence_years is None:
        return {
            "id": condition["id"],
            "label": condition.get("label", condition["id"]),
            "status": "unknown",
            "reason_code": "residence_years_not_provided",
            "minimum_years": _json_number(minimum),
            "confirmed_years": None,
            "value_source": residence_years_source,
        }
    years = _decimal(residence_years)
    if years > MAX_RESIDENCE_YEARS:
        raise ValueError("在学期間は100年以下である必要があります")
    return {
        "id": condition["id"],
        "label": condition.get("label", condition["id"]),
        "status": "satisfied" if years >= minimum else "not_satisfied",
        "reason_code": "minimum_reached" if years >= minimum else "confirmed_years_below_minimum",
        "minimum_years": _json_number(minimum),
        "confirmed_years": _json_number(years),
        "value_source": residence_years_source,
    }


def _overall_status(conditions: list[dict[str, Any]]) -> str:
    statuses = {condition["status"] for condition in conditions}
    if not statuses <= RESULTS:
        raise ValueError("未知の判定状態があります")
    if "not_satisfied" in statuses:
        return "not_satisfied"
    if "unknown" in statuses:
        return "unknown"
    return "satisfied"


def _condition_description(condition: dict[str, Any]) -> str:
    """画面が判定ロジックを再実装せず表示できる説明を生成する。"""
    reason_code = condition["reason_code"]
    if "course_results" in condition:
        total = condition["required_course_count"]
        passed = condition["satisfied_course_count"]
        missing = len(condition["missing_course_names"])
        uncertain = len(condition["unknown_course_names"])
        return (
            f"必修{total}科目のうち{passed}科目の修得を確認しました。"
            f"未修得または必要単位未達が{missing}科目、判定不能が{uncertain}科目です。"
        )
    if reason_code == "residence_years_not_provided":
        return "在学期間が入力されていないため、この条件は判定できません。"
    if "minimum_years" in condition:
        confirmed = condition.get("confirmed_years")
        minimum = condition["minimum_years"]
        source_note = (
            "CSVの学年と在学年数が一致するMVP前提により、"
            if condition.get("value_source") == "student_grade_assumption"
            else "入力された在学期間により、"
        )
        if reason_code == "minimum_reached":
            return f"{source_note}在学期間を{confirmed}年として扱い、必要な{minimum}年以上です。"
        return f"{source_note}在学期間を{confirmed}年として扱い、必要な{minimum}年に届いていません。"

    confirmed = condition.get("confirmed_credits", 0)
    minimum = condition.get("minimum_credits", 0)
    shortfall = condition.get("confirmed_credit_shortfall", 0)
    if "allocated_to_prior_conditions" in condition:
        source_credits = condition.get("confirmed_area_credits", 0)
        allocated = condition["allocated_to_prior_conditions"]
        allocation_summary = (
            f"対象となる確認済み{source_credits}単位のうち、"
            f"先行する最低枠へ{allocated}単位を充当し、残りは{confirmed}単位です。"
        )
        if reason_code == "minimum_reached":
            return f"{allocation_summary}必要な{minimum}単位以上です。"
        if reason_code == "uncertain_courses_may_affect_result":
            return (
                f"{allocation_summary}確定値ではあと{shortfall}単位ですが、"
                "未確定または分類不能な科目が結果へ影響するため判定できません。"
            )
        if reason_code == "confirmed_credits_below_minimum":
            return f"{allocation_summary}必要な{minimum}単位まであと{shortfall}単位です。"
    if reason_code == "minimum_reached":
        return f"確認済み{confirmed}単位で、必要な{minimum}単位以上です。"
    if reason_code == "uncertain_courses_may_affect_result":
        return (
            f"確認済みは{confirmed}単位で、確定値ではあと{shortfall}単位です。"
            "未確定または分類不能な科目が結果へ影響するため判定できません。"
        )
    if reason_code == "confirmed_credits_below_minimum":
        return f"確認済みは{confirmed}単位で、必要な{minimum}単位まであと{shortfall}単位です。"
    return "この条件の評価方法はまだ実装されていません。"


def _source_details(
    profile: dict[str, Any],
    refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    documents = {document["id"]: document for document in profile["source_documents"]}
    resolved = []
    for ref in refs:
        document = documents[ref["document_id"]]
        resolved.append({
            "document_id": ref["document_id"],
            "title": document["title"],
            "url": document["url"],
            "section": ref.get("section"),
            "printed_pages": ref["printed_pages"],
            "pdf_pages": ref["pdf_pages"],
        })
    return resolved


def _caveat_details(
    profile: dict[str, Any],
    caveat_ids: list[str],
) -> list[dict[str, str]]:
    questions = {question["id"]: question for question in profile["open_questions"]}
    return [
        {
            "id": caveat_id,
            "status": questions[caveat_id]["status"],
            "message": questions[caveat_id]["question"],
        }
        for caveat_id in caveat_ids
    ]


def _overall_description(status: str) -> str:
    return {
        "satisfied": "入力内容から確認できる範囲では、すべての条件を満たしています。",
        "not_satisfied": "入力内容から確認できる範囲で、満たしていない条件があります。",
        "unknown": "不足入力または未確定情報があるため、総合結果を確定できません。",
    }[status]


def student_grade_year(report: dict[str, Any]) -> int | None:
    """CSVの学年表記を表示対象の選択にだけ使える整数へ変換する。"""
    raw = report.get("student", {}).get("grade")
    if raw is None:
        return None
    match = re.fullmatch(r"\s*([1-9]\d*)\s*(?:年(?:次)?)?\s*", str(raw))
    return int(match.group(1)) if match else None


def requirement_ids_for_grade(grade_year: int | None) -> tuple[str, ...]:
    """学年別に画面へ出す要件を返す。学年不明時は安全側ですべて表示する。"""
    if grade_year == 1:
        return ("progression_year_2", "graduation")
    if grade_year in {2, 3}:
        return ("progression_year_4", "graduation")
    if grade_year is not None and grade_year >= 4:
        return ("graduation",)
    return SUPPORTED_REQUIREMENT_IDS


def _evaluate_requirement(
    requirement_id: str,
    report: dict[str, Any],
    *,
    residence_years: int | float | None,
    residence_years_source: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    requirement = profile["requirements"][requirement_id]
    courses = report.get("courses", [])
    if not isinstance(courses, list):
        raise ValueError("report.courses は配列である必要があります")

    evaluations = []
    evaluated_by_id: dict[str, dict[str, Any]] = {}
    for condition in requirement["conditions"]:
        kind = condition["kind"]
        if kind == "minimum_residence_years":
            evaluated = _evaluate_residence_condition(
                condition,
                residence_years,
                residence_years_source,
            )
        elif kind == "minimum_credits":
            evaluated = _evaluate_credit_condition(condition, courses)
        elif kind == "minimum_credits_from_named_courses":
            evaluated = _evaluate_named_course_condition(condition, courses)
        elif kind == "minimum_residual_credits":
            evaluated = _evaluate_residual_credit_condition(
                condition,
                courses,
                evaluated_by_id,
            )
        elif kind == "shared_surplus_minimum":
            evaluated = _evaluate_shared_surplus_condition(
                condition,
                evaluated_by_id,
            )
        elif kind == "required_courses":
            evaluated = _evaluate_required_courses_condition(
                condition, courses, requirement_id, profile,
            )
        else:
            evaluated = {
                "id": condition["id"],
                "label": condition.get("label", condition["id"]),
                "status": "unknown",
                "reason_code": "condition_kind_not_implemented",
            }
        evaluations.append(evaluated)
        evaluated_by_id[evaluated["id"]] = evaluated

    for evaluated in evaluations:
        evaluated["description"] = _condition_description(evaluated)

    if requirement["status"] == "blocked":
        overall_status = "unknown"
        overall_description = (
            "一部の条件は集計できますが、単位配賦または必修科目の確認事項が残るため、"
            "総合結果はまだ確定できません。"
        )
    else:
        overall_status = _overall_status(evaluations)
        overall_description = _overall_description(overall_status)
    caveat_ids = requirement["blocking_open_question_ids"]

    return {
        "requirement_id": requirement_id,
        "title": requirement.get("title", requirement_id),
        "profile_id": profile["profile_id"],
        "status": overall_status,
        "description": overall_description,
        "advisory_only": True,
        "rule_status": requirement["status"],
        "evidence_status": requirement["evidence_status"],
        "input_context": {
            "residence_years": residence_years,
            "residence_years_source": residence_years_source,
            "student_grade_year": student_grade_year(report),
        },
        "conditions": evaluations,
        "source_refs": requirement["source_refs"],
        "sources": _source_details(profile, requirement["source_refs"]),
        "caveat_ids": caveat_ids,
        "caveats": _caveat_details(profile, caveat_ids),
    }


def evaluate_second_year_progression(
    report: dict[str, Any],
    *,
    residence_years: int | float | None = None,
    residence_years_source: str | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """第2年次進級要件を三値で評価する。結果は大学の正式判定ではない。"""
    rule_profile = profile or load_rule_profile()
    return _evaluate_requirement(
        "progression_year_2",
        report,
        residence_years=residence_years,
        residence_years_source=residence_years_source or (
            "user_input" if residence_years is not None else "unavailable"
        ),
        profile=rule_profile,
    )


def evaluate_fourth_year_progression(
    report: dict[str, Any],
    *,
    residence_years: int | float | None = None,
    residence_years_source: str | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """確認済み条件を示しつつ、未確認事項があれば総合結果をunknownにする。"""
    return _evaluate_requirement(
        "progression_year_4",
        report,
        residence_years=residence_years,
        residence_years_source=residence_years_source or (
            "user_input" if residence_years is not None else "unavailable"
        ),
        profile=profile or load_rule_profile(),
    )


def evaluate_graduation(
    report: dict[str, Any],
    *,
    residence_years: int | float | None = None,
    residence_years_source: str | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """卒業要件の確認済み内訳を示し、未確認事項を総合判定へ伝播する。"""
    return _evaluate_requirement(
        "graduation",
        report,
        residence_years=residence_years,
        residence_years_source=residence_years_source or (
            "user_input" if residence_years is not None else "unavailable"
        ),
        profile=profile or load_rule_profile(),
    )


def evaluate_supported_requirements(
    report: dict[str, Any],
    *,
    residence_years: int | float | None = None,
    residence_years_source: str | None = None,
    profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """CSVの学年に応じ、プロファイルに存在する表示対象だけを列挙する。"""
    rule_profile = profile or load_rule_profile()
    evaluators = {
        "progression_year_2": evaluate_second_year_progression,
        "progression_year_4": evaluate_fourth_year_progression,
        "graduation": evaluate_graduation,
    }
    results = []
    for requirement_id in requirement_ids_for_grade(student_grade_year(report)):
        if requirement_id not in rule_profile["requirements"]:
            continue
        evaluator = evaluators.get(requirement_id)
        if evaluator is None:
            continue
        results.append(
            evaluator(
                report,
                residence_years=residence_years,
                residence_years_source=residence_years_source,
                profile=rule_profile,
            )
        )
    return results
