from __future__ import annotations

import csv
import hashlib
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .catalog import FIELD_NAMES


def list_catalog_urls(csv_path: str | Path) -> list[str]:
    path = Path(csv_path)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        urls = {(row.get("datasheet_url") or "").strip() for row in reader}
    return sorted(u for u in urls if u.startswith(("http://", "https://")))


def _safe_file_name(url: str) -> str:
    parsed = urlparse(url)
    base = Path(parsed.path).name or "catalog"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"{digest}_{base}"


# Vendor document hosts sit behind CDNs that reject the default urllib agent, which
# is why a plain urlopen failed on roughly half of the catalog's URLs while the same
# links open fine in a browser.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def download_catalogs(
    csv_path: str | Path,
    output_dir: str | Path,
    *,
    limit: int | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    """Download every datasheet URL in the catalog.

    Reports the outcome of each URL rather than a bare failure count: a silent
    "failed: 14" gives no way to tell a dead link from a blocked user agent.
    """
    urls = list_catalog_urls(csv_path)
    if limit is not None:
        urls = urls[: max(0, limit)]

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []

    for url in urls:
        target = out / _safe_file_name(url)
        if target.exists():
            results.append({"url": url, "status": "skipped", "path": str(target)})
            continue
        try:
            request = Request(url, headers=_BROWSER_HEADERS)
            with urlopen(request, timeout=timeout) as resp:
                body = resp.read()
                content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
        except HTTPError as exc:
            results.append({"url": url, "status": "failed", "error": f"HTTP {exc.code} {exc.reason}"})
            continue
        except (URLError, TimeoutError, ValueError, OSError) as exc:
            results.append({"url": url, "status": "failed", "error": str(exc)})
            continue

        target.write_bytes(body)
        entry: dict[str, Any] = {
            "url": url,
            "status": "downloaded",
            "path": str(target),
            "bytes": len(body),
            "content_type": content_type,
        }
        # A PDF link that answers with HTML is usually a consent wall or an error page
        # dressed as a 200, and silently saving it corrupts the ingestion input.
        if url.lower().endswith(".pdf") and not body.startswith(b"%PDF"):
            entry["warning"] = f"expected a PDF but received {content_type or 'unknown content'}"
        results.append(entry)

    counts = Counter(r["status"] for r in results)
    return {
        "total": len(urls),
        "downloaded": counts.get("downloaded", 0),
        "skipped": counts.get("skipped", 0),
        "failed": counts.get("failed", 0),
        "results": results,
    }


def build_sqlite_database(csv_path: str | Path, sqlite_path: str | Path) -> int:
    csv_file = Path(csv_path)
    db_file = Path(sqlite_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    with csv_file.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    conn = sqlite3.connect(db_file)
    try:
        cols = ", ".join(f'"{c}" TEXT' for c in FIELD_NAMES)
        conn.execute("DROP TABLE IF EXISTS equipment_catalog")
        conn.execute(f"CREATE TABLE equipment_catalog ({cols})")
        placeholders = ", ".join("?" for _ in FIELD_NAMES)
        insert_sql = f"INSERT INTO equipment_catalog ({', '.join(FIELD_NAMES)}) VALUES ({placeholders})"
        for row in rows:
            conn.execute(insert_sql, [row.get(c, "") for c in FIELD_NAMES])
        conn.commit()
    finally:
        conn.close()

    return len(rows)



# Rows added through the browse UI land here rather than in a vendor file, so a
# hand-entered row is never mistaken for one transcribed during a catalogue build.
USER_ADDED_FILE = "user_added.csv"


def append_component(
    row: dict[str, str],
    *,
    vendors_dir: str | Path,
    catalog_csv: str | Path,
    sqlite_path: str | Path | None = None,
) -> dict[str, Any]:
    """Add one component to the catalogue.

    Runs the same validation as a catalogue build: controlled category vocabulary, a
    required source, something to match on, and unique part numbers. A row that fails
    is rejected with its reasons and nothing is written.
    """
    from .dataset_pipeline import build_catalog_from_vendor_sources, validate_rows

    complete = {name: str(row.get(name, "") or "").strip() for name in FIELD_NAMES}
    if complete["verification_status"] not in {"verified", "unverified", "disputed"}:
        complete["verification_status"] = "unverified"

    errors = validate_rows([complete])
    existing_parts = set()
    catalog_path = Path(catalog_csv)
    if catalog_path.exists():
        with catalog_path.open("r", encoding="utf-8", newline="") as handle:
            existing_parts = {
                (r.get("part_number") or "").strip().lower() for r in csv.DictReader(handle)
            }
    if complete["part_number"].lower() in existing_parts:
        errors.append(f"part_number {complete['part_number']} is already in the catalogue")

    if errors:
        return {"added": False, "errors": [e.replace("row 1: ", "") for e in errors]}

    target = Path(vendors_dir) / USER_ADDED_FILE
    is_new = not target.exists()
    with target.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELD_NAMES)
        if is_new:
            writer.writeheader()
        writer.writerow(complete)

    build_errors = build_catalog_from_vendor_sources(vendors_dir, catalog_csv)
    if build_errors:
        return {"added": False, "errors": build_errors}
    rows = None
    if sqlite_path is not None:
        rows = build_sqlite_database(catalog_csv, sqlite_path)

    return {"added": True, "part_number": complete["part_number"], "catalog_rows": rows}
