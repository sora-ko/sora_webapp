# 単位取得状況 MVP

成績CSVをブラウザーからアップロードし、バックエンドのメモリ上で解析して区分別集計を表示します。CSV原本はファイル、一時領域、データベースへ保存しません。

MVPの対象は、新潟大学工学部・2025年度入学・現在2年次・知能情報システムプログラム所属の学生本人です。進級・卒業要件との比較とログインはまだ実装していません。

## 要件・設計文書

- [プロダクト要件](docs/requirements.md)
- [学務判定ルール](docs/academic-rules.md)
- [データ契約](docs/data-contract.md)
- [アーキテクチャ方針](docs/architecture.md)
- [テスト方針](docs/testing.md)
- [開発ロードマップ](docs/roadmap.md)
- [AIエージェント作業規約](AGENTS.md)

## 使用技術

- Python 3.12
- FastAPI / Uvicorn
- python-multipart（メモリ内ストリーミング解析）
- HTML / CSS / JavaScript
- pytest / httpx2（開発・APIテスト）

## WSL Ubuntu + Dockerで起動

WSL Ubuntu側で Docker Engine / Compose plugin が利用できることを確認してください（Docker Desktop の WSL 統合でも可）。このフォルダーで実行します。

```bash
docker compose up --build
```

ブラウザーで http://localhost:8000 を開き、手元のCSVを選択して「解析する」を押します。Dockerイメージには`data/`を含めず、コンテナーにも成績CSVをマウントしません。終了は`Ctrl+C`、バックグラウンド起動時は`docker compose down`です。

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

テストは架空データだけを使用し、プロジェクトの`data/`は読みません。

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## 解析ルールとAPI

- `POST /api/v1/reports`: `multipart/form-data`の`file`としてCSVを1つ送信します。上限は5 MiBです。
- `GET /api/healthz`: 稼働確認用です。
- UTF-8（BOMありを含む）とCP932に対応します。
- 学生情報の前置きと科目表の見出しを検出し、科目行数を固定せずファイル終端まで解析します。
- `合否=合`かつ単位数が確定した科目だけを取得済みに加算します。
- 合否空欄、未知の合否、または「合」でも単位数空欄の科目は未確定です。
- 認識できない科目区分を教養・専門へ推測で割り当てず、「不明」として警告します。
- レスポンスはschema version 2で、`curriculum`, `student`, `summary`, `courses`, `warnings`, `evaluations`を返します。
- 旧`GET /api/report`は固定CSVを読み込まず、HTTP 410を返します。

APIだけを確認する例:

```bash
curl -F 'file=@/path/to/grades.csv;type=text/csv' http://127.0.0.1:8000/api/v1/reports
```
