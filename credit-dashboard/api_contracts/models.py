"""現在のHTTP応答を表す型。API処理や学務判定から独立して検証に使う。"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import NotRequired, TypedDict


Count = Annotated[int, Field(ge=0)]
PageNumber = Annotated[int, Field(ge=1)]
Credit = Annotated[float, Field(ge=0)]
PositiveCredit = Annotated[float, Field(gt=0)]
AcademicYear = Annotated[int, Field(ge=2000, le=2099)]
Term = Literal[1, 2, 3, 4]
Weekday = Annotated[int, Field(ge=1, le=5)]
Period = Annotated[int, Field(ge=1, le=5)]
TimetableWeekday = Annotated[int, Field(ge=1, le=7)]
TimetablePeriod = Annotated[int, Field(ge=1, le=99)]
Judgment = Literal["satisfied", "not_satisfied", "unknown"]
CourseResult = Literal["passed", "failed", "unconfirmed"]
RuleStatus = Literal["ready", "partial", "blocked"]
EvidenceStatus = Literal["transcribed", "verified", "needs_confirmation"]
ResidenceSource = Literal["user_input", "student_grade_assumption", "unavailable"]
Major = Literal["教養", "専門", "不明", "対象外"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class HealthResponse(ContractModel):
    status: Literal["ok"]


class RuleRequirement(ContractModel):
    requirement_id: str
    title: str
    rule_status: RuleStatus


class RuleProfile(ContractModel):
    profile_id: str
    institution: str
    faculty: str
    program: str
    admission_year: int
    policy_notes: list[str]
    requirements: list[RuleRequirement]
    implemented_requirement_ids: list[str]


class RuleProfilesResponse(ContractModel):
    profiles: list[RuleProfile]
    default_profile_id: str


class Curriculum(ContractModel):
    institution: str
    faculty: str
    program: str
    admission_year: int
    rules_version: str = Field(description="選択されたprofile_idと同じ値。")
    policy_notes: list[str]


class Student(ContractModel):
    name: str | None
    student_number: str | None
    affiliation: str | None
    grade: str | None = Field(description="CSVの学年表記。数値化した学年とは別。")


class MajorSummary(ContractModel):
    major: Major
    earned_credits: Credit
    unconfirmed_credits: Credit
    course_count: Count


class CategorySummary(MajorSummary):
    source_category: str
    field: str
    detail: str | None
    passed_count: Count
    unconfirmed_count: Count


class ReportSummary(ContractModel):
    course_count: Count
    passed_count: Count
    unconfirmed_count: Count
    unknown_credit_count: Count
    earned_credits: Credit = Field(description="確認済みの修得単位。不明な単位数は加算しない。")
    unconfirmed_credits: Credit
    majors: list[MajorSummary]
    categories: list[CategorySummary]


class TranscriptCourse(ContractModel):
    no: Count
    sequence: Count = Field(description="noの互換エイリアス。")
    row_number: PageNumber
    code: str | None
    course_code: str | None = Field(description="codeと同じ開講番号。")
    name: str
    source_category: str
    normalized_name: str
    major: Major
    field: str
    detail: str | None
    curriculum_area: Literal["liberal_arts", "faculty_specialized", "unknown", "excluded"]
    classification_status: Literal["classified", "unknown"]
    course_group: str | None
    requirement_code: str | None
    catalog_course_id: str | None
    classification_reason_code: str
    requirement_type: str | None
    field_codes: list[str]
    level: str | None
    credits: Credit | None = Field(description="nullは単位数未確認。0への置換は禁止。")
    score: Annotated[float, Field(ge=0)] | None = Field(
        description="CSVの得点。列なし・空欄はnull。合否・単位集計には使わない。"
    )
    status: CourseResult
    result: CourseResult = Field(description="statusと同じ正規化状態。原文はsource_result。")
    source_result: str | None
    year: str | None
    earned_year: str | None = Field(description="yearの互換エイリアス。")
    term: str | None
    earned_term: str | None = Field(description="termの互換エイリアス。")


class SourceRef(ContractModel):
    document_id: str
    printed_pages: list[PageNumber]
    pdf_pages: list[PageNumber]
    section: str | None = None


class ResolvedSource(SourceRef):
    title: str
    url: str
    section: str | None


class Caveat(ContractModel):
    id: str
    status: Literal["open", "resolved"]
    message: str


class EvaluationInputContext(ContractModel):
    residence_years: Credit | None
    residence_years_source: ResidenceSource
    student_grade_year: Annotated[int, Field(ge=1)] | None


class EvaluationContext(EvaluationInputContext):
    displayed_requirement_ids: list[str]


class ConditionBase(ContractModel):
    id: str
    label: str
    status: Judgment
    reason_code: str
    description: str


class CreditValues(ConditionBase):
    minimum_credits: Credit
    confirmed_credits: Credit
    confirmed_credit_shortfall: Credit = Field(
        description="確認済み値との差。statusがunknownなら確定した不足とは限らない。"
    )
    has_uncertain_candidate: bool


class CreditCondition(CreditValues):
    applied_credit_caps: dict[str, Credit]


class NamedCourseCondition(CreditValues):
    matched_course_names: list[str]


class SharedSurplusCondition(CreditValues):
    source_surplus_credits: dict[str, Credit]


class ResidualCreditCondition(CreditCondition):
    confirmed_area_credits: Credit
    allocated_to_prior_conditions: Credit
    allocated_by_condition: dict[str, Credit]


class RequiredCourseResult(ContractModel):
    catalog_course_id: str
    name: str
    status: Judgment
    reason_code: str
    minimum_credits: Credit
    confirmed_credits: Credit
    confirmed_credit_shortfall: Credit
    has_uncertain_candidate: bool
    source_refs: list[SourceRef]
    description: str


class RequiredCoursesCondition(ConditionBase):
    required_course_count: Count
    satisfied_course_count: Count
    missing_course_names: list[str]
    unknown_course_names: list[str]
    course_results: list[RequiredCourseResult]


class ResidenceCondition(ConditionBase):
    minimum_years: Credit
    confirmed_years: Credit | None
    value_source: ResidenceSource


class UnsupportedCondition(ConditionBase):
    status: Literal["unknown"]
    reason_code: Literal["condition_kind_not_implemented"]


EvaluationCondition: TypeAlias = (
    CreditCondition | NamedCourseCondition | SharedSurplusCondition | ResidualCreditCondition
    | RequiredCoursesCondition | ResidenceCondition | UnsupportedCondition
)


class Evaluation(ContractModel):
    requirement_id: str
    title: str
    profile_id: str
    status: Judgment
    description: str
    advisory_only: Literal[True]
    rule_status: RuleStatus
    evidence_status: EvidenceStatus
    input_context: EvaluationInputContext
    conditions: list[EvaluationCondition]
    source_refs: list[SourceRef]
    sources: list[ResolvedSource]
    caveat_ids: list[str]
    caveats: list[Caveat]


class ReportResponse(ContractModel):
    schema_version: Literal[2]
    curriculum: Curriculum
    student: Student
    summary: ReportSummary
    courses: list[TranscriptCourse]
    warnings: list[str]
    evaluations: list[Evaluation]
    evaluation_context: EvaluationContext


class TimetableContext(ContractModel):
    academic_year: AcademicYear | None
    semester: Literal[1, 2] | None
    term: Term | None


class DisplayContext(ContractModel):
    academic_year: AcademicYear
    term: Term


class TimetableSlot(ContractModel):
    weekday: TimetableWeekday
    period: TimetablePeriod


class TimetableCourse(DisplayContext):
    course_code: str
    slots: list[TimetableSlot]


class BusySlot(DisplayContext, TimetableSlot):
    pass


class TimetableWarning(ContractModel):
    code: str
    row_number: PageNumber
    message: str


class OutsideGridCourse(ContractModel):
    course_code: str
    row_number: PageNumber
    reason_code: Literal["regular_course_outside_grid"]


class MissingCourseCode(TimetableSlot):
    course_code: None
    row_number: PageNumber
    reason_code: Literal["missing_course_code"]


class TimetableResponse(ContractModel):
    schema_version: Literal[1]
    format: Literal["niigata-rsrefer-grid"]
    context: TimetableContext
    display_contexts: list[DisplayContext]
    represented_weekdays: list[TimetableWeekday]
    represented_periods: list[TimetablePeriod]
    courses: list[TimetableCourse]
    busy_slots: list[BusySlot]
    excluded_term_zero_course_count: Count
    policy_notes: list[str]
    unresolved_courses: list[OutsideGridCourse | MissingCourseCode]
    ready_for_recommendation: bool
    warnings: list[TimetableWarning]


class RecommendationCatalog(ContractModel):
    academic_year: AcademicYear
    profile_id: str
    program: str
    course_count: Count
    terms: list[Term]
    weekdays: list[Weekday]
    periods: list[Period]


class RecommendationCatalogsResponse(ContractModel):
    schema_version: Literal[1]
    catalogs: list[RecommendationCatalog]


class RecommendationContext(DisplayContext):
    profile_id: str


class SlotContext(RecommendationContext):
    weekday: Weekday
    period: Period


class OfferingSlot(ContractModel):
    weekday: Weekday
    period: Period


class Candidate(ContractModel):
    course_code: str
    name: str
    credits: PositiveCredit
    category: str
    terms: Annotated[list[Term], Field(min_length=1)]
    schedule: Annotated[list[OfferingSlot], Field(min_length=1)]


class ApiMessage(ContractModel):
    code: str
    message: str


class SlotCounts(ContractModel):
    matching: Count
    returned: Count
    excluded_overlap: Count
    excluded_unconfirmed: Count
    excluded_registered: Count


class SlotChecks(ContractModel):
    timetable: Literal["checked", "not_provided", "needs_review"]
    earned_credits: Literal["not_checked"]
    requirements: Literal["not_checked"]
    enrollment: Literal["not_checked"]


class SlotRecommendationsResponse(ContractModel):
    schema_version: Literal[1]
    context: SlotContext
    basis: Literal["catalog", "timetable"]
    status: Literal["ok", "empty", "occupied", "unknown"]
    candidates: list[Candidate]
    counts: SlotCounts
    checks: SlotChecks
    messages: list[ApiMessage]


class BaselineCondition(ContractModel):
    id: str
    label: str
    status: Judgment
    minimum_credits: Credit
    confirmed_credits: Credit
    confirmed_credit_shortfall: Credit
    has_uncertain_candidate: bool


class CandidateBenefit(ContractModel):
    condition_id: str
    label: str
    before_shortfall: Credit
    after_shortfall: Credit
    reduced_credits: PositiveCredit
    before_status: Judgment
    after_status: Judgment


class SearchCandidate(Candidate):
    benefits: list[CandidateBenefit]
    uncertain_benefits: list[CandidateBenefit]
    review_reasons: list[str]


class SearchCounts(ContractModel):
    catalog_in_term: Count
    excluded_earned: Count
    excluded_registered: Count
    excluded_overlap: Count
    excluded_unconfirmed_time: Count
    excluded_no_benefit: Count
    returned: Count
    review_required: Count


class SearchChecks(ContractModel):
    timetable: Literal["checked", "needs_review"]
    earned_credits: Literal["checked"]
    requirements: Literal["checked", "needs_review"]
    enrollment: Literal["not_checked"]


class RecommendationSearchResponse(ContractModel):
    schema_version: Literal[1]
    context: RecommendationContext
    target_requirement_id: Literal["graduation"]
    status: Literal["ok", "empty", "unknown"]
    baseline: list[BaselineCondition]
    free_slots: list[OfferingSlot]
    candidates: list[SearchCandidate]
    review_candidates: list[SearchCandidate]
    counts: SearchCounts
    checks: SearchChecks
    messages: list[ApiMessage]


class ErrorDetails(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)
    field: NotRequired[Literal["file", "grades_file", "timetable_file"]]
    columns: NotRequired[list[str]]
    profile_id: NotRequired[str]


class ApiErrorBody(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)
    code: Annotated[str, Field(description="機械可読コード。未知のコードは共通の表示へフォールバックする。")]
    message: str
    details: NotRequired[ErrorDetails]


class ErrorResponse(ContractModel):
    error: ApiErrorBody


class SessionResponse(ContractModel):
    schema_version: Literal[1]
    status: Literal["active"]
    csrf_token: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{43}$")]
    ttl_seconds: Annotated[int, Field(ge=1)]
    expires_in_seconds: Annotated[int, Field(ge=1)] = Field(
        description="作成時からの固定期限までの残り秒数。GET・POSTで延長しない。")


class SessionEndedResponse(ContractModel):
    schema_version: Literal[1]
    status: Literal["ended"]


class SessionWorkspaceResponse(ContractModel):
    schema_version: Literal[1]
    revision: Count
    session: SessionResponse
    report: ReportResponse | None
    timetable: TimetableResponse | None


RESPONSE_MODELS: dict[str, type[ContractModel]] = {
    model.__name__: model for model in (
        HealthResponse, RuleProfilesResponse, ReportResponse, TimetableResponse,
        RecommendationCatalogsResponse, SlotRecommendationsResponse,
        RecommendationSearchResponse, ErrorResponse, SessionResponse, SessionEndedResponse, SessionWorkspaceResponse,
    )
}
