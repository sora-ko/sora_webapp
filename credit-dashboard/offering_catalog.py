"""公開の教養開講データの正規化。修得単位・履修許可・推薦順位を判定しない。"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
import re
import unicodedata

from catalog_import import G_CODE, compact


DAYS = {day: index for index, day in enumerate("月火水木金土日", 1)}
CATEGORIES = {"英語", "初修外国語", "健康・スポーツ", "情報リテラシー", "新潟大学個性化科目",
              "留学生基本科目", "大学学習法", "自然系共通専門基礎", "自然科学", "人文社会・教育科学", "医歯学"}
UNCERTAIN_SCHEDULE = ("未定", "指定", "他", "別途", "オンデマンド", "集中")


def display_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    value = re.sub(r"(?<=[ぁ-んァ-ン一-龥])\n|\n(?=[ぁ-んァ-ン一-龥])", "", value)
    return re.sub(r"\s+", " ", value)


def parse_terms(value: str) -> list[int] | None:
    value = compact(value)
    term = re.fullmatch(r"第([1-4](?:[・,][1-4])*)ターム", value)
    if term:
        return sorted({int(item) for item in re.split(r"[・,]", term[1])})
    semester = re.fullmatch(r"第([12])学期", value)
    if semester:
        first = 2 * int(semester[1]) - 1
        return [first, first + 1]
    return [1, 2, 3, 4] if value == "通年" else None


def parse_meetings(weekdays: str, periods: str) -> list[dict] | None:
    """一方が単一の明示リストだけを展開。複数×複数の対応関係は推測しない。"""
    day_text, period_text = compact(weekdays), compact(periods)
    if "\n" in weekdays or "\n" in periods:
        # リストの行折返しだけは結合できる。別行同士の対応は推測しない。
        if not all(line.endswith("・") for line in weekdays.splitlines()[:-1]):
            return None
        if len(periods.splitlines()) > 1:
            return None
    if not re.fullmatch(r"[月火水木金土日](?:・[月火水木金土日])*", day_text):
        return None
    if not re.fullmatch(r"[1-9][0-9]?(?:・[1-9][0-9]?)*", period_text):
        return None
    days = sorted({DAYS[item] for item in day_text.split("・")})
    slots = sorted({int(item) for item in period_text.split("・")})
    if len(days) > 1 and len(slots) > 1:
        return None
    return [{"weekday": day, "period": period} for day in days for period in slots]


def parse_credits(value: str) -> int | float | None:
    try:
        amount = Decimal(compact(value))
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount <= 0:
        return None
    return int(amount) if amount == amount.to_integral_value() else float(amount)


def normalize_offering(record: dict, config: dict) -> dict:
    cells, source = record["cells"], record["source"]
    code = compact(cells["course_code"])
    if not G_CODE.fullmatch(code):
        raise ValueError("Gコード以外は教養推薦カタログの対象外です")
    year = 2000 + int(code[:2])
    code_term = int(code[2])
    reasons = []
    excluded = []
    category = re.fullmatch(r"(.+)\(細区分:(.+)\)", compact(source["heading"]))
    field, detail = category.groups() if category else (None, None)
    if field not in CATEGORIES:
        reasons.append("unknown_category")
    if field in config["scope"]["excluded_categories"]:
        excluded.append("category_out_of_scope")
    name = display_text(cells["name"])
    credits = parse_credits(cells["credits"])
    if not name:
        reasons.append("missing_course_name")
    if credits is None:
        reasons.append("unknown_credits")
    if year != config["academic_year"]:
        reasons.append("academic_year_mismatch")
    terms = parse_terms(cells["offered_period"])
    if terms is None:
        reasons.append("unknown_offered_period")
    if code_term not in range(5):
        reasons.append("unsupported_code_term")
    elif code_term and terms is not None and terms != [code_term]:
        reasons.append("code_period_mismatch")
    if code_term == 0 and config["scope"]["excluded_term_zero_policy"]:
        excluded.append("term_zero_mvp_policy")
    meetings = parse_meetings(cells["weekdays"], cells["periods"])
    if meetings is None:
        combined = compact(cells["weekdays"] + cells["periods"])
        reasons.append("intensive_or_unspecified_schedule" if any(value in combined for value in UNCERTAIN_SCHEDULE)
                       else "ambiguous_or_missing_schedule")
    if compact(cells["remote_type"]) not in {"", "イ"}:
        # ロはオンデマンド。イ・ロの併記も、通常曜限だけで全体を把握したとはしない。
        reasons.append("asynchronous_or_unknown_delivery")
    slots = [] if terms is None or meetings is None else [
        {"term": term, **meeting} for term in terms for meeting in meetings
    ]
    return {
        "offering_id": f"niigata-{year}-{code}",
        "course_code": code, "academic_year": year, "name": name, "credits": credits,
        "category": {"field": field, "detail": detail},
        "discipline_codes": [compact(cells[key]) for key in ["discipline_1", "discipline_2", "discipline_3"] if compact(cells[key])],
        "level_code": compact(cells["level"]),
        "offered_period": {"raw": cells["offered_period"], "terms": terms,
                           "code_term": code_term if code_term else None},
        "schedule": {"weekdays_raw": cells["weekdays"], "periods_raw": cells["periods"],
                     "slots": slots, "status": "known" if terms is not None and meetings is not None else "unknown"},
        "audience_raw": cells["audience"],
        "capacity_raw": cells["capacity"],
        "teaching_type": display_text(cells["teaching_type"]),
        "remote_type": compact(cells["remote_type"]) or None,
        "data_readiness": {"status": "excluded" if excluded else "needs_review" if reasons else "ready",
                           "reason_codes": sorted(set(excluded + reasons))},
        "source_refs": [{**source, "url": config["source"]["url"] + f'#page={source["pdf_page"]}'}],
        "syllabus": {"search_url": config["syllabus"]["search_url"], "academic_year": year,
                     "course_code": code, "description": None, "grading_policy": None,
                     "status": "not_collected_robots_disallow"},
    }


def assess_audience(value: str, target: dict) -> dict:
    """主聴講対象との整合だけを評価する。受講資格・履修許可とは同一視しない。"""
    text = compact(value)
    grade = target.get("grade")
    if "留学生" in text:
        return {"status": "excluded", "reason_code": "international_audience_out_of_scope"}
    # 明示的な工学部除外は、自然系や全学部という語より優先する。
    if re.search(re.escape(target["faculty"]) + r"(?:を除く|以外)", text):
        return {"status": "excluded", "reason_code": "faculty_explicitly_excluded"}
    # 括弧内の条件や他学部との組合せを、単純な学年指定と読み替えない。
    prefixes = ["全学部", target["faculty"], *target.get("additional_primary_audiences", [])]
    basis = next((prefix for prefix in sorted(prefixes, key=len, reverse=True) if text.startswith(prefix)), None)
    if basis is None:
        return {"status": "needs_review", "reason_code": "audience_conditions_need_review", "stated_years": None}
    remainder = text[len(basis):]
    years = None
    match = re.fullmatch(r"([1-4](?:[・,~〜-][1-4])*)年(以上)?", remainder)
    if match:
        if match[2]:
            if not re.fullmatch(r"[1-4]", match[1]):
                return {"status": "needs_review", "reason_code": "ambiguous_year_restriction"}
            years = list(range(int(match[1]), 5))
        elif re.fullmatch(r"[1-4][~〜-][1-4]", match[1]):
            first, last = int(match[1][0]), int(match[1][-1])
            if first > last:
                return {"status": "needs_review", "reason_code": "ambiguous_year_restriction"}
            years = list(range(first, last + 1))
        else:
            years = sorted({int(item) for item in re.split(r"[・,]", match[1])})
        if grade is not None and grade not in years:
            return {"status": "excluded", "reason_code": "stated_grade_does_not_match", "stated_years": years}
        remainder = ""
    elif remainder == "初年次":
        if grade is not None and grade != 1:
            return {"status": "excluded", "reason_code": "stated_grade_does_not_match", "stated_years": [1]}
        years = [1]
        remainder = ""
    if remainder == "" or (basis == "全学部" and remainder == "・研究科"):
        return {"status": "primary_audience_match", "basis": basis, "stated_years": years}
    return {"status": "needs_review", "reason_code": "audience_conditions_need_review", "stated_years": years}


def assess_for_target(offering: dict, target: dict) -> dict:
    data = offering["data_readiness"]
    audience = assess_audience(offering["audience_raw"], target)
    reasons = list(data["reason_codes"])
    if audience.get("reason_code"):
        reasons.append(audience["reason_code"])
    if data["status"] == "excluded" or audience["status"] == "excluded":
        status = "excluded"
    elif data["status"] != "ready" or audience["status"] != "primary_audience_match":
        status = "needs_review"
    else:
        status = "candidate"
    return {"offering_id": offering["offering_id"], "course_code": offering["course_code"],
            "status": status, "reason_codes": sorted(set(reasons)), "primary_audience": audience}


def build_catalog(records: list[dict], config: dict, source_sha256: str) -> tuple[dict, dict, dict]:
    source_rows = [row for row in records if G_CODE.fullmatch(compact(row["cells"]["course_code"]))]
    offerings = [normalize_offering(row, config) for row in source_rows]
    codes = [item["course_code"] for item in offerings]
    if len(set(codes)) != len(codes):
        raise ValueError("同じG開講番号が複数行にあります。機械的に統合せず原資料を確認してください")
    offerings.sort(key=lambda item: item["course_code"])
    assessments = [assess_for_target(item, config["target_profile"]) for item in offerings]
    candidate_ids = {item["offering_id"] for item in assessments if item["status"] == "candidate"}
    metadata = {"schema_version": 1, "institution": config["institution"], "academic_year": config["academic_year"],
                "catalog_id": f'niigata-g-{config["academic_year"]}-v1',
                "source": {**config["source"], "sha256": source_sha256},
                "scope": config["scope"],
                "limitations": ["Gコードの教養開講情報。G以外の科目は対象外。",
                    "主聴講対象との整合確認は履修許可ではない。先修条件・抽選・定員の空き・修得済み科目との重複は未確認。",
                    "授業概要・成績評価方法はシラバスを自動取得せずnull。科目名から推測しない。",
                    f'資料は{config["source"]["source_as_of"]}時点。MVPでは曜限が変更されない前提。現行シラバスとの照合済みを意味しない。',
                    "番号0の除外は利用者指定のMVP方針であり、公式の集中講義判定ではない。"]}
    catalog = {**metadata, "offerings": offerings}
    target_view = {**metadata, "target_profile": config["target_profile"],
                   "candidate_count": len(candidate_ids),
                   "candidates": [item for item in offerings if item["offering_id"] in candidate_ids],
                   "assessments": assessments}
    quality = {
        "schema_version": 1, "academic_year": config["academic_year"],
        "source_rows": len(records), "g_offerings": len(offerings), "non_g_rows_outside_scope": len(records) - len(offerings),
        "category_counts": dict(sorted(Counter(item["category"]["field"] or "unknown" for item in offerings).items())),
        "data_readiness_counts": dict(Counter(item["data_readiness"]["status"] for item in offerings)),
        "target_status_counts": dict(Counter(item["status"] for item in assessments)),
        "target_reason_counts": dict(Counter(reason for item in assessments for reason in item["reason_codes"])),
        "candidate_term_counts": {str(term): sum(term in item["offered_period"]["terms"] for item in target_view["candidates"])
                                  for term in range(1, 5)},
        "description_count": sum(item["syllabus"]["description"] is not None for item in offerings),
    }
    validate_catalog(catalog)
    for item in target_view["candidates"]:
        if item["data_readiness"]["status"] != "ready" or not item["schedule"]["slots"]:
            raise ValueError("未確認の科目を候補へ混入させてはいけません")
    return catalog, target_view, quality


def validate_catalog(catalog: dict) -> None:
    if catalog.get("schema_version") != 1 or not isinstance(catalog.get("offerings"), list):
        raise ValueError("カタログの版またはofferingsが不正です")
    seen = set()
    for item in catalog["offerings"]:
        code = item["course_code"]
        if not G_CODE.fullmatch(code) or code in seen or item["academic_year"] != catalog["academic_year"]:
            raise ValueError("カタログの年度・番号・一意性が不正です")
        seen.add(code)
        if item["data_readiness"]["status"] == "ready":
            if not item["name"] or item["credits"] is None or item["credits"] <= 0 or not item["schedule"]["slots"]:
                raise ValueError("ready科目の必須情報が不足しています")
            if item["data_readiness"]["reason_codes"] or item["category"]["field"] not in CATEGORIES:
                raise ValueError("未確認の科目をreadyにできません")
        tuples = []
        for slot in item["schedule"]["slots"]:
            if slot["term"] not in range(1, 5) or slot["weekday"] not in range(1, 8) or slot["period"] not in range(1, 100):
                raise ValueError("曜限の範囲が不正です")
            tuples.append((slot["term"], slot["weekday"], slot["period"]))
        if len(tuples) != len(set(tuples)):
            raise ValueError("曜限が重複しています")


def common_offerings(offerings: list[dict], target: dict) -> list[dict]:
    """全学部向け。学年は絞り込まず、曜限が丸ごと範囲内にあるもの。"""
    return sorted((item for item in offerings
                   if item["data_readiness"]["status"] == "ready"
                   and compact(item["audience_raw"]).startswith("全学部")
                   and assess_audience(item["audience_raw"], {**target, "grade": None})["status"] == "primary_audience_match"
                   and item["schedule"]["slots"]
                   and all(slot["weekday"] in range(1, 6) and slot["period"] in range(1, 6)
                           for slot in item["schedule"]["slots"])), key=lambda item: item["course_code"])


def coverage_features(offering: dict) -> set[tuple]:
    """元候補の曜限と、タームごとの要件計算用大区分を保持するための集合。"""
    slots = offering["schedule"]["slots"]
    return ({("slot", slot["term"], slot["weekday"], slot["period"]) for slot in slots}
            | {("category", slot["term"], offering["category"]["field"]) for slot in slots})


def representative_offerings(offerings: list[dict]) -> list[dict]:
    """未保持の曜限・区分を多く補える科目から採用する。最小件数の保証はしない。"""
    remaining = set().union(*(coverage_features(item) for item in offerings))
    universe = set(remaining)
    choices = sorted(offerings, key=lambda item: item["course_code"])
    selected = []
    while remaining:
        best = max(choices, key=lambda item: len(coverage_features(item) & remaining))
        selected.append(best)
        remaining -= coverage_features(best)
        choices.remove(best)
    for item in list(reversed(selected)):
        others = [other for other in selected if other is not item]
        if set().union(*(coverage_features(other) for other in others)) == universe:
            selected.remove(item)
    return sorted(selected, key=lambda item: item["course_code"])


def summarize_coverage(offerings: list[dict]) -> dict:
    """ターム×曜日×時限の100枠。複数曜限の同じ科目も枠ごとに数える。"""
    counts = Counter((slot["term"], slot["weekday"], slot["period"])
                     for item in offerings for slot in item["schedule"]["slots"]
                     if slot["weekday"] in range(1, 6) and slot["period"] in range(1, 6))
    missing = [{"term": term, "weekday": day, "period": period}
               for term in range(1, 5) for day in range(1, 6) for period in range(1, 6)
               if not counts[term, day, period]]
    return {
        "course_count": len(offerings), "total_slots": 100, "covered_slots": 100 - len(missing),
        "missing_slots": missing,
        "matrices": {str(term): [[counts[term, day, period] for day in range(1, 6)] for period in range(1, 6)]
                     for term in range(1, 5)},
        "term_period_counts": {str(term): [sum(any(slot["term"] == term and slot["period"] == period
                                                   and slot["weekday"] in range(1, 6)
                                                   for slot in item["schedule"]["slots"])
                                               for item in offerings)
                                          for period in range(1, 6)] for term in range(1, 5)},
    }


def compact_course(offering: dict) -> dict:
    terms = offering["offered_period"]["terms"]
    by_term = [{(slot["weekday"], slot["period"]) for slot in offering["schedule"]["slots"] if slot["term"] == term}
               for term in terms]
    if not by_term or not by_term[0] or any(slots != by_term[0] for slots in by_term):
        raise ValueError("タームごとに異なる曜限を単純化してはいけません")
    field, detail = offering["category"]["field"], offering["category"]["detail"]
    return {"course_code": offering["course_code"], "name": offering["name"], "credits": offering["credits"],
            "category": f"{field}（{detail}）", "terms": terms,
            "schedule": [{"weekday": day, "period": period} for day, period in sorted(by_term[0])]}


def build_compact_catalog(catalog: dict, config: dict) -> tuple[dict, dict]:
    target = config["target_profile"]
    pool = common_offerings(catalog["offerings"], target)
    selected = representative_offerings(pool)
    result = {"schema_version": 3, "academic_year": config["academic_year"],
              "profile_id": target["profile_id"],
              "courses": [compact_course(item) for item in selected]}
    report = {"pool": summarize_coverage(pool), "selected": summarize_coverage(selected)}
    return result, report
