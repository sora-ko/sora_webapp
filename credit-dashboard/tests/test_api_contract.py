"""公開契約・配布例と、実際のHTTP境界の一致を架空入力だけで検証する。"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path

import httpx2
from fastapi.openapi.utils import get_openapi
from jsonschema import Draft202012Validator
import pytest
from pydantic import ValidationError

import server
from api_contracts.examples import collect_examples, fictional_catalog, fictional_grades, multipart
from api_contracts.models import RESPONSE_MODELS
from api_contracts.specification import OPERATIONS, REQUEST_SCHEMAS, json_schemas, openapi_document, response_schema
from api_contracts.typescript import schema_type
from scripts.build_api_contract import build_artifacts


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def bundle():
    return json_schemas()


@pytest.fixture(scope="module")
def examples():
    return {item.name: item for item in asyncio.run(collect_examples())}


@pytest.fixture(scope="module")
def artifacts():
    return asyncio.run(build_artifacts())


def test_generated_contract_and_examples_match_current_backend(artifacts):
    for relative, content in artifacts.items():
        assert (ROOT / "contracts" / relative).read_text(encoding="utf-8") == content, relative
    actual = {file.relative_to(ROOT / "contracts").as_posix() for file in (ROOT / "contracts" / "examples").glob("*.json")}
    assert actual == {name for name in artifacts if name.startswith("examples/")}


def test_all_schemas_and_local_references_are_valid(bundle):
    Draft202012Validator.check_schema(bundle)
    document = openapi_document(bundle)

    def check(value, root):
        if isinstance(value, dict):
            if "$ref" in value:
                reference = value["$ref"]
                assert reference.startswith("#/"), "Contracts must not fetch external reference data"
                current = root
                for token in reference[2:].split("/"):
                    current = current[token.replace("~1", "/").replace("~0", "~")]
            for child in value.values():
                check(child, root)
        elif isinstance(value, list):
            for child in value:
                check(child, root)

    check(bundle, bundle)
    check(document, document)
    for name in RESPONSE_MODELS:
        Draft202012Validator.check_schema(response_schema(name, bundle))


def test_all_existing_api_routes_are_described_without_enabling_docs_endpoints():
    # include_routerの遅延登録も含め、FastAPI自身に実効パスを列挙させる。
    routes = [route for route in server.app.routes if getattr(route, "path", None) != "/api/{api_path:path}"]
    paths = get_openapi(title="Contract route check", version="1", routes=routes)["paths"]
    methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    actual = {(method, path) for path, item in paths.items() if path.startswith("/api/")
              for method in item if method in methods}
    described = {(item["method"], item["path"]) for item in OPERATIONS}
    assert actual == described
    assert server.app.openapi_url is None
    assert server.app.docs_url is None
    assert server.app.redoc_url is None


def test_session_contract_separates_headers_cookies_and_body_and_preserves_fixed_expiry(examples):
    document = openapi_document()
    operations = document["paths"]["/api/v1/session"]
    for method in ["get", "post", "delete"]:
        entry = operations[method]
        assert "requestBody" not in entry
        headers = {item["name"]: item for item in entry["parameters"]}
        assert headers["X-Session-Request"]["schema"]["const"] == "1"
        assert headers["X-Session-Request"]["required"] is True
        assert ("X-CSRF-Token" in headers) == (method == "delete")
    assert operations["get"]["security"] == [{"SessionCookie": []}, {"LocalSessionCookie": []}]
    assert "security" not in operations["post"]
    assert "Set-Cookie" in operations["post"]["responses"]["200"]["headers"]
    created, resumed = examples["session-created"].body, examples["session-resumed"].body
    assert created["ttl_seconds"] == created["expires_in_seconds"] == 1200
    assert resumed["expires_in_seconds"] == 1140
    assert resumed["csrf_token"] == created["csrf_token"]
    assert examples["error-session-expired"].body["error"]["code"] == "session_required"
    assert examples["session-ended"].body == {"schema_version": 1, "status": "ended"}


@pytest.mark.parametrize("name", list(RESPONSE_MODELS))
def test_real_http_examples_validate_with_both_pydantic_and_json_schema(name, examples, bundle):
    validator = Draft202012Validator(response_schema(name, bundle))
    selected = [example for example in examples.values() if example.model == name]
    assert selected
    for example in selected:
        result = RESPONSE_MODELS[name].model_validate(example.body)
        assert result.model_dump(mode="json", exclude_unset=True) == example.body
        assert not list(validator.iter_errors(example.body)), example.name
        json.dumps(example.body, allow_nan=False)


def test_wire_versions_nulls_omissions_aliases_and_grade_context_remain_unchanged(examples):
    assert "schema_version" not in examples["health"].body
    assert "schema_version" not in examples["rule-profiles"].body
    report = examples["report-year2"].body
    assert report["schema_version"] == 2
    assert all(item.body["schema_version"] == 1 for item in examples.values()
               if item.model in {"TimetableResponse", "RecommendationCatalogsResponse", "SlotRecommendationsResponse", "RecommendationSearchResponse"})
    assert any(course["credits"] is None for course in report["courses"])
    assert any(course["credits"] == 1.5 for course in report["courses"])
    for course in report["courses"]:
        for first, second in [("no", "sequence"), ("code", "course_code"), ("status", "result"),
                              ("year", "earned_year"), ("term", "earned_term")]:
            assert course[first] == course[second]
    for name, expected in [("report-year1", ["progression_year_2", "graduation"]),
                           ("report-year2", ["progression_year_4", "graduation"]),
                           ("report-year3", ["progression_year_4", "graduation"]),
                           ("report-graduation", ["graduation"])]:
        assert examples[name].body["evaluation_context"]["displayed_requirement_ids"] == expected
    assert examples["report-year3"].body["evaluation_context"]["residence_years"] == 2.5
    assert examples["report-unknown"].body["evaluation_context"]["residence_years"] is None
    assert "details" not in examples["error-internal"].body["error"]
    assert examples["error-search-csv"].body["error"]["details"] == {"field": "grades_file"}
    assert examples["error-invalid-csv"].body["error"]["details"]["columns"]


def test_nonempty_empty_unknown_and_occupied_examples_cannot_be_confused(examples):
    assert examples["slot-catalog"].body["candidates"]
    assert examples["slot-catalog"].body["checks"]["timetable"] == "not_provided"
    assert examples["slot-empty"].body["status"] == "empty"
    assert examples["slot-occupied"].body["status"] == "occupied"
    assert examples["slot-unknown"].body["status"] == "unknown"
    assert examples["search-ok"].body["candidates"]
    assert examples["search-review"].body["review_candidates"]
    fulfilled = examples["search-fulfilled-unknown-time"].body
    assert fulfilled["status"] == "empty"
    assert fulfilled["checks"]["timetable"] == "needs_review"
    assert not fulfilled["candidates"]
    assert any(message["code"] == "liberal_requirements_satisfied" for message in fulfilled["messages"])
    assert examples["catalogs-empty"].body["catalogs"] == []
    assert examples["report-no-courses"].body["courses"] == []


def test_report_scores_are_numeric_or_null_in_public_examples(examples):
    courses = examples["report-year2"].body["courses"]
    assert [course["score"] for course in courses] == [85.5, 0, 90, 100, 80, None]
    assert courses[2]["status"] == "unconfirmed"
    assert examples["report-year1"].body["courses"][0]["score"] == 85


def test_each_condition_shape_and_unresolved_timetable_shape_is_demonstrated(examples):
    kinds = {type(condition).__name__ for item in examples.values() if item.model == "ReportResponse"
             for evaluation in RESPONSE_MODELS["ReportResponse"].model_validate(item.body).evaluations
             for condition in evaluation.conditions}
    assert kinds == {"CreditCondition", "NamedCourseCondition", "SharedSurplusCondition",
                     "ResidualCreditCondition", "RequiredCoursesCondition", "ResidenceCondition"}
    assert examples["report-blocked"].body["evaluations"][0]["caveats"][0]["status"] == "open"
    assert examples["timetable-missing-code"].body["unresolved_courses"][0]["course_code"] is None
    outside = examples["timetable-outside-grid"].body["unresolved_courses"][0]
    assert "weekday" not in outside and "period" not in outside
    assert max(examples["timetable-weekend"].body["represented_weekdays"]) == 7
    assert max(examples["timetable-weekend"].body["represented_periods"]) == 7
    unknown = examples["timetable-no-context"].body
    assert unknown["context"]["academic_year"] is None and unknown["display_contexts"] == []


@pytest.mark.parametrize(("name", "path", "value"), [
    ("report-year2", ("schema_version",), 1),
    ("report-year2", ("evaluation_context",), "DELETE"),
    ("report-year2", ("summary", "earned_credits"), "5"),
    ("report-year2", ("courses", 0, "status"), "合"),
    ("report-year2", ("courses", 0, "credits"), True),
    ("report-year2", ("courses", 0, "credits"), "DELETE"),
    ("report-year2", ("courses", 0, "score"), "85.5"),
    ("report-year2", ("courses", 0, "score"), True),
    ("report-year2", ("courses", 0, "score"), -1),
    ("report-year2", ("courses", 0, "score"), "DELETE"),
    ("report-year2", ("warnings",), [{"message": "架空の型違い"}]),
    ("report-year2", ("raw_csv",), "fictional"),
    ("timetable", ("courses", 0, "teacher"), "架空教員"),
    ("timetable", ("context", "term"), 0),
    ("slot-catalog", ("status",), "not_satisfied"),
    ("search-ok", ("status",), "occupied"),
    ("error-internal", ("error", "details"), None),
    ("error-search-csv", ("error", "details", "field"), "student_name"),
    ("session-created", ("session_id",), "fictional_cookie_must_not_be_exposed"),
    ("session-created", ("expires_in_seconds",), 0),
])
def test_contract_rejects_breaking_or_privacy_relevant_response_changes(name, path, value, examples, bundle):
    example = examples[name]
    payload = deepcopy(example.body)
    target = payload
    for key in path[:-1]:
        target = target[key]
    if value == "DELETE":
        del target[path[-1]]
    else:
        target[path[-1]] = value
    assert not Draft202012Validator(response_schema(example.model, bundle)).is_valid(payload)
    with pytest.raises(ValidationError):
        RESPONSE_MODELS[example.model].model_validate(payload)


def test_unrecognized_machine_codes_are_strings_not_closed_enums(examples, bundle):
    payload = deepcopy(examples["error-internal"].body)
    payload["error"]["code"] = "fictional_future_error"
    assert Draft202012Validator(response_schema("ErrorResponse", bundle)).is_valid(payload)
    RESPONSE_MODELS["ErrorResponse"].model_validate(payload)


@pytest.mark.parametrize(("path", "field", "value"), [
    ("/api/v1/recommendations", field, value)
    for field, values in [("academic_year", [1999, 2100]), ("term", [0, 5]), ("weekday", [0, 6]), ("period", [0, 6])]
    for value in values
] + [("/api/v1/recommendation-searches", field, value)
     for field, values in [("academic_year", [1999, 2100]), ("term", [0, 5])] for value in values]
  + [("/api/v1/reports", "residence_years", -1), ("/api/v1/reports", "residence_years", 100.5)])
def test_documented_request_ranges_match_real_api_rejection(path, field, value, monkeypatch):
    operation = next(item for item in OPERATIONS if item["path"] == path)
    field_schema = REQUEST_SCHEMAS[operation["request"]]["properties"][field]
    assert not Draft202012Validator(field_schema).is_valid(value)
    monkeypatch.setattr(server, "_recommendation_catalogs", lambda: [fictional_catalog()])

    async def call():
        fields = {"profile_id": fictional_catalog()["profile_id"], "academic_year": 2026,
                  "term": 3, "weekday": 2, "period": 2, field: value}
        files = {"grades_file": fictional_grades(), "timetable_file": b"fictional"} if path.endswith("searches") else {"file": fictional_grades()}
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=server.app), base_url="http://contract.test") as client:
            response = await client.post(path, files=multipart(fields, **files))
            assert response.status_code == 422
            assert response.headers["cache-control"] == "no-store"
            assert response.json()["error"]["code"] in {"invalid_recommendation_context", "invalid_evaluation_context"}
    asyncio.run(call())


def test_typescript_preserves_optional_file_nullable_credits_and_union_results(artifacts):
    text = artifacts["api.d.ts"]
    assert '"credits": (number) | (null);' in text
    assert '"file"?: Blob;' in text and '"file": Blob;' in text
    assert '"details"?: ErrorDetails;' in text
    assert 'export type EvaluationCondition = Evaluation["conditions"][number];' in text
    assert '"occupied"' in text and '"unconfirmed"' in text
    assert "Record<string, unknown>" in text
    assert ": any" not in text
    with pytest.raises(ValueError):
        schema_type({"oneOf": [{"type": "string"}, {"type": "number"}]})
    with pytest.raises(ValueError):
        schema_type({"$ref": "https://fictional.invalid/schema.json"})
