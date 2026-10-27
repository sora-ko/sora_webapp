# 分業・データ引き継ぎ手順

更新日: 2026-10-27。Gitにはアプリケーション、規則プロファイル、生成コード、自動テスト、文書を置く。推薦用生成データと架空CSVは手渡しZIPで渡す。実在する学生の成績CSV・履修表CSVはどちらにも含めない。

## 1. 現在利用できる範囲

- 2025年度入学・知能情報システムの規則で、CSV解析、単位集計、第2・第4年次進級と卒業の三値判定、個別必修16科目の確認を行う。
- 同じ規則の1年生は第2年次進級＋卒業、2・3年生は第4年次進級＋卒業、4年以上は卒業を表示する。留年・編入なし、在学期間と学年が一致する前提。
- 2026年度の代表63開講で、教養の曜限検索と、修得単位・空き時間からの探索を行う。推薦は学年で絞らない。教養条件がすべて充足していれば、専門だけの不足では推薦しない。
- CSVと解析結果はサーバー・ブラウザーのメモリだけで扱い、保存・セッション・ログインは実装しない。

## 2. 手渡しZIPの内容

ZIP名は`credit-dashboard-handoff-2026-10-27.zip`。作成側ではGit対象外の`handoff/`に置く。展開先はGitリポジトリのルートではなく、`compose.yaml`・`server.py`がある`credit-dashboard/`ディレクトリとする。

| ZIP内の相対パス | 用途 |
| --- | --- |
| `data/recommendations/2026/liberal-catalog.json` | 実行に必要なカタログ。schema version 3、63開講 |
| `data/recommendations/2026/README.md` | 85/100枠のカバー範囲と候補がない15枠の調査結果 |
| `data/recommendations/2026/sources/course-offerings.pdf` | 公開の公式開設一覧。オフライン再生成用 |
| `data/recommendations/2026/raw-rows.json` | 公開表の抽出済みセル。再生成用 |
| `data/recommendations/2026/extraction-audit.json` | PDF・抽出セルのハッシュとページ別照合。再生成用 |
| `examples/first-year-sample.csv` | 架空の1年生。34単位、第2年次進級`satisfied` |
| `examples/graduation-sample.csv` | 架空の卒業確認用簡略版。124単位、卒業`satisfied` |
| `examples/graduation-sample-original-format.csv` | 上記と同じ科目構成のCP932・19列版。卒業`satisfied` |
| `handoff/README.md`・`manifest.json`・`SHA256SUMS` | 展開手順、コードの対応リビジョン、同梱ファイルのSHA256 |

旧版カタログ、画像、仮想環境、キャッシュ、実際の学生CSVは同梱しない。実行時に必要な推薦データはJSON1ファイルだけで、公開PDF・抽出結果は生成作業用である。PDFに記載された公開の教員情報は学生データとは区別する。

## 3. 復元と起動

1. 更新されたGitのコードを取得する。ZIPの`handoff/manifest.json`に対応する`source_commit`を記録するので、組み合わせるコードを確認する。
2. `credit-dashboard/`へ移動し、ZIPを展開する。既に独自データがある場合は別の作業コピーで検証し、無断で上書きしない。

```bash
cd credit-dashboard
python3 -m zipfile -e /path/to/credit-dashboard-handoff-2026-10-27.zip .
sha256sum -c handoff/SHA256SUMS
docker compose up --build
```

`http://localhost:8000`で利用する。Composeは生成済みJSONの存在を前提とし、未配置なら起動に失敗する。学生CSVをサーバーのフォルダーへ置く必要はなく、ブラウザーから毎回選択する。

Dockerを使わない場合はPython 3.12で次を実行する。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python server.py
```

架空CSV3点は一部の自動テストも利用するため、テスト前に復元する。期待値は[サンプル説明](../examples/README.md)。公開資料の抽出キャッシュが復元されていれば、次でネットワーク取得なしに同じ簡易JSONを再生成できる。

```bash
.venv/bin/python scripts/build_liberal_catalog.py
```

PDFを再抽出するときだけ`requirements-catalog.txt`が必要になる。新規取得・年度更新は[カタログ生成手順](liberal-catalog.md)を参照する。ZIPを再作成する際も同梱パスを明示し、`data/`全体をまとめない。

## 4. フロントエンドとの契約

| API | 入力・目的 | 応答schema | 正本の仕様 |
| --- | --- | --- | --- |
| `GET /api/healthz` | 稼働確認 | バージョン項目なし | `server.py` |
| `GET /api/v1/rule-profiles` | 規則・対象範囲の一覧 | バージョン項目なし | [データ契約](data-contract.md) |
| `POST /api/v1/reports` | `file`、`profile_id`、任意`residence_years`。成績集計・判定 | 2 | [データ契約](data-contract.md) |
| `POST /api/v1/timetables` | `file`。履修表と表示可能な年度・ターム | 1 | [履修表契約](timetable-csv.md) |
| `GET /api/v1/recommendation-catalogs` | 対応する開講年度・プロファイル | 1 | [候補API](recommendation-api.md) |
| `POST /api/v1/recommendations` | 年度・ターム・曜日・時限、任意の履修表`file`。マスの候補閲覧 | 1 | [候補API](recommendation-api.md) |
| `POST /api/v1/recommendation-searches` | 年度・ターム、`grades_file`と`timetable_file`。教養不足の探索 | 1 | [単位照合API](recommendation-search-api.md) |

CSVは`multipart/form-data`で送る。レポートID、Cookie、事前の解析API呼出しは不要で、各APIが元CSVを再検証する。1ファイル5 MiB、探索は2ファイルで合計10 MiB＋multipart用64 KiB。エラーは`error.code`・日本語`error.message`、必要に応じて`error.details`を返す。全応答は`Cache-Control: no-store`。

フロントエンドは入力・表示・メモリ上の状態管理を担当し、CSV分類・単位配賦・学務判定・推薦効果・時間重複はバックエンドに任せる。未知値と未充足を区別し、配列が空という理由だけで履修不可と表示しない。元Fileと結果を同じアプリのメモリで共有し、ファイル・プロファイル・対象タームの変更で古い結果を無効にする。

別ポートでの開発は`/api`をプロキシするか、バックエンドの環境変数`CORS_ALLOWED_ORIGINS`に実際のOriginをカンマ区切りで設定する。例は`http://localhost:5173,http://127.0.0.1:5173`。Composeにも同じ変数を渡せる。ワイルドカードとCookie認証は使わない。

参考UIは置き換えてよい。`static/recommendation-api.js`はDOMに依存しない通信クライアントだが、その他の画面JSには内部依存が残る。機械可読な応答スキーマ・型は今後整備するため、現段階は上記MarkdownとAPIテストを契約にする。

## 5. 既知の制約と次の作業

推薦は公開資料から選んだ教養の代表例であり、全科目、全不足枠、履修許可を保証しない。集中講義・時限未定・複雑な聴講指定等は除外し、先修条件、順位付け、候補同士の組合せ計画は未実装。学務判定は参考情報で、公式判定を代替しない。

別年度・プログラムへ展開するときは、既存規則を上書きせず追加する。分類体系・進級節目・配賦エンジンの制約は[規則データ設計](rule-data.md#8-現行スキーマ評価器の拡張上の制約)、未修正のレビュー指摘は[バックログ](backlog.md)へ残している。現行MVPの分業は、これらの制約とAPI契約を共有したうえで開始できる。
