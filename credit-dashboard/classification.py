"""選択された年度・プログラム別プロファイルによる科目分類。"""

from __future__ import annotations

import re

from academic_rules import catalog_name_key, load_profile_course_catalog, load_rule_profile


_RULE_PROFILE = load_rule_profile()
_SCOPE = _RULE_PROFILE["scope"]
_CLASSIFICATION = _RULE_PROFILE["classification"]


def curriculum_profile(profile: dict | None = None) -> dict:
    """APIへ返す規則スコープを、選択されたプロファイルから生成する。"""
    selected = profile or _RULE_PROFILE
    scope = selected["scope"]
    return {
        "institution": scope["institution"],
        "faculty": scope["faculty"],
        "program": scope["program"],
        "admission_year": scope["admission_year"],
        "rules_version": selected["profile_id"],
        "policy_notes": selected.get("mvp_policy", {}).get("notes", []),
    }


CURRICULUM_PROFILE = curriculum_profile()
LIBERAL_CATEGORY_PREFIXES = tuple(_CLASSIFICATION["liberal_category_prefixes"])
FACULTY_SPECIALIZED_PREFIXES = tuple(_CLASSIFICATION["faculty_specialized_prefixes"])
SPECIALIZED_GROUPS = tuple(_CLASSIFICATION["specialized_groups"])
REQUIREMENT_TYPE_CODES = dict(_CLASSIFICATION["requirement_type_codes"])


def normalize_course_name(name: str, profile: dict | None = None) -> str:
    """プロファイルで明示したCSV表示用接尾辞だけを照合時に除去する。"""
    classification = (profile or _RULE_PROFILE)["classification"]
    normalized = name.strip()
    suffixes = sorted(
        classification.get("course_name_ignored_suffixes", []),
        key=len,
        reverse=True,
    )
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if normalized.endswith(suffix):
                normalized = normalized.removesuffix(suffix).rstrip()
                changed = True
                break
    return classification.get("course_name_aliases", {}).get(normalized, normalized)


def classify_category(
    category: str,
    profile: dict | None = None,
) -> tuple[str, str, str | None, str, str]:
    """元CSVの科目区分を、根拠がある範囲だけ大分類へ正規化する。"""
    classification = (profile or _RULE_PROFILE)["classification"]
    specialized_prefixes = tuple(classification["faculty_specialized_prefixes"])
    liberal_prefixes = tuple(classification["liberal_category_prefixes"])
    if category.startswith(specialized_prefixes):
        major = "専門"
        curriculum_area = "faculty_specialized"
        classification_status = "classified"
    elif category.startswith(liberal_prefixes):
        major = "教養"
        curriculum_area = "liberal_arts"
        classification_status = "classified"
    else:
        major = "不明"
        curriculum_area = "unknown"
        classification_status = "unknown"
    match = re.fullmatch(r"(.+?)（(.+)）", category)
    if match:
        return major, match.group(1), match.group(2), curriculum_area, classification_status
    return major, category, None, curriculum_area, classification_status


def classify_specialized(
    category: str,
    requirement_type: str,
    profile: dict | None = None,
) -> tuple[str | None, str | None]:
    """専門科目群とA〜Eコードを正規化する。"""
    classification = (profile or _RULE_PROFILE)["classification"]
    specialized_prefixes = tuple(classification["faculty_specialized_prefixes"])
    if not category.startswith(specialized_prefixes):
        return None, None
    course_group = next(
        (
            group["normalized_value"]
            for group in classification["specialized_groups"]
            if category.startswith(group["source_prefix"])
        ),
        None,
    )
    requirement_code = classification["requirement_type_codes"].get(requirement_type)
    return course_group, requirement_code


def course_catalog_index(profile: dict | None = None) -> dict[str, dict] | None:
    """一回の解析で使う公開科目マスターの名前索引を作る。"""
    catalog = load_profile_course_catalog(profile or _RULE_PROFILE)
    if catalog is None:
        return None
    return {
        catalog_name_key(name): course
        for course in catalog["courses"]
        for name in [course["name"], *course.get("aliases", [])]
    }


def classify_course(
    name: str,
    category: str,
    requirement_type: str,
    *,
    profile: dict | None = None,
    catalog_index: dict[str, dict] | None = None,
) -> dict:
    """CSV区分の分類後、選択プロファイルの科目一覧とMVP方針を適用する。"""
    selected = profile or _RULE_PROFILE
    classification = selected["classification"]
    major, field, detail, area, status = classify_category(category, selected)
    group, code = classify_specialized(category, requirement_type, selected)
    normalized_name = normalize_course_name(name, selected)
    reason = "source_category" if status == "classified" else "unknown_category"
    catalog_id = None

    excluded_names = {
        catalog_name_key(value)
        for value in classification.get("excluded_course_names", [])
    }
    if catalog_name_key(normalized_name) in excluded_names:
        major, area, status = "対象外", "excluded", "classified"
        group, code = None, None
        reason = "excluded_by_mvp_policy"
    elif area == "faculty_specialized" and classification.get("course_catalog_path"):
        if catalog_index is None:
            catalog_index = course_catalog_index(selected)
        match = catalog_index.get(catalog_name_key(normalized_name))
        if match is not None:
            group, code = match["course_group"], match["requirement_code"]
            normalized_name = match["name"]
            catalog_id = match["id"]
            reason = "selected_program_catalog"
        elif classification["outside_catalog_policy"] == "liberal_elective":
            major, area = "教養", "liberal_arts"
            field, detail = "対象専門科目一覧外", field
            group, code = None, None
            reason = "outside_catalog_as_liberal"

    return {
        "normalized_name": normalized_name,
        "major": major,
        "field": field,
        "detail": detail,
        "curriculum_area": area,
        "classification_status": status,
        "course_group": group,
        "requirement_code": code,
        "catalog_course_id": catalog_id,
        "classification_reason_code": reason,
    }
