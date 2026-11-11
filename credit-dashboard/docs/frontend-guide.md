# フロントエンド実装ガイド

更新日：2026-11-11。API契約リビジョン`1.3.0`のバックエンドに接続する担当者向け。`courses[].score`の追加、短期セッションによる解析結果の復元、教養候補の検索・不足探索を含む。画面構成・フレームワークは担当者が選べる。

## 1. 実装を始めるときに読むもの

1. この文書で接続方法・画面の責務・点数表示を確認する。
2. [API契約README](../contracts/README.md)と[TypeScript型](../contracts/api.d.ts)で入出力を確認する。[OpenAPI](../contracts/openapi.json)・[JSON Schema](../contracts/schemas.json)も同じ契約から生成される。
3. [架空応答の索引](../contracts/examples/index.json)から必要な画面状態を選ぶ。全文のJSONが必要な場合は、この配布例を使う。
4. 開発環境を[引き継ぎ手順の起動方法](handoff.md#3-クローンと起動)で起動し、確認済みの架空CSVで接続する。

現在の参考UIは`/`と`/prototype/`。APIを利用すれば、Pythonの内部実装や既存画面の状態管理に依存せず新しい画面を作れる。[試作UIの記録](prototype-handoff-test.md)は作成当時の経緯であり、最新の接続契約はこの文書と上記の生成済み契約を使う。

契約リビジョン`1.3.0`と成績本文の`schema_version: 2`は別の版である。点数は追加フィールドなので本文は`2`のまま。型・Schema・モックは同じ契約版を使う。`api.d.ts`のimportや型アサーションだけでは、受信JSONの実行時検証にはならない。

## 2. バックエンドと画面の分担

| 表示・操作 | APIから使う情報 | 画面の処理 |
| --- | --- | --- |
| 対象の選択 | 規則一覧の`profiles`・`default_profile_id` | `profile_id`を一度選び、単位集計と教養候補で共有する |
| 学生情報・単位の状況 | レポートの`student`・`summary` | APIの集計値を表示する。氏名・学籍番号はマスクなしで表示可 |
| 科目一覧 | レポートの`courses` | 検索、並べ替え、ページ切替、点数と修得状況の表示 |
| 進級・卒業 | レポートの`evaluations`・`evaluation_context` | APIが返す要件と三値判定を表示する |
| 時間割 | 履修表の`display_contexts`・`courses`・`busy_slots`・警告等 | 表示可能な期間・曜限を描画する。未掲載の枠を空きと断定しない |
| マスの教養候補 | 時限候補の`status`・`candidates`・`checks`・`messages` | 対象枠の候補と未確認事項を表示する |
| 教養不足への候補 | 不足探索の`candidates`・`review_candidates`・効果・`messages` | 確認済みと要確認を分け、候補ごとの効果を表示する |

CSVの解析・分類、単位配賦、合否・学務判定、時間重複、修得済みの除外、推薦効果はバックエンドが行う。`summary`を画面で再集計したり、点数から`status`を作ったりしない。必修条件内の`course_results`は修得確認の説明用であり、成績一覧の`courses`とは異なる型である。

学務判定の`satisfied`は「条件を満たす」、`not_satisfied`は「条件を満たさない」、`unknown`は「判定不能・要確認」とする。条件名・必要単位・表示対象の要件を学年別に画面へ固定せず、APIが返す配列を使う。`policy_notes`・警告・`sources`・`caveats`も確認できるようにする。

入学年度は`curriculum.admission_year`、学生の学年は`student.grade`、候補検索の開講年度は`academic_year`。これらを混同しない。候補検索には学年を送らず、開講年度・ターム・曜日・時限を使う。

## 3. 点数追加への対応

### 受信場所と型

| API | 点数の位置 |
| --- | --- |
| `POST /api/v1/reports` | `courses[i].score` |
| `POST /api/v1/session/reports` | `report.courses[i].score` |
| `GET /api/v1/session/workspace` | `report`がある場合の`report.courses[i].score` |

各成績科目の`score`は必須の`number | null`。CSVの`得点`を返し、整数・小数・0を保持する。列がないCSVと空欄は`null`。科目行には不合格・未確定の点数も含み得る。`student.grade`は学年であり、点数のフィールドではない。履修表・教養候補・個別必修の説明用結果へ`score`を追加したわけではない。

以下は[report-year2.json](../contracts/examples/report-year2.json)の最初・2番目・最後の科目から、説明に必要な項目だけを抜粋した架空例。これは完全なレポート応答ではない。

```json
[
  {"no": 1, "name": "架空の修得科目", "credits": 1.5, "score": 85.5, "status": "passed"},
  {"no": 2, "name": "架空の未修得科目", "credits": 2, "score": 0, "status": "failed"},
  {"no": 6, "name": "架空の結果不明", "credits": 2, "score": null, "status": "unconfirmed"}
]
```

### 表示例

| 値 | 表示例 | 意味 |
| --- | --- | --- |
| `85.5` | `85.5点` | CSVに記録された点数 |
| `0` | `0点` | 点数が0。空欄と区別する |
| `null` | `未記載`または`—` | 点数の記載を確認できない。合否は別に表示する |

科目一覧へ「得点」列を追加するときのTypeScript例。import先は新しいフロントの配置に合わせる。

```typescript
import type { TranscriptCourse } from "../contracts/api";

export function scoreText(score: TranscriptCourse["score"]): string {
  return score === null ? "未記載" : `${score}点`;
}

const resultText: Record<TranscriptCourse["status"], string> = {
  passed: "修得済み",
  failed: "不合格",
  unconfirmed: "未確定",
};

export function courseCells(course: TranscriptCourse): string[] {
  return [
    course.name,
    course.course_code ?? "—",
    course.credits === null ? "未確認" : `${course.credits}単位`,
    scoreText(course.score),
    resultText[course.status],
  ];
}
```

各文字列は`textContent`やフレームワークの通常のテキスト描画へ渡す。`score || "—"`は0点も消してしまうため使わない。`Number(null)`による0への変換や、小数の切捨て・100点への丸め込みも行わない。`score: null`から未修得を推定せず、`status`を使う。GP・評語・GPAの新しい返却や計算は今回の追加に含まれない。

契約どおりの応答では、`score`の欠落・文字列・負数・非有限値は正常な点数ではない。実行時検証で検出したら応答不整合として案内し、0へ補完しない。`schema_version: 2`でも`score`が欠落する場合は、古いバックエンドや保持結果の可能性があるため、バックエンドの更新とCSVの再解析を確認する。

点数は既存画面のJSON表示には含まれるが、参考UIの科目一覧表にはまだ専用列がない。点数を一覧に表示する場合は、新しい画面側で列を追加する。フロントから点数を個別更新するAPIはない。

### 不正な入力

CSVの`得点`が非数値・負数・NaN・Infinity等の場合はHTTP 422・`invalid_value`となる。行番号と項目名を含む日本語メッセージを表示できるが、点数を補正して再送する処理は作らない。架空の非数値を2行目に置いた場合の応答例：

```json
{"error":{"code":"invalid_value","message":"2行目: 得点が数値ではありません"}}
```

## 4. APIの接続方法

再読み込みで解析結果を復元する画面ではセッション版を使う。起動時に`GET /api/v1/session/workspace`を試し、401なら未解析表示にする。利用者がCSVを送るときにセッションを開始する。

| 操作 | セッション版 | CSV APIだけを使う場合 |
| --- | --- | --- |
| 規則・対象一覧 | `GET /api/v1/rule-profiles` | 同じ |
| カタログ年度一覧 | `GET /api/v1/recommendation-catalogs` | 同じ |
| 成績解析 | `POST /api/v1/session/reports` | `POST /api/v1/reports` |
| 履修表解析 | `POST /api/v1/session/timetables` | `POST /api/v1/timetables` |
| マスの候補 | `POST /api/v1/session/recommendations` | `POST /api/v1/recommendations` |
| 教養不足の探索 | `POST /api/v1/session/recommendation-searches` | `POST /api/v1/recommendation-searches` |
| 復元 | `GET /api/v1/session/workspace` | なし。元CSVを再選択・送信する |

CSVは`FormData`で送り、`Content-Type`はブラウザーへ任せる。成績解析は`file`・`profile_id`・任意の`residence_years`、履修表解析は`file`。各CSVの上限は5 MiB。CSV APIだけで不足探索する場合は`grades_file`・`timetable_file`の両方が必要で、合計10 MiB＋multipart用64 KiBまで。解析済みJSONをアップロード入力として送らない。

セッション版は`credentials: "include"`と`X-Session-Request: 1`を使う。CSV送信・個別クリア・候補検索には、直前のworkspaceから取得した`X-CSRF-Token`・`X-Session-Revision`も付ける。作成は`POST /api/v1/session`、全削除は`DELETE /api/v1/session`（CSRF必須）、個別クリアは`DELETE /api/v1/session/reports`または`/timetables`。CSRF・更新番号・workspaceはメモリだけで管理する。Cookie値はJavaScriptで組み立てない。

既存CSV APIは`credentials: "omit"`で使える。別ポートで開発するときは`/api`のプロキシ、またはバックエンドの`CORS_ALLOWED_ORIGINS`に実際のOriginを設定する。セッションは同一サイトで使い、`localhost`と`127.0.0.1`を混ぜない。詳細は[セッション接続契約](session-api.md#8-解析結果の保持復元session-002)を参照する。

### 既存の通信クライアントを再利用する場合

[static/session-client.js](../static/session-client.js)はDOMに依存せず、Cookie・CSRF・更新番号・通信の直列化・失効を扱う。新しいフロントにこのファイルを含め、先に読み込むと`window.createSessionClient(apiBase)`を使える。型宣言の`api.d.ts`には、このJavaScriptクライアントの実装やWindow拡張の型は含まれない。

以下は通信部分のJavaScript例。描画関数、入力の無効化、後述の世代番号による確認は新しい画面側で実装する。`saveReport`は内部で必要なセッションを開始する。

```javascript
// static/session-client.jsを読み込んだ後。APIを同じOriginへプロキシする例。
const session = window.createSessionClient("");

// 起動時：未開始ならnull、保持中ならworkspace。
const restored = await session.restore();
renderReport(restored?.report ?? null);

// CSVを送信するとき。古い応答の描画を防ぐ確認は呼出し側で行う。
const saved = await session.saveReport(
  {profile_id: selectedProfileId, residence_years: residenceYearsInput},
  gradesFile,
  abortController.signal,
);
renderReport(saved.report); // 点数はsaved.report.courses[i].score
```

| クライアント操作 | 戻り値・扱い |
| --- | --- |
| `restore()` / `data()` | workspaceまたは`null`。前者は初期取得、後者は現在のメモリ上の状態 |
| `saveReport(fields, file, signal)` / `saveTimetable(file, signal)` | 更新後のworkspace。描画と更新番号はこの応答を使う |
| `clear("reports")` / `clear("timetables")` | 更新後のworkspace、未開始・失効時は`null` |
| `end()` | セッション全削除。画面側の参照も消す |
| `slot(fields, signal)` / `search(fields, signal)` | 候補結果。不足探索には成績・履修表の解析済み結果が必要 |
| `onReset(listener)` / `check()` / `suspend()` | 失効等の通知・期限確認・ページ離脱時の無効化。詳細は[セッション契約](session-api.md#表示側での保護) |

`onReset`で画面の成績・点数・履修表・File・候補を破棄し、フォーカスや再表示時に`check()`で期限を確認する。`pagehide`では`suspend()`し、履歴から戻った場合は再読み込みしてサーバーへ確認する。クライアントを使わず独自実装する場合も、同じ失効・競合・削除の扱いが必要。

## 5. 入力変更・競合・失効時の画面

| 発生したこと | 画面の対応 |
| --- | --- |
| 新しいCSVの選択 | 同種の旧結果と関連候補を先に消す。読み込み失敗でも旧結果を再表示しない |
| プロファイル変更 | 旧成績・候補と遅延応答を無効化し、対象を合わせて再解析する。保持する旧成績はDELETEでクリアする |
| 在学期間変更 | 旧判定を無効化し、元CSVで再解析する。復元後にFileがなければ再選択を案内する |
| ターム・年度・曜限変更 | 条件が変わった候補結果と遅延応答を無効化する。成績の点数を消す理由にはしない |
| 再読み込み | workspaceから成績・点数・履修表を復元する。File入力は空にする |
| HTTP 401 | セッション失効として表示・参照・送信中処理を破棄し、再アップロードを案内する |
| HTTP 409 `session_revision_conflict` | 旧入力と最新入力を混ぜず、旧表示・応答を無効化する。再読み込み等でworkspaceを取得し、利用者の再操作で続ける |
| CSV送信が422・413等で失敗 | 旧結果はサーバーでも破棄され得る。GET workspaceで最新番号と残った結果を確認し、旧点数を復活させない |
| 個別クリア・全削除 | サーバーへDELETEを送り、対応する画面・File・候補を消す。通信失敗時は削除完了と表示しない |

画面側も`AbortController`と世代番号を使い、応答が現在の入力に対するものか確認してから描画する。リクエストを中断するだけでは、すでに完了した古い応答の表示を防げない。セッション更新は順番に送信し、更新番号の増分を推測しない。失敗時にも番号が進む場合がある。

保持期限はセッション作成から既定20分で、操作やGETで延長しない。再起動でも消える。表示の失効タイマーは応答の`expires_in_seconds`に従い、再取得によって延ばさない。タブ間で同じCookieを共有するため、競合を正常な状態遷移として扱う。

APIの日本語エラーは`error.message`、処理分岐は`error.code`を使う。未知のコードは一般的なエラー表示へフォールバックする。ネットワーク障害やJSONの読取り失敗も別途扱い、CSV本文・受信レポート・点数をコンソールやエラー収集サービスへ送らない。

## 6. 教養候補と不足探索を接続する際の注意

対象プログラムは単位集計側で一度選ぶ。候補画面に別のプログラム選択欄を置かず、同じ`profile_id`を送る。解析済み履修表の選択年度、未解析なら同一プロファイルの最新カタログ年度を明示して使う。対象・年度が未対応なら案内し、別対象へ置き換えない。

マスの候補は`academic_year`・`term`・`weekday`・`period`、不足探索は`academic_year`・`term`を送る。前者は修得済み・不足単位を照合しない。後者は卒業の教養条件だけを改善する候補を返し、教養充足時は専門・総計だけが不足していても推薦しない。点数は候補の順位や必要度に使わない。

`review_candidates`は要確認の一覧とする。`unknown`を候補なし・履修不可へ置き換えない。効果は1科目ずつ仮追加した結果なので、複数候補の改善単位を合算して履修計画の充足を断定しない。候補相互の時間重複、履修許可、先修条件も確定していない。詳細は[時限候補](recommendation-api.md)・[不足探索](recommendation-search-api.md)。

## 7. 架空データでの受入確認

モックとブラウザー確認には、次の配布例・確認済みCSVを使う。実在する学生データをfixture・スクリーンショット・トレースへ転記しない。

| 確認対象 | 入力・応答例 | 期待する表示・動作 |
| --- | --- | --- |
| 点数の小数・0・null | [report-year2.json](../contracts/examples/report-year2.json) | `85.5点`・`0点`・`未記載`等を区別する。0点を空欄にしない |
| 点数と合否の分離 | 同例の3番目の科目 | `score: 90`でも単位数未確定のため`status: unconfirmed`。修得済みにしない |
| 点数列なしのCSV | [graduation-sample.csv](../examples/graduation-sample.csv) | 各科目の`score: null`を表示し、124単位・卒業`satisfied`を維持する |
| 元の19列形式 | [graduation-sample-original-format.csv](../examples/graduation-sample-original-format.csv) | 得点を表示し、124単位・卒業`satisfied`を維持する |
| 学年別・未知の判定 | [report-year1.json](../contracts/examples/report-year1.json)・[report-unknown.json](../contracts/examples/report-unknown.json) | APIが返す要件を表示し、`unknown`を不合格にしない |
| 保持・復元・空状態 | [workspace-report.json](../contracts/examples/workspace-report.json)・[workspace-restored.json](../contracts/examples/workspace-restored.json)・[workspace-empty.json](../contracts/examples/workspace-empty.json) | 成績の取得位置とworkspaceの包みを区別する。空の`report`を描画しない |
| 教養充足・時間未確認 | [search-fulfilled-unknown-time.json](../contracts/examples/search-fulfilled-unknown-time.json) | 推薦不要と、時間情報の要確認を両方表示する |

実際のlocalhost APIでも、新規解析→再読み込みで点数が戻り、File入力は空になることを確認する。架空データで、点数の空欄・列なし・非数値・負数・非有限値、差し替え失敗、クリア、期限切れ、別タブ競合、遅延応答を試す。クリア・期限切れ後は再読み込みでも旧点数を復元しない。

点数ソートを付ける場合、数値順で並べ、小数・0を保持する。`null`の配置を決めて表示し、0と同じ値に変換しない。科目行のキーは一つのレポート内の`no`等を使い、科目名や`catalog_course_id`で再履修行を統合しない。行数を固定せず、ページ切替・絞り込み後も同じ科目の点数と対応させる。

開発中も成績・点数・File・セッション情報はメモリだけに置き、localStorage・sessionStorage・IndexedDB・Cache Storage・URL・履歴state・アクセス解析へ保存しない。Service Workerやフロントのキャッシュ層にも`/api`の成績・workspaceを保存させない。型・公開規則・確認済み架空例は共有できる。

バックエンド契約の整合確認は次で行う。新しい画面では上の表示・状態遷移に対応する自動テストを追加する。

```bash
.venv/bin/python scripts/build_api_contract.py --check
.venv/bin/python -m pytest -q tests/test_parser.py tests/test_api_contract.py tests/test_session_workspace.py
```

API変更が必要になった場合は、先に[データ契約](data-contract.md)・型・架空例・テストを揃える。生成済みの`api.d.ts`やJSONを手で改変して独自フィールドを足さない。
