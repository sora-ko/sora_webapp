# 短時間セッションAPI

更新日：2026-11-11。SESSION-001・SESSION-002の実装とフロントエンド担当向けの契約。OpenAPI・型・応答例は[API契約ガイド](../contracts/README.md)を参照する。

## 1. 現在できること

ログインなしでセッションを作成・取得・終了する。利用者指定により、既定の有効期限は**作成から20分**で、操作・GET・有効セッションに対するPOSTでは延長しない。無効・期限切れのセッションをGETしても新規作成しない。

成績・履修表の解析結果をセッションへ結び付け、リロード後に復元できる。通常画面と試作画面を接続済み。保持する学生データは解析済みJSONだけで、CSV原本・ファイル名は保持せず、ファイル・DB・ブラウザーの永続ストレージへも保存しない。既存CSV APIはCookieなしで利用できるまま維持した。復元を使う入口は第8節の追加APIであり、既存APIへCookieを付けるだけでは保持しない。

## 2. エンドポイント

全リクエストで`X-Session-Request: 1`、ブラウザーのfetchで`credentials: "include"`を指定する。リクエスト本文は送らない。ブラウザーがCookieを管理し、JavaScriptからCookieを読み書きしない。

| メソッド・URL | 動作 | 正常応答 |
| --- | --- | --- |
| `POST /api/v1/session` | 新規作成。有効なCookieがあれば同じセッションを返す | `SessionResponse`、200 |
| `GET /api/v1/session` | 有効なセッションの情報を取得。期限は延長しない | `SessionResponse`、200 |
| `DELETE /api/v1/session` | メモリ上の情報とCookieを削除する | `SessionEndedResponse`、200 |

DELETEでは、作成・取得時の`csrf_token`を`X-CSRF-Token`ヘッダーに指定する。CSRFトークンはJavaScriptのメモリだけで保持し、URL・ログ・永続ストレージへ入れない。GETではCSRFトークンは不要だが、`X-Session-Request`は必要。

`SessionResponse`の例は固定の架空値である。

```json
{
  "schema_version": 1,
  "status": "active",
  "csrf_token": "fictional_contract_token_0002______________",
  "ttl_seconds": 1200,
  "expires_in_seconds": 1200
}
```

`expires_in_seconds`はサーバーが返答を作った時点の残り秒数を切り上げた整数。有効期限の判断はサーバーが行う。通信遅延や端末の時計だけで有効と判断しない。同じセッションを再取得すると残り時間が減り、CSRFトークンは変わらない。

終了時は`{"schema_version":1,"status":"ended"}`を返す。既に無効なセッションのGET・DELETEは401になる。401では表示中のセッション情報を破棄し、必要なら明示的にPOSTで新しく開始する。新規作成したセッションは以前のセッションと別物である。

## 3. フレームワークに依存しない呼出し例

```javascript
let csrfToken = null;

async function sessionRequest(method) {
  const headers = { "X-Session-Request": "1" };
  if (method === "DELETE" && csrfToken) {
    headers["X-CSRF-Token"] = csrfToken;
  }
  const response = await fetch("/api/v1/session", {
    method,
    credentials: "include",
    cache: "no-store",
    headers
  });
  const payload = await response.json();
  if (response.status === 401) csrfToken = null;
  if (!response.ok) {
    throw new Error(payload.error?.message ?? "セッションを操作できません。");
  }
  csrfToken = payload.status === "active" ? payload.csrf_token : null;
  return payload;
}

// 開始: await sessionRequest("POST");
// リロード後の存在確認: await sessionRequest("GET");
// 終了: await sessionRequest("DELETE");
```

リロード直後はまずGETで存在を確認できる。ブラウザー内のCSRF変数が初期化されていても、有効なCookieがあればGETの応答から取り直せる。定期ポーリングで有効期限を延ばす必要はなく、実際に延長もされない。

## 4. Cookie・接続元・CSRFの保護

| 接続 | Cookie名 | 属性 |
| --- | --- | --- |
| HTTPS | `__Host-credit_session` | `Secure; HttpOnly; SameSite=Strict; Path=/`、Domain指定なし |
| HTTPのlocalhost・ループバック | `credit_session` | `HttpOnly; SameSite=Strict; Path=/`、Domain指定なし |

Cookieは暗号学的乱数256bitの不透明な識別子だけを持つ。サーバーは識別子のSHA-256をメモリのキーにし、Cookie原文を保存しない。氏名・学籍番号・成績をCookieへ入れず、ログイン・本人確認・完全な匿名性を保証する仕組みとしても扱わない。

Cookieに`Expires`・`Max-Age`を付けず、固定期限をサーバー側で管理する。ブラウザーがCookieを復元した場合もサーバーの期限を超えて利用できない。終了時にはサーバー側の情報も無効化する。

作成・取得・終了は本文を受け付けず、カスタムヘッダーとOrigin照合で単純なフォーム・画像等からの操作を拒否する。`Sec-Fetch-Site: cross-site`も拒否する。状態変更と保持結果の検索にはセッションごとの独立したCSRFトークンを追加で要求する。第8節のアップロード・検索だけは制限付きmultipart本文を受け付ける。ワイルドカードOriginは許可しない。

HTTPはlocalhost・ループバックに限定し、それ以外はHTTPSを要求する。リバースプロキシでは信頼するプロキシを明示し、ASGIサーバーが実際のHTTPS接続を認識できるようにする。アプリは任意の`X-Forwarded-Proto`ヘッダーだけでHTTPをHTTPSとみなさない。

## 5. 別フロントエンドからの利用

同一Originでの`/api`プロキシを推奨する。別ポートで直接呼ぶ場合は、`CORS_ALLOWED_ORIGINS`へ実際のOriginを設定する。セッションAPIだけ、許可Originからの資格情報付きCORSと`GET/POST/DELETE`、`X-Session-Request/X-CSRF-Token/X-Session-Revision`を許可する。従来APIのCORS設定は資格情報なしのまま維持する。

`SameSite=Strict`を使うため、別サイトを跨ぐCookie連携は対象外。同じホスト名・スキームを使い、localhostと127.0.0.1を途中で切り替えない。別ドメインで画面を開発する場合はAPIをプロキシする。

## 6. エラー

既存の`error.code`・日本語`error.message`形式を使い、Cookie・CSRF・入力本文をエラーへ転記しない。全応答に`Cache-Control: no-store`を付ける。

| HTTP | code | 意味 |
| --- | --- | --- |
| 401 | `session_required` | Cookieなし・識別子が無効・固定期限切れ |
| 403 | `session_https_required` | localhost等以外でHTTPを使用 |
| 403 | `session_request_header_required` | `X-Session-Request: 1`なし・重複・値違い |
| 403 | `session_origin_forbidden` | 未許可・不正・重複Origin、またはcross-site |
| 403 | `invalid_csrf_token` | 状態変更・保持結果検索のCSRF確認失敗 |
| 422 | `invalid_request` | リクエスト本文が送信された |
| 503 | `session_capacity_exceeded` | 有効セッション数の上限。既存の利用者は追い出さない |
| 503 | `session_unavailable` | セッション作成不可 |

## 7. 運用設定

| 環境変数 | 既定 | 内容 |
| --- | --- | --- |
| `SESSION_TTL_SECONDS` | `1200` | 作成からの固定有効秒数。操作では延長しない |
| `SESSION_MAX_COUNT` | `1000` | 単一プロセスの有効セッション数上限 |
| `SESSION_MAX_BYTES` | `8388608` | 1セッションの解析済みJSONの合計上限（8 MiB） |
| `SESSION_TOTAL_BYTES` | `67108864` | 全セッションの保持JSONの合計上限（64 MiB） |

いずれも正の整数。不正な設定では起動を失敗させる。期限到来時点から参照を拒否し、定期掃除は通常30秒ごとに行うため、未参照の失効レコードは最大約30秒後にメモリから除去する。明示終了・正常シャットダウンでも破棄し、プロセス再起動後は復元しない。

初版は**単一ワーカー・単一プロセス**で運用する。ワーカーやコンテナを増やすとメモリが分かれるため、同じCookieでも別プロセスでは認識できない。SQLiteへセッションや成績を移して解消する変更は行わない。

参考：[OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)、[OWASP CSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)、[FastAPI Lifespan](https://fastapi.tiangolo.com/advanced/events/)。

## 8. 解析結果の保持・復元（SESSION-002）

### 追加API

全経路でCookieと`X-Session-Request: 1`を使う。POST・個別DELETEには`X-CSRF-Token`と`X-Session-Revision`も必須。`X-Session-Revision`は最後に受け取ったworkspaceの`revision`を文字列化したもの。

| メソッド・URL | 入力 | 正常応答 |
| --- | --- | --- |
| `GET /api/v1/session/workspace` | 本文なし | `SessionWorkspaceResponse` |
| `POST /api/v1/session/reports` | 既存成績APIと同じFormData：`file`、任意の`profile_id`・`residence_years` | `SessionWorkspaceResponse` |
| `POST /api/v1/session/timetables` | 既存履修表APIと同じFormData：`file` | `SessionWorkspaceResponse` |
| `DELETE /api/v1/session/reports` | 本文なし | `SessionWorkspaceResponse`、成績だけを削除 |
| `DELETE /api/v1/session/timetables` | 本文なし | `SessionWorkspaceResponse`、履修表だけを削除 |
| `POST /api/v1/session/recommendations` | FormData：`academic_year`・`term`・`weekday`・`period`、任意の`profile_id`。CSVなし | 既存の`SlotRecommendationsResponse` |
| `POST /api/v1/session/recommendation-searches` | FormData：`academic_year`・`term`、任意の`profile_id`。CSVなし | 既存の`RecommendationSearchResponse` |

全件200。数値の範囲・判定不能・時間重複・修得済み除外・教養充足後の推薦停止は従来と同じ。検索時の`profile_id`を省略すると、保持する成績のプロファイルを使い、成績がない候補閲覧ではアプリの既定を使う。保持する成績と異なるプロファイルの指定は409で拒否する。不足探索には成績と履修表の両方が必要。

`SessionWorkspaceResponse`は次の構造を持つ。各項目は必須で、未解析・削除済みの`report`・`timetable`は`null`。`session`は第2節の`SessionResponse`、`report`は既存のschema version 2、`timetable`は既存のschema version 1そのものである。

```text
{
  schema_version: 1,
  revision: 非負の整数,
  session: SessionResponse,
  report: ReportResponse または null,
  timetable: TimetableResponse または null
}
```

実際の架空例は`contracts/examples/workspace-empty.json`、`workspace-both.json`、`workspace-restored.json`等を参照する。レスポンスを改変したJSONで更新するAPIは設けず、アップロード時は元CSVをサーバーが検証・解析する。

### フロントエンドの処理順序

1. 起動時はGET workspaceで復元を試みる。401なら未開始として空表示し、新規セッションを自動作成しない。
2. 利用者がCSVを読み込むときだけ、必要に応じてPOST sessionで開始し、GET workspaceからCSRFと更新番号を取得する。
3. CSVをPOST session/reportsまたはsession/timetablesへ送る。成功応答のworkspaceを表示し、CSRF・更新番号も更新する。
4. リロード時はGET workspaceの解析済みJSONを再表示する。ブラウザーのFile入力は空のままにし、再解析するときはCSVの再選択を求める。
5. 復元後の推薦は追加のsession配下のAPIを使う。保持したJSONをブラウザーから送り返したり、架空のCSVへ再構成したりしない。
6. 個別クリアは対応するDELETE、全削除はDELETE sessionを呼ぶ。期限切れは表示・JS変数・File入力・推薦結果を消し、再アップロードを案内する。

`static/session-client.js`はこのHTTP契約だけを使うDOM非依存クライアント。`window.createSessionClient(baseUrl)`で作成し、`restore`・`saveReport`・`saveTimetable`・`clear`・`end`・`slot`・`search`を利用できる。CSRF・解析結果・処理待ちPromiseが学生データを長期参照しないよう、結果を保持するPromiseをキューへ残さない。フレームワークや画面構成を指定するものではない。

### 競合・失敗・削除

各セッションに更新番号を持ち、受信前の照合に加え、解析完了後にも同じ番号と有効期限を確認する。削除・別操作・期限切れの後に終わった処理は保存しない。クライアント内の更新は順番に送信する。別タブの更新等で番号が変わったら409となる。

両参考UIの共通クライアントは`session_revision_conflict`で古い表示・ローカル参照・送信中の操作を無効にし、再読み込みを案内する。サーバーの最新入力は消さず、再読み込み後にGET workspaceから表示し直す。別タブの成績を画面に表示していないまま推薦の入力へ切り替えたり、409の検索を古い番号で繰り返したりしない。

置き換え要求を受けると旧結果を先に破棄して番号を進める。CSV形式エラーや容量不足でも旧結果を復元しない。成功時にもう一度番号が進むため、クライアントは増分を推測せず応答値を使う。失敗後にもGET workspaceで番号・残った結果を取得し直す。削除をサーバーへ届けられなかった場合はエラーを表示し、削除完了とは扱わない。

| HTTP | 追加code | 意味 |
| --- | --- | --- |
| 422 | `invalid_session_revision` | 更新番号なし・不正・重複 |
| 409 | `session_revision_conflict` | 既に別の操作が行われた。取得し直して明示的に再試行する |
| 409 | `session_profile_mismatch` | 保持する成績と異なるプロファイルを指定 |
| 409 | `session_inputs_missing` | 不足探索に必要な解析結果が不足 |
| 413 | `session_data_too_large` | 1セッションの保持上限を超える |
| 503 | `session_memory_full` | 全セッションの保持上限を超える |

上限は保持するUTF-8 JSONバイト列に対する値であり、処理中のコピーを含むプロセス全体のRSS上限ではない。期限切れ・個別削除・全削除・停止時には使用量も解放する。他利用者を追い出して新しいデータを入れない。

### 表示側での保護

- 画面は`textContent`等で組み立て、CSV由来の氏名・科目名をHTMLとして解釈しない。既存のCSP・no-storeも維持する。
- 期限はサーバーが決め、画面も残り時間から破棄タイマーを設定する。端数と通信時間を考慮し、表示側は少し早めに破棄する。再取得でタイマーを延長しない。
- タブが再表示・フォーカスされたときにも期限を確認する。`pagehide`で画面とローカル変数を消し、履歴から戻った場合は再読み込みしてサーバーへ確認する。
- 明示削除と期限切れは進行中のリクエスト・旧応答も無効化する。localStorage・sessionStorage・IndexedDB・Cache Storage・URL・history stateへ学生データを保存しない。
- 同じブラウザープロファイルのタブは同じCookieと解析結果を共有する。別人で利用する場合は全削除し、ブラウザープロファイル等を分ける。ログインによる本人識別は行っていない。

ブラウザーの終了・強制停止などではイベントが必ず実行されるとは限らないため、サーバーの固定期限を保持データの失効根拠とする。[pagehideの仕様](https://developer.mozilla.org/en-US/docs/Web/API/Window/pagehide_event)

## 9. 動作確認

通常画面は`/`、試作画面は`/prototype/`で同じ契約を使う。Dockerの場合は`docker compose up -d --build`で更新してから、次を確認する。

1. 架空の`examples/first-year-sample.csv`を成績欄へ読み込み、解析後に34単位と表示されることを確認する。
2. ページを再読み込みする。成績表示は復元し、ファイル選択欄は空になる。再解析する場合だけファイルを選び直す。
3. 履修表も解析済みなら、再読み込み後に不足探索を実行できる。送信するのは年度・ターム等の条件だけで、CSVを再送しない。
4. 成績欄のクリア後に再読み込みする。成績は復元せず、履修表は残る。全削除は通常画面の「読み込んだ情報をすべて削除」、試作画面の「読み込んだ情報をクリア」を使う。削除完了後は両方とも復元しない。
5. 作成から20分が過ぎると、操作を続けていても表示が消えて再読み込み後も復元しない。サーバーを再起動した場合も同様。
6. 同じブラウザーの別タブで入力を変更すると、古いタブの次の検索・更新は409になり、旧表示を消して再読み込みを案内する。再読み込みで最新の入力を復元する。

Cookieは開発者ツールのApplication/Storageから属性を確認できるが、値をコピー・記録しない。JavaScriptの`document.cookie`からは読めず、localStorage等に学生データは作られない。localhostのHTTP例外はTLS設定を追加するものではなく、外部配置時は別途HTTPSを構成する。

自動の実ブラウザー確認は`scripts/check_session_reload.cjs`。Playwrightとブラウザーのある開発環境で、通常設定のlocalhostサーバーと`SESSION_TTL_SECONDS=8`の別サーバーを用意して実行する。

```bash
node scripts/check_session_reload.cjs \
  --base-url http://localhost:18080 \
  --expiry-url http://localhost:18081
```

接続先はlocalhostに制限し、同梱の確認済み架空CSVとメモリ生成の履修表だけを使う。CSV・応答本文・Cookie・画像・トレース・動画は保存しない。SQLite・共有評価は導入せず、2026-11-11の利用者指定により保留する。
