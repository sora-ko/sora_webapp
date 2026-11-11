"""ローカルASGIアプリと固定の架空入力だけで公開応答例を作る。CSVパスは受け付けない。"""

from __future__ import annotations

from copy import deepcopy
import csv
from dataclasses import dataclass
import io
from pathlib import Path
from unittest.mock import patch

import httpx2

import server
from academic_rules import load_rule_profile
from recommendations import RecommendationError
from session_store import SessionSettings, SessionStore


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Example:
    name: str
    method: str
    path: str
    status: int
    model: str
    body: dict


def _csv(rows: list[list[str]]) -> bytes:
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def _shared_sample(name: str) -> bytes:
    if name not in {"first-year-sample.csv", "graduation-sample-original-format.csv"}:
        raise ValueError("Only reviewed fictional examples are supported")
    raw = (ROOT / "examples" / name).read_bytes()
    text = raw.decode("cp932" if "original-format" in name else "utf-8-sig")
    metadata = {cell: row[index + 1] for row in csv.reader(io.StringIO(text))
                for index, cell in enumerate(row[:-1]) if cell in {"[学生氏名]", "[在籍番号]"}}
    if "架空" not in metadata.get("[学生氏名]", "") or metadata.get("[在籍番号]") != "T00000000":
        raise ValueError("The reviewed example must contain an explicitly fictional identity")
    return raw


def fictional_grades(*, grade: str = "2", pending: bool = False) -> bytes:
    rows = [
        ["[学生氏名]", "架空 契約確認", "[在籍番号]", "T00000000", "[学生所属]",
         "知能情報システムプログラム（架空学生）", "[学年]", grade],
        ["No.", "開講番号", "科目", "科目区分", "単位数", "合否", "修得年度", "修得学期"],
        ["1", "FAKE-1", "架空の修得科目", "英語（英語）", "1.5", "合", "2025", "第1学期"],
        ["2", "FAKE-2", "架空の未修得科目", "自然科学（工学）", "2", "否", "", ""],
        ["3", "FAKE-3", "架空の未確定科目", "英語（英語）", "", "合", "", ""],
        ["4", "FAKE-4", "架空の分類不明", "架空の未知区分", "2", "合", "", ""],
        ["5", "FAKE-5", "架空の一覧外専門", "専門応用科目群（選択）", "2", "合", "", ""],
        ["6", "FAKE-6", "架空の結果不明", "英語（英語）", "2", "判定待ち", "", ""],
    ]
    if pending:
        rows.append(["7", "FAKE-7", "架空の教養候補A", "自然科学（工学）", "2", "", "", ""])
    return _csv(rows)


def fictional_timetable(*, empty: bool = False, missing_code: bool = False,
                        outside: bool = False, exclude_zero: bool = False,
                        no_context: bool = False, weekend: bool = False) -> bytes:
    rows = [] if no_context else [["[年度・学期]", "2026年度 第2学期"]]
    days = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日"] + (["土曜日", "日曜日"] if weekend else [])
    rows.append(["", *days])
    for period in range(1, 8 if weekend else 6):
        columns = len(days) + 1
        code, subject, teacher = [""] * columns, [""] * columns, [""] * columns
        code[0] = f"{period}限"
        if not empty and period == 1:
            code[1], subject[1], teacher[1] = "263T9501", "架空の登録科目", "架空教員"
        if not empty and period == 2:
            code[3], subject[3], teacher[3] = "264T9502", "架空の別ターム科目", "架空教員"
        if missing_code and period == 2:
            subject[2] = "架空の開講番号不明科目"
        if weekend and period == 7:
            code[-1], subject[-1], teacher[-1] = "263T9503", "架空の休日科目", "架空教員"
        rows.extend([code, subject, teacher])
    if outside:
        rows.append(["通常科目", "263T9599"])
    if exclude_zero:
        rows.append(["集中講義", "260T9599"])
    return _csv(rows)


def fictional_catalog() -> dict:
    profile_id = load_rule_profile()["profile_id"]
    return {"schema_version": 3, "academic_year": 2026, "profile_id": profile_id,
            "courses": [
                {"course_code": "263G9901", "name": "架空の教養候補A", "credits": 2,
                 "category": "自然科学（工学）", "terms": [3], "schedule": [{"weekday": 2, "period": 2}]},
                {"course_code": "263G9902", "name": "架空の教養候補B", "credits": 1.5,
                 "category": "英語（英語）", "terms": [3], "schedule": [{"weekday": 3, "period": 3}]},
                {"course_code": "263G9903", "name": "架空の教養候補C", "credits": 2,
                 "category": "新潟大学個性化科目（地域）", "terms": [3],
                 "schedule": [{"weekday": 4, "period": 4}, {"weekday": 5, "period": 4}]},
            ]}


def multipart(fields: dict, **files: bytes) -> list:
    return ([(key, (None, str(value))) for key, value in fields.items()]
            + [(key, ("fictional.csv", value, "text/csv")) for key, value in files.items()])


async def collect_examples() -> list[Example]:
    """ネットワーク接続、利用者データの入力、CSV・応答のログ出力を行わない。"""
    profile_id = load_rule_profile()["profile_id"]
    context = {"profile_id": profile_id, "academic_year": 2026, "term": 3}
    slot = {**context, "weekday": 2, "period": 2}
    examples = []
    transport = httpx2.ASGITransport(app=server.app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://contract.test") as client:
        async def record(name, method, path, model, *, status=200, **kwargs):
            response = await client.request(method, path, **kwargs)
            if response.status_code != status:
                raise ValueError(f"Unexpected HTTP status for fictional case {name}: {response.status_code}")
            if response.headers.get("cache-control") != "no-store" or "set-cookie" in response.headers:
                raise ValueError("API privacy headers changed in fictional contract case: " + name)
            examples.append(Example(name, method, path, status, model, response.json()))

        with patch.object(server, "_recommendation_catalogs", return_value=[fictional_catalog()]):
            await record("health", "GET", "/api/healthz", "HealthResponse")
            await record("rule-profiles", "GET", "/api/v1/rule-profiles", "RuleProfilesResponse")
            await record("catalogs", "GET", "/api/v1/recommendation-catalogs", "RecommendationCatalogsResponse")
            for name, raw, fields in [
                ("report-year1", _shared_sample("first-year-sample.csv"), {"profile_id": profile_id}),
                ("report-year2", fictional_grades(), {"profile_id": profile_id}),
                ("report-year3", fictional_grades(grade="3"), {"profile_id": profile_id, "residence_years": 2.5}),
                ("report-graduation", _shared_sample("graduation-sample-original-format.csv"), {"profile_id": profile_id}),
                ("report-unknown", fictional_grades(grade="不明"), {"profile_id": profile_id}),
                ("report-no-courses", _csv([["No.", "科目", "科目区分", "単位数", "合否"]]), {}),
            ]:
                await record(name, "POST", "/api/v1/reports", "ReportResponse", files=multipart(fields, file=raw))
            for name, raw in [
                ("timetable", fictional_timetable()),
                ("timetable-empty", fictional_timetable(empty=True)),
                ("timetable-term-zero", fictional_timetable(exclude_zero=True)),
                ("timetable-missing-code", fictional_timetable(missing_code=True)),
                ("timetable-outside-grid", fictional_timetable(outside=True)),
                ("timetable-no-context", fictional_timetable(empty=True, no_context=True)),
                ("timetable-weekend", fictional_timetable(weekend=True)),
            ]:
                await record(name, "POST", "/api/v1/timetables", "TimetableResponse", files=multipart({}, file=raw))
            for name, fields, raw in [
                ("slot-catalog", slot, None),
                ("slot-empty", {**slot, "weekday": 1, "period": 5}, None),
                ("slot-timetable", slot, fictional_timetable()),
                ("slot-occupied", {**slot, "weekday": 1, "period": 1}, fictional_timetable()),
                ("slot-unknown", slot, fictional_timetable(missing_code=True)),
            ]:
                await record(name, "POST", "/api/v1/recommendations", "SlotRecommendationsResponse",
                             files=multipart(fields, **({"file": raw} if raw is not None else {})))
            for name, grades, timetable in [
                ("search-ok", _shared_sample("first-year-sample.csv"), fictional_timetable(empty=True)),
                ("search-review", fictional_grades(pending=True), fictional_timetable(empty=True)),
                ("search-unknown-time", fictional_grades(), fictional_timetable(missing_code=True)),
                ("search-fulfilled", _shared_sample("graduation-sample-original-format.csv"), fictional_timetable(empty=True)),
                ("search-fulfilled-unknown-time", _shared_sample("graduation-sample-original-format.csv"), fictional_timetable(missing_code=True)),
            ]:
                await record(name, "POST", "/api/v1/recommendation-searches", "RecommendationSearchResponse",
                             files=multipart(context, grades_file=grades, timetable_file=timetable))
            await record("error-missing-file", "POST", "/api/v1/reports", "ErrorResponse", status=400,
                         files=multipart({"profile_id": profile_id}))
            await record("error-invalid-csv", "POST", "/api/v1/reports", "ErrorResponse", status=422,
                         files=multipart({}, file=b"fictional invalid csv"))
            await record("error-unknown-profile", "POST", "/api/v1/reports", "ErrorResponse", status=422,
                         files=multipart({"profile_id": "fictional-unregistered-profile"}, file=fictional_grades()))
            await record("error-unsupported-media", "POST", "/api/v1/reports", "ErrorResponse", status=415,
                         content=b"fictional")
            await record("error-invalid-context", "POST", "/api/v1/recommendations", "ErrorResponse", status=422,
                         files=multipart({**slot, "term": 0}))
            await record("error-invalid-residence", "POST", "/api/v1/reports", "ErrorResponse", status=422,
                         files=multipart({"residence_years": "NaN"}, file=fictional_grades()))
            await record("error-invalid-multipart", "POST", "/api/v1/reports", "ErrorResponse", status=400,
                         content=b"fictional", headers={"content-type": "multipart/form-data"})
            await record("error-multiple-files", "POST", "/api/v1/reports", "ErrorResponse", status=400,
                         files=[("file", ("fictional-a.csv", fictional_grades(), "text/csv")),
                                ("file", ("fictional-b.csv", fictional_grades(), "text/csv"))])
            await record("error-unsupported-encoding", "POST", "/api/v1/reports", "ErrorResponse", status=415,
                         files=multipart({}, file=b"\x81"))
            await record("error-no-catalog", "POST", "/api/v1/recommendations", "ErrorResponse", status=404,
                         files=multipart({**slot, "academic_year": 2027}))
            await record("error-search-csv", "POST", "/api/v1/recommendation-searches", "ErrorResponse", status=422,
                         files=multipart(context, grades_file=b"fictional invalid", timetable_file=fictional_timetable()))
            await record("error-route", "GET", "/api/v1/fictional-missing", "ErrorResponse", status=404)
            await record("error-method", "GET", "/api/v1/reports", "ErrorResponse", status=405)
            await record("error-legacy", "GET", "/api/report", "ErrorResponse", status=410)
            await record("error-too-large", "POST", "/api/v1/reports", "ErrorResponse", status=413,
                         files=multipart({}, file=b"x" * (server.MAX_FILE_BYTES + 1)))

        with patch.object(server, "_recommendation_catalogs", return_value=[]):
            await record("catalogs-empty", "GET", "/api/v1/recommendation-catalogs", "RecommendationCatalogsResponse")
        blocked_profile = deepcopy(load_rule_profile())
        question = blocked_profile["open_questions"][0]
        question.update(status="open", question="架空の契約確認用: 根拠の確認待ち。")
        blocked_profile["requirements"]["graduation"].update(
            status="blocked", blocking_open_question_ids=[question["id"]])
        with (patch.object(server, "_selected_profile", return_value=blocked_profile),
              patch.object(server, "_recommendation_catalogs", return_value=[fictional_catalog()])):
            await record("report-blocked", "POST", "/api/v1/reports", "ReportResponse",
                         files=multipart({}, file=_shared_sample("graduation-sample-original-format.csv")))
            await record("search-blocked", "POST", "/api/v1/recommendation-searches", "RecommendationSearchResponse",
                         files=multipart(context, grades_file=_shared_sample("graduation-sample-original-format.csv"),
                                         timetable_file=fictional_timetable(empty=True)))
        empty_catalog = {**fictional_catalog(), "courses": []}
        with patch.object(server, "_recommendation_catalogs", return_value=[empty_catalog]):
            await record("search-empty", "POST", "/api/v1/recommendation-searches", "RecommendationSearchResponse",
                         files=multipart(context, grades_file=fictional_grades(), timetable_file=fictional_timetable(empty=True)))
        with patch.object(server, "_recommendation_catalogs", side_effect=RecommendationError(
            503, "recommendation_catalog_invalid", "推薦用カタログを読み取れません。配置と形式を確認してください。"
        )):
            await record("error-invalid-catalog", "GET", "/api/v1/recommendation-catalogs", "ErrorResponse", status=503)
        with patch.object(server, "_recommendation_catalogs", side_effect=RuntimeError("fictional failure")):
            await record("error-internal", "GET", "/api/v1/recommendation-catalogs", "ErrorResponse", status=500)
    return examples + await collect_session_examples() + await collect_workspace_examples()


async def collect_session_examples() -> list[Example]:
    """固定の架空トークンと時計で再現する。実行中のセッションには触れない。"""
    now = [0.0]
    counter = [0]

    def fictional_token():
        counter[0] += 1
        return f"fictional_contract_token_{counter[0]:04d}".ljust(43, "_")

    store = SessionStore(SessionSettings(max_sessions=1), clock=lambda: now[0], token_factory=fictional_token)
    examples = []
    with (patch.object(server.app.state, "session_store", store),
          patch.object(server.app.state, "session_allowed_origins", [])):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=server.app),
                                      base_url="https://contract.test", headers={"X-Session-Request": "1"}) as client:
            async def record(name, method, model="ErrorResponse", *, status=200, cookie=False, **kwargs):
                response = await client.request(method, "/api/v1/session", **kwargs)
                if response.status_code != status or response.headers.get("cache-control") != "no-store":
                    raise ValueError("Unexpected HTTP session contract status: " + name)
                if ("set-cookie" in response.headers) != cookie:
                    raise ValueError("Unexpected cookie lifecycle in fictional case: " + name)
                body = response.json()
                examples.append(Example(name, method, "/api/v1/session", status, model, body))
                return body

            try:
                await record("error-session-required", "GET", status=401)
                await record("error-session-header", "POST", status=403, headers={"X-Session-Request": "0"})
                await record("error-session-origin", "POST", status=403, headers={"Origin": "https://foreign.test"})
                created = await record("session-created", "POST", "SessionResponse", cookie=True)
                await record("session-active", "GET", "SessionResponse")
                now[0] = 60
                await record("session-resumed", "POST", "SessionResponse")
                await record("error-session-csrf", "DELETE", status=403, headers={"X-CSRF-Token": "invalid"})
                await record("session-ended", "DELETE", "SessionEndedResponse", cookie=True,
                             headers={"X-CSRF-Token": created["csrf_token"]})
                store.create_or_resume(None)
                await record("error-session-capacity", "POST", status=503)
                now[0] += 1200
                await client.post("/api/v1/session")
                now[0] += 1200
                await record("error-session-expired", "GET", status=401)
            finally:
                store.clear()
    return examples


async def collect_workspace_examples() -> list[Example]:
    now, counter = [0.0], [0]

    def token():
        counter[0] += 1
        return f"fictional_workspace_token_{counter[0]:04d}".ljust(43, "_")

    store = SessionStore(clock=lambda: now[0], token_factory=token)
    examples = []
    prefix = "/api/v1/session"
    with (patch.object(server.app.state, "session_store", store),
          patch.object(server.app.state, "session_allowed_origins", []),
          patch.object(server, "_recommendation_catalogs", return_value=[fictional_catalog()])):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=server.app), base_url="https://contract.test",
                                      headers={"X-Session-Request": "1"}) as client:
            async def mutation_headers():
                response = await client.get(prefix + "/workspace")
                if response.status_code != 200:
                    raise ValueError("Fictional workspace setup failed")
                saved = response.json()
                return {"X-CSRF-Token": saved["session"]["csrf_token"], "X-Session-Revision": str(saved["revision"])}

            async def record(name, method, path, model="SessionWorkspaceResponse", *, status=200, **kwargs):
                response = await client.request(method, prefix + path, **kwargs)
                if response.status_code != status or response.headers.get("cache-control") != "no-store" or "set-cookie" in response.headers:
                    raise ValueError("Unexpected fictional workspace response: " + name)
                examples.append(Example(name, method, prefix + path, status, model, response.json()))

            try:
                created = await client.post(prefix)
                if created.status_code != 200:
                    raise ValueError("Fictional workspace session failed")
                await record("workspace-empty", "GET", "/workspace")
                await record("workspace-report", "POST", "/reports", headers=await mutation_headers(),
                             files=multipart({}, file=_shared_sample("first-year-sample.csv")))
                await record("workspace-both", "POST", "/timetables", headers=await mutation_headers(),
                             files=multipart({}, file=fictional_timetable(empty=True)))
                await record("workspace-restored", "GET", "/workspace")
                context = {"profile_id": fictional_catalog()["profile_id"], "academic_year": 2026, "term": 3}
                await record("workspace-slot", "POST", "/recommendations", "SlotRecommendationsResponse",
                             headers=await mutation_headers(), files=multipart({**context, "weekday": 2, "period": 2}))
                await record("workspace-search", "POST", "/recommendation-searches", "RecommendationSearchResponse",
                             headers=await mutation_headers(), files=multipart(context))
                stale = await mutation_headers()
                await record("workspace-cleared", "DELETE", "/reports", headers=stale)
                await record("error-workspace-conflict", "DELETE", "/reports", "ErrorResponse", status=409, headers=stale)
                await record("error-workspace-inputs", "POST", "/recommendation-searches", "ErrorResponse", status=409,
                             headers=await mutation_headers(), files=multipart(context))
                await record("error-workspace-csv", "POST", "/reports", "ErrorResponse", status=422,
                             headers=await mutation_headers(), files=multipart({}, file=b"fictional invalid csv"))
                await record("error-workspace-media", "POST", "/reports", "ErrorResponse", status=415,
                             headers=await mutation_headers(), json={"fictional": True})
                await record("error-workspace-csrf", "DELETE", "/timetables", "ErrorResponse", status=403,
                             headers={**await mutation_headers(), "X-CSRF-Token": "invalid"})
                await record("workspace-cleared-all-documents", "DELETE", "/timetables", headers=await mutation_headers())
                store.settings = SessionSettings(max_data_bytes=100, total_data_bytes=100)
                await record("error-workspace-capacity", "POST", "/reports", "ErrorResponse", status=413,
                             headers=await mutation_headers(), files=multipart({}, file=fictional_grades()))
                now[0] = 1200
                await record("error-workspace-expired", "GET", "/workspace", "ErrorResponse", status=401)
            finally:
                store.clear()
    return examples
