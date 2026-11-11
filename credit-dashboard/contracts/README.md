# API契約：フロントエンド担当向け

更新日：2026-11-11。契約リビジョン`1.3.0`。成績科目に`score: number | null`を追加した。通常APIとセッションの保持・復元の双方で返し、既存の合否・単位集計・学務判定には使わない。任意利用の短時間セッションと解析結果復元のAPIを含み、SQLite・共有評価のAPIは含まない。

画面を新規制作する担当者は、[フロントエンド実装ガイド](../docs/frontend-guide.md)から接続・表示・状態管理・架空データでの受入確認を確認する。点数の取得場所とTypeScriptの表示例は[点数追加への対応](../docs/frontend-guide.md#3-点数追加への対応)を参照する。

## まず使うファイル

| ファイル | 用途 |
| --- | --- |
| [openapi.json](openapi.json) | OpenAPI 3.1。メソッド・URL・入力・成功応答・エラー・サイズ制限 |
| [api.d.ts](api.d.ts) | 同じ定義から生成したTypeScript型。アプリの実行コードを含まない |
| [schemas.json](schemas.json) | JSON Schema Draft 2020-12。バックエンドの契約テスト用の厳密な型定義 |
| [examples/index.json](examples/index.json) | 72件の架空HTTP応答例の索引。メソッド・URL・HTTPステータス・応答型を記録 |

この契約はGitで配布する静的ファイルである。アプリの`/docs`・`/redoc`・`/openapi.json`は引き続き無効で、仕様取得用の新しいHTTP APIは追加していない。JSONをAPI設計ツールへ読み込む場合も、個人データを使う必要はない。

文章による仕様は[データ契約](../docs/data-contract.md)、[履修表](../docs/timetable-csv.md)、[時限指定の候補](../docs/recommendation-api.md)、[不足探索](../docs/recommendation-search-api.md)、[短時間セッション](../docs/session-api.md)を参照する。

## 既存フロントの変更は必須ではない

APIの返却処理に型変換やフィールド除去を挿入していない。既存フロントはそのまま接続でき、新しいフロントは必要に応じて型や架空応答を利用できる。画面構成やフレームワークを指定する契約ではない。

TypeScriptでの利用例（import先はフロントの配置に合わせる）：

```typescript
import type {
  ReportResponse,
  TimetableResponse,
  SlotRecommendationsResponse,
  RecommendationSearchResponse,
  ErrorResponse,
  ApiOperations,
} from "../contracts/api";

type ReportInput = ApiOperations["POST /api/v1/reports"]["request"];
type ReportOutput = ApiOperations["POST /api/v1/reports"]["response"];
```

型宣言はコンパイル時の補助で、`response.json()`の実行時検証を自動では行わない。CSVや表示値は引き続き安全なテキストとして扱う。

## 入力と通信

- CSVは`FormData`へ追加し、`Content-Type`を手動設定しない。ファイルの上限は各5 MiB。
- 従来の不足探索APIは`grades_file`と`timetable_file`の両方が必須。合計は10 MiB＋multipart用64 KiB。セッション版の探索は解析済み結果を使い、CSVを送らない。
- それ以外のアップロードは合計5 MiB＋64 KiB。文字列フィールドは各256バイトまで。
- 型の入力数値は送信前の値を表す。FormDataには文字列化して追加する。`residence_years`は省略・空欄を許し、0〜100の有限数を受け付ける。
- `profile_id`は規則一覧の値を使う。省略・空欄では既定値。学年を候補検索の入力へ追加しない。
- 従来の時限候補APIの`file`は任意。成績集計・履修表解析の`file`、従来の不足探索の2ファイルは必須。セッション版の入力は後述する。
- 既知のフィールドの重複は拒否する。未知の入力フィールドは現在の実装では無視する。
- 既存CSV APIはログイン・Cookie・セッションなしで元CSVを検証する。新しい短時間セッションAPIは任意で利用できる。
- 別ポートで配信する場合は既存のCORS設定、または`/api`へのプロキシを利用する。
- 成功・エラーとも`Cache-Control: no-store`。学生データをブラウザーの永続ストレージへ保存しない。

```typescript
const body = new FormData();
body.append("file", file);
body.append("profile_id", profileId);

const response = await fetch(`${apiBase}/api/v1/reports`, {
  method: "POST",
  body,
  credentials: "omit",
  cache: "no-store",
});
// HTTPステータス、応答形式、必要な項目を確認してから画面へ反映する。
```

## バージョン・省略・null

| 応答 | 本文のschema_version |
| --- | --- |
| 成績レポート | `2` |
| 履修表・候補カタログ一覧・時限候補・不足探索・セッション・workspace | `1` |
| 稼働確認・規則一覧・エラー | 項目なし |

契約リビジョン`1.3.0`と、上記本文の`schema_version`は別物である。追加項目`score`により成績本文の`schema_version: 2`は変更していない。

- `credits: number | null`は必須項目で、`null`は単位数未確認。0へ変換しない。
- `courses[].score: number | null`も必須項目。CSVの`得点`を返し、列なし・空欄は`null`、0点は`0`。非数値・負数・非有限値の入力は422・`invalid_value`。点数から合否を推定しない。
- `student`の氏名・番号・所属・学年も、値が得られなければ明示的に`null`となる。
- `summary`の単位合計は数値で、確認できた単位だけを合計する。不明な科目の単位が0だったという意味ではない。
- `error.details`とその中の項目は省略され得る。現在のエラーは`null`を返す形式ではない。
- 条件の種類によって数値項目が異なる。在学期間は`minimum_years`、単位条件は`minimum_credits`、個別必修は`course_results`などを持つ。`EvaluationCondition`のUnion型として記述する。
- 科目の`status`・`result`は同じ正規化状態。CSVの「合」「否」は`source_result`に入る。その他の互換エイリアスも残す。
- `error.code`、説明用の`reason_code`・`messages[].code`は文字列。未知のコードでは共通表示へフォールバックする。公開状態のenumと混同しない。

## 判定と表示の注意

1. 学務判定は`satisfied / not_satisfied / unknown`の三値。`unknown`を不合格にしない。
2. 時限候補は`ok / empty / occupied / unknown`、不足探索は`ok / empty / unknown`。異なる応答の`status`を一つの型へまとめない。
3. レポートの警告は文字列配列、履修表の警告は`code / row_number / message`を持つ配列。
4. 履修表の`ready_for_recommendation`は解析上の未解決がないことを示す。年度・タームの確認には`context`・`display_contexts`も使い、空欄から空き時間を推測しない。
5. 教養充足時は、不足探索の`status: empty`と`checks.timetable: needs_review`が両立する。教養充足の説明は`liberal_requirements_satisfied`で区別する。
6. `confirmed_credit_shortfall`は`status: unknown`なら確定した不足とは限らない。候補の効果や、分類別条件・総計を合算しない。
7. 修得済みの単位や最終判定はAPIの値を使う。フロントで配賦・学務判定を再計算しない。

## 架空例の選び方

- `report-year1.json`：架空の34単位、第2年次進級と卒業。
- `report-year2.json`・`report-year3.json`：修得・未修得・未確定・小数単位・分類不明を含む。
- `report-graduation.json`：架空の124単位、個別必修16科目を含む。
- `report-unknown.json`・`report-blocked.json`：学年不明や、架空の規則確認待ち。
- `timetable-*.json`：空の時間割、ターム0、開講番号不明、時間割外の通常科目、土日・7限など。
- `slot-*.json`：CSVなしの候補・空・占有・要確認。
- `search-*.json`：確定候補・要確認候補・教養充足・時間未確認・空結果。
- `session-*.json`：作成・取得・再取得・終了。トークンは固定の架空値。
- `workspace-*.json`：空・成績保持・両結果保持・復元・CSVなしの探索・個別クリア・競合・未入力・期限切れ。全入力は架空値。
- `error-*.json`：400・401・403・404・405・410・413・415・422・500・503。

## 任意利用の短時間セッション

`POST/GET/DELETE /api/v1/session`は本文なし、`credentials: "include"`と`X-Session-Request: 1`を使う。DELETEだけ、取得したCSRFトークンを`X-CSRF-Token`へ追加する。TypeScriptでは`ApiOperations["DELETE /api/v1/session"]["headers"]`等でヘッダーを型付けできる。Cookie値をJavaScriptで組み立てたり、CSRFトークンを永続保存したりしない。

作成から既定20分で失効し、操作・GET・POSTによる再取得では延長しない。期限切れは401。解析結果はサーバーのメモリだけに保持し、`GET /api/v1/session/workspace`で取得する。`SessionWorkspaceResponse`は`schema_version / revision / session / report / timetable`を持ち、未解析・クリア済みの結果は`null`になる。

`POST /api/v1/session/reports`・`timetables`は従来と同じCSVのFormDataを受け取り、workspaceを返す。`DELETE`で同種の結果をクリアする。`POST /api/v1/session/recommendations`・`recommendation-searches`は条件だけのFormDataを受け取り、既存と同じ推薦応答を返す。これらのPOST・個別DELETEには`X-Session-Request: 1`に加え、取得した`X-CSRF-Token`と`X-Session-Revision`を指定する。検索にも同じ更新番号を使い、結果を取得中に入力が変わっていないことを確認する。検索本文は64 KiBまででファイルを受け付けない。アップロードのCSVサイズは従来と同じ。

復元後のFile入力は空とし、再解析するときだけ再選択する。409の競合ではworkspaceを再取得してから明示的に再試行する。失敗した差し替えでも旧結果が消えるため、失敗後にも最新の番号を取得する。既存APIは引き続きCookieなしで利用でき、Cookieを付けただけでは結果を保持しない。Cookie属性・別Origin・運用設定・接続手順は[セッションAPI第8節](../docs/session-api.md#8-解析結果の保持復元session-002)を参照する。

例は固定の架空入力をローカルASGIアプリへ送り、実際の応答から生成した。実在する学生データ・提供された私的CSV・外部APIは使わない。生成スクリプトに利用者のCSVを指定するオプションはない。

## 検証・再生成と互換性

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/build_api_contract.py --check
.venv/bin/python -m pytest -q tests/test_api_contract.py
```

仕様変更時はソースの`api_contracts/models.py`・`specification.py`を更新し、次で再生成する。生成ファイルを直接編集しない。

```bash
.venv/bin/python scripts/build_api_contract.py
```

`schemas.json`は提供側のCI用に、未宣言の返却項目を禁止する。これにより項目の書き間違いや、CSV本文・教員情報等の意図しない追加を検出する。フロントでは未知の追加項目を無視できる表示を基本とする。この厳密なスキーマをフロントの実行時検証にも使う場合は、契約更新時に同時更新する。

`schemas.json`は型の定義集であり、ファイルのルート自体を応答へ適用しない。応答に対応する`#/$defs/ReportResponse`などを選んで検証する。Python側では`api_contracts.specification.response_schema("ReportResponse")`で、ローカル参照を含む検証用スキーマを取得できる。

既存のURL、必須項目、型、nullable、省略条件、状態、単位の意味を変更する場合は事前に調整し、必要に応じて新しいAPI・本文バージョンを用意する。追加項目やコードも契約・文書・テストを同時に更新する。日本語の説明文だけを固定値として条件分岐しない。

Pydanticは既存のFastAPI依存を利用し、開発環境ではスキーマ再現性のため版を固定する。JSON Schemaの検証ライブラリだけを開発依存へ追加した。実行中のAPIに`response_model`のフィルターや新たな変換処理を挿入していない。

形式の根拠：[OpenAPI 3.1](https://spec.openapis.org/oas/v3.1.0)、[PydanticのJSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/)。
