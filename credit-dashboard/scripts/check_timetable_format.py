"""セル値をdecode・解析せず、CSVの構造記号だけをローカルで診断する。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


MAX_BYTES = 5 * 1024 * 1024
SYMBOLS = {34: "QUOTE", 44: "COMMA", 59: "SEMICOLON", 9: "TAB", 32: "SPACE",
           13: "CR", 10: "LF", 0: "NUL"}
BOMS = ((b"\xff\xfe\x00\x00", "utf-32-le", 4, True),
        (b"\x00\x00\xfe\xff", "utf-32-be", 4, False),
        (b"\xef\xbb\xbf", "utf-8-sig", 1, True),
        (b"\xff\xfe", "utf-16-le", 2, True), (b"\xfe\xff", "utf-16-be", 2, False))


def _structural_tokens(raw: bytes) -> tuple[str | None, list[str]]:
    """値に相当する全バイト／コード単位を同じOTHERへ写す。文字列にはしない。"""
    mark = next((item for item in BOMS if raw.startswith(item[0])), None)
    if mark is None:
        return None, [SYMBOLS.get(byte, "OTHER") for byte in raw]
    prefix, encoding, width, little = mark
    patterns = {
        bytes([symbol]) + bytes(width - 1) if little else bytes(width - 1) + bytes([symbol]): token
        for symbol, token in SYMBOLS.items()
    }
    body = raw[len(prefix):]
    return encoding, [patterns.get(body[index:index + width], "OTHER")
                      for index in range(0, len(body), width)]


def _scan(tokens: list[str], *, delimiter: str = "COMMA", allow_padding: bool = False) -> dict:
    state, line, record, field = "START", 1, 1, 1
    records, max_columns, padding_regions = 0, 0, 0
    index = 0
    result = {"readable": False, "records_read": 0, "max_columns": 0,
              "physical_error_line": None, "record_number": None, "field_number": None,
              "error_kind": None, "following_token_class": None, "padding_regions": 0}
    previous_cr = False
    while index < len(tokens):
        token = tokens[index]
        if previous_cr and token == "LF":
            previous_cr = False
            index += 1
            continue
        previous_cr = token == "CR"
        newline = token in {"CR", "LF"}
        if state == "QUOTED":
            if token == "QUOTE":
                state = "CLOSED"
        elif state == "CLOSED":
            if token == "QUOTE":
                state = "QUOTED"
            elif token == delimiter:
                state, field = "START", field + 1
            elif newline:
                records += 1
                max_columns = max(max_columns, field)
                record, field, state = record + 1, 1, "START"
            else:
                end = index
                if allow_padding and token in {"SPACE", "TAB"}:
                    while end < len(tokens) and tokens[end] in {"SPACE", "TAB"}:
                        end += 1
                    if end == len(tokens) or tokens[end] in {delimiter, "CR", "LF"}:
                        padding_regions += 1
                        index = end
                        continue
                result.update(physical_error_line=line, record_number=record, field_number=field,
                              error_kind="characters_after_quote", following_token_class=token)
                break
        elif token == delimiter:
            state, field = "START", field + 1
        elif newline:
            records += 1
            max_columns = max(max_columns, field)
            record, field, state = record + 1, 1, "START"
        elif state == "START":
            state = "QUOTED" if token == "QUOTE" else "UNQUOTED"
        if newline:
            line += 1
        index += 1
    else:
        if state == "QUOTED":
            result.update(physical_error_line=line, record_number=record, field_number=field,
                          error_kind="unclosed_quote")
        else:
            if state != "START" or field > 1:
                records += 1
                max_columns = max(max_columns, field)
            result["readable"] = True
    result.update(records_read=records, max_columns=max_columns, padding_regions=padding_regions)
    return result


def diagnose(raw: bytes) -> dict:
    """出力は構造の件数・固定ラベルだけ。セル値・ファイル名は返さない。"""
    result = {"size_bytes": len(raw), "values_decoded": False, "cell_values_parsed": False,
              "bom": None, "newline_counts": None, "contains_nul": None, "readers": {}}
    if not raw or len(raw) > MAX_BYTES:
        result["input_status"] = "empty" if not raw else "too_large"
        return result
    bom, tokens = _structural_tokens(raw)
    result["bom"] = bom
    result["input_status"] = "structure_examined"
    crlf = sum(a == "CR" and b == "LF" for a, b in zip(tokens, tokens[1:]))
    result["newline_counts"] = {"crlf": crlf, "lf_only": tokens.count("LF") - crlf,
                                "cr_only": tokens.count("CR") - crlf}
    result["contains_nul"] = "NUL" in tokens
    for name, options in [
        ("comma_strict", {}),
        ("comma_with_quote_padding", {"allow_padding": True}),
        ("tab_strict", {"delimiter": "TAB"}),
        ("semicolon_strict", {"delimiter": "SEMICOLON"}),
    ]:
        result["readers"][name] = _scan(tokens, **options)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="元CSV、必要ならExcel保存後CSVも指定する")
    args = parser.parse_args()
    reports = []
    for number, path in enumerate(args.files, 1):
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            report = diagnose(raw)
        except Exception:
            report = {"input_status": "diagnostic_failed"}
        reports.append({"input_number": number, "format": report})
    print(json.dumps({"values_included": False, "files_modified": False, "reports": reports}, ensure_ascii=False))
    return 0 if all(item["format"]["input_status"] == "structure_examined" for item in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
