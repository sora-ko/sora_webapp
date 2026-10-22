# データ契約

## 1. 方針

CSV固有の表記を直接フロントエンドや判定ロジックへ流さない。
バックエンドで正規化し、バージョン付きJSONとして返す。

CSV原本はリクエスト処理中だけメモリに保持し、レスポンス完了後に参照を破棄する。

## 2. アップロードAPI

### `POST /api/v1/reports`

- Content-Type: `multipart/form-data`
- ファイルフィールド: `file`
- 受け付けるファイル数: 1
- 最大サイズ: 5 MiB
- 文字コード: UTF-8、UTF-8 BOM、CP932
- 認証: MVPではなし。サーバー公開時に別途定義する。

成功時はHTTP 200で解析結果を返す。サーバーにはレポートIDを保存しない。

### 主なエラー

| HTTP | code | 例 |
| ---: | --- | --- |
| 400 | `missing_file` | ファイルが指定されていない |
| 400 | `multiple_files` | 複数ファイルが指定された |
| 400 | `invalid_multipart` | multipartの構文が不正 |
| 413 | `file_too_large` | 上限を超えた |
| 415 | `unsupported_media_type` | multipart/form-dataではない |
| 415 | `unsupported_encoding` | 対応外の文字コード |
| 422 | `invalid_csv` | CSVとして読めない |
| 422 | `missing_columns` | 必須列が不足 |
| 422 | `invalid_value` | 単位数等が不正 |
| 404 | `route_not_found` | APIのURLが存在しない |
| 405 | `method_not_allowed` | APIが受け付けないHTTPメソッド |
| 500 | `internal_error` | 予期しない障害。入力内容をメッセージやログへ含めない |

エラー形式の例:

```json
{
  "error": {
    "code": "missing_columns",
    "message": "必要な列が見つかりません。",
    "details": {
      "columns": ["科目区分", "合否"]
    }
  }
}
```

## 3. 入力CSV

### 必須列

- `No.`
- `科目`
- `科目区分`
- `単位数`
- `合否`

### 利用する任意列

- `分野`
- `水準`
- `開講番号`
- `必選区分`
- `得点`
- `評価`
- `GP`
- `修得年度`
- `修得学期`
- `読替前科目`
- `読替後科目`

列の前にある学生情報欄から、氏名、在籍番号、所属、学年を読み取れる。ただし、欠落しても科目解析は続行する。

要件確認時に参照した入力CSVは、CP932、学生情報の前置き、19列の見出し、可変数の科目行という構造だった。実在データをプロジェクトへ残さず、テストでは同じ特徴を持つ架空データを生成する。実装は確認例の行数を定数として使用せず、見出し行を検出した後、ファイル終端まで読み、空行を除く各行を検証する。

## 4. 正規化モデル

科目ごとに、少なくとも次を保持する。

```json
{
  "row_number": 6,
  "sequence": 1,
  "course_code": "251T4001",
  "name": "架空専門科目",
  "credits": 2,
  "result": "passed",
  "source_result": "合",
  "source_category": "専門基礎科目群（選択必修）",
  "curriculum_area": "faculty_specialized",
  "course_group": "specialized_foundation",
  "requirement_code": "B",
  "field_codes": ["41"],
  "level": "3",
  "earned_year": "2025",
  "earned_term": "第1学期",
  "classification_status": "classified"
}
```

値が不明な項目は `null` とする。空文字列と `null` を混在させない。

### `result`

- `passed`: `合否` が「合」で、有効な単位数も記録されており、取得単位として算入できる
- `failed`: 不合格
- `unconfirmed`: 合否が空欄・未知の表記、または「合」でも単位数が未確定

取得済み単位へ加算する条件は `result == passed` とする。「合」という文字だけでは単位認定済みとみなさない。

### `curriculum_area`

- `liberal_arts`: 教養系科目
- `faculty_specialized`: 学部専門系科目
- `unknown`: 判定不能

### `classification_status`

- `classified`: 根拠のある規則で分類できた
- `ambiguous`: 複数候補がある
- `unknown`: 規則に一致しない

曖昧または未知の科目を便宜的に教養・専門へ割り当てない。

## 5. レスポンス

概形は次のとおり。

```json
{
  "schema_version": 2,
  "curriculum": {
    "institution": "新潟大学",
    "faculty": "工学部",
    "program": "知能情報システムプログラム",
    "admission_year": 2025,
    "rules_version": "niigata-engineering-sis-2025-v1"
  },
  "student": {
    "name": null,
    "student_number": null,
    "affiliation": null,
    "grade": null
  },
  "summary": {},
  "courses": [],
  "warnings": [],
  "evaluations": []
}
```

リリース1では `evaluations` を空配列とし、進級・卒業判定の追加時に同じスキーマへ拡張する。
`student` の値はMVP画面にマスクせず表示するが、ログや永続ストレージには保存しない。

## 6. 後方互換性

- 破壊的な変更では `schema_version` を上げる。
- フロントエンドは未知の追加フィールドを無視する。
- 列名の別名対応は入力アダプター内に閉じ込める。
- 公式CSVの形式変更に対し、旧形式用テストを残す。

## 7. ログ禁止項目

次の値を通常ログへ出力しない。

- CSV本文および行内容
- 氏名、在籍番号、所属
- 科目名と成績を組み合わせた情報
- APIレスポンス本文

ログに残してよいものは、時刻、HTTPメソッド、パス、ステータス、処理時間、ファイルサイズ、匿名化されたエラーコードまでとする。

## 8. 旧API

旧`GET /api/report`はプロジェクト内の固定CSVを読み込まない。HTTP 410と`upload_required`を返し、画面からのアップロードを案内する。

