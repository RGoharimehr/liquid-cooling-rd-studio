from __future__ import annotations

import csv
import json
import re
import socket
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from pypdf import PdfReader

from .assistant import AssistantConfig, default_assistant_config
from .catalog import CATEGORY_ALIASES, FIELD_NAMES, KNOWN_CATEGORIES
from .catalog_tools import build_sqlite_database
from .dataset_pipeline import validate_rows


def _validate_pdf_path(pdf_path: str | Path) -> Path:
    """Cheap checks that run before anything expensive, so the first error a user
    sees is the one that actually applies to their command."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    if path.is_dir():
        raise ValueError(f"Expected a PDF file but got a directory: {path}")
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise ValueError(
                f"{path} is not a PDF. A datasheet URL that answers with an HTML "
                "consent wall is the usual cause; re-fetch it with 'dcef sync-catalogs'."
            )
    return path


def extract_pdf_text(pdf_path: str | Path, *, max_pages: int | None = None) -> str:
    path = _validate_pdf_path(pdf_path)
    reader = PdfReader(str(path))
    pages = reader.pages[: max_pages or len(reader.pages)]
    text = "\n\n".join((page.extract_text() or "").strip() for page in pages).strip()
    if not text:
        raise ValueError(f"No extractable text found in PDF: {path}")
    return text


def _chunk_text(text: str, *, max_chars: int = 12000) -> list[str]:
    chunks: list[str] = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, max_chars)
        if split_at <= 0:
            split_at = max_chars
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    return chunks


def _extract_json_payload(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise ValueError("Model response did not contain JSON")
    start = min(starts)
    end_object = text.rfind("}")
    end_array = text.rfind("]")
    end = max(end_object, end_array)
    if end <= start:
        raise ValueError("Model response did not contain complete JSON")
    return json.loads(text[start : end + 1])


def _pdf_prompt(text_chunk: str) -> str:
    return (
        "Convert the following PDF catalog text into structured JSON rows.\n"
        "Return JSON only. Use the exact schema keys below for every row.\n"
        "Only include rows that represent actual equipment items.\n"
        "Every field value must be a string; use an empty string when unknown.\n"
        "part_number is required. Use the manufacturer's ordering code or SKU when the "
        "document prints one. When it does not, use the vendor's product designation "
        "exactly as printed in this document. Never invent a code, and never copy an "
        "identifier from these instructions.\n"
        "Emit a row only for a component that can be ordered and that this document "
        "gives at least one number for: a capacity, a nominal or connection size, or a "
        "flow coefficient. Do not emit rows for system arrangements, piping topologies, "
        "application notes, accessories mentioned only in prose, or the document's own "
        "title or publication number.\n"
        "Do not guess numeric values. Leave a field empty rather than estimating it.\n"
        f"Schema keys: {FIELD_NAMES}\n"
        f"category must be exactly one of: {sorted(KNOWN_CATEGORIES)}\n"
        'Return an object like {"rows": [...]}.\n'
        f"PDF text:\n{text_chunk}"
    )


def _request_local_model(prompt: str, config: AssistantConfig) -> Any:
    if not config.local_endpoint or not config.local_model:
        raise ValueError("DCEF_LOCAL_AI_ENDPOINT and DCEF_LOCAL_AI_MODEL are required for PDF extraction")

    endpoint = config.local_endpoint.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if config.local_api_key:
        headers["Authorization"] = "Bearer " + config.local_api_key
        headers["X-API-Key"] = config.local_api_key

    if endpoint.endswith("/api/generate"):
        payload: dict[str, Any] = {
            "model": config.local_model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
        }
    else:
        payload = {
            "model": config.local_model,
            "messages": [
                {"role": "system", "content": "Return only JSON for the requested schema."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }

    req = Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(req, timeout=config.pdf_timeout_seconds) as resp:
            response_data = json.loads(resp.read().decode("utf-8"))
    except (TimeoutError, socket.timeout) as exc:
        raise ValueError(
            f"The local model at {endpoint} did not answer within "
            f"{config.pdf_timeout_seconds}s. Extraction is slow on a local model, and "
            "the first call also pays the cost of loading it into memory. Raise the "
            "limit with DCEF_PDF_AI_TIMEOUT_SECONDS, or shorten the job with "
            f"--max-pages. ({exc})"
        ) from exc
    except (URLError, json.JSONDecodeError) as exc:
        raise ValueError(f"Local model request failed: {exc}") from exc

    if isinstance(response_data, dict):
        if isinstance(response_data.get("response"), str):
            return _extract_json_payload(response_data["response"])
        if isinstance(response_data.get("message"), dict) and isinstance(response_data["message"].get("content"), str):
            return _extract_json_payload(response_data["message"]["content"])
        choices = response_data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return _extract_json_payload(message["content"])
        return response_data
    return response_data


def _normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _normalize_row(row: dict[str, Any]) -> dict[str, str]:
    normalized = {field: _normalize_value(row.get(field)) for field in FIELD_NAMES}
    normalized["verification_status"] = "unverified"
    category = normalized["category"].lower().replace(" ", "_").replace("-", "_")
    normalized["category"] = CATEGORY_ALIASES.get(category, category)
    normalized["component_subtype"] = normalized["component_subtype"].lower().replace(" ", "_")
    coeff = normalized["flow_coefficient_type"].lower()
    if coeff == "cv":
        normalized["flow_coefficient_type"] = "Cv"
    elif coeff == "kv":
        normalized["flow_coefficient_type"] = "Kv"
    return normalized


def _rows_from_payload(payload: Any) -> list[dict[str, str]]:
    rows_data = payload.get("rows") if isinstance(payload, dict) else payload
    if not isinstance(rows_data, list):
        raise ValueError("Model response must contain a rows list")
    rows: list[dict[str, str]] = []
    for item in rows_data:
        if isinstance(item, dict):
            rows.append(_normalize_row(item))
    return rows


def _merge_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    ordered: list[str] = []
    for row in rows:
        part_number = row.get("part_number", "").strip()
        key = part_number.lower() or json.dumps(row, sort_keys=True)
        if key not in merged:
            merged[key] = dict(row)
            ordered.append(key)
            continue
        current = merged[key]
        for field in FIELD_NAMES:
            if not current.get(field) and row.get(field):
                current[field] = row[field]
    return [merged[key] for key in ordered]


def extract_catalog_rows_from_pdf(
    pdf_path: str | Path,
    *,
    config: AssistantConfig | None = None,
    max_pages: int | None = None,
    max_chars_per_chunk: int = 12000,
) -> list[dict[str, str]]:
    cfg = config or default_assistant_config()
    # Validate the input before complaining about configuration: a mistyped filename
    # should say so, not send the user off to install a model they may already have.
    _validate_pdf_path(pdf_path)
    if not cfg.local_endpoint or not cfg.local_model:
        raise ValueError(
            "PDF extraction needs a local model. Set DCEF_LOCAL_AI_ENDPOINT and "
            "DCEF_LOCAL_AI_MODEL, for example:\n"
            "  export DCEF_LOCAL_AI_ENDPOINT=http://127.0.0.1:11434/api/generate\n"
            "  export DCEF_LOCAL_AI_MODEL=llama3.1"
        )
    text = extract_pdf_text(pdf_path, max_pages=max_pages)
    chunks = _chunk_text(text, max_chars=max_chars_per_chunk)
    rows: list[dict[str, str]] = []
    for chunk in chunks:
        payload = _request_local_model(_pdf_prompt(chunk), cfg)
        rows.extend(_rows_from_payload(payload))
    return _merge_rows(rows)


def _partition_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Split an extraction into rows that pass validation and rows that do not.

    Extraction is a draft-producing step. Discarding a whole document because one row
    is unusable loses the good rows and shows the user nothing to correct.
    """
    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, Any]] = []
    for row in rows:
        problems = validate_rows([row])
        if problems:
            reasons = [re.sub(r"^row \d+: ", "", problem) for problem in problems]
            rejected.append({"row": row, "reasons": reasons})
        else:
            accepted.append(row)
    # Re-check the accepted set as a whole to catch duplicates between rows.
    duplicate_errors = validate_rows(accepted)
    if duplicate_errors:
        seen: set[str] = set()
        deduped: list[dict[str, str]] = []
        for row in accepted:
            key = row.get("part_number", "").strip().lower()
            if key in seen:
                rejected.append({"row": row, "reasons": [f"duplicate part_number {row.get('part_number')}"]})
                continue
            seen.add(key)
            deduped.append(row)
        accepted = deduped
    return accepted, rejected


def write_catalog_csv(rows: list[dict[str, str]], csv_path: str | Path) -> Path:
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELD_NAMES)
        writer.writeheader()
        writer.writerows(rows)
    return path


def build_database_from_pdf(
    pdf_path: str | Path,
    sqlite_path: str | Path,
    *,
    csv_path: str | Path | None = None,
    config: AssistantConfig | None = None,
    max_pages: int | None = None,
    max_chars_per_chunk: int = 12000,
    strict: bool = False,
) -> dict[str, Any]:
    extracted = extract_catalog_rows_from_pdf(
        pdf_path,
        config=config,
        max_pages=max_pages,
        max_chars_per_chunk=max_chars_per_chunk,
    )
    # The command knows which document it read; the model should not have to report
    # it, and "www.boydcorp.com" is not a citation.
    source_name = Path(pdf_path).name
    document_tokens = {
        Path(pdf_path).stem.lower(),
        Path(pdf_path).stem.split("_", 1)[-1].lower(),
    }
    for row in extracted:
        if not row.get("source_catalog", "").strip():
            row["source_catalog"] = source_name
        # A catalog's own publication number reads like a part number; it is not one.
        if row.get("part_number", "").strip().lower() in document_tokens:
            row["part_number"] = ""

    rows, rejected = _partition_rows(extracted)

    if strict and rejected:
        detail = "\n".join(
            f"- {'; '.join(item['reasons'])}" for item in rejected[:20]
        )
        raise ValueError(f"Extracted PDF rows failed validation:\n{detail}")
    if not rows:
        detail = "\n".join(f"- {'; '.join(item['reasons'])}" for item in rejected[:20])
        raise ValueError(
            f"No usable rows were extracted from {Path(pdf_path)}."
            + (f" Rejected {len(rejected)}:\n{detail}" if rejected else "")
        )

    temp_csv: Path | None = None
    target_csv: Path
    if csv_path is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="dcef-pdf-", dir="/tmp"))
        temp_csv = temp_dir / "catalog_from_pdf.csv"
        target_csv = temp_csv
    else:
        target_csv = Path(csv_path)

    write_catalog_csv(rows, target_csv)
    row_count = build_sqlite_database(target_csv, sqlite_path)

    rejected_path: Path | None = None
    if rejected:
        # Keep what the model produced so the user can correct it rather than
        # re-running the extraction blind.
        rejected_path = target_csv.with_suffix(".rejected.json")
        rejected_path.write_text(json.dumps(rejected, indent=2), encoding="utf-8")

    return {
        "pdf_path": str(Path(pdf_path)),
        "csv_path": str(target_csv),
        "sqlite_path": str(Path(sqlite_path)),
        "rows": row_count,
        "rejected": len(rejected),
        "rejected_path": str(rejected_path) if rejected_path else None,
        "used_temporary_csv": temp_csv is not None,
    }
