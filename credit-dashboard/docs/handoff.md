# 分業・データ引き継ぎ手順

更新日: 2026-10-28。Gitにはアプリケーション、規則プロファイル、生成コード、自動テスト、文書に加え、起動用の公開カタログと確認済みの架空CSVを置く。クローン後の起動に手渡しZIPは不要。実在する学生の成績CSV・履修表CSVは含めない。

2026-10-28追記：この文書とAPI仕様から別の試作UIを作成した。画面は`/prototype/`、参照した資料・不足していた契約項目・検証方法は[試作フロントエンドの記録](prototype-handoff-test.md)にまとめる。

## 1. 現在利用できる範囲

- 2025年度入学・知能情報システムの規則で、CSV解析、単位集計、第2・第4年次進級と卒業の三値判定、個別必修16科目の確認を行う。
- 同じ規則の1年生は第2年次進級＋卒業、2・3年生は第4年次進級＋卒業、4年以上は卒業を表示する。留年・編入なし、在学期間と学年が一致する前提。
- 2026年度の代表63開講で、教養の曜限検索と、修得単位・空き時間からの探索を行う。推薦は学年で絞らない。教養条件がすべて充足していれば、専門だけの不足では推薦しない。
- CSVと解析結果はサーバー・ブラウザーのメモリだけで扱い、保存・セッション・ログインは実装しない。

## 2. Gitで共有するデータ

2026-10-28の利用者指定により、次の5ファイルをGitへ追加した。通常のCSVや`data/`全体を許可せず、`.gitignore`の許可リストで共有対象を限定する。

| プロジェクト内の相対パス | 用途 |
| --- | --- |
| `data/recommendations/2026/liberal-catalog.json` | 実行に必要なカタログ。schema version 3、63開講 |
| `data/recommendations/2026/README.md` | 85/100枠のカバー範囲と候補がない15枠の調査結果 |
| `examples/first-year-sample.csv` | 架空の1年生。34単位、第2年次進級`satisfied` |
| `examples/graduation-sample.csv` | 架空の卒業確認用簡略版。124単位、卒業`satisfied` |
| `examples/graduation-sample-original-format.csv` | 上記と同じ科目構成のCP932・19列版。卒業`satisfied` |

カタログには開講番号・科目名・単位・区分・ターム・曜限だけを含み、学生情報・教員情報・成績を含めない。サンプルの氏名・在籍番号・教員・成績は架空であり、実在する学生CSVから転記していない。`.gitattributes`でサンプルの文字コード・改行を保持する。

元PDF・抽出セル・監査結果・旧版・画像・旧手渡しZIPはローカルに保持し、Git対象外を維持する。公開PDFや抽出セルに含まれる教員名も配布用ファイルへ含めない。これらは起動・通常テストには不要で、再生成する開発者が必要時に公式原本を取得する。旧ZIPは以前のコード向けのため、新しいクローンへ展開しない。

## 3. クローンと起動

Docker Engine / Compose pluginが利用できる環境で、次を実行する。カタログの別途配置・ZIP展開・PDF解析依存のインストールは不要である。初回のDockerビルドではベースイメージとPython依存を取得するネットワーク接続が必要。

```bash
git clone https://github.com/sora-ko/sora_webapp.git
cd sora_webapp/credit-dashboard
docker compose up --build
```

`http://localhost:8000/prototype/`で試作画面、`http://localhost:8000/`で従来画面を利用する。CSVなしの教養候補閲覧も利用できる。成績集計の確認には、ブラウザーから`examples/first-year-sample.csv`または`examples/graduation-sample-original-format.csv`を選択する。学生CSVをサーバーのフォルダーへ置く必要はなく、実データを使う場合もブラウザーから毎回選択する。

Dockerを使わない場合はPython 3.12で次を実行する。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python server.py
```

架空CSV3点は一部の自動テストも利用する。期待値は[サンプル説明](../examples/README.md)。再生成作業だけを行う場合は、次で開発専用依存と公式原本を取得する。

```bash
.venv/bin/python -m pip install -r requirements-catalog.txt
.venv/bin/python scripts/build_liberal_catalog.py --download
```

原本と有効な抽出キャッシュが既にローカルにある場合は`--download`なしで再生成できる。新規取得・年度更新は[カタログ生成手順](liberal-catalog.md)を参照する。新しい年度・サンプルをGitへ追加するときも個人情報を確認し、許可するファイルを明示する。

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

対象プログラムは単位集計側で一度だけ選び、公開プロファイル情報をメモリで共有する。教養候補側は対象名を表示し、候補閲覧と不足探索に同じ`profile_id`を渡す。解析済み履修表の選択年度に対応するカタログを使い、未解析なら同一プロファイルの最新年度を明示する。対象や年度に対応するデータがなければ案内し、別の対象へ代替しない。APIの入力・JSON形式は従来どおり。

別ポートでの開発は`/api`をプロキシするか、バックエンドの環境変数`CORS_ALLOWED_ORIGINS`に実際のOriginをカンマ区切りで設定する。例は`http://localhost:5173,http://127.0.0.1:5173`。Composeにも同じ変数を渡せる。ワイルドカードとCookie認証は使わない。

参考UIは置き換えてよい。`static/recommendation-api.js`はDOMに依存しない通信クライアントだが、その他の画面JSには内部依存が残る。機械可読な応答スキーマ・型は今後整備するため、現段階は上記MarkdownとAPIテストを契約にする。

## 5. 既知の制約と次の作業

推薦は公開資料から選んだ教養の代表例であり、全科目、全不足枠、履修許可を保証しない。集中講義・時限未定・複雑な聴講指定等は除外し、先修条件、順位付け、候補同士の組合せ計画は未実装。学務判定は参考情報で、公式判定を代替しない。

別年度・プログラムへ展開するときは、既存規則を上書きせず追加する。分類体系・進級節目・配賦エンジンの制約は[規則データ設計](rule-data.md#8-現行スキーマ評価器の拡張上の制約)、未修正のレビュー指摘は[バックログ](backlog.md)へ残している。現行MVPの分業は、これらの制約とAPI契約を共有したうえで開始できる。
