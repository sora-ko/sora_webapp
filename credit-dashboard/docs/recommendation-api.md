# 教養候補APIとフロントエンド接続

確認日: 2026-10-27。初回のカタログ配置・別フロントとの分業手順は[引き継ぎ手順](handoff.md)を参照する。

時間割のマスから候補を取得するためのAPI。FastAPIの画面実装に依存しない。単位集計APIとは別リソースで、サーバーセッション・Cookie・解析結果のIDを使わない。

現在は代表63科目からの曜限検索と履修表との重複除外に対応する。利用者指定により、学生の学年で候補を変えず、学年の確認も行わない。成績CSVは入力せず、修得済み単位・不足枠への効果・先修条件・履修許可は未判定。APIの`checks`と`messages`を画面にも表示する。

修得単位と空き時間からの探索は、別の`POST /api/v1/recommendation-searches`で提供する。[単位照合の探索API](recommendation-search-api.md)を参照する。このマス検索APIの入力・効果未判定という契約は維持する。

## 1. 操作の流れ

1. `GET /api/v1/recommendation-catalogs`で対応年度・プロファイル・表示可能なタームを取得する。
2. その範囲の時間割を表示する。参考UIは「時間割と教養候補」タブにある。
3. マスのクリックで`POST /api/v1/recommendations`へコンテキストを送る。
4. 履修表を読み込んでいる場合は、元の`File`も毎回送る。バックエンドが解析し、科目の全曜限との重複を除外する。
5. `status`、候補の配列、未確認事項を表示する。空配列だけで不合格・履修不可と表示しない。

CSVなしでもカタログ上の候補を確認できる。履修表を読んでからはその表のマスを使う。通常授業のある枠もクリックでき、APIが`occupied`を返す。

## 2. 対応カタログ一覧

`GET /api/v1/recommendation-catalogs`

```json
{
  "schema_version": 1,
  "catalogs": [{
    "academic_year": 2026,
    "profile_id": "niigata-engineering-sis-2025-v1",
    "program": "知能情報システムプログラム",
    "course_count": 63,
    "terms": [1, 2, 3, 4],
    "weekdays": [1, 2, 3, 4, 5],
    "periods": [1, 2, 3, 4, 5]
  }]
}
```

未配置なら`catalogs: []`。不正なJSONや重複するカタログは503。過年度へフォールバックしない。フロント側はこの一覧を使い、対象を知能情報・2026年度へ固定しない。同じ年度・プロファイルの候補を全学年で共用する。

## 3. マスの候補取得

`POST /api/v1/recommendations`

Content-Typeは`multipart/form-data`。ブラウザーでは`FormData`を使い、Content-Typeを手動で指定しない。

| フィールド | 必須 | 内容 |
| --- | --- | --- |
| `profile_id` | 推奨 | 一覧のプロファイルID。省略すると既定プロファイル |
| `academic_year` | 必須 | 開講年度。2000〜2099 |
| `term` | 必須 | ターム。1〜4 |
| `weekday` | 必須 | 月=1〜金=5 |
| `period` | 必須 | 1〜5限 |
| `file` | 任意 | 履修表CSV。最大5 MiB。成績CSVではない |

学年は入力不要で、旧クライアントが送る`grade`も無視する。履修表の学年が空欄・未知表記・矛盾する値でも、この検索は保留しない。入学年度からの学年補完も行わない。学務規則のプロファイルは分類のために選び、候補検索の開講年度と入学年度の関係は制約しない。単位集計APIの学年別要件表示は従来どおりとする。

ファイル名・拡張子・MIME typeではなく内容を検証する。元CSVは処理中のメモリだけに置き、氏名・在籍番号・所属・元の科目名等は応答やログに含めない。通常の履修表APIの返却項目は変更していない。

## 4. 成功応答

例の科目は架空値である。

```json
{
  "schema_version": 1,
  "context": {"profile_id": "niigata-engineering-sis-2025-v1", "academic_year": 2026, "term": 3, "weekday": 2, "period": 1},
  "basis": "catalog",
  "status": "ok",
  "candidates": [{
    "course_code": "263G9901", "name": "架空の推薦候補", "credits": 2,
    "category": "自然科学（架空区分）", "terms": [3], "schedule": [{"weekday": 2, "period": 1}]
  }],
  "counts": {"matching": 1, "returned": 1, "excluded_overlap": 0, "excluded_unconfirmed": 0, "excluded_registered": 0},
  "checks": {"timetable": "not_provided", "earned_credits": "not_checked", "requirements": "not_checked", "enrollment": "not_checked"},
  "messages": [{"code": "timetable_not_provided", "message": "履修表未読込のため、登録済み授業との時間重複は確認していません。"}]
}
```

- `basis`：CSVなしは`catalog`、ありは`timetable`。
- `status`：`ok`は候補あり、`empty`は確認できた範囲で候補なし、`occupied`はクリックした枠に授業あり、`unknown`は必要情報が未確認で保留。
- `candidates`：簡易カタログと同じ6項目。開講番号順で、成績や必要度によるランキングではない。
- `counts.matching`：クリック枠を含む元候補数。残りの件数は重複等を除いた結果。全体の不確定・占有で保留した際は候補を返さない。
- `checks.timetable`：`checked`、`not_provided`、`needs_review`。現在、他の3項目は常に`not_checked`。
- `messages`：画面へ表示する日本語の説明。番号0を除外した履修表では、除外した授業との重複は未確認である注意も返す。

クリックした枠が空いていても、同じ科目の別の曜限が重なれば除外する。別タームの授業は混同しない。対象期間・曜日・時限が履修表に掲載されていなければ空きと断定しない。未解決の履修表情報がある場合も候補を保留する。

保留理由は`messages`で区別する。`timetable_unconfirmed`は解析上の未解決、`timetable_period_unconfirmed`は対象期間未確認、`slot_unconfirmed`は未掲載の曜限。学年を理由とする保留やエラーは返さない。

## 5. エラー

形は既存APIと同じ`{"error":{"code":"...","message":"日本語の説明"}}`。通常のHTTP 200の`status`と区別する。

| HTTP | code | 内容 |
| ---: | --- | --- |
| 404 | `recommendation_catalog_not_found` | 対応する年度・プロファイルのカタログなし |
| 422 | `invalid_recommendation_context` | 必須コンテキスト不足、範囲外 |
| 422 | `unknown_rule_profile` | 対象プロファイルが未登録 |
| 503 | `recommendation_catalog_invalid` | カタログの形式・配置・一意性が不正 |
| 400/413/415/422 | 既存のアップロード系コード | multipart不正、複数file、上限超過、未対応文字コード、不正CSV等 |

不正なCSVをファイルなしの検索へ読み替えない。全応答は`Cache-Control: no-store`で、セッションCookieを発行しない。

## 6. フロントエンドの分離

DOMに依存しない通信部分は`static/recommendation-api.js`、参考UIは`static/recommendations.js`。UIはReact等へ置き換えてよく、バックエンドの抽出・重複判定を画面へ移植しない。

```javascript
const api = window.createRecommendationClient(); // 別OriginのAPIならURLを渡す
const catalogs = await api.catalogs();
const result = await api.recommend({
  profile_id: catalogs[0].profile_id,
  academic_year: catalogs[0].academic_year,
  term: 3, weekday: 2, period: 1
}, timetableFileOrNull, abortController.signal);
```

再選択・ファイル変更・ターム変更・クリアでは送信を中断し、古い応答も世代番号で無視する。CSVと応答は画面利用中のメモリだけに保持し、URLや永続ストレージへ載せない。タブ切替では保持し、再読込とクリアで破棄する。

フロントを別ポートで開発する場合は`/api`をバックエンドへプロキシするか、サーバー起動時の`CORS_ALLOWED_ORIGINS`へ明示的なOriginを設定する。例：`http://localhost:5173,http://127.0.0.1:5173`。既定は別Originを許可せず、Cookie認証は使わない。

## 7. カタログの配置と拡張

通常起動では`data/recommendations/`、Dockerでは`RECOMMENDATION_CATALOG_DIR`の下にある`liberal-catalog.json`を読む。`archive/`・`sources/`の旧版・原表は検索対象外。公開カタログだけを読み、学生CSVをファイルから検索しない。

Composeは生成済みの`data/recommendations/2026/liberal-catalog.json`だけを読み取り専用で配置する。`data/`全体や学生CSVはマウントしない。新しい開発環境では生成または公開JSONの配置を済ませてからComposeを起動する。

別年度・別プロファイルは別の公開カタログとして配置し、メタデータで選択する。サーバーは年度・プロファイルを組にして選び、学年は使わない。必要な学務規則プロファイルも先に登録する。利用用カタログは`schema_version: 3`で、旧版は読み込まないため、コード更新時には再生成して配置する。
