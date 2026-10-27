import pytest

from requirement_evaluator import (
    evaluate_fourth_year_progression,
    evaluate_graduation,
    evaluate_second_year_progression,
    evaluate_supported_requirements,
    requirement_ids_for_grade,
)


def course(
    name,
    credits,
    *,
    area="liberal_arts",
    requirement_code=None,
    status="passed",
    field=None,
    course_group=None,
    normalized_name=None,
    requirement_type=None,
):
    return {
        "name": name,
        "normalized_name": normalized_name or name,
        "credits": credits,
        "curriculum_area": area,
        "course_group": course_group,
        "requirement_code": requirement_code,
        "requirement_type": requirement_type,
        "field": field,
        "classification_status": "classified" if area != "unknown" else "unknown",
        "status": status,
    }


def report_with(total_credits, designated_credits=4, extra_courses=None):
    courses = [course("総合工学概論", designated_credits)]
    remainder = total_credits - designated_credits
    if remainder:
        courses.append(course("架空一般科目", remainder))
    courses.extend(extra_courses or [])
    return {"courses": courses}


def condition(result, condition_id):
    return next(item for item in result["conditions"] if item["id"] == condition_id)


@pytest.mark.parametrize(
    ("credits", "expected"),
    [(31, "not_satisfied"), (32, "satisfied"), (33, "satisfied")],
)
def test_second_year_total_credit_boundary(credits, expected):
    result = evaluate_second_year_progression(report_with(credits), residence_years=1)
    assert condition(result, "total_credits")["status"] == expected
    assert result["status"] == expected


@pytest.mark.parametrize(
    ("credits", "expected"),
    [(3, "not_satisfied"), (4, "satisfied"), (5, "satisfied")],
)
def test_designated_course_credit_boundary(credits, expected):
    result = evaluate_second_year_progression(report_with(32, designated_credits=credits), residence_years=1)
    assert condition(result, "designated_course_group")["status"] == expected
    assert result["status"] == expected


def test_d_credit_is_not_counted_for_second_year_total():
    report = report_with(31, extra_courses=[
        course(
            "架空特殊選択科目",
            1,
            area="faculty_specialized",
            requirement_code="D",
        )
    ])
    result = evaluate_second_year_progression(report, residence_years=1)
    total = condition(result, "total_credits")
    assert total["confirmed_credits"] == 31
    assert total["status"] == "not_satisfied"


def test_uncertain_course_does_not_become_failure():
    report = report_with(31, extra_courses=[course("履修結果未確定科目", 2, status="unconfirmed")])
    result = evaluate_second_year_progression(report, residence_years=1)
    total = condition(result, "total_credits")
    assert total["status"] == "unknown"
    assert result["status"] == "unknown"


def test_missing_residence_is_unknown_even_when_credit_conditions_are_satisfied():
    result = evaluate_second_year_progression(report_with(32))
    assert condition(result, "minimum_residence")["status"] == "unknown"
    assert result["status"] == "unknown"
    assert result["advisory_only"] is True
    assert result["description"]
    assert condition(result, "minimum_residence")["description"]
    assert result["sources"][0]["url"].startswith("https://")
    assert {item["id"] for item in result["caveats"]} == set(result["caveat_ids"])


def test_supported_requirement_dispatch_is_profile_driven():
    report = report_with(32)
    report["student"] = {"grade": "1年"}
    results = evaluate_supported_requirements(report, residence_years=1)
    assert [item["requirement_id"] for item in results] == [
        "progression_year_2",
        "graduation",
    ]


@pytest.mark.parametrize(
    ("grade", "expected"),
    [
        (1, ("progression_year_2", "graduation")),
        (2, ("progression_year_4", "graduation")),
        (3, ("progression_year_4", "graduation")),
        (4, ("graduation",)),
    ],
)
def test_requirement_ids_follow_student_grade(grade, expected):
    assert requirement_ids_for_grade(grade) == expected


def test_graduation_liberal_categories_allocate_without_double_counting():
    report = {
        "student": {"grade": "4年"},
        "courses": [
            course("工学リテラシー入門（架空分野）", 2, field="大学学習法", requirement_type="必修"),
            course("架空英語", 2, field="英語", requirement_type="選択必修"),
            course("架空初修外国語", 2, field="初修外国語", requirement_type="選択"),
            course("健康スポーツ科学実習Ⅰ", 1, field="健康・スポーツ", requirement_type="必修"),
            course("エンジニアのためのデータサイエンス入門", 2, field="情報リテラシー／自然系共通専門基礎", requirement_type="必修"),
            course("架空人文社会必修", 4, field="人文社会・教育科学", requirement_type="選択"),
            course("架空個性化選択必修", 2, field="新潟大学個性化科目", requirement_type="選択"),
            course("架空自然系基礎", 10, field="情報リテラシー／自然系共通専門基礎", requirement_type="選択"),
            course("架空自由教養", 13, field="自然科学", requirement_type="選択"),
        ],
    }
    result = evaluate_graduation(report)
    assert result["status"] == "not_satisfied"
    assert condition(result, "liberal_natural_foundation")["confirmed_credits"] == 23
    assert condition(result, "liberal_elective")["confirmed_credits"] == 13
    assert condition(result, "liberal_total")["confirmed_credits"] == 38
    assert all(
        condition(result, condition_id)["status"] == "satisfied"
        for condition_id in (
            "liberal_university_study",
            "liberal_english",
            "liberal_initial_language",
            "liberal_health_sports",
            "liberal_information_literacy",
            "liberal_humanities_social_required",
            "liberal_humanities_personalization_required_elective",
            "liberal_natural_foundation",
            "liberal_elective",
            "liberal_total",
        )
    )


def test_personalization_course_counts_toward_humanities_required_elective():
    report = {
        "courses": [
            course(
                "架空人文社会必修",
                4,
                field="人文社会・教育科学",
                requirement_type="選択",
            ),
            course(
                "架空個性化選択必修",
                2,
                field="新潟大学個性化科目",
                requirement_type="選択",
            ),
        ]
    }

    result = evaluate_graduation(report)

    assert condition(result, "liberal_humanities_social_required")["status"] == "satisfied"
    required_elective = condition(
        result,
        "liberal_humanities_personalization_required_elective",
    )
    assert required_elective["confirmed_credits"] == 2
    assert required_elective["status"] == "satisfied"


def test_liberal_minimum_buckets_are_removed_before_elective_residual():
    report = {
        "courses": [
            course(
                "架空人文社会科目",
                4,
                field="人文社会・教育科学",
                requirement_type="選択",
            ),
            course(
                "架空自然系選択",
                10,
                field="自然系共通専門基礎",
                requirement_type="選択",
            ),
        ]
    }

    result = evaluate_graduation(report)

    assert condition(result, "liberal_humanities_social_required")["confirmed_credits"] == 4
    assert condition(result, "liberal_humanities_social_required")["status"] == "satisfied"
    assert condition(result, "liberal_humanities_personalization_required_elective")["confirmed_credits"] == 0
    assert condition(result, "liberal_natural_foundation")["confirmed_credits"] == 10
    assert condition(result, "liberal_natural_foundation")["status"] == "satisfied"
    assert condition(result, "liberal_elective")["confirmed_credits"] == 0


@pytest.mark.parametrize("evaluator", [evaluate_fourth_year_progression, evaluate_graduation])
@pytest.mark.parametrize(
    ("subjects", "expected_credits", "expected_status", "elective"),
    [
        ([('自然科学', 10)], 10, 'satisfied', 0),
        ([('自然系共通専門基礎', 6), ('自然科学', 4)], 10, 'satisfied', 0),
        ([('情報リテラシー', 2), ('自然科学', 8)], 10, 'satisfied', 0),
        ([('自然科学', 9)], 9, 'not_satisfied', 0),
        ([('自然科学', 12)], 12, 'satisfied', 2),
    ],
)
def test_natural_required_elective_combines_all_three_official_categories(
    evaluator, subjects, expected_credits, expected_status, elective,
):
    report = {"courses": [course(f"架空教養{i}", credits, field=field) for i, (field, credits) in enumerate(subjects)]}
    result = evaluator(report)
    natural = condition(result, "liberal_natural_foundation")
    assert natural["confirmed_credits"] == expected_credits
    assert natural["status"] == expected_status
    assert condition(result, "liberal_elective")["confirmed_credits"] == elective


@pytest.mark.parametrize("evaluator", [evaluate_fourth_year_progression, evaluate_graduation])
def test_required_data_science_credits_cannot_fill_natural_required_elective(evaluator):
    report = {"courses": [
        course("エンジニアのためのデータサイエンス入門", 2, field="情報リテラシー"),
        course("架空自然科学", 8, field="自然科学"),
    ]}
    result = evaluator(report)
    assert condition(result, "liberal_information_literacy")["confirmed_credits"] == 2
    assert condition(result, "liberal_natural_foundation")["confirmed_credits"] == 8
    assert condition(result, "liberal_natural_foundation")["status"] == "not_satisfied"
    assert condition(result, "liberal_elective")["confirmed_credits"] == 0


@pytest.mark.parametrize("name", [
    "工学リテラシー入門", "工学リテラシー入門(情報電子分野)",
    "工学リテラシー入門（架空分野）", "架空工学リテラシー入門・演習",
])
def test_engineering_literacy_matches_substring_without_field_suffix_restriction(name):
    result = evaluate_graduation({"courses": [course(name, 2, field="大学学習法")]})
    assert condition(result, "liberal_university_study")["confirmed_credits"] == 2


def test_other_university_study_course_does_not_fill_engineering_literacy():
    result = evaluate_graduation({"courses": [course("架空大学学習法", 2, field="大学学習法")]})
    assert condition(result, "liberal_university_study")["confirmed_credits"] == 0
    assert condition(result, "liberal_elective")["confirmed_credits"] == 2


def fourth_year_satisfied_report():
    return {
        "student": {"grade": "3年"},
        "courses": [
            course("架空専門基礎B", 10, area="faculty_specialized", requirement_code="B", course_group="specialized_foundation"),
            course("架空専門応用A", 19, area="faculty_specialized", requirement_code="A", course_group="specialized_applied"),
            course("架空専門応用B", 26, area="faculty_specialized", requirement_code="B", course_group="specialized_applied"),
            course("架空専門応用C", 17, area="faculty_specialized", requirement_code="C", course_group="specialized_applied"),
            course("工学リテラシー入門（架空分野）", 2, field="大学学習法", requirement_type="必修"),
            course("架空英語", 2, field="英語", requirement_type="選択必修"),
            course("架空初修外国語", 2, field="初修外国語", requirement_type="選択"),
            course("健康スポーツ科学実習Ⅰ", 1, field="健康・スポーツ", requirement_type="必修"),
            course("エンジニアのためのデータサイエンス入門", 2, field="情報リテラシー／自然系共通専門基礎", requirement_type="必修"),
            course("架空人文社会必修", 4, field="人文社会・教育科学", requirement_type="選択"),
            course("架空個性化選択必修", 2, field="新潟大学個性化科目", requirement_type="選択"),
            course("架空自然系基礎", 10, field="自然系共通専門基礎", requirement_type="選択"),
            course("架空自由教養", 7, field="自然科学", requirement_type="選択"),
        ],
    }


def test_fourth_year_overall_is_satisfied_when_every_condition_is_satisfied():
    result = evaluate_fourth_year_progression(
        fourth_year_satisfied_report(),
        residence_years=3,
    )

    assert all(item["status"] == "satisfied" for item in result["conditions"])
    assert result["status"] == "satisfied"


def test_fourth_year_foundation_b_surplus_is_deterministically_transferred():
    report = fourth_year_satisfied_report()
    foundation_b = next(
        item for item in report["courses"]
        if item["name"] == "架空専門基礎B"
    )
    applied_b = next(
        item for item in report["courses"]
        if item["name"] == "架空専門応用B"
    )
    foundation_b["credits"] = 12
    applied_b["credits"] = 24

    result = evaluate_fourth_year_progression(report, residence_years=3)

    applied_b_condition = condition(result, "specialized_applied_b")
    assert applied_b_condition["status"] == "satisfied"
    assert applied_b_condition["confirmed_credits"] == 26
    assert applied_b_condition["allocated_by_condition"] == {
        "specialized_foundation_b": 10,
    }
    assert result["status"] == "satisfied"


def test_fourth_year_applied_pool_uses_only_credits_left_after_b_minimum():
    report = {
        "courses": [
            course("架空専門基礎B", 10, area="faculty_specialized", requirement_code="B", course_group="specialized_foundation"),
            course("架空専門応用B", 26, area="faculty_specialized", requirement_code="B", course_group="specialized_applied"),
        ]
    }

    result = evaluate_fourth_year_progression(report, residence_years=3)
    pool = condition(result, "specialized_applied_pool")

    assert pool["confirmed_area_credits"] == 36
    assert pool["allocated_to_prior_conditions"] == 36
    assert pool["confirmed_credits"] == 0
    assert pool["status"] == "not_satisfied"


def test_fourth_year_applied_pool_accepts_foundation_transfer_without_double_counting():
    report = {
        "courses": [
            course("架空専門基礎B", 12, area="faculty_specialized", requirement_code="B", course_group="specialized_foundation"),
            course("架空専門応用B", 24, area="faculty_specialized", requirement_code="B", course_group="specialized_applied"),
            course("架空専門応用C", 11, area="faculty_specialized", requirement_code="C", course_group="specialized_applied"),
        ]
    }

    result = evaluate_fourth_year_progression(report, residence_years=3)

    assert condition(result, "specialized_applied_b")["confirmed_credits"] == 26
    pool = condition(result, "specialized_applied_pool")
    assert pool["confirmed_credits"] == 11
    assert pool["allocated_by_condition"] == {
        "specialized_foundation_b": 10,
        "specialized_applied_b": 26,
    }
    assert pool["status"] == "satisfied"


def test_fourth_year_applied_pool_caps_e_and_excludes_d():
    report = {
        "courses": [
            course("架空専門基礎B", 10, area="faculty_specialized", requirement_code="B", course_group="specialized_foundation"),
            course("架空専門応用B", 26, area="faculty_specialized", requirement_code="B", course_group="specialized_applied"),
            course("架空専門応用E", 7, area="faculty_specialized", requirement_code="E", course_group="specialized_applied"),
            course("架空専門応用D", 20, area="faculty_specialized", requirement_code="D", course_group="specialized_applied"),
        ]
    }

    result = evaluate_fourth_year_progression(report, residence_years=3)
    pool = condition(result, "specialized_applied_pool")

    assert pool["confirmed_credits"] == 6
    assert pool["applied_credit_caps"] == {"E": 6}
    assert pool["status"] == "not_satisfied"


def test_graduation_applied_pool_includes_d_and_does_not_cap_e():
    report = {
        "courses": [
            course("架空専門基礎B", 10, area="faculty_specialized", requirement_code="B", course_group="specialized_foundation"),
            course("架空専門応用B", 28, area="faculty_specialized", requirement_code="B", course_group="specialized_applied"),
            course("架空専門応用D", 10, area="faculty_specialized", requirement_code="D", course_group="specialized_applied"),
            course("架空専門応用E", 7, area="faculty_specialized", requirement_code="E", course_group="specialized_applied"),
        ]
    }

    result = evaluate_graduation(report, residence_years=4)
    pool = condition(result, "specialized_applied_pool")

    assert pool["confirmed_credits"] == 17
    assert pool["applied_credit_caps"] == {}
    assert pool["status"] == "satisfied"


@pytest.mark.parametrize(
    ("specialized_credits", "liberal_credits", "expected_credits", "expected_status"),
    [
        (87, 36, 5, "not_satisfied"),
        (88, 36, 6, "satisfied"),
        (84, 40, 6, "satisfied"),
        (89, 36, 7, "satisfied"),
    ],
)
def test_graduation_shared_surplus_uses_excess_from_both_areas(
    specialized_credits,
    liberal_credits,
    expected_credits,
    expected_status,
):
    report = {
        "student": {"grade": "4年"},
        "courses": [
            course(
                "架空専門科目",
                specialized_credits,
                area="faculty_specialized",
                requirement_code="B",
                course_group="specialized_applied",
            ),
            course("架空教養科目", liberal_credits),
        ],
    }

    result = evaluate_graduation(report, residence_years=4)
    surplus = condition(result, "cross_area_surplus")

    assert surplus["confirmed_credits"] == expected_credits
    assert surplus["status"] == expected_status
    assert surplus["source_surplus_credits"] == {
        "specialized_total": max(specialized_credits - 82, 0),
        "liberal_total": max(liberal_credits - 36, 0),
    }


def test_graduation_shared_surplus_remains_unknown_when_uncertain_course_can_fill_gap():
    report = {
        "student": {"grade": "4年"},
        "courses": [
            course(
                "架空専門科目",
                87,
                area="faculty_specialized",
                requirement_code="B",
                course_group="specialized_applied",
            ),
            course("架空教養科目", 36),
            course("架空分類未確定科目", 2, area="unknown"),
        ],
    }

    result = evaluate_graduation(report, residence_years=4)
    surplus = condition(result, "cross_area_surplus")

    assert surplus["confirmed_credits"] == 5
    assert surplus["status"] == "unknown"
    assert surplus["reason_code"] == "uncertain_courses_may_affect_result"


def test_duplicate_course_identity_is_not_counted_twice():
    report = {
        "courses": [
            {**course("総合工学概論", 2), "course_code": "DUP-1"},
            {**course("総合工学概論", 2), "course_code": "DUP-1"},
            course("架空一般科目", 30),
        ]
    }
    result = evaluate_second_year_progression(report, residence_years=1)
    designated = condition(result, "designated_course_group")
    assert designated["confirmed_credits"] == 2
    assert designated["status"] == "unknown"


def test_invalid_residence_is_rejected():
    with pytest.raises(ValueError, match="0以上"):
        evaluate_second_year_progression(report_with(32), residence_years=-1)

    with pytest.raises(ValueError, match="100年以下"):
        evaluate_second_year_progression(report_with(32), residence_years=101)


def test_non_finite_residence_is_rejected():
    with pytest.raises(ValueError, match="有限"):
        evaluate_second_year_progression(report_with(32), residence_years=float("nan"))
