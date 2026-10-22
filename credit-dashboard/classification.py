"""2025年度知能情報システムプログラム向けの科目分類規則。"""

from __future__ import annotations

import re


CURRICULUM_PROFILE = {
    "institution": "新潟大学",
    "faculty": "工学部",
    "program": "知能情報システムプログラム",
    "admission_year": 2025,
    "rules_version": "niigata-engineering-sis-2025-v1",
}

LIBERAL_CATEGORY_PREFIXES = (
    "大学学習法",
    "英語",
    "初修外国語",
    "健康・スポーツ",
    "情報リテラシー",
    "自然系共通専門基礎",
    "自然科学",
    "人文社会・教育科学",
    "新潟大学個性化科目",
    "医歯学",
    "留学生基本科目",
)


def classify_category(category: str) -> tuple[str, str, str | None, str, str]:
    """元CSVの科目区分を、根拠がある範囲だけ大分類へ正規化する。"""
    if category.startswith("専門"):
        major = "専門"
        curriculum_area = "faculty_specialized"
        classification_status = "classified"
    elif category.startswith(LIBERAL_CATEGORY_PREFIXES):
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
) -> tuple[str | None, str | None]:
    """専門科目群とA〜Eコードを正規化する。"""
    if not category.startswith("専門"):
        return None, None
    course_group = (
        "specialized_foundation"
        if category.startswith("専門基礎")
        else "specialized_applied"
        if category.startswith("専門応用")
        else None
    )
    requirement_code = {
        "必修": "A",
        "選択必修": "B",
        "選択": "C",
        "特殊選択": "D",
        "自由": "E",
    }.get(requirement_type)
    return course_group, requirement_code
