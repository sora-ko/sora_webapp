# 修得単位と空き時間からの教養探索API

確認日: 2026-10-27。教養充足時の推薦停止を含む現行契約。初回の環境・架空CSVの復元は[引き継ぎ手順](handoff.md)を参照する。

2026-10-27追加。指定したマスの教養を返す`POST /api/v1/recommendations`とは別のAPIとする。成績CSVと履修表CSVを受け取り、選択タームの空き時間にある教養のうち、卒業の単位条件を改善できる候補を返す。学生の学年は使わない。

## 1. リクエスト

`POST /api/v1/recommendation-searches`

`multipart/form-data`を使う。ブラウザーは`FormData`に任せ、Content-Typeを手動設定しない。

| フィールド | 必須 | 内容 |
| --- | --- | --- |
| `profile_id` | 推奨 | カタログ一覧の規則プロファイルID。省略時は既定値 |
| `academic_year` | 必須 | 開講年度。2000〜2099 |
| `term` | 必須 | 探索するターム。1〜4 |
| `grades_file` | 必須 | 元の成績CSV。5 MiB以下、1ファイル |
| `timetable_file` | 必須 | 元の履修表CSV。5 MiB以下、1ファイル |

年度とプロファイルは`GET /api/v1/recommendation-catalogs`から選ぶ。曜日・時限は指定せず、月〜金・1〜5限の空き時間全体を探索する。両CSVは同じ学生のものを選ぶ。本人確認や両ファイルの学生同一性の検証は行わない。学年に応じた推薦対象の切替や、入学年度による学年制限は行わない。

受信は各CSV5 MiB、multipart全体は10 MiB＋64 KiBを上限とし、ストリームの実サイズを検証する。ファイル名・拡張子・MIME typeは信用せず、専用パーサーで内容を検証する。元CSVと解析結果は処理中のメモリだけに置き、一時ファイル・DB・サーバーセッションへ保存しない。

## 2. 判断の手順

1. 選択プロファイルの分類器で成績CSVを解析する。`合否=合`かつ単位数が有効な行だけを取得済みとして扱う。成績CSV内の行を科目名で名寄せしない。
2. 同じ開講番号、または同じ科目名を修得済みなら推薦から外す。科目名は既存プロファイルの明示済み接尾辞・別名と、既存マスター照合でも使う全半角・ローマ数字・空白の差だけを正規化する。類似名や括弧を推測でまとめない。この除外は利用者が明示した推薦方針であり、再履修行の既存の集計方法とは別。
3. 履修表の年度・ターム・全曜限を確認する。登録済みコードと時間重複を除外する。科目の一部の時限だけが空いていても推薦しない。未掲載・未解決・対象期間不明は空きと見なさない。開講番号のターム値0は既存の利用者方針で除外し、その授業との重複は未確認と説明する。
4. 学年にかかわらず、卒業要件のうち教養だけを要求する単位条件を推薦の基準とする。セレクターの`curriculum_areas`が教養だけの条件、または複合条件の全選択肢が教養に限定される条件から、必修・選択必修・選択・教養合計を選ぶ。すべて充足なら、専門・共通超過分・総計が不足していても候補と要確認候補を空にし、`status: empty`と`liberal_requirements_satisfied`の説明を返す。教養合計だけでなく分類別条件も確認し、判定不能を充足と見なさない。条件IDや必要単位数は探索コードへ直書きしない。
5. 教養に未充足の条件がある場合、候補を1科目だけ合格・単位修得したと仮定し、共通の`evaluate_graduation`で再計算する。教養だけの条件に確定した改善がある候補を`candidates`へ返す。共通超過分・総計の改善だけでは推薦しないが、採用候補の付随効果として返す。元の成績・実際の取得単位は変更しない。
6. 元の条件が`unknown`なら、不足だと確定せず、確認済み単位だけに基づく差の改善を`uncertain_benefits`へ分ける。教養だけの条件に未確定の改善しかない科目は`review_candidates`へ返す。同名・同一番号の成績が結果未確定の候補も要確認へ回す。専門側の未確定だけでは教養の要確認候補を作らない。規則が保留中のプロファイルは確定推薦を返さない。

教養の必修・選択必修・選択の配賦は既存判定器と同じ。自然科学の選択必修へ使った単位を、そのまま選択枠へ重ねて充当しない。分類別条件・合計・総計は階層が重なるため、それぞれの改善量を合算して推薦点数にしない。初版の表示順は開講番号順。

候補はそれぞれ独立した選択肢であり、全科目を組み合わせた履修計画ではない。候補同士が同じ時間に開講されることもある。履修中の単位を先取りせず、成績の予測も行わない。先修条件・抽選・履修許可・シラバス本文は未確認。検索対象は既存の代表63開講であり、全ての不足枠に候補が見つかる保証はない。

## 3. 成功応答

主な項目は次のとおり。数値は元の成績ではなく、確認済みの集計または候補修得を仮定した差分である。

| 項目 | 内容 |
| --- | --- |
| `schema_version` | `1` |
| `context` | 年度、ターム、プロファイルID |
| `target_requirement_id` | `graduation`。全学年共通 |
| `status` | `ok`：確定した不足への候補あり、`empty`：確認できた範囲で該当なし、`unknown`：候補が要確認のみ、または必要情報が未確定 |
| `baseline` | 照合した卒業の単位条件。`id`、`label`、三値の`status`、`minimum_credits`、`confirmed_credits`、`confirmed_credit_shortfall`、`has_uncertain_candidate` |
| `free_slots` | 履修表で確認できた空き時間。`weekday`、`period`。選択年度・ターム内だけ |
| `candidates` | 確認済みの不足を減らせる候補 |
| `review_candidates` | 必要性や既存成績に確認が必要な候補。`candidates`とは別に表示する |
| `checks` | `timetable`、`earned_credits`、`requirements`、`enrollment`の確認状態 |
| `counts` | 探索・除外件数。下記参照 |
| `messages` | `code`と画面表示用の日本語`message`。仮定・未確認事項を含む |

各候補は既存の6項目（開講番号、名前、単位、区分、ターム、曜限）に、`benefits`、`uncertain_benefits`、`review_reasons`を加える。効果1件の形は次のとおり。

```json
{
  "condition_id": "liberal_natural_foundation",
  "label": "教養・情報リテラシー／自然系共通専門基礎／自然科学（選択必修）",
  "before_shortfall": 2,
  "after_shortfall": 0,
  "reduced_credits": 2,
  "before_status": "not_satisfied",
  "after_status": "satisfied"
}
```

`uncertain_benefits`は同じ形式だが、元の条件が判定不能等のため必要性を確定していない。`confirmed_credit_shortfall`も、条件が`unknown`の場合は「確定した不足」ではなく「確認済み単位だけによる差」と表示する。確定した改善と未確定の改善を同じ表示へまとめない。

`checks.earned_credits`は`checked`。`checks.timetable`と`checks.requirements`は`checked`または`needs_review`。`checks.requirements`は推薦基準となる教養だけの条件と規則の確定状態を示す。`baseline`には引き続き共通超過分・総計も返すため、専門に由来するそれらの`unknown`と、`checks.requirements: checked`は両立する。`checks.enrollment`は常に`not_checked`。一部に要確認があっても、別の教養条件で確定した改善のある候補は返せるため、`status: ok`と`needs_review`も両立する。

教養が充足していると確定した場合は、時間割に未解決があっても推薦不要として`empty`を返す。このとき時間割の確認状態は`needs_review`のままで、未解決の時間を空きに変換しない。

`counts`は`catalog_in_term`、`excluded_earned`、`excluded_registered`、`excluded_overlap`、`excluded_unconfirmed_time`、`excluded_no_benefit`、`returned`、`review_required`。除外は修得済み→時間→効果の順で、1候補を複数の除外理由へ数えない。全体の時間情報を確認できず探索を保留した場合や、教養充足により科目探索を省略した場合、科目ごとの探索件数は0のまま返す。

氏名・学籍番号・所属、元の成績一覧・科目名と成績の組合せは返さない。レスポンスやCSVはブラウザーでもメモリ上だけに持つ。`Cache-Control: no-store`、Cookieなし。

## 4. エラー

共通の`{"error":{"code":"...","message":"日本語","details":{"field":"grades_file"}}}`形式。`details.field`は入力を特定できる場合だけ返し、CSVのセル値や元ファイル名を含めない。

- 400 `missing_file` / `multiple_files`：必須CSVなし、同じ入力欄に複数ファイル。
- 413 `file_too_large`：各CSVまたはmultipart全体が上限超過。
- 415 `unsupported_media_type` / `unsupported_encoding`：送信形式・文字コードの問題。
- 422 `invalid_recommendation_context`：年度・タームが不足または範囲外。
- 422 `invalid_csv` / `missing_columns`等：成績または履修表の形式不正。`details.field`で入力を区別。
- 422 `unknown_rule_profile` / `recommendation_rules_unsupported`：プロファイル未登録または教養探索に対応する卒業条件なし。
- 404 `recommendation_catalog_not_found` / 503 `recommendation_catalog_invalid`：公開カタログの配置・形式の問題。

## 5. フロントエンドの接続

DOM非依存の`static/recommendation-api.js`へ`search`を追加した。独自フロントでも同じmultipartで呼べる。

```javascript
const api = window.createRecommendationClient();
const result = await api.search({
  profile_id: selectedCatalog.profile_id,
  academic_year: selectedCatalog.academic_year,
  term: 3
}, gradesFile, timetableFile, abortController.signal);
```

参考UIの`static/workspace-state.js`は元の`File`と単位集計で選択した対象プロファイルの公開メタデータをメモリ共有する。教養候補側にプログラムのプルダウンは置かず、単位集計の`profile_id`を候補閲覧と不足探索の両方へ渡す。成績CSVは単位集計タブ、履修表CSVは時間割タブで選び、「不足単位を補える教養を探す」で呼び出す。事前に集計・時間割解析ボタンを押すことは必須ではなく、探索APIが元ファイルを検証し直す。フロント側の解析JSONを正本として送らない。

開講年度は解析済み履修表の選択中の年度に合わせる。履修表をまだ解析していない場合は同一プロファイルの最新カタログ年度を明示して使い、APIが元CSVの対象期間を検証する。対応するカタログがない場合は送信せず案内し、別年度・別プログラムへ代替しない。対象変更時は`recommendation-context-changed`で探索結果を破棄する。

`static/recommendation-search.js`は既存のマス検索の画面コードと分離した。ファイル、カタログ、タームの変更とクリアでは探索結果を破棄し、リクエストを中断する。中断できなかった古い応答も世代番号で無視する。タブの切替ではファイルを保持し、再読み込みで破棄する。永続ストレージ、URL、履歴stateへ保存しない。CORSの設定は[既存の候補API](recommendation-api.md)と共通。

## 6. 根拠と拡張

学務規則は変更していない。2025年度入学・知能情報システムの卒業条件と配賦は`rules/niigata/engineering/smart-information-systems/2025/profile.json`、根拠ページは[規則確認記録](rule-verification-2025-sis.md)と[学務規則](academic-rules.md)に従う。探索はこの評価器の結果を比較するアプリケーション機能であり、新しい公式規則ではない。

別プログラムでは分類・要件プロファイルと公開カタログを追加する。卒業の教養セレクターを見て照合条件を選ぶため、現在の条件ID・単位数へ固定しない。将来の先修条件や履修計画の最適化は、この独立APIの効果計算と時間照合の上へ追加できる。
