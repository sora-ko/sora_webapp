"""匿名セッションのHTTP境界。既存のCSV APIから独立して追加する。"""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from session_store import SessionError


SESSION_PATH = "/api/v1/session"
SECURE_COOKIE_NAME = "__Host-credit_session"
LOCAL_COOKIE_NAME = "credit_session"


def _origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            return None
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        return parsed.scheme, parsed.hostname.lower(), port
    except ValueError:
        return None


class SessionAwareCorsMiddleware:
    """既存APIは従来のCORSを保ち、セッションAPIだけ資格情報を許可する。"""

    def __init__(self, app: ASGIApp, *, allow_origins: list[str]) -> None:
        if any(value == "*" or _origin(value) is None for value in allow_origins):
            raise ValueError("CORS_ALLOWED_ORIGINSには具体的なhttp(s)のOriginを指定してください")
        self._public = CORSMiddleware(app, allow_origins=allow_origins, allow_methods=["GET", "POST"],
                                      allow_headers=["Content-Type"], allow_credentials=False)
        self._sessions = CORSMiddleware(app, allow_origins=allow_origins,
                                        allow_methods=["GET", "POST", "DELETE"],
                                        allow_headers=["Content-Type", "X-Session-Request", "X-CSRF-Token", "X-Session-Revision"],
                                        allow_credentials=True)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        selected = self._sessions if path == SESSION_PATH or path.startswith(SESSION_PATH + "/") else self._public
        await selected(scope, receive, send)


def _cookie_name(request: Request) -> str:
    return SECURE_COOKIE_NAME if request.url.scheme == "https" else LOCAL_COOKIE_NAME


async def guard_session_request(request: Request, *, allow_body: bool = False) -> None:
    if request.url.scheme != "https":
        host = request.url.hostname or ""
        try:
            local = ip_address(host).is_loopback
        except ValueError:
            local = host.lower() == "localhost"
        if not local:
            raise SessionError(403, "session_https_required", "localhost以外ではHTTPSで接続してください。")
    if request.headers.getlist("x-session-request") != ["1"]:
        raise SessionError(403, "session_request_header_required", "X-Session-Request: 1を指定してください。")
    origins = request.headers.getlist("origin")
    expected = _origin(str(request.base_url.replace(path="/")))
    allowed = {_origin(value) for value in request.app.state.session_allowed_origins}
    if (len(origins) > 1 or (origins and (_origin(origins[0]) is None
                                         or _origin(origins[0]) not in {expected, *allowed}))
            or request.headers.get("sec-fetch-site") == "cross-site"):
        raise SessionError(403, "session_origin_forbidden", "この接続元からセッションは操作できません。")
    if not allow_body:
        async for chunk in request.stream():
            if chunk:
                raise SessionError(422, "invalid_request", "このAPIにはリクエスト本文を送信しないでください。")


def workspace_headers(request: Request) -> tuple[str | None, str | None, int]:
    revisions = request.headers.getlist("x-session-revision")
    if (len(revisions) != 1 or not revisions[0].isascii() or not revisions[0].isdigit()
            or len(revisions[0]) > 15):
        raise SessionError(422, "invalid_session_revision", "X-Session-Revisionに更新番号を指定してください。")
    csrf_headers = request.headers.getlist("x-csrf-token")
    csrf = csrf_headers[0] if len(csrf_headers) == 1 else None
    return request.cookies.get(_cookie_name(request)), csrf, int(revisions[0])


router = APIRouter()


@router.post(SESSION_PATH)
async def create_session(request: Request) -> JSONResponse:
    await guard_session_request(request)
    token, body = request.app.state.session_store.create_or_resume(request.cookies.get(_cookie_name(request)))
    response = JSONResponse(body)
    if token is not None:
        response.set_cookie(_cookie_name(request), token, httponly=True, secure=request.url.scheme == "https",
                            samesite="strict", path="/")
    return response


@router.get(SESSION_PATH)
async def get_session(request: Request) -> dict:
    await guard_session_request(request)
    return request.app.state.session_store.get(request.cookies.get(_cookie_name(request)))


@router.delete(SESSION_PATH)
async def end_session(request: Request) -> JSONResponse:
    await guard_session_request(request)
    csrf_headers = request.headers.getlist("x-csrf-token")
    csrf = csrf_headers[0] if len(csrf_headers) == 1 else None
    request.app.state.session_store.end(request.cookies.get(_cookie_name(request)), csrf)
    response = JSONResponse({"schema_version": 1, "status": "ended"})
    response.delete_cookie(_cookie_name(request), path="/", httponly=True,
                           secure=request.url.scheme == "https", samesite="strict")
    return response


@router.get(SESSION_PATH + "/workspace")
async def get_workspace(request: Request) -> dict:
    await guard_session_request(request)
    return request.app.state.session_store.workspace(request.cookies.get(_cookie_name(request)))
