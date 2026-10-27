"""公開カタログの曜限検索と、メモリ上の履修表による時間重複の除外。"""

from __future__ import annotations

import json
import math
from pathlib import Path
import re

from academic_rules import load_rule_profile_by_id
from classification import classify_category


class RecommendationError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def _valid_int(value, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def validate_catalog(data: dict) -> None:
    if not isinstance(data, dict) or data.get("schema_version") != 3:
        raise ValueError("unsupported catalog")
    year = data.get("academic_year")
    if not _valid_int(year, 2000, 2099):
        raise ValueError("invalid context")
    profile = load_rule_profile_by_id(data.get("profile_id"))
    courses = data.get("courses")
    if not isinstance(courses, list) or len(courses) > 5000:
        raise ValueError("invalid courses")
    seen = set()
    for course in courses:
        if not isinstance(course, dict) or set(course) != {"course_code", "name", "credits", "category", "terms", "schedule"}:
            raise ValueError("invalid course shape")
        code = course["course_code"]
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{2}[1-4]G[0-9]{4}", code):
            raise ValueError("unsupported course code")
        if code in seen or int(code[:2]) + 2000 != year:
            raise ValueError("duplicate or wrong year")
        seen.add(code)
        if any(not isinstance(course[key], str) or not course[key].strip() or len(course[key]) > 500
               for key in ["name", "category"]):
            raise ValueError("invalid label")
        if classify_category(course["category"], profile)[0] != "教養":
            raise ValueError("unknown category")
        credits = course["credits"]
        if type(credits) not in {int, float} or not math.isfinite(credits) or credits <= 0:
            raise ValueError("invalid credits")
        terms = course["terms"]
        if not isinstance(terms, list) or terms != [int(code[2])]:
            raise ValueError("code and terms do not match")
        slots = course["schedule"]
        if not isinstance(slots, list) or not slots:
            raise ValueError("missing schedule")
        unique = set()
        for slot in slots:
            if not isinstance(slot, dict) or set(slot) != {"weekday", "period"}:
                raise ValueError("invalid schedule shape")
            if not _valid_int(slot["weekday"], 1, 5) or not _valid_int(slot["period"], 1, 5):
                raise ValueError("invalid schedule")
            unique.add((slot["weekday"], slot["period"]))
        if len(unique) != len(slots):
            raise ValueError("duplicate schedule")


def load_catalogs(root: Path) -> list[dict]:
    catalogs = []
    identities = set()
    try:
        for path in sorted(root.rglob("liberal-catalog.json")):
            if any(part in {"archive", "sources"} for part in path.relative_to(root).parts):
                continue
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("oversized catalog")
            data = json.loads(path.read_text(encoding="utf-8"))
            validate_catalog(data)
            identity = (data["academic_year"], data["profile_id"])
            if identity in identities:
                raise ValueError("ambiguous catalog")
            identities.add(identity)
            catalogs.append(data)
    except (ValueError, OSError, KeyError, TypeError, OverflowError) as error:
        raise RecommendationError(503, "recommendation_catalog_invalid", "推薦用カタログを読み取れません。配置と形式を確認してください。") from error
    return catalogs


def catalog_metadata(catalog: dict) -> dict:
    profile = load_rule_profile_by_id(catalog["profile_id"])
    return {"academic_year": catalog["academic_year"], "profile_id": catalog["profile_id"],
            "program": profile["scope"]["program"],
            "course_count": len(catalog["courses"]),
            "terms": sorted({term for course in catalog["courses"] for term in course["terms"]}),
            "weekdays": list(range(1, 6)), "periods": list(range(1, 6))}


def find_catalog(catalogs: list[dict], context: dict) -> dict:
    for catalog in catalogs:
        if (catalog["academic_year"], catalog["profile_id"]) == (
            context["academic_year"], context["profile_id"]
        ):
            return catalog
    raise RecommendationError(404, "recommendation_catalog_not_found", "この年度・プロファイルの教養候補データはありません。")


def recommend_for_slot(catalog: dict, context: dict, timetable: dict | None = None) -> dict:
    matching = [course for course in catalog["courses"] if context["term"] in course["terms"]
                and {"weekday": context["weekday"], "period": context["period"]} in course["schedule"]]
    matching.sort(key=lambda course: course["course_code"])
    result = {"schema_version": 1, "context": context,
              "basis": "timetable" if timetable is not None else "catalog",
              "status": "ok", "candidates": [],
              "counts": {"matching": len(matching), "returned": 0, "excluded_overlap": 0,
                         "excluded_unconfirmed": 0, "excluded_registered": 0},
              "checks": {"timetable": "checked" if timetable is not None else "not_provided",
                         "earned_credits": "not_checked", "requirements": "not_checked", "enrollment": "not_checked"},
              "messages": [{"code": "scope_note", "message": "代表科目からの候補です。修得済み・不足単位・先修条件・履修許可は未確認です。"}]}
    if timetable is None:
        result["candidates"] = matching
        result["messages"].append({"code": "timetable_not_provided", "message": "履修表未読込のため、登録済み授業との時間重複は確認していません。"})
    else:
        def hold(code: str, message: str) -> dict:
            result["status"] = "unknown"
            result["checks"]["timetable"] = "needs_review"
            result["messages"].append({"code": code, "message": message})
            return result

        for note in timetable["policy_notes"]:
            result["messages"].append({"code": "timetable_policy", "message": note})
        represented = {(item["academic_year"], item["term"]) for item in timetable["display_contexts"]}
        target = (context["academic_year"], context["term"])
        if not timetable["ready_for_recommendation"]:
            return hold("timetable_unconfirmed", "履修表に未解決の情報や期間の矛盾があるため、候補の判定を保留しました。")
        if target not in represented:
            return hold("timetable_period_unconfirmed", "選択した年度・タームを履修表で確認できないため、候補の判定を保留しました。")
        busy = {(slot["academic_year"], slot["term"], slot["weekday"], slot["period"])
                for slot in timetable["busy_slots"]}
        clicked = (*target, context["weekday"], context["period"])
        if clicked in busy:
            result["status"] = "occupied"
            result["counts"]["excluded_overlap"] = len(matching)
            result["messages"].append({"code": "slot_occupied", "message": "選択した枠には通常授業があります。"})
            return result
        if context["weekday"] not in timetable["represented_weekdays"] or context["period"] not in timetable["represented_periods"]:
            result["status"] = "unknown"
            result["checks"]["timetable"] = "needs_review"
            result["messages"].append({"code": "slot_unconfirmed", "message": "選択した枠は履修表で確認できていません。"})
            return result
        registered = {course["course_code"] for course in timetable["courses"]}
        for course in matching:
            if course["course_code"] in registered:
                result["counts"]["excluded_registered"] += 1
                continue
            slots = {(context["academic_year"], term, slot["weekday"], slot["period"])
                     for term in course["terms"] for slot in course["schedule"]}
            if slots & busy:
                result["counts"]["excluded_overlap"] += 1
            elif any((year, term) not in represented or day not in timetable["represented_weekdays"]
                     or period not in timetable["represented_periods"] for year, term, day, period in slots):
                result["counts"]["excluded_unconfirmed"] += 1
            else:
                result["candidates"].append(course)
    result["counts"]["returned"] = len(result["candidates"])
    if not result["candidates"]:
        result["status"] = "unknown" if result["counts"]["excluded_unconfirmed"] else "empty"
        if result["status"] == "unknown":
            result["checks"]["timetable"] = "needs_review"
    return result
