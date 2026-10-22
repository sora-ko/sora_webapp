"""成績CSVをメモリ上で解析するFastAPIアプリケーション。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from parser import CsvFormatError, parse_csv_bytes


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


async def _read_uploaded_csv(request: Request) -> bytes:
    content_type, options = parse_options_header(request.headers.get("content-type"))
    if content_type.lower() != b"multipart/form-data":
        raise ApiError(415, "unsupported_media_type", "multipart/form-dataで送信してください。")
    boundary = options.get(b"boundary")
    if not boundary:
        raise ApiError(400, "invalid_multipart", "multipart boundaryがありません。")

    current = MultipartPart()
    uploaded: bytes | None = None

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
        current.capture = current.field_name == b"file" and current.has_filename

    def on_part_data(data: bytes, start: int, end: int) -> None:
        if not current.capture:
            return
        chunk = data[start:end]
        if len(current.data) + len(chunk) > MAX_FILE_BYTES:
            raise ApiError(413, "file_too_large", "CSVは5 MiB以下にしてください。")
        current.data.extend(chunk)

    def on_part_end() -> None:
        nonlocal uploaded
        if current.field_name != b"file":
            return
        if not current.has_filename:
            raise ApiError(400, "missing_file", "CSVファイルを選択してください。")
        if uploaded is not None:
            raise ApiError(400, "multiple_files", "アップロードできるCSVは1つだけです。")
        uploaded = bytes(current.data)

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
        max_size=MAX_MULTIPART_BYTES,
        max_header_count=8,
        max_header_size=4096,
    )
    total_bytes = 0
    try:
        async for chunk in request.stream():
            total_bytes += len(chunk)
            if total_bytes > MAX_MULTIPART_BYTES:
                raise ApiError(413, "file_too_large", "CSVは5 MiB以下にしてください。")
            if parser.write(chunk) != len(chunk):
                raise ApiError(413, "file_too_large", "CSVは5 MiB以下にしてください。")
        parser.finalize()
    except MultipartParseError as exc:
        raise ApiError(400, "invalid_multipart", "アップロード形式が不正です。") from exc

    if uploaded is None:
        raise ApiError(400, "missing_file", "CSVファイルを選択してください。")
    if not uploaded:
        raise ApiError(422, "invalid_csv", "CSVが空です。")
    return uploaded


app = FastAPI(
    title="単位取得状況 API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(ApiError)
async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(exc.code, exc.message, exc.details),
    )


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
    raw = await _read_uploaded_csv(request)
    try:
        return parse_csv_bytes(raw)
    except CsvFormatError as exc:
        status_code = 415 if exc.code == "unsupported_encoding" else 422
        raise ApiError(status_code, exc.code, str(exc), exc.details) from exc


@app.api_route(
    "/api/{api_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE"],
)
async def unknown_api_route(request: Request, api_path: str) -> None:
    known_methods = {
        "healthz": {"GET"},
        "report": {"GET"},
        "v1/reports": {"POST"},
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
