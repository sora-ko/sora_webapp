"""成績CSVをメモリ上で解析するFastAPIアプリケーション。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from academic_rules import (
    RuleProfileNotFoundError,
    discover_rule_profiles,
    load_rule_profile,
    load_rule_profile_by_id,
    public_rule_profile,
)
from parser import CsvFormatError, parse_csv_bytes
from timetable_parser import parse_timetable_csv_bytes
from recommendations import RecommendationError, load_catalogs, catalog_metadata, find_catalog, recommend_for_slot
from recommendation_search import search_recommendations
from requirement_evaluator import (
    MAX_RESIDENCE_YEARS,
    SUPPORTED_REQUIREMENT_IDS,
    evaluate_supported_requirements,
    student_grade_year,
)


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_MULTIPART_BYTES = MAX_FILE_BYTES + 64 * 1024


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass
class MultipartPart:
    headers: dict[bytes, bytes] = field(default_factory=dict)
    header_name: bytearray = field(default_factory=bytearray)
    header_value: bytearray = field(default_factory=bytearray)
    field_name: bytes | None = None
    has_filename: bool = False
    capture: bool = False
    data: bytearray = field(default_factory=bytearray)


@dataclass(frozen=True)
class ReportUpload:
    raw: bytes
    fields: dict[str, str]


@dataclass(frozen=True)
class MultipartUpload:
    files: dict[str, bytes]
    fields: dict[str, str]


def _error_payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict:
    payload: dict[str, Any] = {"code": code, "message": message}
    if details:
        payload["details"] = details
    return {"error": payload}


class SecurityHeadersMiddleware:
    """全HTTP応答へ安全側のヘッダーを付け、予期しない例外を秘匿する。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Content-Security-Policy"] = (
                    "default-src 'self'; base-uri 'none'; "
                    "form-action 'self'; frame-ancestors 'none'"
                )
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            if response_started:
                raise
            # 入力データや例外本文をログへ流さず、機械可読な最小情報だけを返す。
            response = JSONResponse(
                status_code=500,
                content=_error_payload(
                    "internal_error",
                    "サーバー内部でエラーが発生しました。",
                ),
            )
            await response(scope, receive, send_with_headers)


async def _read_report_upload(request: Request, *, require_file: bool = True,
                              allowed_fields: frozenset[str] = frozenset({"profile_id", "residence_years"})) -> ReportUpload:
    upload = await _read_upload(request, file_fields=frozenset({"file"}),
                                required_files=frozenset({"file"}) if require_file else frozenset(),
                                allowed_fields=allowed_fields)
    return ReportUpload(raw=upload.files.get("file", b""), fields=upload.fields)


async def _read_upload(request: Request, *, file_fields: frozenset[str], required_files: frozenset[str],
                       allowed_fields: frozenset[str]) -> MultipartUpload:
    """許可したファイルだけをサイズ制限付きでメモリへ受信する。一時保存しない。"""
    content_type, options = parse_options_header(request.headers.get("content-type"))
    if content_type.lower() != b"multipart/form-data":
        raise ApiError(415, "unsupported_media_type", "multipart/form-dataで送信してください。")
    boundary = options.get(b"boundary")
    if not boundary:
        raise ApiError(400, "invalid_multipart", "multipart boundaryがありません。")

    current = MultipartPart()
    uploaded: dict[str, bytes] = {}
    form_fields: dict[str, str] = {}
    encoded_file_fields = {name.encode("ascii") for name in file_fields}
    max_total_bytes = MAX_FILE_BYTES * len(file_fields) + 64 * 1024

    def on_part_begin() -> None:
        nonlocal current
        current = MultipartPart()

    def on_header_field(data: bytes, start: int, end: int) -> None:
        current.header_name.extend(data[start:end])

    def on_header_value(data: bytes, start: int, end: int) -> None:
        current.header_value.extend(data[start:end])

    def on_header_end() -> None:
        current.headers[bytes(current.header_name).lower()] = bytes(current.header_value)
        current.header_name.clear()
        current.header_value.clear()

    def on_headers_finished() -> None:
        disposition, disposition_options = parse_options_header(
            current.headers.get(b"content-disposition")
        )
        if disposition.lower() != b"form-data":
            return
        current.field_name = disposition_options.get(b"name")
        current.has_filename = bool(disposition_options.get(b"filename"))
        current.capture = (
            current.field_name in encoded_file_fields
            or (
                not current.has_filename
                and current.field_name.decode("ascii", errors="replace") in allowed_fields
            )
        )

    def on_part_data(data: bytes, start: int, end: int) -> None:
        if not current.capture:
            return
        chunk = data[start:end]
        limit = MAX_FILE_BYTES if current.field_name in encoded_file_fields else 256
        if len(current.data) + len(chunk) > limit:
            if current.field_name in encoded_file_fields:
                raise ApiError(413, "file_too_large", "CSVは5 MiB以下にしてください。")
            raise ApiError(422, "invalid_evaluation_context", "入力項目が長すぎます。")
        current.data.extend(chunk)

    def on_part_end() -> None:
        if current.field_name not in encoded_file_fields:
            if current.capture and current.field_name is not None:
                try:
                    name = current.field_name.decode("ascii")
                    value = bytes(current.data).decode("utf-8").strip()
                except UnicodeDecodeError as exc:
                    raise ApiError(
                        422,
                        "invalid_evaluation_context",
                        "判定条件の文字コードが不正です。",
                    ) from exc
                if name in form_fields:
                    raise ApiError(
                        422,
                        "invalid_evaluation_context",
                        f"{name}は1つだけ指定してください。",
                    )
                form_fields[name] = value
            return
        if not current.has_filename:
            raise ApiError(400, "missing_file", "CSVファイルを選択してください。")
        name = current.field_name.decode("ascii")
        if name in uploaded:
            raise ApiError(400, "multiple_files", "同じ入力欄に指定できるCSVは1つだけです。", {"field": name})
        if not current.data:
            raise ApiError(422, "invalid_csv", "CSVが空です。", {"field": name})
        uploaded[name] = bytes(current.data)

    parser = MultipartParser(
        boundary,
        {
            "on_part_begin": on_part_begin,
            "on_header_field": on_header_field,
            "on_header_value": on_header_value,
            "on_header_end": on_header_end,
            "on_headers_finished": on_headers_finished,
            "on_part_data": on_part_data,
            "on_part_end": on_part_end,
        },
        max_size=max_total_bytes,
        max_header_count=8,
        max_header_size=4096,
    )
    total_bytes = 0
    try:
        async for chunk in request.stream():
            total_bytes += len(chunk)
            if total_bytes > max_total_bytes:
                raise ApiError(413, "file_too_large", "CSVの合計サイズが上限を超えています。")
            if parser.write(chunk) != len(chunk):
                raise ApiError(413, "file_too_large", "CSVは5 MiB以下にしてください。")
        parser.finalize()
    except MultipartParseError as exc:
        raise ApiError(400, "invalid_multipart", "アップロード形式が不正です。") from exc

    for name in sorted(required_files):
        if name not in uploaded:
            raise ApiError(400, "missing_file", "必要なCSVファイルを選択してください。", {"field": name})
    return MultipartUpload(files=uploaded, fields=form_fields)


def _residence_years(value: str | None) -> int | float | None:
    if value is None or not value.strip():
        return None
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ApiError(
            422,
            "invalid_evaluation_context",
            "在学期間は0以上の数値で入力してください。",
        ) from exc
    if not number.is_finite() or number < 0 or number > MAX_RESIDENCE_YEARS:
        raise ApiError(
            422,
            "invalid_evaluation_context",
            "在学期間は0年以上100年以下の有限数で入力してください。",
        )
    return int(number) if number == number.to_integral_value() else float(number)


def _selected_profile(profile_id: str | None) -> dict[str, Any]:
    if profile_id is None or not profile_id.strip():
        return load_rule_profile()
    try:
        return load_rule_profile_by_id(profile_id.strip())
    except RuleProfileNotFoundError as exc:
        raise ApiError(
            422,
            "unknown_rule_profile",
            "選択された対象年度・プログラムには対応していません。",
            {"profile_id": profile_id.strip()},
        ) from exc


def _append_scope_warning(report: dict[str, Any], profile: dict[str, Any]) -> None:
    affiliation = report.get("student", {}).get("affiliation")
    if not affiliation:
        return
    expected_program = profile["scope"]["program"]
    normalized_affiliation = "".join(str(affiliation).split())
    normalized_program = "".join(expected_program.split())
    if normalized_program not in normalized_affiliation:
        report["warnings"].append(
            "CSVの所属表記だけでは、選択した規則プロファイルの対象プログラムを確認できませんでした。"
        )


app = FastAPI(
    title="単位取得状況 API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
cors_origins = [value.strip() for value in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if value.strip()]
if cors_origins:
    if "*" in cors_origins:
        raise ValueError("CORS_ALLOWED_ORIGINSには具体的なOriginを指定してください")
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"], allow_credentials=False)
app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(ApiError)
async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(exc.code, exc.message, exc.details),
    )


@app.exception_handler(RecommendationError)
async def recommendation_error_handler(_request: Request, exc: RecommendationError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=_error_payload(exc.code, str(exc)))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_error_payload("invalid_request", "リクエストが不正です。"),
    )


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    code, message = {
        404: ("route_not_found", "指定されたURLが見つかりません。"),
        405: ("method_not_allowed", "このHTTPメソッドは使用できません。"),
    }.get(exc.status_code, ("http_error", "HTTPリクエストを処理できませんでした。"))
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(code, message),
        headers=exc.headers,
    )


@app.get("/api/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/rule-profiles")
async def rule_profiles() -> dict[str, Any]:
    profiles = discover_rule_profiles()
    default_profile_id = load_rule_profile()["profile_id"]
    public_profiles = []
    for profile in profiles:
        public_profile = public_rule_profile(profile)
        public_profile["implemented_requirement_ids"] = [
            requirement_id
            for requirement_id in SUPPORTED_REQUIREMENT_IDS
            if requirement_id in profile["requirements"]
        ]
        public_profiles.append(public_profile)
    return {
        "profiles": public_profiles,
        "default_profile_id": default_profile_id,
    }


@app.get("/api/report")
async def legacy_report() -> JSONResponse:
    return JSONResponse(
        status_code=410,
        content=_error_payload(
            "upload_required",
            "固定CSVの読み込みは廃止しました。画面からCSVをアップロードしてください。",
        ),
    )


@app.post("/api/v1/reports")
async def create_report(request: Request) -> dict:
    upload = await _read_report_upload(request)
    profile = _selected_profile(upload.fields.get("profile_id"))
    requested_residence_years = _residence_years(upload.fields.get("residence_years"))
    try:
        report = parse_csv_bytes(upload.raw, profile=profile)
    except CsvFormatError as exc:
        status_code = 415 if exc.code == "unsupported_encoding" else 422
        raise ApiError(status_code, exc.code, str(exc), exc.details) from exc
    _append_scope_warning(report, profile)
    grade_year = student_grade_year(report)
    if requested_residence_years is not None:
        residence_years = requested_residence_years
        residence_years_source = "user_input"
    elif grade_year is not None:
        residence_years = grade_year
        residence_years_source = "student_grade_assumption"
    else:
        residence_years = None
        residence_years_source = "unavailable"
    report["evaluations"] = evaluate_supported_requirements(
        report,
        residence_years=residence_years,
        residence_years_source=residence_years_source,
        profile=profile,
    )
    report["evaluation_context"] = {
        "residence_years": residence_years,
        "residence_years_source": residence_years_source,
        "student_grade_year": grade_year,
        "displayed_requirement_ids": [
            evaluation["requirement_id"] for evaluation in report["evaluations"]
        ],
    }
    return report


@app.post("/api/v1/timetables")
async def create_timetable(request: Request) -> dict:
    upload = await _read_report_upload(request)
    try:
        return parse_timetable_csv_bytes(upload.raw)
    except CsvFormatError as error:
        status_code = 415 if error.code == "unsupported_encoding" else 422
        raise ApiError(status_code, error.code, str(error), error.details) from error


def _recommendation_catalogs() -> list[dict]:
    root = Path(os.environ.get("RECOMMENDATION_CATALOG_DIR", ROOT / "data" / "recommendations"))
    return load_catalogs(root)


@app.get("/api/v1/recommendation-catalogs")
async def recommendation_catalogs() -> dict:
    return {"schema_version": 1, "catalogs": [catalog_metadata(catalog) for catalog in _recommendation_catalogs()]}


@app.post("/api/v1/recommendations")
async def create_recommendations(request: Request) -> dict:
    fields = frozenset({"profile_id", "academic_year", "term", "weekday", "period"})
    upload = await _read_report_upload(request, require_file=False, allowed_fields=fields)
    profile = _selected_profile(upload.fields.get("profile_id"))
    context = {"profile_id": profile["profile_id"]}
    for name, lower, upper in [("academic_year", 2000, 2099), ("term", 1, 4),
                               ("weekday", 1, 5), ("period", 1, 5)]:
        value = upload.fields.get(name, "")
        if not value.isascii() or not value.isdigit() or not lower <= int(value) <= upper:
            raise ApiError(422, "invalid_recommendation_context", "年度・ターム・曜日・時限を正しく指定してください。")
        context[name] = int(value)
    catalog = find_catalog(_recommendation_catalogs(), context)
    timetable = None
    if upload.raw:
        try:
            timetable = parse_timetable_csv_bytes(upload.raw)
        except CsvFormatError as error:
            status = 415 if error.code == "unsupported_encoding" else 422
            raise ApiError(status, error.code, str(error), error.details) from error
    return recommend_for_slot(catalog, context, timetable)


@app.post("/api/v1/recommendation-searches")
async def create_recommendation_search(request: Request) -> dict:
    fields = frozenset({"profile_id", "academic_year", "term"})
    files = frozenset({"grades_file", "timetable_file"})
    upload = await _read_upload(request, file_fields=files, required_files=files, allowed_fields=fields)
    profile = _selected_profile(upload.fields.get("profile_id"))
    context = {"profile_id": profile["profile_id"]}
    for name, lower, upper in [("academic_year", 2000, 2099), ("term", 1, 4)]:
        value = upload.fields.get(name, "")
        if not value.isascii() or not value.isdigit() or not lower <= int(value) <= upper:
            raise ApiError(422, "invalid_recommendation_context", "開講年度・タームを正しく指定してください。")
        context[name] = int(value)
    catalog = find_catalog(_recommendation_catalogs(), context)
    parsed = {}
    for field_name, parse in [("grades_file", lambda raw: parse_csv_bytes(raw, profile=profile)),
                              ("timetable_file", parse_timetable_csv_bytes)]:
        try:
            parsed[field_name] = parse(upload.files[field_name])
        except CsvFormatError as error:
            # CSV由来の詳細・科目名は探索APIへ転記せず、どちらの入力かだけ示す。
            status = 415 if error.code == "unsupported_encoding" else 422
            label = "成績CSV" if field_name == "grades_file" else "履修表CSV"
            raise ApiError(status, error.code, f"{label}の形式を確認してください。", {"field": field_name}) from error
    return search_recommendations(catalog, context, parsed["grades_file"], parsed["timetable_file"], profile)


@app.api_route(
    "/api/{api_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE"],
)
async def unknown_api_route(request: Request, api_path: str) -> None:
    known_methods = {
        "healthz": {"GET"},
        "report": {"GET"},
        "v1/rule-profiles": {"GET"},
        "v1/reports": {"POST"},
        "v1/timetables": {"POST"},
        "v1/recommendation-catalogs": {"GET"},
        "v1/recommendations": {"POST"},
        "v1/recommendation-searches": {"POST"},
    }
    if api_path in known_methods and request.method not in known_methods[api_path]:
        raise ApiError(405, "method_not_allowed", "このHTTPメソッドは使用できません。")
    raise ApiError(404, "route_not_found", "指定されたAPIのURLが見つかりません。")


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        access_log=False,
    )
