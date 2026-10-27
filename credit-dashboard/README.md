# 単位取得状況 MVP

更新日: 2026-10-27。共同開発者は[引き継ぎ・初回起動手順](docs/handoff.md)から確認してください。

成績CSVをブラウザーからアップロードし、バックエンドのメモリ上で解析して区分別集計を表示します。CSV原本はファイル、一時領域、データベースへ保存しません。

MVPの対象は、新潟大学工学部・2025年度入学・知能情報システムプログラム所属の学生本人です。CSVの学年に応じて第2年次進級、第4年次進級、卒業資格の進捗を参考情報として表示します。卒業は単位合計に加え、専門系必修16科目を個別に確認します。全条件を満たせば`satisfied`、確定した不足があれば`not_satisfied`、未確定情報が結論へ影響する場合は`unknown`にします。ログインはまだ実装していません。

## 要件・設計文書

- [プロダクト要件](docs/requirements.md)
- [学務判定ルール](docs/academic-rules.md)
- [2025年度・知能情報システムプログラム 学務規則検証記録](docs/rule-verification-2025-sis.md)
- [データ契約](docs/data-contract.md)
- [履修表CSVの読み取り仕様](docs/timetable-csv.md)
- [教養推薦の設計メモ](docs/recommendation-design.md)
- [教養開講カタログ・生成手順](docs/liberal-catalog.md)
- [教養候補API・フロントエンド接続](docs/recommendation-api.md)
- [修得単位と空き時間からの教養探索API](docs/recommendation-search-api.md)
- [分業・手渡しZIPの復元手順](docs/handoff.md)
- [アーキテクチャ方針](docs/architecture.md)
- [学務規則データ設計](docs/rule-data.md)
- [テスト方針](docs/testing.md)
- [開発ロードマップ](docs/roadmap.md)
- [実装バックログ](docs/backlog.md)
- [AIエージェント作業規約](AGENTS.md)

## 使用技術

- Python 3.12
- FastAPI / Uvicorn
- python-multipart（メモリ内ストリーミング解析）
- HTML / CSS / JavaScript
- pytest / httpx2（開発・APIテスト）
- JSON形式の年度別学務規則プロファイル（実行時検証はPython標準ライブラリ）

## WSL Ubuntu + Dockerで起動

WSL Ubuntu側で Docker Engine / Compose plugin が利用できることを確認してください（Docker Desktop の WSL 統合でも可）。Composeは公開の簡易JSONを読み取り専用で使います。新しいcloneでは先に[手渡しZIPを復元](docs/handoff.md)するか、下記「推薦用の教養開講データ」の手順で`data/recommendations/2026/liberal-catalog.json`を生成・配置してください。このフォルダーで実行します。

```bash
docker compose up --build
```

ブラウザーで http://localhost:8000 を開き、「単位集計」で成績CSVを選択して「解析する」を押します。「時間割と教養候補」では履修照会CSVをアップロードし、時間割のマスをクリックすると、その枠を含む教養候補を確認できます。他の曜限との重複もバックエンドで除外します。「CSVなしで候補を見る」なら、登録済み授業との重複を未確認と明示してカタログを閲覧できます。不足単位による順位付けはまだ実装していません。

両タブの入力と結果はメモリだけに保持し、タブ切替では残り、各画面の「クリア」またはページ再読込で破棄します。画面はフロントエンド担当が置き換えられる参考UIです。変更が表示されない場合は再ビルド後にページを再読込してください。

Dockerイメージには`data/`を含めず、公開の簡易JSON1ファイルだけを読み取り専用でマウントします。学生CSVはマウント・保存しません。終了は`Ctrl+C`、バックグラウンド起動時は`docker compose down`です。

## Dockerを使わず確認

Python 3.12で仮想環境を作り、依存パッケージをインストールします。

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python server.py
```

ブラウザーで http://localhost:8000 を開きます。既定では`127.0.0.1`だけで待ち受けます。

## テスト

テストは架空データだけを使用し、プロジェクトの`data/`は読みません。`examples/`のCSV3点はGit対象外で、一部のテストに必要です。初回は[手渡しZIP](docs/handoff.md)から復元してください。

ブラウザーでの手動確認には、実在する学生情報を含まない[`examples/first-year-sample.csv`](examples/first-year-sample.csv)を使用できます。卒業確認には、元CSVと同じ前置き4行・19列・CP932・CRLF形式の[`examples/graduation-sample-original-format.csv`](examples/graduation-sample-original-format.csv)を使用してください。期待結果は[`examples/README.md`](examples/README.md)に記載しています。

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

稼働中のlocalhostに架空CSVを送る32ケースの確認も実行できます。CSVや応答本文は保存せず、外部ホストへは送信しません。

```bash
.venv/bin/python scripts/check_localhost_uploads.py
```

確認範囲と結果は[アップロード確認記録](docs/upload-check-2026-10-26.md)に記載しています。

履修表と集計の参考UIには、架空CSVだけを使うブラウザーテスト`scripts/check_frontend.cjs`もあります。実行には開発環境のPlaywrightとブラウザーが必要です。確認項目と実施結果は[テスト方針の参考UI節](docs/testing.md#12-参考uiのブラウザーテスト)を参照してください。

## 推薦用の教養開講データ

利用するデータは`data/recommendations/2026/liberal-catalog.json`の1つです。全学部向けの309開講から代表63開講へ絞り、学年で候補を変更しません。1科目は開講番号・科目名・単位数・区分・ターム・曜限の6項目です。曜日をまとめたターム×1〜5限の20通りには全て候補があり、曜日別では100枠中85枠に候補があります。指定枠の検索と履修表との重複除外をAPI・画面から利用できます。このマス検索では修得済み・不足単位・履修許可は未判定です。

別機能として、成績CSVと履修表CSVから「不足単位を補える教養を探す」を追加しました。単位集計タブで成績CSV、時間割タブで履修表CSVを選び、対象タームを指定して探索します。学年によらず卒業の単位条件を使い、同名の修得済み科目と全曜限の重複を除外し、1科目修得した場合の不足の変化を表示します。判定不能の不足は要確認の一覧へ分けます。[単位照合の探索API](docs/recommendation-search-api.md)を分業時の契約とします。履修許可や候補同士の同時履修計画は未判定です。

参考UIはデバッグ時に見渡しやすいよう、結果・科目の詳細を初期状態で折りたたみ、成績CSVと履修表CSVの読み込み欄だけは開いておきます。見出しまたは右端の「＋」をクリックすると開きます。キーボードでも見出しへ移動してEnterで開閉でき、開閉だけでは入力や解析結果を破棄しません。CSVが未選択でも不足単位の探索ボタンは押せるようにし、不足しているファイルと選択する場所を日本語で案内します。

不足単位の探索では、教養の必修・選択必修・選択・合計をすべて満たしていれば、専門や共通超過分・総計が不足していても教養を推薦しません。教養に不足が残る場合は、その教養条件を改善する科目だけを返します。時限を指定した候補閲覧と、成績集計の不足表示は従来どおり利用できます。

生成物と原本はGit・Docker対象外です。出典は科目JSONから外し、年度設定と原表で別管理します。旧JSONは`archive/`へ保持します。原本と抽出済みセルがある場合は`.venv/bin/python scripts/build_liberal_catalog.py`だけで再生成できます。共同開発者の初回取得は次のコマンドです。開発専用のPDF解析依存はWebアプリの実行環境には追加しません。

```bash
.venv/bin/python -m pip install -r requirements-catalog.txt
.venv/bin/python scripts/build_liberal_catalog.py --download
```

G以外の教養・特定学部向け・解釈できない受講条件は対象外です。公開シラバスは自動取得禁止設定のため巡回せず、授業概要・評価方法は簡易JSONに含めません。候補のない15枠と曜日別の件数は生成README、データ契約・再生成・制約は[教養開講カタログ](docs/liberal-catalog.md)を参照してください。

## 解析ルールとAPI

- `GET /api/v1/rule-profiles`: 利用可能な対象年度・プログラムと、実装済みの判定を取得します。
- `POST /api/v1/reports`: `multipart/form-data`の`file`としてCSVを1つ送信します。`profile_id`と任意の`residence_years`も指定できます。上限は5 MiBです。
- `POST /api/v1/timetables`: `file`として履修表CSVを送信し、年度・ターム別の占有時間と表示可能な期間を取得します。「時間割と教養候補」タブで結果を表示できます。開講番号のターム値0を占有時間から除外するMVP方針には注意事項があります。候補の取得には別の推薦APIを使います。
- `GET /api/healthz`: 稼働確認用です。
- `GET /api/v1/recommendation-catalogs`: 候補検索に対応する年度・プロファイルを取得します。候補検索で学年は使いません。
- `POST /api/v1/recommendation-searches`: 成績CSVと履修表CSVから、空き時間で卒業の不足単位を減らせる教養を探索します。
- `POST /api/v1/recommendations`: マスのターム・曜日・時限と、任意の履修表CSVを送って教養候補を取得します。別フロントへの接続方法とJSON契約は[候補API仕様](docs/recommendation-api.md)を参照してください。
- UTF-8（BOMありを含む）とCP932に対応します。
- 学生情報の前置きと科目表の見出しを検出し、科目行数を固定せずファイル終端まで解析します。
- `合否=合`かつ単位数が確定した科目だけを取得済みに加算します。
- 合否空欄、未知の合否、または「合」でも単位数空欄の科目は未確定です。
- 認識できない科目区分を教養・専門へ推測で割り当てず、「不明」として警告します。
- 1年生には第2年次進級と卒業、2・3年生には第4年次進級と卒業、4年生以上には卒業を表示します。
- 卒業資格条件では、工学部の教養系要件を公式区分ごとに全学年へ表示します。
- レスポンスはschema version 2で、`curriculum`, `student`, `summary`, `courses`, `warnings`, `evaluation_context`, `evaluations`を返します。
- 旧`GET /api/report`は固定CSVを読み込まず、HTTP 410を返します。

学務規則は`rules/niigata/engineering/smart-information-systems/2025/profile.json`へ年度・プログラム別データとして置きます。各条件は`satisfied`、`not_satisfied`、`unknown`の三値で表示します。MVPでは留年・編入がなく学年と在学年数が一致する前提で、在学期間の未入力時はCSVの学年を使用します。任意入力した値で上書きでき、学年も入力も得られなければ`unknown`です。専門・教養の共通6単位は両区分の最低単位超過分を合算して評価します。第4年次進級と卒業は表示条件がすべて充足なら`satisfied`になります。卒業条件の「専門系の個別必修科目」を開くと、各科目の修得・未修得・判定不能と確認理由を表示します。

別年度・別プログラムへ対応するときは既存プロファイルを上書きせず、新しい`profile.json`と対応する判定テストを追加します。画面の対象表示と分類処理は選択されたプロファイルから生成されます。

専門科目は、公式資料から整理した[`course-catalog.json`](rules/niigata/engineering/smart-information-systems/2025/course-catalog.json)の83科目（工学科共通・情報電子分野の導入科目を含む）へ照合します。CSVで専門系と分かる科目のうち一覧にないものは、利用者指定のMVP方針で教養の選択枠へ分類します。この扱いは大学の正式な他プログラム科目の取扱いとは異なり、画面にも明示します。

留学生向け代替規則と早期卒業は対象外とし、夜間主科目は含まれない前提です。他大学の単位認定は未対応で、既知の他大学単位ラベルだけを要件から除外します。開講コードが異なる行は、同名でも別科目として扱います。「工学リテラシー入門」は科目名の部分一致で判定し、分野名を区別しません。教養の選択必修10単位は、情報リテラシー（必修指定科目を除く）・自然系共通専門基礎・自然科学から集計します。

APIだけを確認する例:

```bash
curl \
  -F 'profile_id=niigata-engineering-sis-2025-v1' \
  -F 'residence_years=1' \
  -F 'file=@/path/to/grades.csv;type=text/csv' \
  http://127.0.0.1:8000/api/v1/reports
```
