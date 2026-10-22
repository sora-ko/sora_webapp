import csv
import io
import tempfile
from pathlib import Path

import httpx2
import pytest

import server
from server import MAX_FILE_BYTES, app


HEADERS = ["No.", "分野", "水準", "開講番号", "科目", "科目区分", "必選区分", "単位数", "合否"]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


def csv_bytes(rows: list[list[str]], encoding: str = "utf-8-sig") -> bytes:
    output = io.StringIO(newline="")
    csv.writer(output).writerows(rows)
    return output.getvalue().encode(encoding)


def valid_csv() -> bytes:
    return csv_bytes([
        ["[学生氏名]", "架空学生", "[在籍番号]", "T00000000", "[学生所属]", "架空所属", "[学年]", "2"],
        HEADERS,
        ["1", "10", "1", "X-1", "架空科目", "英語（英語）", "必修", "2", "合"],
        ["2", "20", "2", "X-2", "架空専門科目", "専門応用科目群（選択）", "選択", "2", ""],
    ], "cp932")


@pytest.mark.anyio
async def test_upload_returns_versioned_report_without_logging_student_data(client, caplog):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("grades.csv", valid_csv(), "text/csv")},
    )
    assert response.status_code == 200
    report = response.json()
    assert report["schema_version"] == 2
    assert report["student"]["name"] == "架空学生"
    assert report["student"]["student_number"] == "T00000000"
    assert report["summary"]["earned_credits"] == 2
    assert report["summary"]["unconfirmed_credits"] == 2
    assert "架空学生" not in caplog.text
    assert "T00000000" not in caplog.text


@pytest.mark.anyio
async def test_upload_does_not_use_spooled_temporary_files(client, monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("一時ファイルを使用してはいけません")

    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", fail_if_called)
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("grades.csv", valid_csv(), "text/csv")},
    )
    assert response.status_code == 200


@pytest.mark.anyio
async def test_missing_file_has_machine_readable_error(client):
    response = await client.post("/api/v1/reports", files={"other": (None, "value")})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_file"


@pytest.mark.anyio
async def test_multiple_files_are_rejected(client):
    response = await client.post(
        "/api/v1/reports",
        files=[
            ("file", ("first.csv", valid_csv(), "text/csv")),
            ("file", ("second.csv", valid_csv(), "text/csv")),
        ],
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "multiple_files"


@pytest.mark.anyio
async def test_empty_file_is_rejected(client):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_csv"


@pytest.mark.anyio
async def test_file_larger_than_limit_is_rejected(client):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("large.csv", b"x" * (MAX_FILE_BYTES + 1), "text/csv")},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


@pytest.mark.anyio
async def test_unsupported_encoding_is_rejected(client):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("grades.csv", b"\x81", "text/csv")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_encoding"


@pytest.mark.anyio
async def test_missing_columns_is_rejected(client):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("grades.csv", csv_bytes([["別の列"], ["値"]]), "text/csv")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "missing_columns"


@pytest.mark.anyio
async def test_file_name_and_declared_mime_are_not_trusted(client):
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("not-a-csv.exe", valid_csv(), "application/octet-stream")},
    )
    assert response.status_code == 200


@pytest.mark.anyio
async def test_non_multipart_request_is_rejected(client):
    response = await client.post(
        "/api/v1/reports",
        content=valid_csv(),
        headers={"content-type": "text/csv"},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


@pytest.mark.anyio
async def test_api_routing_errors_are_machine_readable(client):
    missing = await client.get("/api/v1/missing")
    wrong_method = await client.get("/api/v1/reports")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "route_not_found"
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["code"] == "method_not_allowed"


@pytest.mark.anyio
async def test_security_headers_and_health_check(client):
    response = await client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_upload_screen_uses_versioned_api_without_browser_persistence():
    html = Path("static/index.html").read_text(encoding="utf-8")
    script = Path("static/app.js").read_text(encoding="utf-8")
    assert any(getattr(route, "name", None) == "static" for route in app.routes)
    assert 'id="upload-form"' in html
    assert "/api/v1/reports" in script
    assert "/api/report" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script


@pytest.mark.anyio
async def test_unexpected_error_is_sanitized(client, monkeypatch, caplog):
    def fail_safely(_raw):
        raise RuntimeError("sensitive sentinel must not be returned or logged")

    monkeypatch.setattr(server, "parse_csv_bytes", fail_safely)
    response = await client.post(
        "/api/v1/reports",
        files={"file": ("grades.csv", valid_csv(), "text/csv")},
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "sensitive sentinel" not in response.text
    assert "sensitive sentinel" not in caplog.text


@pytest.mark.anyio
async def test_legacy_report_does_not_read_project_csv(client):
    response = await client.get("/api/report")
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "upload_required"
