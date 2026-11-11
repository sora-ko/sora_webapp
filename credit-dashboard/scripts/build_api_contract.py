"""静的API契約を再生成、または--checkで実装とのずれを確認する。利用者CSVは受け付けない。"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from api_contracts.examples import collect_examples
from api_contracts.models import RESPONSE_MODELS
from api_contracts.specification import CONTRACT_VERSION, json_schemas, openapi_document, response_schema
from api_contracts.typescript import typescript_declarations


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


async def build_artifacts() -> dict[str, str]:
    schemas = json_schemas()
    Draft202012Validator.check_schema(schemas)
    validators = {name: Draft202012Validator(response_schema(name, schemas)) for name in RESPONSE_MODELS}
    document = openapi_document(schemas)
    artifacts = {}
    entries = []
    for example in await collect_examples():
        # 検証失敗時も入力値・CSV・応答本文は出力しない。
        try:
            RESPONSE_MODELS[example.model].model_validate(example.body)
        except ValidationError as error:
            locations = [".".join(map(str, item["loc"])) for item in error.errors(include_input=False, include_url=False)]
            raise ValueError("Contract mismatch in fictional example " + example.name + ": " + ", ".join(locations)) from None
        errors = list(validators[example.model].iter_errors(example.body))
        if errors:
            locations = [".".join(map(str, error.absolute_path)) for error in errors]
            raise ValueError("JSON Schema mismatch in fictional example " + example.name + ": " + ", ".join(locations))
        relative = "examples/" + example.name + ".json"
        artifacts[relative] = _json(example.body)
        entries.append({"name": example.name, "method": example.method, "path": example.path,
                        "status": example.status, "model": example.model, "file": relative})
        operation = document["paths"].get(example.path, {}).get(example.method.lower())
        if operation:
            response = operation["responses"].get(str(example.status), operation["responses"]["default"])
            media = response["content"]["application/json"]
            if "examples" not in media:
                media["examples"] = {example.name: {"summary": "固定の架空入力に対する応答例", "value": example.body}}
    artifacts["examples/index.json"] = _json({
        "contract_version": CONTRACT_VERSION,
        "synthetic_data_only": True,
        "description": "固定の架空CSV・メモリ生成データとローカルASGI応答だけから生成。利用者CSVは含めない。",
        "examples": entries,
    })
    artifacts["schemas.json"] = _json(schemas)
    artifacts["openapi.json"] = _json(document)
    artifacts["api.d.ts"] = typescript_declarations(schemas)
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="生成せずに、契約ファイルと現行APIの一致を確認する")
    args = parser.parse_args()
    try:
        artifacts = asyncio.run(build_artifacts())
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    destination = ROOT / "contracts"
    mismatches = []
    for relative, contents in artifacts.items():
        target = destination / relative
        if args.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != contents:
                mismatches.append(relative)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8", newline="\n")
    extra_examples = sorted(path.relative_to(destination).as_posix() for path in (destination / "examples").glob("*.json")
                            if path.relative_to(destination).as_posix() not in artifacts)
    if mismatches or extra_examples:
        print("API契約に差分があります（本文・学生情報は出力しません）。", file=sys.stderr)
        for path in mismatches + extra_examples:
            print(path, file=sys.stderr)
        return 1
    print(f"API contract {'checked' if args.check else 'generated'}: {len(artifacts)} files, "
          f"{len(artifacts) - 4} fictional HTTP examples.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
