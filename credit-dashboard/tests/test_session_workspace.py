"""解析結果の期限付き保持・復元・競合・非永続化を架空入力で確認する。"""

import json
from pathlib import Path
import sqlite3
import tempfile
from copy import deepcopy

import httpx2
import pytest

import server
from academic_rules import load_rule_profile
from api_contracts.examples import fictional_catalog, fictional_grades, fictional_timetable, multipart
from session_store import SessionError, SessionSettings, SessionStore


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def state(monkeypatch):
    now = [0.0]
    store = SessionStore(clock=lambda: now[0])
    monkeypatch.setattr(server.app.state, "session_store", store)
    monkeypatch.setattr(server.app.state, "session_allowed_origins", [])
    monkeypatch.setattr(server, "_recommendation_catalogs", lambda: [fictional_catalog()])
    yield store, now
    store.clear()


@pytest.fixture
async def client(state):
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=server.app),
                                  base_url="https://workspace.test", headers={"X-Session-Request": "1"}) as client:
        assert (await client.post("/api/v1/session")).status_code == 200
        yield client


async def workspace(client):
    response = await client.get("/api/v1/session/workspace")
    assert response.status_code == 200
    return response.json()


def headers(snapshot):
    return {"X-CSRF-Token": snapshot["session"]["csrf_token"], "X-Session-Revision": str(snapshot["revision"])}


async def upload(client, kind, raw):
    return await client.post("/api/v1/session/" + kind, headers=headers(await workspace(client)),
                             files=multipart({}, file=raw))


async def search(client, path="recommendation-searches"):
    snapshot = await workspace(client)
    fields = {"profile_id": fictional_catalog()["profile_id"], "academic_year": 2026, "term": 3}
    if path == "recommendations":
        fields.update(weekday=2, period=2)
    return await client.post("/api/v1/session/" + path, headers=headers(snapshot), files=multipart(fields))


def test_store_snapshots_are_independent_and_clear_prevents_late_commit():
    store = SessionStore()
    token, session = store.create_or_resume(None)
    csrf = session["csrf_token"]
    pending = store.begin_update(token, csrf, 0, "report")
    saved = store.commit(token, csrf, pending, "report", {"student": {"name": "架空"}})
    saved["report"]["student"]["name"] = "架空の変更"
    assert store.workspace(token)["report"]["student"]["name"] == "架空"
    pending = store.begin_update(token, csrf, saved["revision"], "report")
    store.begin_update(token, csrf, pending, "report")
    with pytest.raises(SessionError) as failure:
        store.commit(token, csrf, pending, "report", {"student": {"name": "架空の遅延"}})
    assert failure.value.code == "session_revision_conflict"
    assert store.workspace(token)["report"] is None
    assert store._stored_bytes == 0


def test_expiry_and_end_during_processing_do_not_recreate_state():
    now = [0.0]
    store = SessionStore(clock=lambda: now[0])
    token, session = store.create_or_resume(None)
    pending = store.begin_update(token, session["csrf_token"], 0, "report")
    now[0] = 1200
    with pytest.raises(SessionError) as failure:
        store.commit(token, session["csrf_token"], pending, "report", {"fictional": True})
    assert failure.value.code == "session_required" and not store._records
    token, session = store.create_or_resume(None)
    pending = store.begin_update(token, session["csrf_token"], 0, "timetable")
    store.end(token, session["csrf_token"])
    with pytest.raises(SessionError):
        store.commit(token, session["csrf_token"], pending, "timetable", {"fictional": True})
    assert store._stored_bytes == 0


def test_data_limits_include_both_documents_and_reclaim_global_capacity():
    payload = {"fictional": "架空"}
    size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    store = SessionStore(SessionSettings(max_data_bytes=size, total_data_bytes=size))
    first, a = store.create_or_resume(None)
    second, b = store.create_or_resume(None)
    revision = store.begin_update(first, a["csrf_token"], 0, "report")
    saved = store.commit(first, a["csrf_token"], revision, "report", payload)
    assert store._stored_bytes == size
    pending = store.begin_update(first, a["csrf_token"], saved["revision"], "timetable")
    with pytest.raises(SessionError) as failure:
        store.commit(first, a["csrf_token"], pending, "timetable", payload)
    assert failure.value.code == "session_data_too_large"
    second_revision = store.begin_update(second, b["csrf_token"], 0, "report")
    with pytest.raises(SessionError) as failure:
        store.commit(second, b["csrf_token"], second_revision, "report", payload)
    assert failure.value.code == "session_memory_full"
    store.end(first, a["csrf_token"])
    store.commit(second, b["csrf_token"], second_revision, "report", payload)
    assert store._stored_bytes == size
    store.clear()
    assert store._stored_bytes == 0


def test_expiry_cleanup_releases_stored_data_bytes():
    now = [0.0]
    store = SessionStore(clock=lambda: now[0])
    token, session = store.create_or_resume(None)
    revision = store.begin_update(token, session["csrf_token"], 0, "report")
    store.commit(token, session["csrf_token"], revision, "report", {"fictional": True})
    assert store._stored_bytes > 0
    now[0] = 1200
    assert store.cleanup() == 1
    assert store._stored_bytes == 0


@pytest.mark.anyio
async def test_upload_restore_and_recommend_without_original_files(client, state):
    empty = await workspace(client)
    assert empty["revision"] == 0 and empty["report"] is None and empty["timetable"] is None
    report = await upload(client, "reports", fictional_grades())
    assert report.status_code == 200
    assert report.json()["report"]["student"]["name"].startswith("架空")
    assert [course["score"] for course in report.json()["report"]["courses"]] == [85.5, 0, 90, 100, 80, None]
    timetable = await upload(client, "timetables", fictional_timetable(empty=True))
    assert timetable.status_code == 200
    restored = await workspace(client)
    assert restored["report"] == report.json()["report"]
    assert restored["timetable"] == timetable.json()["timetable"]
    assert restored["revision"] == 4
    for path in ["recommendations", "recommendation-searches"]:
        response = await search(client, path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "student" not in response.json()
    state[1][0] = 1199
    assert (await workspace(client))["session"]["expires_in_seconds"] == 1
    state[1][0] = 1200
    assert (await client.get("/api/v1/session/workspace")).status_code == 401
    assert state[0]._stored_bytes == 0


@pytest.mark.anyio
async def test_cached_search_matches_original_stateless_search(client):
    await upload(client, "reports", fictional_grades())
    await upload(client, "timetables", fictional_timetable(empty=True))
    cached = await search(client)
    fields = {"profile_id": fictional_catalog()["profile_id"], "academic_year": 2026, "term": 3}
    original = await client.post("/api/v1/recommendation-searches", files=multipart(
        fields, grades_file=fictional_grades(), timetable_file=fictional_timetable(empty=True)))
    assert cached.json() == original.json()


@pytest.mark.anyio
async def test_stateless_upload_does_not_implicitly_hold_student_data(client):
    response = await client.post("/api/v1/reports", files=multipart({}, file=fictional_grades()))
    assert response.status_code == 200
    assert (await workspace(client))["report"] is None


@pytest.mark.anyio
@pytest.mark.parametrize(("raw", "code"), [
    (b"fictional invalid csv", "missing_columns"),
    ("No.,科目,科目区分,単位数,合否,得点\n1,架空科目,英語,2,合,架空の不正得点\n".encode("utf-8"), "invalid_value"),
], ids=["invalid_structure", "invalid_score"])
async def test_failed_replacement_clears_previous_report_and_preserves_timetable(client, raw, code):
    await upload(client, "reports", fictional_grades())
    await upload(client, "timetables", fictional_timetable(empty=True))
    snapshot = await workspace(client)
    failed = await upload(client, "reports", raw)
    assert failed.status_code == 422
    assert failed.json()["error"]["code"] == code
    restored = await workspace(client)
    assert restored["report"] is None and restored["timetable"] == snapshot["timetable"]
    assert restored["revision"] > snapshot["revision"]


@pytest.mark.anyio
async def test_explicit_document_clear_cannot_be_undone_by_old_revision(client):
    await upload(client, "reports", fictional_grades())
    snapshot = await workspace(client)
    cleared = await client.delete("/api/v1/session/reports", headers=headers(snapshot))
    assert cleared.status_code == 200 and cleared.json()["report"] is None
    rejected = await client.post("/api/v1/session/reports", headers=headers(snapshot), files=multipart({}, file=fictional_grades()))
    assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "session_revision_conflict"
    assert (await workspace(client))["report"] is None


@pytest.mark.anyio
async def test_sessions_do_not_share_reports(client):
    await upload(client, "reports", fictional_grades())
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=server.app), base_url="https://workspace.test",
                                  headers={"X-Session-Request": "1"}) as other:
        assert (await other.get("/api/v1/session/workspace")).status_code == 401
        await other.post("/api/v1/session")
        assert (await workspace(other))["report"] is None
        assert (await workspace(client))["report"] is not None


@pytest.mark.anyio
@pytest.mark.parametrize("bad_headers,code", [
    ({"X-Session-Revision": "0"}, "invalid_csrf_token"),
    ({"X-Session-Revision": "-1"}, "invalid_session_revision"),
    ({"X-Session-Revision": "NaN"}, "invalid_session_revision"),
    ({"X-Session-Revision": "1.5"}, "invalid_session_revision"),
])
async def test_mutations_require_valid_csrf_and_revision(client, bad_headers, code):
    response = await client.delete("/api/v1/session/reports", headers=bad_headers)
    assert response.status_code in {403, 422} and response.json()["error"]["code"] == code
    assert (await workspace(client))["revision"] == 0


@pytest.mark.anyio
async def test_untrusted_origin_cannot_read_or_change_workspace(client):
    await upload(client, "reports", fictional_grades())
    snapshot = await workspace(client)
    for method, path in [("GET", "workspace"), ("DELETE", "reports")]:
        response = await client.request(method, "/api/v1/session/" + path,
            headers={**headers(snapshot), "Origin": "https://foreign.test"})
        assert response.status_code == 403
    assert (await workspace(client))["revision"] == snapshot["revision"]


@pytest.mark.anyio
async def test_session_data_capacity_failure_does_not_restore_old_results(client, state):
    state[0].settings = SessionSettings(max_data_bytes=100, total_data_bytes=100)
    response = await upload(client, "reports", fictional_grades())
    assert response.status_code == 413 and response.json()["error"]["code"] == "session_data_too_large"
    assert (await workspace(client))["report"] is None and state[0]._stored_bytes == 0


@pytest.mark.anyio
async def test_raw_csv_tempfiles_and_database_are_not_used_for_retention(client, state, monkeypatch, caplog):
    def forbidden(*args, **kwargs):
        raise AssertionError("Student input must not be persisted")
    monkeypatch.setattr(tempfile, "TemporaryFile", forbidden)
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    response = await upload(client, "reports", fictional_grades())
    assert response.status_code == 200
    record = next(iter(state[0]._records.values()))
    assert record.report_json.startswith(b"{") and b"fictional.csv" not in record.report_json
    assert record.timetable_json is None
    assert "T00000000" not in caplog.text and "架空 契約確認" not in caplog.text


@pytest.mark.anyio
async def test_upload_finishing_after_session_end_is_rejected(client, monkeypatch, state):
    original = server.create_report

    async def delayed(request):
        parsed = await original(request)
        state[0].clear()
        return parsed

    monkeypatch.setattr(server, "create_report", delayed)
    response = await upload(client, "reports", fictional_grades())
    assert response.status_code == 401 and not state[0]._records


@pytest.mark.anyio
async def test_search_requires_both_parsed_inputs(client):
    response = await search(client)
    assert response.status_code == 409 and response.json()["error"]["code"] == "session_inputs_missing"


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["recommendations", "recommendation-searches"])
async def test_cached_results_are_not_reused_under_another_profile(client, monkeypatch, path):
    await upload(client, "reports", fictional_grades())
    await upload(client, "timetables", fictional_timetable(empty=True))
    other = deepcopy(load_rule_profile())
    other["profile_id"] = "fictional-different-profile"
    monkeypatch.setattr(server, "_selected_profile", lambda value: other)
    response = await search(client, path)
    assert response.status_code == 409 and response.json()["error"]["code"] == "session_profile_mismatch"
    assert (await workspace(client))["report"]["curriculum"]["rules_version"] != other["profile_id"]


def test_a_concurrent_document_update_cannot_commit_an_older_snapshot():
    store = SessionStore()
    token, meta = store.create_or_resume(None)
    csrf = meta["csrf_token"]
    report_revision = store.begin_update(token, csrf, 0, "report")
    table_revision = store.begin_update(token, csrf, report_revision, "timetable")
    store.commit(token, csrf, table_revision, "timetable", {"fictional": True})
    with pytest.raises(SessionError) as failure:
        store.commit(token, csrf, report_revision, "report", {"fictional": True})
    assert failure.value.code == "session_revision_conflict"
    saved = store.workspace(token)
    assert saved["report"] is None and saved["timetable"] == {"fictional": True}
