"""年度・プログラム別の学務規則データを読み込み、構造を検証する。"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any


RULES_ROOT = Path(__file__).resolve().parent / "rules"
DEFAULT_PROFILE_PATH = (
    RULES_ROOT
    / "niigata"
    / "engineering"
    / "smart-information-systems"
    / "2025"
    / "profile.json"
)

REQUIREMENT_STATUSES = {"partial", "blocked", "ready"}
EVIDENCE_STATUSES = {"transcribed", "verified", "needs_confirmation"}
CONDITION_KINDS = {
    "minimum_residence_years",
    "minimum_credits",
    "minimum_credits_from_named_courses",
    "minimum_residual_credits",
    "shared_surplus_minimum",
    "required_courses",
}
QUESTION_STATUSES = {"open", "resolved"}
ALLOCATION_KINDS = {
    "credit_cap",
    "exclude_requirement_code",
    "no_double_counting",
    "requires_individual_required_courses",
}
COURSE_AREAS = {"liberal_arts", "faculty_specialized", "unknown"}
COURSE_GROUPS = {"specialized_foundation", "specialized_applied", None}


class RuleDataError(ValueError):
    """規則データがスキーマ上または意味上不正な場合のエラー。"""


class RuleProfileNotFoundError(RuleDataError):
    """指定された規則プロファイルが登録されていない場合のエラー。"""


def _require_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuleDataError(f"{path} はオブジェクトである必要があります")
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise RuleDataError(f"{path} は配列である必要があります")
    return value


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuleDataError(f"{path} は空でない文字列である必要があります")
    return value


def _require_nonnegative_number(value: Any, path: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise RuleDataError(f"{path} は0以上の数値である必要があります")
    return value


def _unique_ids(items: list[Any], path: str) -> set[str]:
    ids: set[str] = set()
    for index, item in enumerate(items):
        mapping = _require_mapping(item, f"{path}[{index}]")
        item_id = _require_string(mapping.get("id"), f"{path}[{index}].id")
        if item_id in ids:
            raise RuleDataError(f"{path} に重複したidがあります: {item_id}")
        ids.add(item_id)
    return ids


def _require_string_list(value: Any, path: str) -> list[str]:
    items = _require_list(value, path)
    for index, item in enumerate(items):
        _require_string(item, f"{path}[{index}]")
    return items


def _validate_source_refs(
    refs: Any,
    path: str,
    source_ids: set[str],
) -> None:
    for index, ref in enumerate(_require_list(refs, path)):
        mapping = _require_mapping(ref, f"{path}[{index}]")
        document_id = _require_string(
            mapping.get("document_id"),
            f"{path}[{index}].document_id",
        )
        if document_id not in source_ids:
            raise RuleDataError(f"{path}[{index}] が未知の資料を参照しています: {document_id}")
        for page_kind in ("printed_pages", "pdf_pages"):
            pages = _require_list(mapping.get(page_kind), f"{path}[{index}].{page_kind}")
            if not pages or any(isinstance(page, bool) or not isinstance(page, int) or page < 1 for page in pages):
                raise RuleDataError(f"{path}[{index}].{page_kind} は1以上のページ番号が必要です")


def _validate_selector(selector: dict[str, Any], path: str) -> None:
    """複合selectorを含め、規則データの最低限の構造を検証する。"""
    if "course_name_contains_any" in selector:
        fragments = _require_string_list(
            selector["course_name_contains_any"], f"{path}.course_name_contains_any"
        )
        if not fragments:
            raise RuleDataError(f"{path}.course_name_contains_any は1件以上必要です")
    alternatives = selector.get("any_of")
    if alternatives is None:
        return
    alternative_list = _require_list(alternatives, f"{path}.any_of")
    if not alternative_list:
        raise RuleDataError(f"{path}.any_of は1件以上必要です")
    for index, alternative in enumerate(alternative_list):
        alternative_path = f"{path}.any_of[{index}]"
        alternative_mapping = _require_mapping(alternative, alternative_path)
        if not alternative_mapping:
            raise RuleDataError(f"{alternative_path} は空にできません")
        _validate_selector(alternative_mapping, alternative_path)


def validate_rule_profile(profile: Any) -> dict[str, Any]:
    """規則プロファイルを検証し、型を絞った同じオブジェクトを返す。"""
    root = _require_mapping(profile, "profile")
    if root.get("schema_version") != 1:
        raise RuleDataError("schema_version=1 の規則データだけを読み込めます")
    _require_string(root.get("profile_id"), "profile.profile_id")
    if "mvp_policy" in root:
        policy = _require_mapping(root["mvp_policy"], "profile.mvp_policy")
        _require_string_list(policy.get("notes"), "profile.mvp_policy.notes")

    scope = _require_mapping(root.get("scope"), "profile.scope")
    for key in ("institution", "faculty", "program"):
        _require_string(scope.get(key), f"profile.scope.{key}")
    admission_year = scope.get("admission_year")
    if isinstance(admission_year, bool) or not isinstance(admission_year, int):
        raise RuleDataError("profile.scope.admission_year は整数である必要があります")

    sources = _require_list(root.get("source_documents"), "profile.source_documents")
    source_ids = _unique_ids(sources, "profile.source_documents")
    if not source_ids:
        raise RuleDataError("profile.source_documents は1件以上必要です")
    for index, source in enumerate(sources):
        mapping = _require_mapping(source, f"profile.source_documents[{index}]")
        _require_string(mapping.get("title"), f"profile.source_documents[{index}].title")
        _require_string(mapping.get("url"), f"profile.source_documents[{index}].url")

    questions = _require_list(root.get("open_questions"), "profile.open_questions")
    question_ids = _unique_ids(questions, "profile.open_questions")
    for index, question in enumerate(questions):
        mapping = _require_mapping(question, f"profile.open_questions[{index}]")
        status = mapping.get("status")
        if status not in QUESTION_STATUSES:
            raise RuleDataError(f"profile.open_questions[{index}].status が不正です")
        _require_string(mapping.get("question"), f"profile.open_questions[{index}].question")

    classification = _require_mapping(root.get("classification"), "profile.classification")
    catalog_path = classification.get("course_catalog_path")
    if catalog_path is not None:
        _require_string(catalog_path, "profile.classification.course_catalog_path")
        if Path(catalog_path).is_absolute() or ".." in Path(catalog_path).parts:
            raise RuleDataError("course_catalog_path はrules配下の相対パスで指定してください")
        if classification.get("outside_catalog_policy") != "liberal_elective":
            raise RuleDataError("科目マスター利用時はoutside_catalog_policyの明示が必要です")
    _require_string_list(
        classification.get("excluded_course_names", []),
        "profile.classification.excluded_course_names",
    )
    if classification.get("evidence_status") not in EVIDENCE_STATUSES:
        raise RuleDataError("profile.classification.evidence_status が不正です")
    prefixes = _require_list(
        classification.get("liberal_category_prefixes"),
        "profile.classification.liberal_category_prefixes",
    )
    if not prefixes:
        raise RuleDataError("教養系科目区分の接頭辞が1件以上必要です")
    for index, prefix in enumerate(prefixes):
        _require_string(prefix, f"profile.classification.liberal_category_prefixes[{index}]")
    specialized_prefixes = _require_list(
        classification.get("faculty_specialized_prefixes"),
        "profile.classification.faculty_specialized_prefixes",
    )
    if not specialized_prefixes:
        raise RuleDataError("専門系科目区分の接頭辞が1件以上必要です")
    for index, prefix in enumerate(specialized_prefixes):
        _require_string(prefix, f"profile.classification.faculty_specialized_prefixes[{index}]")
    _require_string_list(
        classification.get("course_name_ignored_suffixes", []),
        "profile.classification.course_name_ignored_suffixes",
    )
    aliases = _require_mapping(
        classification.get("course_name_aliases", {}),
        "profile.classification.course_name_aliases",
    )
    for alias, canonical_name in aliases.items():
        _require_string(alias, "profile.classification.course_name_aliases key")
        _require_string(
            canonical_name,
            f"profile.classification.course_name_aliases.{alias}",
        )
    groups = _require_list(
        classification.get("specialized_groups"),
        "profile.classification.specialized_groups",
    )
    _unique_ids(groups, "profile.classification.specialized_groups")
    for index, group in enumerate(groups):
        mapping = _require_mapping(group, f"profile.classification.specialized_groups[{index}]")
        _require_string(mapping.get("source_prefix"), f"profile.classification.specialized_groups[{index}].source_prefix")
        _require_string(mapping.get("normalized_value"), f"profile.classification.specialized_groups[{index}].normalized_value")
    codes = _require_mapping(
        classification.get("requirement_type_codes"),
        "profile.classification.requirement_type_codes",
    )
    if set(codes.values()) != {"A", "B", "C", "D", "E"}:
        raise RuleDataError("必選区分コードはA〜Eを一意に定義する必要があります")
    classification_blockers = _require_string_list(
        classification.get("blocking_open_question_ids", []),
        "profile.classification.blocking_open_question_ids",
    )
    unknown_classification_questions = set(classification_blockers) - question_ids
    if unknown_classification_questions:
        raise RuleDataError(
            "profile.classification が未知の要確認事項を参照しています: "
            + ", ".join(sorted(unknown_classification_questions))
        )

    requirements = _require_mapping(root.get("requirements"), "profile.requirements")
    if not requirements:
        raise RuleDataError("profile.requirements は1件以上必要です")
    for requirement_id, requirement in requirements.items():
        _require_string(requirement_id, "profile.requirements key")
        mapping = _require_mapping(requirement, f"profile.requirements.{requirement_id}")
        title = mapping.get("title")
        if title is not None:
            _require_string(title, f"profile.requirements.{requirement_id}.title")
        if mapping.get("status") not in REQUIREMENT_STATUSES:
            raise RuleDataError(f"profile.requirements.{requirement_id}.status が不正です")
        evidence_status = mapping.get("evidence_status")
        if evidence_status not in EVIDENCE_STATUSES:
            raise RuleDataError(f"profile.requirements.{requirement_id}.evidence_status が不正です")
        _validate_source_refs(
            mapping.get("source_refs"),
            f"profile.requirements.{requirement_id}.source_refs",
            source_ids,
        )
        blocking_ids = _require_string_list(
            mapping.get("blocking_open_question_ids", []),
            f"profile.requirements.{requirement_id}.blocking_open_question_ids",
        )
        unknown_ids = set(blocking_ids) - question_ids
        if unknown_ids:
            raise RuleDataError(
                f"profile.requirements.{requirement_id} が未知の要確認事項を参照しています: "
                + ", ".join(sorted(unknown_ids))
            )
        conditions = _require_list(
            mapping.get("conditions"),
            f"profile.requirements.{requirement_id}.conditions",
        )
        condition_ids = _unique_ids(
            conditions,
            f"profile.requirements.{requirement_id}.conditions",
        )
        earlier_condition_ids: set[str] = set()
        for index, condition in enumerate(conditions):
            condition_path = f"profile.requirements.{requirement_id}.conditions[{index}]"
            condition_mapping = _require_mapping(condition, condition_path)
            label = condition_mapping.get("label")
            if label is not None:
                _require_string(label, f"{condition_path}.label")
            if condition_mapping.get("kind") not in CONDITION_KINDS:
                raise RuleDataError(f"{condition_path}.kind が不正です")
            if condition_mapping["kind"] == "required_courses":
                if not classification.get("course_catalog_path"):
                    raise RuleDataError(f"{condition_path} には科目マスターの指定が必要です")
            else:
                _require_nonnegative_number(condition_mapping.get("minimum"), f"{condition_path}.minimum")
            if condition_mapping.get("kind") != "minimum_residence_years":
                selector = _require_mapping(
                    condition_mapping.get("selector"),
                    f"{condition_path}.selector",
                )
                _validate_selector(selector, f"{condition_path}.selector")
                if condition_mapping.get("kind") == "minimum_credits_from_named_courses":
                    names = _require_string_list(
                        selector.get("course_names"),
                        f"{condition_path}.selector.course_names",
                    )
                    if not names:
                        raise RuleDataError(f"{condition_path} には対象科目名が必要です")
                if condition_mapping.get("kind") == "minimum_residual_credits":
                    dependency_ids = _require_string_list(
                        condition_mapping.get("subtract_condition_ids"),
                        f"{condition_path}.subtract_condition_ids",
                    )
                    if not dependency_ids:
                        raise RuleDataError(f"{condition_path} には参照条件が必要です")
                    unknown_dependencies = set(dependency_ids) - condition_ids
                    if unknown_dependencies:
                        raise RuleDataError(
                            f"{condition_path} が未知の条件を参照しています: "
                            + ", ".join(sorted(unknown_dependencies))
                        )
                    if condition_mapping["id"] in dependency_ids:
                        raise RuleDataError(f"{condition_path} は自分自身を参照できません")
                    forward_dependencies = set(dependency_ids) - earlier_condition_ids
                    if forward_dependencies:
                        raise RuleDataError(
                            f"{condition_path} は先に定義された条件だけを参照できます: "
                            + ", ".join(sorted(forward_dependencies))
                        )
                if condition_mapping.get("kind") == "shared_surplus_minimum":
                    dependency_ids = _require_string_list(
                        condition_mapping.get("source_condition_ids"),
                        f"{condition_path}.source_condition_ids",
                    )
                    if not dependency_ids:
                        raise RuleDataError(f"{condition_path} には参照条件が必要です")
                    unknown_dependencies = set(dependency_ids) - condition_ids
                    if unknown_dependencies:
                        raise RuleDataError(
                            f"{condition_path} が未知の条件を参照しています: "
                            + ", ".join(sorted(unknown_dependencies))
                        )
                    if condition_mapping["id"] in dependency_ids:
                        raise RuleDataError(f"{condition_path} は自分自身を参照できません")
                    forward_dependencies = set(dependency_ids) - earlier_condition_ids
                    if forward_dependencies:
                        raise RuleDataError(
                            f"{condition_path} は先に定義された条件だけを参照できます: "
                            + ", ".join(sorted(forward_dependencies))
                        )
            earlier_condition_ids.add(condition_mapping["id"])

        allocation_path = f"profile.requirements.{requirement_id}.allocation_rules"
        allocation_rules = _require_list(mapping.get("allocation_rules"), allocation_path)
        _unique_ids(allocation_rules, allocation_path)
        for index, allocation_rule in enumerate(allocation_rules):
            rule_path = f"{allocation_path}[{index}]"
            rule_mapping = _require_mapping(allocation_rule, rule_path)
            kind = rule_mapping.get("kind")
            if kind not in ALLOCATION_KINDS:
                raise RuleDataError(f"{rule_path}.kind が不正です")
            referenced_conditions = []
            for key in ("from_condition_id", "to_condition_id"):
                if key in rule_mapping:
                    referenced_conditions.append(_require_string(rule_mapping[key], f"{rule_path}.{key}"))
            referenced_conditions.extend(
                _require_string_list(
                    rule_mapping.get("applies_to_condition_ids", []),
                    f"{rule_path}.applies_to_condition_ids",
                )
            )
            unknown_conditions = set(referenced_conditions) - condition_ids
            if unknown_conditions:
                raise RuleDataError(
                    f"{rule_path} が未知の条件を参照しています: "
                    + ", ".join(sorted(unknown_conditions))
                )
            if kind == "credit_cap":
                _require_nonnegative_number(rule_mapping.get("maximum"), f"{rule_path}.maximum")

    return root


def load_rule_profile(path: str | Path = DEFAULT_PROFILE_PATH) -> dict[str, Any]:
    """UTF-8 JSONの規則プロファイルを読み込み、検証する。"""
    profile_path = Path(path)
    try:
        raw = profile_path.read_text(encoding="utf-8")
        profile = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuleDataError(f"規則データを読み込めません: {profile_path}") from exc
    return validate_rule_profile(profile)


def catalog_name_key(name: str) -> str:
    """公式名の全半角・ローマ数字・空白の差だけを照合時に吸収する。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name))


def validate_course_catalog(
    catalog: Any,
    profile: dict[str, Any],
) -> dict[str, Any]:
    """科目マスターを規則プロファイルとの参照整合性も含めて検証する。"""
    root = _require_mapping(catalog, "catalog")
    if root.get("schema_version") != 1:
        raise RuleDataError("科目マスターはschema_version=1である必要があります")
    _require_string(root.get("catalog_id"), "catalog.catalog_id")
    if root.get("profile_id") != profile.get("profile_id"):
        raise RuleDataError("catalog.profile_id が規則プロファイルと一致しません")
    if root.get("evidence_status") not in EVIDENCE_STATUSES:
        raise RuleDataError("catalog.evidence_status が不正です")

    source_ids = {
        _require_string(source.get("id"), "profile.source_documents[].id")
        for source in _require_list(profile.get("source_documents"), "profile.source_documents")
    }
    requirement_ids = set(
        _require_mapping(profile.get("requirements"), "profile.requirements")
    )
    courses = _require_list(root.get("courses"), "catalog.courses")
    _unique_ids(courses, "catalog.courses")
    seen_names: set[str] = set()
    for index, course in enumerate(courses):
        course_path = f"catalog.courses[{index}]"
        mapping = _require_mapping(course, course_path)
        _require_string(mapping.get("name"), f"{course_path}.name")
        course_code = mapping.get("course_code")
        if course_code is not None:
            _require_string(course_code, f"{course_path}.course_code")
        if mapping.get("curriculum_area") not in COURSE_AREAS:
            raise RuleDataError(f"{course_path}.curriculum_area が不正です")
        if mapping.get("course_group") not in COURSE_GROUPS:
            raise RuleDataError(f"{course_path}.course_group が不正です")
        requirement_code = mapping.get("requirement_code")
        if requirement_code is not None and requirement_code not in {"A", "B", "C", "D", "E"}:
            raise RuleDataError(f"{course_path}.requirement_code が不正です")
        credits = mapping.get("credits")
        if credits is not None:
            _require_nonnegative_number(credits, f"{course_path}.credits")
        years = _require_list(mapping.get("standard_years"), f"{course_path}.standard_years")
        if any(isinstance(year, bool) or not isinstance(year, int) or year < 1 for year in years):
            raise RuleDataError(f"{course_path}.standard_years は1以上の整数配列である必要があります")
        _require_string_list(mapping.get("terms", []), f"{course_path}.terms")
        aliases = _require_string_list(mapping.get("aliases", []), f"{course_path}.aliases")
        names = {catalog_name_key(name) for name in [mapping["name"], *aliases]}
        if seen_names & names:
            raise RuleDataError("科目マスターの科目名または別名が複数科目へ一致します")
        seen_names.update(names)
        required_for = _require_string_list(
            mapping.get("required_for", []),
            f"{course_path}.required_for",
        )
        unknown_requirements = set(required_for) - requirement_ids
        if unknown_requirements:
            raise RuleDataError(
                f"{course_path} が未知の要件を参照しています: "
                + ", ".join(sorted(unknown_requirements))
            )
        if required_for and (credits is None or credits <= 0):
            raise RuleDataError(f"{course_path} の必修科目には正の確定単位数が必要です")
        _validate_source_refs(
            mapping.get("source_refs"),
            f"{course_path}.source_refs",
            source_ids,
        )
    for requirement_id, requirement in profile["requirements"].items():
        if any(condition["kind"] == "required_courses" for condition in requirement["conditions"]):
            if not any(requirement_id in course.get("required_for", []) for course in courses):
                raise RuleDataError(f"{requirement_id} の必修科目一覧が空です")
    return root


def load_course_catalog(
    path: str | Path,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """UTF-8 JSONの科目マスターを読み込み、対応する規則とともに検証する。"""
    catalog_path = Path(path)
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuleDataError(f"科目マスターを読み込めません: {catalog_path}") from exc
    return validate_course_catalog(catalog, profile or load_rule_profile())


def load_profile_course_catalog(profile: dict[str, Any]) -> dict[str, Any] | None:
    """選択プロファイルが明示する公開科目マスターだけを読み込む。"""
    relative_path = profile["classification"].get("course_catalog_path")
    if relative_path is None:
        return None
    catalog_path = (RULES_ROOT / relative_path).resolve()
    if not catalog_path.is_relative_to(RULES_ROOT.resolve()):
        raise RuleDataError("科目マスターはrules配下に置いてください")
    return load_course_catalog(catalog_path, profile)


def discover_rule_profiles(root: str | Path = RULES_ROOT) -> list[dict[str, Any]]:
    """追加済みの年度・プログラム別プロファイルを検証して列挙する。"""
    profiles = [load_rule_profile(path) for path in sorted(Path(root).glob("**/profile.json"))]
    profile_ids = [profile["profile_id"] for profile in profiles]
    if len(profile_ids) != len(set(profile_ids)):
        raise RuleDataError("異なるファイルに同じprofile_idが定義されています")
    return profiles


def load_rule_profile_by_id(
    profile_id: str,
    root: str | Path = RULES_ROOT,
) -> dict[str, Any]:
    """列挙・検証済みプロファイルからIDが一致するものだけを返す。"""
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise RuleProfileNotFoundError("規則プロファイルIDを指定してください")
    profiles = {profile["profile_id"]: profile for profile in discover_rule_profiles(root)}
    try:
        return profiles[profile_id]
    except KeyError as exc:
        raise RuleProfileNotFoundError(
            f"未対応の規則プロファイルです: {profile_id}"
        ) from exc


def public_rule_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """画面選択用に、学生データを含まない規則メタデータだけを返す。"""
    scope = profile["scope"]
    return {
        "profile_id": profile["profile_id"],
        "institution": scope["institution"],
        "faculty": scope["faculty"],
        "program": scope["program"],
        "admission_year": scope["admission_year"],
        "policy_notes": profile.get("mvp_policy", {}).get("notes", []),
        "requirements": [
            {
                "requirement_id": requirement_id,
                "title": requirement.get("title", requirement_id),
                "rule_status": requirement["status"],
            }
            for requirement_id, requirement in profile["requirements"].items()
        ],
    }
