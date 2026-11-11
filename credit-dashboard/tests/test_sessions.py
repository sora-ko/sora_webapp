"""匿名セッションの固定期限・隔離・HTTP保護。実学生データを使用しない。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import logging

from fastapi import FastAPI
import httpx2
import pytest

import server
from session_api import LOCAL_COOKIE_NAME, SECURE_COOKIE_NAME, SessionAwareCorsMiddleware, router
from session_store import SessionError, SessionSettings, SessionStore


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def session_state(monkeypatch):
    clock = Clock()
    store = SessionStore(SessionSettings(max_sessions=2), clock=clock)
    monkeypatch.setattr(server.app.state, "session_store", store)
    monkeypatch.setattr(server.app.state, "session_allowed_origins", [])
    yield store, clock
    store.clear()


@pytest.fixture
async def client(session_state):
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=server.app),
                                  base_url="https://session.test", headers={"X-Session-Request": "1"}) as client:
        yield client


def error(response, status, code):
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.headers["cache-control"] == "no-store"


def test_settings_default_to_fixed_twenty_minutes_and_allow_explicit_configuration():
    assert SessionSettings.from_environ({}).ttl_seconds == 1200
    settings = SessionSettings.from_environ({"SESSION_TTL_SECONDS": "60", "SESSION_MAX_COUNT": "3"})
    assert settings.ttl_seconds == 60 and settings.max_sessions == 3


@pytest.mark.parametrize("name", ["SESSION_TTL_SECONDS", "SESSION_MAX_COUNT"])
@pytest.mark.parametrize("value", ["0", "-1", "1.5", "NaN", "１", ""])
def test_invalid_session_settings_fail_at_startup(name, value):
    with pytest.raises(ValueError, match=name):
        SessionSettings.from_environ({name: value})


def test_raw_cookie_is_not_the_server_store_key():
    store = SessionStore()
    token, view = store.create_or_resume(None)
    assert len(token) == 43 and len(view["csrf_token"]) == 43
    assert token != view["csrf_token"]
    assert token not in store._records
    assert hashlib.sha256(token.encode()).hexdigest() in store._records
    assert set(view) == {"schema_version", "status", "csrf_token", "ttl_seconds", "expires_in_seconds"}


def test_reads_and_repeated_bootstrap_never_extend_the_fixed_deadline():
    clock = Clock()
    store = SessionStore(clock=clock)
    token, first = store.create_or_resume(None)
    clock.now = 1199
    assert store.get(token)["expires_in_seconds"] == 1
    new_token, resumed = store.create_or_resume(token)
    assert new_token is None and resumed["csrf_token"] == first["csrf_token"]
    assert resumed["expires_in_seconds"] == 1
    clock.now = 1200
    with pytest.raises(SessionError) as failure:
        store.get(token)
    assert failure.value.code == "session_required"
    assert not store._records


def test_unknown_client_supplied_token_is_replaced_and_restart_loses_state():
    store = SessionStore()
    chosen = "A" * 43
    token, _ = store.create_or_resume(chosen)
    assert token != chosen
    with pytest.raises(SessionError):
        store.get(chosen)
    with pytest.raises(SessionError):
        SessionStore().get(token)


def test_capacity_does_not_evict_active_sessions_and_expired_space_is_reclaimed():
    clock = Clock()
    store = SessionStore(SessionSettings(ttl_seconds=5, max_sessions=1), clock=clock)
    token, _ = store.create_or_resume(None)
    with pytest.raises(SessionError) as failure:
        store.create_or_resume(None)
    assert failure.value.code == "session_capacity_exceeded"
    assert store.get(token)["status"] == "active"
    clock.now = 5
    replacement, _ = store.create_or_resume(None)
    assert replacement != token and len(store._records) == 1


@pytest.mark.parametrize("csrf", [None, "", "wrong", "A" * 43, "あ" * 43])
def test_invalid_csrf_cannot_end_a_session(csrf):
    store = SessionStore()
    token, view = store.create_or_resume(None)
    with pytest.raises(SessionError) as failure:
        store.end(token, csrf)
    assert failure.value.code == "invalid_csrf_token"
    assert store.get(token) == view


def test_one_sessions_csrf_cannot_end_another_session():
    store = SessionStore()
    first_token, first = store.create_or_resume(None)
    second_token, second = store.create_or_resume(None)
    with pytest.raises(SessionError):
        store.end(second_token, first["csrf_token"])
    store.end(first_token, first["csrf_token"])
    with pytest.raises(SessionError):
        store.get(first_token)
    assert store.get(second_token) == second


def test_concurrent_session_creation_obeys_the_capacity():
    store = SessionStore(SessionSettings(max_sessions=4))

    def create(_):
        try:
            return store.create_or_resume(None)[0]
        except SessionError as exc:
            assert exc.code == "session_capacity_exceeded"
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(create, range(20)))
    assert len({token for token in results if token}) == 4
    assert len(store._records) == 4


@pytest.mark.anyio
async def test_create_resume_and_get_preserve_deadline_and_use_secure_host_cookie(client, session_state):
    response = await client.post("/api/v1/session")
    assert response.status_code == 200
    first = response.json()
    cookie = response.headers["set-cookie"]
    assert SECURE_COOKIE_NAME + "=" in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert "Domain=" not in cookie and "Max-Age=" not in cookie and "expires=" not in cookie.lower()
    assert first["expires_in_seconds"] == first["ttl_seconds"] == 1200
    session_state[1].now = 100
    resumed = await client.post("/api/v1/session")
    assert resumed.json()["expires_in_seconds"] == 1100
    assert resumed.json()["csrf_token"] == first["csrf_token"]
    assert "set-cookie" not in resumed.headers
    fetched = await client.get("/api/v1/session")
    assert fetched.json() == resumed.json()
    assert fetched.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_end_invalidates_cookie_and_server_record(client):
    active = (await client.post("/api/v1/session")).json()
    error(await client.delete("/api/v1/session"), 403, "invalid_csrf_token")
    assert (await client.get("/api/v1/session")).status_code == 200
    ended = await client.delete("/api/v1/session", headers={"X-CSRF-Token": active["csrf_token"]})
    assert ended.json() == {"schema_version": 1, "status": "ended"}
    assert "Max-Age=0" in ended.headers["set-cookie"]
    error(await client.get("/api/v1/session"), 401, "session_required")


@pytest.mark.anyio
async def test_expiry_requires_explicit_new_session_and_does_not_recreate_on_get(client, session_state):
    old = (await client.post("/api/v1/session")).json()
    session_state[1].now = 1200
    response = await client.get("/api/v1/session")
    error(response, 401, "session_required")
    assert "set-cookie" not in response.headers and not session_state[0]._records
    fresh = await client.post("/api/v1/session")
    assert fresh.json()["expires_in_seconds"] == 1200
    assert fresh.json()["csrf_token"] != old["csrf_token"]


@pytest.mark.anyio
async def test_two_browsers_are_isolated_and_tokens_are_not_logged(client, caplog):
    caplog.set_level(logging.DEBUG)
    first = (await client.post("/api/v1/session")).json()
    token = client.cookies.get(SECURE_COOKIE_NAME)
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=server.app),
                                  base_url="https://session.test", headers={"X-Session-Request": "1"}) as other:
        error(await other.get("/api/v1/session"), 401, "session_required")
        second = (await other.post("/api/v1/session")).json()
        assert second["csrf_token"] != first["csrf_token"]
        error(await other.delete("/api/v1/session", headers={"X-CSRF-Token": first["csrf_token"]}),
              403, "invalid_csrf_token")
    assert token not in caplog.text and first["csrf_token"] not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
async def test_missing_or_duplicate_custom_request_header_is_rejected(client, method):
    client.headers.pop("X-Session-Request")
    error(await client.request(method, "/api/v1/session"), 403, "session_request_header_required")
    error(await client.request(method, "/api/v1/session", headers=[("X-Session-Request", "1"),
                                                                   ("X-Session-Request", "1")]),
          403, "session_request_header_required")


@pytest.mark.anyio
@pytest.mark.parametrize("origin", ["null", "https://foreign.test", "https://session.test.foreign.test",
                                    "https://foreign@session.test", "https://session.test:invalid", "https://session.test:0"])
async def test_untrusted_origins_are_rejected_before_allocating_a_session(client, session_state, origin):
    error(await client.post("/api/v1/session", headers={"Origin": origin}), 403, "session_origin_forbidden")
    assert not session_state[0]._records


@pytest.mark.anyio
async def test_cross_site_fetch_is_rejected_even_if_origin_header_looks_allowed(client):
    error(await client.post("/api/v1/session", headers={"Origin": "https://session.test", "Sec-Fetch-Site": "cross-site"}),
          403, "session_origin_forbidden")


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
async def test_session_api_does_not_accept_or_retain_request_bodies(client, method):
    error(await client.request(method, "/api/v1/session", content=b"fictional unexpected body"), 422, "invalid_request")


@pytest.mark.anyio
async def test_only_cookies_are_accepted_as_session_identifiers(client):
    error(await client.get("/api/v1/session", params={"session_id": "A" * 43}), 401, "session_required")
    response = await client.put("/api/v1/session")
    error(response, 405, "method_not_allowed")


@pytest.mark.anyio
async def test_http_is_only_allowed_on_loopback_and_forwarded_header_alone_is_insufficient(session_state):
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=server.app),
                                  base_url="http://localhost:8000", headers={"X-Session-Request": "1"}) as local:
        result = await local.post("/api/v1/session")
        assert result.status_code == 200
        cookie = result.headers["set-cookie"]
        assert LOCAL_COOKIE_NAME + "=" in cookie and "; Secure" not in cookie
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=server.app),
                                  base_url="http://remote.test", headers={"X-Session-Request": "1"}) as remote:
        error(await remote.post("/api/v1/session", headers={"X-Forwarded-Proto": "https"}),
              403, "session_https_required")


@pytest.mark.anyio
async def test_capacity_error_is_machine_readable_and_sets_no_cookie(client, session_state):
    session_state[0].create_or_resume(None)
    session_state[0].create_or_resume(None)
    response = await client.post("/api/v1/session")
    error(response, 503, "session_capacity_exceeded")
    assert "set-cookie" not in response.headers


@pytest.mark.anyio
async def test_cors_allows_credentials_only_on_session_routes_and_only_for_explicit_origin():
    app = FastAPI()
    app.state.session_store = SessionStore()
    app.state.session_allowed_origins = ["https://frontend.session.test"]
    app.add_exception_handler(SessionError, server.session_error_handler)
    app.add_middleware(SessionAwareCorsMiddleware, allow_origins=app.state.session_allowed_origins)
    app.add_middleware(server.SecurityHeadersMiddleware)
    app.include_router(router)

    @app.get("/api/healthz")
    async def health():
        return {"status": "ok"}
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="https://api.session.test") as client:
        origin = {"Origin": "https://frontend.session.test"}
        preflight = await client.options("/api/v1/session", headers={**origin,
            "Access-Control-Request-Method": "DELETE", "Access-Control-Request-Headers": "X-Session-Request,X-CSRF-Token"})
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-credentials"] == "true"
        created = await client.post("/api/v1/session", headers={**origin, "X-Session-Request": "1"})
        assert created.status_code == 200
        assert created.headers["access-control-allow-origin"] == origin["Origin"]
        public = await client.get("/api/healthz", headers=origin)
        assert "access-control-allow-credentials" not in public.headers
        denied = await client.options("/api/v1/session", headers={"Origin": "https://foreign.test",
            "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "X-Session-Request"})
        assert denied.status_code == 400 and "access-control-allow-origin" not in denied.headers
    with pytest.raises(ValueError):
        SessionAwareCorsMiddleware(app, allow_origins=["*"])


@pytest.mark.anyio
async def test_periodic_cleanup_runs_without_requests_and_shutdown_clears_active_sessions(monkeypatch):
    clock = Clock()
    store = SessionStore(SessionSettings(ttl_seconds=1, cleanup_interval_seconds=1), clock=clock)
    monkeypatch.setattr(server.app.state, "session_store", store)
    token, _ = store.create_or_resume(None)
    cleaned = asyncio.Event()
    cleanup = store.cleanup

    def observed_cleanup():
        removed = cleanup()
        if removed:
            cleaned.set()
        return removed

    monkeypatch.setattr(store, "cleanup", observed_cleanup)
    async with server.lifespan(server.app):
        clock.now = 1
        await asyncio.wait_for(cleaned.wait(), timeout=3)
        assert not store._records
        active, _ = store.create_or_resume(None)
        assert store.get(active)["status"] == "active"
    with pytest.raises(SessionError):
        store.get(active)
    with pytest.raises(SessionError):
        store.get(token)
