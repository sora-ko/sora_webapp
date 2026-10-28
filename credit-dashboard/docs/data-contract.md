# データ契約

## 1. 方針

CSV固有の表記を直接フロントエンドや判定ロジックへ流さない。
バックエンドで正規化し、バージョン付きJSONとして返す。

CSV原本はリクエスト処理中だけメモリに保持し、レスポンス完了後に参照を破棄する。

## 2. アップロードAPI

履修表の入力には別リソース`POST /api/v1/timetables`を使う。[履修表CSVの読み取り仕様](timetable-csv.md)にフィールド・返却JSON・0のMVP除外方針を定義する。以下の成績レポートJSONとは別モデルであり、履修表の表示科目を取得単位へ加算しない。

公開資料から生成する開講カタログの契約は[教養開講カタログ](liberal-catalog.md)に分離する。現在の簡易JSONは`schema_version: 3`で、`academic_year`・`profile_id`・`courses`を持つ。対象学年は持たず、候補検索のAPIも学年を使わない。科目は開講番号・名前・単位・区分・ターム・曜限の6項目。旧版の`offerings`や出典情報は含めない。ファイル全体の直接配信は行わず、代表科目の収録を履修許可や不足単位に応じた推薦結果として扱わない。

時間割のマスからの取得には`GET /api/v1/recommendation-catalogs`と`POST /api/v1/recommendations`を使う。リクエスト、返却JSON、候補なし・占有・未確認の区別、別Origin接続は[候補API仕様](recommendation-api.md)を参照する。ファイル全体をそのまま配信するAPIとは分け、カタログ検索と履修表による重複除外を行う。

取得単位との照合は別の`POST /api/v1/recommendation-searches`を使う。成績CSVと履修表CSVを受け取り、卒業の教養関連条件を1科目ずつ仮追加して再評価する。確定した不足を減らせる候補と必要性未確定の候補は別配列へ返す。両CSVともメモリ処理だけで、集計APIやマス検索APIの契約は変えない。詳細は[単位照合の探索API](recommendation-search-api.md)。

### `GET /api/v1/rule-profiles`

登録・検証済みの年度・プログラム別規則プロファイルを返す。各要素には対象範囲、プロファイル内の要件メタデータ、現在APIで実装済みの`implemented_requirement_ids`を含む。学生データは含めない。

この一覧には`schema_version`はない。入学年度と開講年度を混同しない。基本形は次のとおりで、注意書き・要件は省略例である。

```json
{
  "default_profile_id": "niigata-engineering-sis-2025-v1",
  "profiles": [{
    "profile_id": "niigata-engineering-sis-2025-v1",
    "institution": "新潟大学",
    "faculty": "工学部",
    "program": "知能情報システムプログラム",
    "admission_year": 2025,
    "policy_notes": [],
    "requirements": [{"requirement_id": "graduation", "title": "卒業資格条件", "rule_status": "partial"}],
    "implemented_requirement_ids": ["progression_year_2", "progression_year_4", "graduation"]
  }]
}
```

初期選択は`default_profile_id`に対応する要素を使う。画面の所属表示と候補APIへの`profile_id`は、同じ選択から生成する。

### `POST /api/v1/reports`

- Content-Type: `multipart/form-data`
- `file`: 必須のCSVファイルフィールド
- `profile_id`: 任意。`GET /api/v1/rule-profiles`で取得したID。省略時は既定プロファイル
- `residence_years`: 任意。入力安全性のため0以上100以下の有限数。在学期間条件を上書きする入力。未入力時は留年・編入なしのMVP前提でCSVの学年を使用し、どちらもなければ`unknown`
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
| 422 | `unknown_rule_profile` | 未登録の対象年度・プログラムが指定された |
| 422 | `invalid_evaluation_context` | 在学期間等の判定入力が不正 |
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
  "course_code": "SAMPLE-CODE",
  "name": "電磁気学",
  "normalized_name": "電磁気学",
  "credits": 2,
  "result": "passed",
  "source_result": "合",
  "source_category": "専門基礎科目群（選択必修）",
  "requirement_type": "選択必修",
  "curriculum_area": "faculty_specialized",
  "course_group": "specialized_foundation",
  "requirement_code": "B",
  "field_codes": ["41"],
  "level": "3",
  "earned_year": "2025",
  "earned_term": "第1学期",
  "classification_status": "classified",
  "catalog_course_id": "sis-foundation-b-04",
  "classification_reason_code": "selected_program_catalog"
}
```

値が不明な項目は `null` とする。空文字列と `null` を混在させない。

`requirement_type`はCSVの「必選区分」の原値である。科目マスターがあるプロファイルでは、既知の専門系科目に対してマスターの群・A〜Eを優先し、原値は変更しない。マスターがないプロファイルは従来どおり`source_category`と組み合わせてA〜Eへ正規化する。教養系では卒業要件表の必修・選択必修・選択と直接一致しないため、この値だけで配賦先を決めず、科目区分・指定科目名と先行枠への充当結果を使う。

### `result`

- `passed`: `合否` が「合」で、有効な単位数も記録されており、取得単位として算入できる
- `failed`: 不合格
- `unconfirmed`: 合否が空欄・未知の表記、または「合」でも単位数が未確定

取得済み単位へ加算する条件は `result == passed` とする。「合」という文字だけでは単位認定済みとみなさない。

科目には同じ正規化値の`status`も返る。`result`と`status`は表示上の互換フィールドであり、CSV原値は`source_result`にある。新しいフロントエンドはどちらかに統一して表示し、未知の値を合格へ読み替えない。

### `curriculum_area`

- `liberal_arts`: 教養系科目
- `faculty_specialized`: 学部専門系科目
- `excluded`: MVP対象外で、進級・卒業要件の算入対象から明示的に除外した科目（大分類表示は「対象外」）
- `unknown`: 判定不能

### `classification_status`

- `classified`: 根拠のある規則で分類できた
- `ambiguous`: 複数候補がある
- `unknown`: 規則に一致しない

曖昧または未知の科目を便宜的に教養・専門へ割り当てない。

### 分類根拠と科目マスター

- `catalog_course_id`: 選択した科目マスターのID。一致しなければ`null`。同じIDであっても開講番号が異なる行は別科目として単位を扱う。
- `classification_reason_code`: `source_category`（CSV区分）、`selected_program_catalog`（対象専門一覧）、`outside_catalog_as_liberal`（利用者指定の一覧外専門→教養）、`excluded_by_mvp_policy`（既知の対象外ラベル）、`unknown_category`（未知区分）。
- 一覧外専門は`field="対象専門科目一覧外"`とし、専門の群・A〜Eは`null`にする。教養の選択残余へだけ使い、自然科学などの細区分へ推測で変換しない。
- 同じ原科目区分でも専門一覧の内外で大分類が異なるため、`summary.categories`は原科目区分と大分類の組合せごとに集計する。
- `summary.earned_credits`はCSV上の確認済み取得単位であり、「対象外」も含む。進級・卒業条件の`confirmed_credits`は各規則が算入できる単位だけを数える。
- `curriculum.policy_notes`と規則一覧APIの各プロファイルの`policy_notes`は、学生データを含まないMVP対象範囲と公式規則との差を返す。画面はこの文言を表示する。

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
  "evaluation_context": {
    "residence_years": 1,
    "residence_years_source": "student_grade_assumption",
    "student_grade_year": 1,
    "displayed_requirement_ids": ["progression_year_2", "graduation"]
  },
  "evaluations": [
    {
      "requirement_id": "progression_year_2",
      "title": "第2年次進級条件",
      "profile_id": "niigata-engineering-sis-2025-v1",
      "status": "unknown",
      "description": "不足入力または未確定情報があるため、総合結果を確定できません。",
      "advisory_only": true,
      "rule_status": "partial",
      "evidence_status": "transcribed",
      "input_context": {"residence_years": 1, "residence_years_source": "student_grade_assumption", "student_grade_year": 1},
      "conditions": [],
      "sources": [],
      "caveats": []
    }
  ]
}
```

`student` の値はMVP画面にマスクせず表示するが、ログや永続ストレージには保存しない。
`curriculum`は選択された規則プロファイルから生成する。CSVの所属表記だけで対象プログラムを確認できない場合は警告するが、表記差だけを根拠に不一致と断定しない。

### `summary`の項目（2026-10-28に公開APIで補足確認）

この項目はバックエンドで計算された集計であり、画面で科目一覧から再計算しない。`null`や欠落は「未確認」として表示し、0で補完しない。

| 項目 | 型 | 意味 |
| --- | --- | --- |
| `course_count` | 整数 | 解析した科目数 |
| `passed_count` | 整数 | 有効な単位数を持つ合格科目数 |
| `unconfirmed_count` | 整数 | 合否・単位等が未確定の科目数 |
| `unknown_credit_count` | 整数 | 単位数が未確定の科目数 |
| `earned_credits` | 数値 | CSV上の取得済み単位の合計。「対象外」を含むため、学務要件への算入値とは区別する |
| `unconfirmed_credits` | 数値 | 未確定科目に記録された既知の単位数の合計。取得済みや修得予定の保証値として扱わない |
| `majors` | 配列 | 大分類ごとの`major`・`earned_credits`・`unconfirmed_credits`・`course_count` |
| `categories` | 配列 | 元科目区分と大分類の組ごとの内訳。下記参照 |

`majors[].major`は「教養」「専門」、入力によって「不明」「対象外」。`categories[]`は`source_category`、`major`、`field`、`detail`、`earned_credits`、`unconfirmed_credits`、`course_count`、`passed_count`、`unconfirmed_count`を持つ。`field`・`detail`は元区分の解析結果であり、卒業枠への配賦結果ではない。

### 条件の表示用の項目

`evaluations[].conditions[]`は`id`・`label`・三値の`status`・`reason_code`・日本語`description`を持ち、条件の種類により次の値を返す。

- 単位条件：`minimum_credits`、`confirmed_credits`、`confirmed_credit_shortfall`、`has_uncertain_candidate`。
- 在学期間：`minimum_years`、`confirmed_years`、`value_source`。
- 個別必修：後述の`required_course_count`、`satisfied_course_count`、`course_results`等。

`confirmed_credit_shortfall`は確認済み単位だけを使った差であり、条件が`unknown`なら確定した不足ではない。「確認済み単位との差」と表示する。分類別条件と合計条件は重なるため、値を足して独自の不足合計を作らない。進捗バーは同一条件の確認済み値・必要値だけを表示に使い、総合判定は`evaluations[].status`をそのまま使う。

### 学年別の`evaluations`

CSVの学年に応じて次の要件を返す。

- 1年: `progression_year_2`, `graduation`
- 2・3年: `progression_year_4`, `graduation`
- 4年以上: `graduation`
- 学年不明: 対応する全要件。任意入力もなければ在学期間は`unknown`

第4年次進級・卒業要件は、専門・教養それぞれの最低単位超過分を共通6単位へ合算し、確認済みの分類別条件を返す。専門基礎Bの超過分は専門応用Bへ配賦し、専門応用の追加枠は基礎B・応用Bの最低枠へ充当した後の残余として返す。個別必修を含む全条件が`satisfied`なら総合も`satisfied`とする。確定した未充足条件があれば`not_satisfied`、それ以外に分類不能や未確定情報が結論へ影響するときは`unknown`とする。卒業要件の教養系条件は全学年のレスポンスへ含まれる。

### 個別必修条件

卒業の`conditions`に`id="individual_required_courses"`を含める。この条件は単位配賦ではなく、科目マスターの`required_for`による全必修科目の修得確認である。次を返す。

- `required_course_count`: 対象の必修科目数
- `satisfied_course_count`: 修得を確認できた必修科目数
- `missing_course_names`: 未修得または必要単位未達と確定した必修科目名
- `unknown_course_names`: 合否・単位数・分類が未確定で確認できない必修科目名
- `course_results`: 各必修の`catalog_course_id`、`name`、三値の`status`、`reason_code`、`minimum_credits`、`confirmed_credits`、`confirmed_credit_shortfall`、`has_uncertain_candidate`、`description`、`source_refs`

この条件の`reason_code`は`all_required_courses_passed`、`required_courses_missing`、`required_course_results_uncertain`。一つでも確定した未充足があれば条件全体は`not_satisfied`、未充足がなく未確定があれば`unknown`とする。

条件自体は`confirmed_credits`を返さず、科目数で表示する。`course_results[].confirmed_credits`は各必修について確認できた1回の有効な修得の最大単位数であり、異コードの同名科目を合算しない。これらは確認用の値なので、区分合計・総計へ追加加算してはならない。API利用者は`description`と科目別の結果を表示し、判定を再計算しない。

```json
{
  "requirement_id": "progression_year_2",
  "title": "第2年次進級条件",
  "profile_id": "niigata-engineering-sis-2025-v1",
  "status": "unknown",
  "description": "不足入力または未確定情報があるため、総合結果を確定できません。",
  "advisory_only": true,
  "rule_status": "partial",
  "evidence_status": "transcribed",
  "input_context": {"residence_years": 1, "residence_years_source": "student_grade_assumption", "student_grade_year": 1},
  "conditions": [
    {
      "id": "minimum_residence",
      "label": "在学期間",
      "status": "satisfied",
      "reason_code": "minimum_reached",
      "minimum_years": 1,
      "confirmed_years": 1,
      "value_source": "student_grade_assumption",
      "description": "CSVの学年と在学年数が一致するMVP前提により、在学期間を1年として扱い、必要な1年以上です。"
    }
  ],
  "source_refs": [
    {
      "document_id": "student_handbook_2025",
      "section": "工学部規程細則 第10条〜第13条",
      "printed_pages": [23, 24],
      "pdf_pages": [27, 28]
    }
  ],
  "sources": [
    {
      "document_id": "student_handbook_2025",
      "title": "新潟大学工学部 学生必携 2025（令和7）年度入学生用",
      "url": "https://www.eng.niigata-u.ac.jp/student/files/hikkei_2025.pdf",
      "section": "工学部規程細則 第10条〜第13条",
      "printed_pages": [23, 24],
      "pdf_pages": [27, 28]
    }
  ],
  "caveat_ids": [],
  "caveats": []
}
```

判定状態は`satisfied`、`not_satisfied`、`unknown`の三値とする。確定単位が最低値に届かず、未確定科目や分類不能科目が結果を変え得る場合は`unknown`とする。同一科目識別子の重複も、同一性が確定するまでは二重加算しない。
日本語の`description`はバックエンドで生成し、フロントエンドは学務判定を再実装せず表示だけを行う。

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

