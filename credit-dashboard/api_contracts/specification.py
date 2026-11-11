"""HTTP契約のエンドポイント情報と、型からのJSON Schema / OpenAPI生成。"""

from __future__ import annotations

from copy import deepcopy

from .models import RESPONSE_MODELS


CONTRACT_VERSION = "1.3.0"
FILE_BYTES = 5 * 1024 * 1024
MULTIPART_OVERHEAD_BYTES = 64 * 1024


def _upload_fields(*, search: bool = False, slot: bool = False, timetable: bool = False) -> dict:
    def file(description: str) -> dict:
        return {"type": "string", "format": "binary", "description": description,
                "x-max-file-bytes": FILE_BYTES}

    properties = {}
    required = []
    if search:
        properties.update(grades_file=file("大学が出力した成績CSV。UTF-8/BOM/CP932。保存しない。"),
                          timetable_file=file("履修表CSV。UTF-8/BOM/CP932。保存しない。"))
        required.extend(["grades_file", "timetable_file"])
    else:
        properties["file"] = file("CSV原本。ファイル名・拡張子・MIME typeに依存せず内容を検証する。")
        if not slot:
            required.append("file")
    if not timetable:
        properties["profile_id"] = {"type": "string", "description": "省略・空欄で既定値。規則一覧のprofile_idを使う。"}
    if search or slot:
        properties.update(
            academic_year={"type": "integer", "minimum": 2000, "maximum": 2099},
            term={"type": "integer", "minimum": 1, "maximum": 4},
        )
        required.extend(["academic_year", "term"])
    elif not timetable:
        properties["residence_years"] = {
            "anyOf": [{"type": "number", "minimum": 0, "maximum": 100}, {"const": "", "type": "string"}],
            "description": "任意の在学年数。空欄・省略はCSV学年からの仮定を使う。有限数のみ。",
        }
    if slot:
        properties.update(weekday={"type": "integer", "minimum": 1, "maximum": 5},
                          period={"type": "integer", "minimum": 1, "maximum": 5})
        required.extend(["weekday", "period"])
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": True,
            "description": "数値はFormDataへ文字列化して送る。既知フィールドの重複は拒否。未知のフィールドは無視する。",
            "x-max-field-bytes": 256,
            "x-max-multipart-bytes": FILE_BYTES * (2 if search else 1) + MULTIPART_OVERHEAD_BYTES}


REQUEST_SCHEMAS = {
    "ReportUpload": _upload_fields(),
    "TimetableUpload": _upload_fields(timetable=True),
    "SlotRecommendationUpload": _upload_fields(slot=True),
    "RecommendationSearchUpload": _upload_fields(search=True),
}
for name, source in [("WorkspaceSlotFields", "SlotRecommendationUpload"),
                     ("WorkspaceSearchFields", "RecommendationSearchUpload")]:
    schema = deepcopy(REQUEST_SCHEMAS[source])
    for key in ["file", "grades_file", "timetable_file"]:
        schema["properties"].pop(key, None)
        if key in schema["required"]:
            schema["required"].remove(key)
    schema["x-max-multipart-bytes"] = MULTIPART_OVERHEAD_BYTES
    schema["description"] = "解析済み情報を使う。年度・ターム等だけをFormDataで送信し、CSVは送信しない。"
    REQUEST_SCHEMAS[name] = schema

HEADER_SCHEMAS = {
    "SessionRequestHeaders": {
        "type": "object", "properties": {"X-Session-Request": {"type": "string", "const": "1"}},
        "required": ["X-Session-Request"], "additionalProperties": True,
    },
    "SessionEndHeaders": {
        "type": "object", "properties": {
            "X-Session-Request": {"type": "string", "const": "1"},
            "X-CSRF-Token": {"type": "string", "pattern": "^[A-Za-z0-9_-]{43}$"},
        }, "required": ["X-Session-Request", "X-CSRF-Token"], "additionalProperties": True,
    },
}
HEADER_SCHEMAS["WorkspaceMutationHeaders"] = deepcopy(HEADER_SCHEMAS["SessionEndHeaders"])
HEADER_SCHEMAS["WorkspaceMutationHeaders"]["properties"]["X-Session-Revision"] = {
    "type": "string", "pattern": "^[0-9]{1,15}$", "description": "直前のworkspace.revisionを文字列化して送る。"}
HEADER_SCHEMAS["WorkspaceMutationHeaders"]["required"].append("X-Session-Revision")

UPLOAD_ERRORS = {
    "400": ["invalid_multipart", "missing_file", "multiple_files"],
    "413": ["file_too_large"],
    "415": ["unsupported_media_type", "unsupported_encoding"],
    "422": ["invalid_request", "invalid_evaluation_context", "invalid_csv", "missing_columns", "invalid_value"],
}
COMMON_ERRORS = {"404": ["route_not_found"], "405": ["method_not_allowed"], "500": ["internal_error"]}


def _errors(*, upload=False, profile=False, recommendation=False, catalog=False) -> dict:
    errors = deepcopy(COMMON_ERRORS)
    if upload:
        errors.update(deepcopy(UPLOAD_ERRORS))
    if profile:
        errors.setdefault("422", []).append("unknown_rule_profile")
    if recommendation:
        errors.setdefault("422", []).append("invalid_recommendation_context")
        errors["404"].append("recommendation_catalog_not_found")
    if catalog or recommendation:
        errors["503"] = ["recommendation_catalog_invalid"]
    return errors


OPERATIONS = [
    dict(method="get", path="/api/healthz", operation_id="getHealth", summary="稼働確認",
         response="HealthResponse", request=None, errors=_errors()),
    dict(method="get", path="/api/v1/rule-profiles", operation_id="listRuleProfiles", summary="規則プロファイルの公開情報",
         response="RuleProfilesResponse", request=None, errors=_errors()),
    dict(method="post", path="/api/v1/reports", operation_id="createReport", summary="成績CSVの集計・学年別の参考判定",
         response="ReportResponse", request="ReportUpload", errors=_errors(upload=True, profile=True)),
    dict(method="post", path="/api/v1/timetables", operation_id="createTimetable", summary="履修表CSVの時間情報を解析",
         response="TimetableResponse", request="TimetableUpload", errors=_errors(upload=True)),
    dict(method="get", path="/api/v1/recommendation-catalogs", operation_id="listRecommendationCatalogs", summary="候補検索に対応する年度・プロファイル",
         response="RecommendationCatalogsResponse", request=None, errors=_errors(catalog=True)),
    dict(method="post", path="/api/v1/recommendations", operation_id="recommendForSlot", summary="時限を指定して教養候補を閲覧",
         response="SlotRecommendationsResponse", request="SlotRecommendationUpload",
         errors=_errors(upload=True, profile=True, recommendation=True)),
    dict(method="post", path="/api/v1/recommendation-searches", operation_id="searchRecommendations", summary="成績と空き時間から教養の不足を改善する候補を探索",
         response="RecommendationSearchResponse", request="RecommendationSearchUpload",
         errors=_errors(upload=True, profile=True, recommendation=True)),
    dict(method="get", path="/api/report", operation_id="legacyReport", summary="廃止済みの固定CSV読み込み",
         response=None, request=None, errors={**_errors(), "410": ["upload_required"]}, deprecated=True),
]
OPERATIONS[-2]["errors"]["422"].append("recommendation_rules_unsupported")


def _session_errors(*, bootstrap=False, end=False) -> dict:
    errors = _errors()
    errors["403"] = ["session_https_required", "session_request_header_required", "session_origin_forbidden"]
    errors["422"] = ["invalid_request"]
    if bootstrap:
        errors["503"] = ["session_capacity_exceeded", "session_unavailable"]
    else:
        errors["401"] = ["session_required"]
    if end:
        errors["403"].append("invalid_csrf_token")
    return errors


OPERATIONS.extend([
    dict(method="post", path="/api/v1/session", operation_id="createSession", summary="短期匿名セッションの作成・再取得（期限延長なし）",
         response="SessionResponse", request=None, headers="SessionRequestHeaders", session="bootstrap",
         errors=_session_errors(bootstrap=True)),
    dict(method="get", path="/api/v1/session", operation_id="getSession", summary="有効な短期匿名セッションを取得（期限延長なし）",
         response="SessionResponse", request=None, headers="SessionRequestHeaders", session="read",
         errors=_session_errors()),
    dict(method="delete", path="/api/v1/session", operation_id="endSession", summary="短期匿名セッションを終了",
         response="SessionEndedResponse", request=None, headers="SessionEndHeaders", session="end",
         errors=_session_errors(end=True)),
])


def _workspace_errors(*, upload=False, recommendation=False) -> dict:
    errors = _session_errors(end=True)
    errors["422"].extend(["invalid_session_revision", "unknown_rule_profile"])
    errors["409"] = ["session_revision_conflict"]
    if upload:
        for status, codes in UPLOAD_ERRORS.items():
            errors.setdefault(status, []).extend(code for code in codes if code not in errors.get(status, []))
        errors["413"].append("session_data_too_large")
        errors["503"] = ["session_memory_full"]
    if recommendation:
        errors["409"].extend(["session_profile_mismatch", "session_inputs_missing"])
        errors["422"].extend(["invalid_recommendation_context", "recommendation_rules_unsupported"])
        errors["404"].append("recommendation_catalog_not_found")
        errors["503"] = ["recommendation_catalog_invalid"]
        for status, codes in UPLOAD_ERRORS.items():
            errors.setdefault(status, []).extend(code for code in codes if code not in errors.get(status, []))
    return errors


OPERATIONS.append(dict(method="get", path="/api/v1/session/workspace", operation_id="getSessionWorkspace",
    summary="解析済みの成績・履修表を復元", response="SessionWorkspaceResponse", request=None,
    headers="SessionRequestHeaders", session="workspace_read", errors=_session_errors()))
for resource, request, action in [("reports", "ReportUpload", "Report"), ("timetables", "TimetableUpload", "Timetable")]:
    OPERATIONS.extend([
        dict(method="post", path="/api/v1/session/" + resource, operation_id="holdSession" + action,
             summary="CSVを解析してメモリへ一時保持", response="SessionWorkspaceResponse", request=request,
             headers="WorkspaceMutationHeaders", session="workspace_upload", errors=_workspace_errors(upload=True)),
        dict(method="delete", path="/api/v1/session/" + resource, operation_id="clearSession" + action,
             summary="一時保持した解析結果を削除", response="SessionWorkspaceResponse", request=None,
             headers="WorkspaceMutationHeaders", session="workspace_mutation", errors=_workspace_errors()),
    ])
OPERATIONS.extend([
    dict(method="post", path="/api/v1/session/recommendations", operation_id="recommendForSessionSlot",
         summary="保持した履修表を使って時限候補を検索", response="SlotRecommendationsResponse", request="WorkspaceSlotFields",
         headers="WorkspaceMutationHeaders", session="workspace_query", errors=_workspace_errors(recommendation=True)),
    dict(method="post", path="/api/v1/session/recommendation-searches", operation_id="searchSessionRecommendations",
         summary="保持した成績・履修表から不足単位を探索", response="RecommendationSearchResponse", request="WorkspaceSearchFields",
         headers="WorkspaceMutationHeaders", session="workspace_query", errors=_workspace_errors(recommendation=True)),
])


def json_schemas() -> dict:
    definitions = {}
    for name, model in RESPONSE_MODELS.items():
        schema = model.model_json_schema(mode="validation", ref_template="#/$defs/{model}")
        children = schema.pop("$defs", {})
        for key, value in {**children, name: schema}.items():
            if key in definitions and definitions[key] != value:
                raise ValueError("Schema definition collision: " + key)
            definitions[key] = value
    definitions.update(deepcopy(REQUEST_SCHEMAS))
    definitions.update(deepcopy(HEADER_SCHEMAS))
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:credit-dashboard:api-contract:" + CONTRACT_VERSION,
        "title": "単位取得状況APIの型定義",
        "description": "単体の応答は$defsの対応する型で検証する。全体を応答スキーマとして使わない。",
        "x-contract-version": CONTRACT_VERSION,
        "$defs": dict(sorted(definitions.items())),
    }


def response_schema(name: str, bundle: dict | None = None) -> dict:
    schemas = bundle if bundle is not None else json_schemas()
    if name not in RESPONSE_MODELS:
        raise ValueError("Unknown response schema: " + name)
    return {"$schema": schemas["$schema"], "$ref": "#/$defs/" + name, "$defs": schemas["$defs"]}


def _openapi_refs(value):
    if isinstance(value, dict):
        return {key: item.replace("#/$defs/", "#/components/schemas/")
                if key == "$ref" and isinstance(item, str) else _openapi_refs(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_openapi_refs(item) for item in value]
    return value


def openapi_document(bundle: dict | None = None) -> dict:
    schemas = bundle if bundle is not None else json_schemas()
    document = {
        "openapi": "3.1.0",
        "info": {"title": "単位取得状況 API", "version": CONTRACT_VERSION,
                 "description": "HTTP APIの静的契約。既存CSV APIはCookie不要。任意の短期匿名セッションは既定で作成から20分、操作で延長しない。CSV・学生データは永続保存しない。ログインなし。"},
        "servers": [{"url": "http://localhost:8000", "description": "開発時の既定値。配信先は別途設定可能。"}],
        "security": [],
        "paths": {},
        "components": {
            "schemas": _openapi_refs(schemas["$defs"]),
            "securitySchemes": {
                "SessionCookie": {"type": "apiKey", "in": "cookie", "name": "__Host-credit_session",
                                  "description": "HTTPS用のHttpOnly・Secure・SameSite=Strict Cookie。ブラウザーが管理する。本人確認を表す認証ではない。"},
                "LocalSessionCookie": {"type": "apiKey", "in": "cookie", "name": "credit_session",
                                       "description": "HTTPのlocalhost・ループバック開発専用。HTTPSではSessionCookieを使う。"},
            },
            "headers": {"NoStore": {"description": "公開情報・エラーを含め全応答でキャッシュしない。",
                                      "schema": {"type": "string", "const": "no-store"}}},
        },
        "x-response-schema-versions": {"ReportResponse": 2, "TimetableResponse": 1,
                                       "RecommendationCatalogsResponse": 1,
                                       "SlotRecommendationsResponse": 1, "RecommendationSearchResponse": 1,
                                       "SessionResponse": 1, "SessionEndedResponse": 1, "SessionWorkspaceResponse": 1},
    }

    def response(model, description):
        return {"description": description, "headers": {"Cache-Control": {"$ref": "#/components/headers/NoStore"}},
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/" + model}}}}

    for operation in OPERATIONS:
        responses = {}
        if operation["response"]:
            responses["200"] = response(operation["response"], "正常なJSON応答。配列が空でもJSONの型は変わらない。")
        for status, codes in sorted(operation["errors"].items()):
            responses[status] = response("ErrorResponse", "error.codeの既知値: " + ", ".join(codes))
            responses[status]["x-error-codes"] = codes
        responses["default"] = response("ErrorResponse", "機械可読コードと日本語メッセージ。未知のコードには共通処理を用意する。")
        entry = {"operationId": operation["operation_id"], "summary": operation["summary"],
                 "responses": responses}
        if operation.get("deprecated"):
            entry["deprecated"] = True
        if operation.get("session"):
            schema = HEADER_SCHEMAS[operation["headers"]]
            entry["parameters"] = [
                {"in": "header", "name": key, "required": True, "schema": value}
                for key, value in schema["properties"].items()]
            entry["description"] = (
                "fetchのcredentialsはinclude。Cookieはブラウザーに任せる。"
                "許可Origin・同一サイトから利用する。固定期限は操作で延長せず、期限切れは401。"
                "解析結果はメモリだけに保持し、CSV原本・ファイル名を保存しない。"
                "更新では旧結果を先に破棄する。失敗した更新や競合はworkspaceを再取得して確認する。")
            if operation["session"] != "bootstrap":
                entry["security"] = [{"SessionCookie": []}, {"LocalSessionCookie": []}]
            if operation["session"] in {"bootstrap", "end"}:
                responses["200"]["headers"]["Set-Cookie"] = {
                    "description": "新規作成時に設定、終了時に削除する。有効セッションの再取得時は設定しない。",
                    "schema": {"type": "string"},
                }
        if operation["request"]:
            entry["requestBody"] = {
                "required": True,
                "description": "FormDataを使用する。Content-Typeのboundaryはブラウザーへ任せる。",
                "content": {"multipart/form-data": {"schema": {
                    "$ref": "#/components/schemas/" + operation["request"]}}},
            }
        document["paths"].setdefault(operation["path"], {})[operation["method"]] = entry
    return document
