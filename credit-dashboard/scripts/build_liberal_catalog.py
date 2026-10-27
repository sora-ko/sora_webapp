"""公式公開PDFから推薦用データを生成する。学生データを入力しない。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalog_import import extract_offering_rows  # noqa: E402
from offering_catalog import build_catalog, build_compact_catalog  # noqa: E402


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def json_digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_summary(folder: Path, config: dict, report: dict) -> None:
    target = config["target_profile"]
    pool, selected = report["pool"], report["selected"]
    rows = [f'# {config["academic_year"]}年度・簡易教養カタログと曜限調査', "",
            f'- 分類プロファイル：{target["program"]}・{target["admission_year"]}年度入学。候補は学生の学年で絞り込まない。',
            '- 入力条件：全学部向け。単純な学年指定は候補の除外に使わない。特定学部・分野・クラス指定、再履修・優先等の複雑な条件は採用しない。',
            '- 番号0・集中・不明曜限・オンデマンドの既存除外は維持。月〜金1〜5限の範囲に全曜限が収まる科目だけ。',
            f'- 元候補：{pool["course_count"]}件 → 採用：{selected["course_count"]}件。',
            f'- 元候補と採用後の時間網羅率：いずれも100枠中{selected["covered_slots"]}枠。元にない候補を補完しない。',
            '- ターム×時限の20組は曜日をまとめた値。曜日別の100枠と区別する。', "",
            '| ターム | 候補がある枠 /25 | 1限 | 2限 | 3限 | 4限 | 5限 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for term in range(1, 5):
        key = str(term)
        total = sum(value > 0 for row in pool["matrices"][key] for value in row)
        counts = ' | '.join(str(value) for value in pool["term_period_counts"][key])
        rows.append(f'| 第{term}ターム | {total} | {counts} |')
    day_names = {1: '月', 2: '火', 3: '水', 4: '木', 5: '金'}
    rows.extend(['', '## 候補のない枠', ''])
    rows.extend(f'- 第{slot["term"]}ターム {day_names[slot["weekday"]]}曜{slot["period"]}限' for slot in pool['missing_slots'])
    rows.extend(['', '## 曜日別の元候補数（減らす前）', ''])
    for term in range(1, 5):
        rows.extend([f'### 第{term}ターム', '', '| 時限 | 月 | 火 | 水 | 木 | 金 |', '| --- | ---: | ---: | ---: | ---: | ---: |'])
        rows.extend(f'| {period}限 | ' + ' | '.join(str(value) for value in counts) + ' |'
                    for period, counts in enumerate(pool['matrices'][str(term)], 1))
        rows.append('')
    rows.extend(['## 読むファイルと残る制約', '',
                 '- 利用するJSONは`liberal-catalog.json`の1つ。科目ごとの出典・監査情報・空の概要は含めない。',
                 '- 元資料と来歴は`catalog_sources/`の年度設定、`sources/`、`raw-rows.json`、`extraction-audit.json`で管理する。',
                 '- 旧JSONは`archive/`へ保管し、完全削除しない。',
                 '- 代表選定は、元候補が持つ曜限とタームごとの大区分を保持する。最小件数の証明や推薦順位付けではない。',
                 '- 各曜日・時限で全科目区分が選べることや、同時履修・修得済み除外・先修条件・履修許可は保証しない。',
                 '- 複数曜限の科目はすべての曜日・時限が履修表と重ならないことを、推薦時に別途確認する。',
                 '- シラバスの授業概要・評価方法は未取得。推薦API・画面では学年を使わず指定枠の候補を表示する。', ''])
    (folder / "README.md").write_text("\n".join(rows), encoding="utf-8")


def archive_legacy(folder: Path, name: str) -> None:
    path = folder / name
    if not path.exists():
        return
    archived = folder / "archive" / name
    if archived.exists():
        archived = archived.with_name(archived.stem + '-' + hashlib.sha256(path.read_bytes()).hexdigest()[:12] + archived.suffix)
    if archived.exists():
        raise ValueError("旧版の退避先が既にあります。既存ファイルを上書きせず確認してください")
    archived.parent.mkdir(parents=True, exist_ok=True)
    path.rename(archived)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--download", action="store_true", help="年度別設定にある公式公開PDFを取得する")
    parser.add_argument("--extract-only", action="store_true", help="PDFのセル抽出と完全性照合まで行う")
    parser.add_argument("--reuse-extraction", action="store_true", help="同じSHA256のPDFから抽出済みのセルを再利用する")
    args = parser.parse_args()
    config = json.loads((ROOT / "catalog_sources" / f"niigata-{args.year}.json").read_text(encoding="utf-8"))
    folder = ROOT / "data" / "recommendations" / str(args.year)
    pdf_path = folder / "sources" / "course-offerings.pdf"
    source = config["source"]
    if args.download:
        with urlopen(source["url"], timeout=45) as response:
            raw = response.read(30_000_001)
        if not raw.startswith(b"%PDF-") or len(raw) > 30_000_000:
            raise ValueError("取得した資料が対応するPDFではないか、サイズ上限を超えています")
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(raw)
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    reuse_extraction = args.reuse_extraction or (not args.extract_only
        and (folder / "raw-rows.json").exists() and (folder / "extraction-audit.json").exists())
    if reuse_extraction:
        records = json.loads((folder / "raw-rows.json").read_text(encoding="utf-8"))
        audit = json.loads((folder / "extraction-audit.json").read_text(encoding="utf-8"))
        if audit["source_sha256"] != digest:
            raise ValueError("PDFが変わっているため、セルの抽出をやり直してください")
        if audit.get("raw_rows_sha256") != json_digest(records) or audit["extracted_rows"] != len(records):
            raise ValueError("抽出セルの整合確認ができません。セルの抽出をやり直してください")
        first, last = source["main_table_pdf_pages"]
        if [page["pdf_page"] for page in audit["pages"]] != list(range(first, last + 1)) or any(
            row["source"]["document_id"] != source["document_id"]
            or row["source"]["printed_page"] != row["source"]["pdf_page"] + source["printed_page_offset"]
            for row in records
        ):
            raise ValueError("出典の版・ページ対応が変わっています。セルの抽出をやり直してください")
    else:
        records, audit = extract_offering_rows(pdf_path, source,
            progress=lambda page, last, count: print(f"PDF {page}/{last}: {count} rows", flush=True))
        audit["source_sha256"] = digest
        audit["raw_rows_sha256"] = json_digest(records)
        write_json(folder / "raw-rows.json", records)
        write_json(folder / "extraction-audit.json", audit)
    if not audit["coverage_matches"]:
        raise ValueError("Gコードの本文照合に不一致があります。extraction-audit.jsonを確認してください")
    print(json.dumps({"extracted_rows": len(records), "coverage_matches": True}, ensure_ascii=False))
    if not args.extract_only:
        catalog, target, quality = build_catalog(records, config, digest)
        compact_catalog, report = build_compact_catalog(catalog, config)
        current = folder / "liberal-catalog.json"
        if current.exists() and json.loads(current.read_text(encoding="utf-8")).get("schema_version") in {1, 2}:
            archive_legacy(folder, "liberal-catalog.json")
        for name in ["sis-year2-candidates.json", "quality-report.json"]:
            if Path(name).name != name or not name.endswith(".json"):
                raise ValueError("旧版ファイル名はフォルダーを含まないJSON名を指定してください")
            archive_legacy(folder, name)
        write_json(current, compact_catalog)
        write_summary(folder, config, report)
        print(json.dumps({"common_candidates": report["pool"]["course_count"],
                          "selected_courses": len(compact_catalog["courses"]),
                          "covered_slots": report["selected"]["covered_slots"], "total_slots": 100}, ensure_ascii=False))


if __name__ == "__main__":
    main()
