"""修得単位と空き時間を照合する。科目を1つずつ仮追加し既存評価器を再利用する。"""
from __future__ import annotations

from decimal import Decimal

from academic_rules import catalog_name_key
from classification import classify_course, normalize_course_name
from recommendations import RecommendationError, recommend_for_slot
from requirement_evaluator import evaluate_graduation


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _name_key(name: str, profile: dict) -> str:
    # 既存の別名と全半角・ローマ数字・空白の差だけ。類似名や括弧を推測で統合しない。
    return catalog_name_key(normalize_course_name(name, profile))


def _liberal_selector(selector: dict) -> bool:
    return "liberal_arts" in selector.get("curriculum_areas", []) or any(
        _liberal_selector(item) for item in selector.get("any_of", [])
    )


def _liberal_only_selector(selector: dict) -> bool:
    """教養だけを要求する枠。専門と共用する超過・総計を推薦の起点にしない。"""
    areas = set(selector.get("curriculum_areas", []))
    if areas == {"liberal_arts"}:
        return True
    if areas and "liberal_arts" not in areas:
        return False
    alternatives = selector.get("any_of", [])
    return bool(alternatives) and all(_liberal_only_selector(item) for item in alternatives)


def _baseline(evaluation: dict, ids: set[str]) -> list[dict]:
    keys = ("id", "label", "status", "minimum_credits", "confirmed_credits",
            "confirmed_credit_shortfall", "has_uncertain_candidate")
    return [{key: condition[key] for key in keys} for condition in evaluation["conditions"]
            if condition["id"] in ids]


def search_recommendations(catalog: dict, context: dict, report: dict, timetable: dict, profile: dict) -> dict:
    """全学年で卒業の不足を参照する。候補は個別の仮定であり、履修計画ではない。"""
    rule = profile.get("requirements", {}).get("graduation")
    kinds = {"minimum_credits", "minimum_residual_credits", "shared_surplus_minimum"}
    ids = {condition["id"] for condition in (rule or {}).get("conditions", [])
           if condition["kind"] in kinds and _liberal_selector(condition.get("selector", {}))}
    liberal_ids = {condition["id"] for condition in (rule or {}).get("conditions", [])
                   if condition["kind"] in kinds and _liberal_only_selector(condition.get("selector", {}))}
    if not liberal_ids:
        raise RecommendationError(422, "recommendation_rules_unsupported", "このプロファイルには探索に対応する卒業要件がありません。")
    baseline = _baseline(evaluate_graduation(report, profile=profile), ids)
    liberal_baseline = [item for item in baseline if item["id"] in liberal_ids]
    before_by_id = {item["id"]: item for item in baseline}
    uncertain_rules = rule["status"] == "blocked" or bool(rule["blocking_open_question_ids"])
    result = {"schema_version": 1, "context": context, "target_requirement_id": "graduation",
              "status": "empty", "baseline": baseline, "free_slots": [],
              "candidates": [], "review_candidates": [],
              "counts": {"catalog_in_term": 0, "excluded_earned": 0, "excluded_registered": 0,
                         "excluded_overlap": 0, "excluded_unconfirmed_time": 0,
                         "excluded_no_benefit": 0, "returned": 0, "review_required": 0},
              "checks": {"timetable": "checked", "earned_credits": "checked",
                         "requirements": "needs_review" if uncertain_rules or any(
                             item["status"] == "unknown" for item in liberal_baseline) else "checked",
                         "enrollment": "not_checked"},
              "messages": [
                  {"code": "individual_simulation", "message": "各候補を1科目修得した場合の卒業要件への効果です。候補同士の同時履修は確認していません。"},
                  {"code": "benefits_not_additive", "message": "分類別条件と教養合計・総計の改善量は重なるため合算できません。履修中の単位は修得済みに含めません。"},
                  {"code": "search_scope", "message": "代表科目から探索します。学年で絞らず、修得済みは開講番号または科目名の一致で除外します。先修条件・履修許可は未確認です。"},
                  {"code": "liberal_shortage_scope", "message": "教養の必修・選択必修・選択・合計の不足を改善する科目だけを推薦します。専門との共通超過分や総計だけの不足では推薦しません。"},
              ]}

    def note(code: str, message: str) -> None:
        if not any(item["code"] == code and item["message"] == message for item in result["messages"]):
            result["messages"].append({"code": code, "message": message})

    # 空き時間も既存サービスへ照会し、未掲載枠・期間不明を空きへ変換しない。
    for day in range(1, 6):
        for period in range(1, 6):
            slot_result = recommend_for_slot({"courses": []}, {**context, "weekday": day, "period": period}, timetable)
            if slot_result["status"] == "empty":
                result["free_slots"].append({"weekday": day, "period": period})
            elif slot_result["status"] == "unknown":
                result["checks"]["timetable"] = "needs_review"
            for message in slot_result["messages"]:
                if message["code"] != "scope_note":
                    note(message["code"], message["message"])
    if not uncertain_rules and all(item["status"] == "satisfied" for item in liberal_baseline):
        note("liberal_requirements_satisfied", "教養の必修・選択必修・選択・合計はすべて充足しています。追加の教養科目は推薦しません。")
        return result
    if not timetable["ready_for_recommendation"] or (context["academic_year"], context["term"]) not in {
        (item["academic_year"], item["term"]) for item in timetable["display_contexts"]
    }:
        result["status"] = "unknown"
        return result

    def matches(existing: dict, candidate: dict) -> bool:
        return existing.get("course_code") == candidate["course_code"] or (
            _name_key(existing.get("name", ""), profile) == _name_key(candidate["name"], profile))

    for candidate in sorted(catalog["courses"], key=lambda course: course["course_code"]):
        if context["term"] not in candidate["terms"]:
            continue
        result["counts"]["catalog_in_term"] += 1
        matching = [item for item in report["courses"] if matches(item, candidate)]
        if any(item["status"] == "passed" and item["credits"] is not None for item in matching):
            result["counts"]["excluded_earned"] += 1
            continue
        first = candidate["schedule"][0]
        time_result = recommend_for_slot({"courses": [candidate]}, {**context, **first}, timetable)
        if not time_result["candidates"]:
            count = "excluded_unconfirmed_time" if time_result["status"] == "unknown" else (
                "excluded_registered" if time_result["counts"]["excluded_registered"] else "excluded_overlap")
            result["counts"][count] += 1
            continue
        classification = classify_course(candidate["name"], candidate["category"], "", profile=profile)
        if classification["curriculum_area"] != "liberal_arts":
            # カタログで確認できても、分類器が対象外と判断した科目を仮算入しない。
            result["counts"]["excluded_no_benefit"] += 1
            continue
        hypothetical = {**classification, "name": candidate["name"], "course_code": candidate["course_code"],
                        "credits": candidate["credits"], "status": "passed"}
        after = _baseline(evaluate_graduation({"courses": [*report["courses"], hypothetical]}, profile=profile), ids)
        benefits, uncertain_benefits = [], []
        for condition in after:
            before = before_by_id[condition["id"]]
            reduction = Decimal(str(before["confirmed_credit_shortfall"])) - Decimal(str(condition["confirmed_credit_shortfall"]))
            if reduction <= 0:
                continue
            effect = {"condition_id": condition["id"], "label": condition["label"],
                      "before_shortfall": before["confirmed_credit_shortfall"],
                      "after_shortfall": condition["confirmed_credit_shortfall"],
                      "reduced_credits": _number(reduction), "before_status": before["status"],
                      "after_status": condition["status"]}
            (benefits if before["status"] == "not_satisfied" and not uncertain_rules else uncertain_benefits).append(effect)
        confirmed_liberal_effect = any(effect["condition_id"] in liberal_ids for effect in benefits)
        uncertain_liberal_effect = any(effect["condition_id"] in liberal_ids for effect in uncertain_benefits)
        if not confirmed_liberal_effect and not uncertain_liberal_effect:
            result["counts"]["excluded_no_benefit"] += 1
            continue
        pending_match = any(item["status"] == "unconfirmed" for item in matching)
        item = {**candidate, "benefits": benefits, "uncertain_benefits": uncertain_benefits,
                "review_reasons": ["matching_earned_course_unconfirmed"] if pending_match else []}
        destination = "candidates" if confirmed_liberal_effect and not pending_match else "review_candidates"
        result[destination].append(item)
    result["counts"]["returned"] = len(result["candidates"])
    result["counts"]["review_required"] = len(result["review_candidates"])
    if result["review_candidates"]:
        note("uncertain_credit_effect", "判定不能の不足や同名科目の結果未確定に関わる候補は、要確認の一覧へ分けています。必要科目と確定したものではありません。")
    if result["candidates"]:
        result["status"] = "ok"
    elif result["review_candidates"] or "needs_review" in result["checks"].values() or result["counts"]["excluded_unconfirmed_time"]:
        result["status"] = "unknown"
    return result
