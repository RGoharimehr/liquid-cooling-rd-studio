from __future__ import annotations

import json
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from pydantic import ValidationError

from .assistant import run_assistant_query
from .catalog import EquipmentCatalog
from .catalog_tools import append_component
from .api_models import (
    AssistantRequest,
    CompatibilityRequest,
    ComponentsQuery,
    FindQuery,
    SelectRequest,
    first_query_value,
    query_payload,
    validation_message,
)
from .service import EquipmentService

API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"
LEGACY_PREFIX = "/api"


HTML_INDEX = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Equipment catalogue</title>
<style>
  :root { color-scheme: light dark; --rule:#d8dee0; --ink:#101619; --soft:#5b6a70;
          --ground:#f7f9f9; --panel:#fff; --accent:#0b6e7f; --bad:#97302f; --ok:#2f6b46; }
  @media (prefers-color-scheme: dark) { :root {
    --rule:#26343a; --ink:#e3eaec; --soft:#9fb0b6; --ground:#0d1315; --panel:#141d20;
    --accent:#4fb3c4; --bad:#e0857f; --ok:#7bbd95; } }
  * { box-sizing:border-box }
  body { margin:0; background:var(--ground); color:var(--ink);
         font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif }
  main { max-width:1180px; margin:0 auto; padding:28px 20px 72px }
  h1 { font-size:1.5rem; margin:0 0 4px }
  .lede { color:var(--soft); margin:0 0 22px }
  .bar { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px }
  input, select, button { font:inherit; padding:7px 10px; border:1px solid var(--rule);
         border-radius:4px; background:var(--panel); color:var(--ink) }
  button { cursor:pointer }
  button.primary { background:var(--accent); border-color:var(--accent); color:#fff }
  .count { color:var(--soft); font-size:13px; align-self:center; margin-left:auto }
  .tablewrap { overflow-x:auto; border:1px solid var(--rule); border-radius:6px;
               background:var(--panel) }
  table { border-collapse:collapse; width:100%; font-size:13.5px; min-width:900px }
  th { text-align:left; font-size:11px; letter-spacing:.08em; text-transform:uppercase;
       color:var(--soft); padding:10px 12px; border-bottom:1px solid var(--rule);
       position:sticky; top:0; background:var(--panel) }
  td { padding:9px 12px; border-bottom:1px solid var(--rule); vertical-align:top }
  tbody tr:last-child td { border-bottom:0 }
  td.num { font-variant-numeric:tabular-nums; white-space:nowrap }
  .pill { font-size:11px; padding:2px 7px; border-radius:10px; border:1px solid currentColor }
  .v-verified { color:var(--ok) } .v-unverified { color:var(--soft) }
  .v-disputed { color:var(--bad) }
  details.add { margin-top:26px; border:1px solid var(--rule); border-radius:6px;
                background:var(--panel); padding:14px 18px }
  details.add summary { cursor:pointer; font-weight:600 }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
          gap:12px; margin-top:16px }
  .grid label { display:flex; flex-direction:column; gap:4px; font-size:12px;
                color:var(--soft) }
  .msg { margin-top:12px; font-size:13.5px }
  .msg.err { color:var(--bad) } .msg.ok { color:var(--ok) }
  .hint { color:var(--soft); font-size:12.5px; margin:10px 0 0 }
  a { color:var(--accent) }
</style></head><body><main>
<h1>Equipment catalogue</h1>
<p class="lede">Browse what is in the catalogue and add a component transcribed from a
vendor document. Selection runs through the API or the CLI, not here.</p>

<div class="bar">
  <input id="q" placeholder="search part, brand, name" size="26">
  <select id="f-cat"><option value="">every category</option></select>
  <select id="f-brand"><option value="">every brand</option></select>
  <select id="f-ver">
    <option value="">any status</option><option>verified</option>
    <option>unverified</option><option>disputed</option>
  </select>
  <input id="api-key" placeholder="X-API-Key (if set)" size="16">
  <span class="count" id="count"></span>
</div>

<div class="tablewrap"><table>
  <thead><tr><th>Part</th><th>Brand</th><th>Category</th><th>Component</th>
  <th>Size mm</th><th>Coefficient</th><th>Capacity kW</th><th>bar</th><th>deg C</th>
  <th>Material</th><th>Status</th></tr></thead>
  <tbody id="rows"></tbody>
</table></div>

<details class="add"><summary>Add a component</summary>
  <p class="hint">Transcribe every value from the document you cite. A row needs a
  category from the catalogue vocabulary, a source, a part number, and at least one of
  capacity, size or flow coefficient: without one, no search can ever return it.</p>
  <div class="grid" id="form"></div>
  <p class="hint"><label style="flex-direction:row;align-items:center;gap:7px">
    <input type="checkbox" id="verified-box">
    I read these values from the cited document (marks the row verified)</label></p>
  <p><button class="primary" id="add">Add to catalogue</button></p>
  <div class="msg" id="msg"></div>
</details>
</main>
<script>
const FIELDS = [
  ["part_number","Part number *"],["brand","Brand *"],["category","Category *"],
  ["component_subtype","Subtype"],["series_name","Series"],
  ["component_name","Description *"],["nominal_size_mm","Nominal size mm"],
  ["nominal_size_inch","Nominal size in"],["flow_coefficient_type","Coefficient type Cv/Kv"],
  ["flow_coefficient_value","Coefficient value"],["capacity_kw","Capacity kW"],
  ["capacity_tons","Capacity tons"],["connection_type","Connection type"],
  ["connection_standard","Connection standard"],["material","Material"],
  ["pressure_rating_bar","Pressure rating bar"],
  ["max_temperature_c","Max fluid temperature C"],["coolant_compatibility","Coolant"],
  ["source_catalog","Source document *"],["source_page","Source page"],
  ["datasheet_url","Datasheet URL"],["baseline_references","Baseline references"]
];
let ALL = [];
const el = function (id) { return document.getElementById(id); };
function headers() {
  const key = el("api-key").value.trim();
  const base = {"Content-Type": "application/json"};
  if (key) { base["X-API-Key"] = key; }
  return base;
}
function esc(value) {
  return String(value === null || value === undefined ? "" : value).replace(
    /[&<>"]/g, function (ch) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}[ch]; });
}
function draw() {
  const q = el("q").value.trim().toLowerCase();
  const cat = el("f-cat").value, brand = el("f-brand").value, ver = el("f-ver").value;
  const rows = ALL.filter(function (c) {
    if (cat && c.category !== cat) return false;
    if (brand && c.brand !== brand) return false;
    if (ver && c.verification_status !== ver) return false;
    if (!q) return true;
    return [c.part_number, c.brand, c.component_name, c.series_name]
      .filter(Boolean).join(" ").toLowerCase().indexOf(q) !== -1;
  });
  el("count").textContent = rows.length + " of " + ALL.length + " rows";
  el("rows").innerHTML = rows.map(function (c) {
    const coeff = c.flow_coefficient_value === null ? ""
      : esc(c.flow_coefficient_type) + " " + c.flow_coefficient_value;
    const name = c.datasheet_url
      ? '<a href="' + esc(c.datasheet_url) + '" target="_blank" rel="noopener noreferrer">'
        + esc(c.part_number) + "</a>"
      : esc(c.part_number);
    const cell = function (v) { return v === null || v === undefined ? "" : v; };
    return "<tr><td>" + name + "</td><td>" + esc(c.brand) + "</td><td>" +
      esc(c.category) + "</td><td>" + esc(c.component_name) +
      '</td><td class="num">' + cell(c.nominal_size_mm) +
      '</td><td class="num">' + coeff +
      '</td><td class="num">' + cell(c.capacity_kw) +
      '</td><td class="num">' + cell(c.pressure_rating_bar) +
      '</td><td class="num">' + cell(c.max_temperature_c) +
      "</td><td>" + esc(c.material) + '</td><td><span class="pill v-' +
      esc(c.verification_status) + '">' + esc(c.verification_status) +
      "</span></td></tr>";
  }).join("");
}
function options(select, values) {
  values.forEach(function (v) {
    const o = document.createElement("option");
    o.value = v; o.textContent = v; select.appendChild(o);
  });
}
async function load() {
  const res = await fetch("/api/v1/components?limit=1000", {headers: headers()});
  const payload = await res.json();
  ALL = payload.data || [];
  const cats = Array.from(new Set(ALL.map(function (c) { return c.category; }))).sort();
  const brands = Array.from(new Set(ALL.map(function (c) { return c.brand; }))).sort();
  el("f-cat").length = 1; el("f-brand").length = 1;
  options(el("f-cat"), cats); options(el("f-brand"), brands);
  draw();
}
FIELDS.forEach(function (pair) {
  const wrap = document.createElement("label");
  wrap.textContent = pair[1];
  const input = document.createElement("input");
  input.id = "f_" + pair[0];
  wrap.appendChild(input);
  el("form").appendChild(wrap);
});
el("add").addEventListener("click", async function () {
  const row = {};
  FIELDS.forEach(function (pair) {
    const v = el("f_" + pair[0]).value.trim();
    if (v) { row[pair[0]] = v; }
  });
  row.verification_status = el("verified-box").checked ? "verified" : "unverified";
  const res = await fetch("/api/v1/components", {
    method: "POST", headers: headers(), body: JSON.stringify(row)});
  const payload = await res.json();
  const msg = el("msg");
  if (payload.ok && payload.data && payload.data.added) {
    msg.className = "msg ok";
    msg.textContent = "Added " + payload.data.part_number + "; catalogue now " +
      payload.data.catalog_rows + " rows";
    FIELDS.forEach(function (pair) { el("f_" + pair[0]).value = ""; });
    await load();
  } else {
    msg.className = "msg err";
    const errs = (payload.data && payload.data.errors) ||
      [payload.error ? payload.error.message : "request failed"];
    msg.textContent = "Not added: " + errs.join("; ");
  }
});
["q", "f-cat", "f-brand", "f-ver"].forEach(function (id) {
  el(id).addEventListener("input", draw);
  el(id).addEventListener("change", draw);
});
load();
</script></body></html>
"""


@dataclass(frozen=True)
class ServerConfig:
    api_key: str | None = None
    rate_limit_per_minute: int = 120


def _default_config() -> ServerConfig:
    configured_key = os.environ.get("DCEF_API_KEY")
    configured_limit = int(os.environ.get("DCEF_RATE_LIMIT_PER_MIN", "120"))
    return ServerConfig(api_key=configured_key, rate_limit_per_minute=max(1, configured_limit))


def _envelope_ok(data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {"ok": True, "data": data, "error": None, "meta": {"api_version": API_VERSION}}
    if meta:
        payload["meta"].update(meta)
    return payload


def _envelope_error(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "ok": False,
        "data": None,
        "error": {"code": code, "message": message, "details": details},
        "meta": {"api_version": API_VERSION},
    }

def _normalized_api_path(path: str) -> str:
    if path.startswith(API_PREFIX):
        return path
    if path == LEGACY_PREFIX:
        return API_PREFIX
    if path.startswith(LEGACY_PREFIX + "/"):
        return API_PREFIX + path[len(LEGACY_PREFIX) :]
    return path


def _json_response(handler: BaseHTTPRequestHandler, payload: dict | list, status: int = 200) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _text_response(handler: BaseHTTPRequestHandler, text: str, status: int = 200) -> None:
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)

def create_handler(service: EquipmentService, config: ServerConfig | None = None):
    cfg = config or _default_config()
    request_buckets: dict[str, deque[float]] = defaultdict(deque)

    class EquipmentHandler(BaseHTTPRequestHandler):
        def _client_id(self) -> str:
            forwarded = self.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()
            return self.client_address[0]

        def _check_rate_limit(self) -> bool:
            now = time.time()
            window_start = now - 60
            bucket = request_buckets[self._client_id()]
            while bucket and bucket[0] < window_start:
                bucket.popleft()
            if len(bucket) >= cfg.rate_limit_per_minute:
                _json_response(
                    self,
                    _envelope_error("rate_limited", "Rate limit exceeded", {"limit_per_minute": cfg.rate_limit_per_minute}),
                    429,
                )
                return False
            bucket.append(now)
            return True

        def _check_auth(self, path: str) -> bool:
            if not path.startswith(API_PREFIX):
                return True
            if path.endswith("/health"):
                return True
            if not cfg.api_key:
                return True
            supplied = self.headers.get("X-API-Key")
            if supplied == cfg.api_key:
                return True
            _json_response(self, _envelope_error("unauthorized", "Missing or invalid API key"), 401)
            return False

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = _normalized_api_path(parsed.path)
            query = parse_qs(parsed.query)

            if path == "/":
                _text_response(self, HTML_INDEX, 200)
                return

            if not self._check_auth(path):
                return
            if path.startswith(API_PREFIX) and not self._check_rate_limit():
                return

            if path == f"{API_PREFIX}/health":
                _json_response(self, _envelope_ok({"status": "ok"}), 200)
                return

            if path == f"{API_PREFIX}/schema":
                _json_response(self, _envelope_ok(service.schema()), 200)
                return

            if path == f"{API_PREFIX}/components":
                try:
                    component_filters = ComponentsQuery.model_validate(
                        query_payload(query, "category", "component_subtype", "brand", "limit", "offset")
                    )
                    payload = service.list_components(
                        category=component_filters.category,
                        component_subtype=component_filters.component_subtype,
                        brand=component_filters.brand,
                        limit=component_filters.limit,
                        offset=component_filters.offset,
                    )
                    _json_response(self, _envelope_ok(payload, {"count": len(payload)}), 200)
                    return
                except ValidationError as exc:
                    _json_response(self, _envelope_error("invalid_request", validation_message(exc)), 400)
                    return

            if path == f"{API_PREFIX}/component":
                part = first_query_value(query, "part_number")
                if not part:
                    _json_response(self, _envelope_error("invalid_request", "part_number is required"), 400)
                    return
                item = service.get_component(part)
                if item is None:
                    _json_response(self, _envelope_error("not_found", "component not found"), 404)
                    return
                _json_response(self, _envelope_ok(item), 200)
                return

            if path == f"{API_PREFIX}/find":
                try:
                    find_filters = FindQuery.model_validate(
                        query_payload(
                            query,
                            "category",
                            "component_subtype",
                            "brand",
                            "size_mm",
                            "connection_size_mm",
                            "connection_size_inch",
                            "required_pressure_bar",
                            "required_temperature_c",
                            "cv",
                            "kv",
                            "capacity_kw",
                            "capacity_tons",
                            "top_n",
                        )
                    )
                    payload = service.find_components(
                        category=find_filters.category,
                        component_subtype=find_filters.component_subtype,
                        brand=find_filters.brand,
                        size_mm=find_filters.size_mm,
                        connection_size_mm=find_filters.connection_size_mm,
                        connection_size_inch=find_filters.connection_size_inch,
                        required_pressure_bar=find_filters.required_pressure_bar,
                        required_temperature_c=find_filters.required_temperature_c,
                        cv=find_filters.cv,
                        kv=find_filters.kv,
                        capacity_kw=find_filters.capacity_kw,
                        capacity_tons=find_filters.capacity_tons,
                        top_n=find_filters.top_n,
                    )
                    _json_response(self, _envelope_ok(payload, {"count": len(payload)}), 200)
                    return
                except ValidationError as exc:
                    _json_response(self, _envelope_error("invalid_request", validation_message(exc)), 400)
                    return

            if path == f"{API_PREFIX}/explain":
                explanation = service.explain(
                    property_name=first_query_value(query, "property"),
                    category=first_query_value(query, "category"),
                )
                _json_response(self, _envelope_ok(explanation), 200)
                return

            if path == f"{API_PREFIX}/openapi.json":
                spec = {
                    "openapi": "3.0.0",
                    "info": {"title": "DCEF API", "version": API_VERSION},
                    "paths": {
                        f"{API_PREFIX}/health": {"get": {}},
                        f"{API_PREFIX}/schema": {"get": {}},
                        f"{API_PREFIX}/components": {"get": {}, "post": {}},
                        f"{API_PREFIX}/component": {"get": {}},
                        f"{API_PREFIX}/find": {"get": {}},
                        f"{API_PREFIX}/compat": {"post": {}},
                        f"{API_PREFIX}/select": {"post": {}},
                        f"{API_PREFIX}/assistant": {"post": {}},
                        f"{API_PREFIX}/explain": {"get": {}},
                    },
                }
                _json_response(self, _envelope_ok(spec), 200)
                return

            _json_response(self, _envelope_error("not_found", "not found"), 404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = _normalized_api_path(parsed.path)

            if not self._check_auth(path):
                return
            if path.startswith(API_PREFIX) and not self._check_rate_limit():
                return

            if path == f"{API_PREFIX}/assistant":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    assistant_request = AssistantRequest.model_validate(json.loads(self.rfile.read(length) or b"{}"))
                    result = run_assistant_query(assistant_request.query, service, mode=assistant_request.mode)
                    _json_response(self, _envelope_ok(result), 200)
                    return
                except json.JSONDecodeError as exc:
                    _json_response(self, _envelope_error("invalid_request", str(exc)), 400)
                    return
                except ValidationError as exc:
                    _json_response(self, _envelope_error("invalid_request", validation_message(exc)), 400)
                    return

            if path == f"{API_PREFIX}/select":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    select_request = SelectRequest.model_validate(
                        json.loads(self.rfile.read(length) or b"{}")
                    )
                except json.JSONDecodeError as exc:
                    _json_response(self, _envelope_error("invalid_request", str(exc)), 400)
                    return
                except ValidationError as exc:
                    _json_response(
                        self, _envelope_error("invalid_request", validation_message(exc)), 400
                    )
                    return
                selection = service.select_for_duty(
                    [item.model_dump() for item in select_request.items],
                    top_n=select_request.top_n,
                )
                _json_response(self, _envelope_ok(selection), 200)
                return

            if path == f"{API_PREFIX}/components":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    submitted = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError as exc:
                    _json_response(self, _envelope_error("invalid_request", str(exc)), 400)
                    return
                if not isinstance(submitted, dict):
                    _json_response(
                        self,
                        _envelope_error("invalid_request", "expected a component object"),
                        400,
                    )
                    return
                catalog_csv = EquipmentCatalog.default_csv_path()
                outcome = append_component(
                    {str(k): "" if v is None else str(v) for k, v in submitted.items()},
                    vendors_dir=catalog_csv.parent / "vendors",
                    catalog_csv=catalog_csv,
                    sqlite_path=catalog_csv.with_suffix(".sqlite"),
                )
                if outcome["added"]:
                    # Serve the new row immediately rather than after a restart.
                    service.catalog = EquipmentCatalog.from_csv()
                _json_response(
                    self, _envelope_ok(outcome), 200 if outcome["added"] else 422
                )
                return

            if path != f"{API_PREFIX}/compat":
                _json_response(self, _envelope_error("not_found", "not found"), 404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                compat_request = CompatibilityRequest.model_validate(json.loads(self.rfile.read(length) or b"{}"))
                report = service.compatibility(
                    compat_request.part_numbers,
                    max_connection_time=compat_request.max_connection_time,
                    required_material=compat_request.required_material,
                    required_connection_standard=compat_request.required_connection_standard,
                    required_coolant=compat_request.required_coolant,
                    required_pressure_bar=compat_request.required_pressure_bar,
                    required_temperature_c=compat_request.required_temperature_c,
                )
                _json_response(self, _envelope_ok(report), 200)
            except json.JSONDecodeError as exc:
                _json_response(self, _envelope_error("invalid_request", str(exc)), 400)
            except ValidationError as exc:
                _json_response(self, _envelope_error("invalid_request", validation_message(exc)), 400)

        def log_message(self, format: str, *args):  # noqa: A003
            return

    return EquipmentHandler


def run_server(host: str = "127.0.0.1", port: int = 8000, *, api_key: str | None = None, rate_limit_per_minute: int | None = None) -> None:
    base_cfg = _default_config()
    config = ServerConfig(
        api_key=api_key if api_key is not None else base_cfg.api_key,
        rate_limit_per_minute=rate_limit_per_minute if rate_limit_per_minute is not None else base_cfg.rate_limit_per_minute,
    )
    server = ThreadingHTTPServer((host, port), create_handler(EquipmentService.default(), config=config))
    print(f"DCEF web server running on http://{host}:{port}")
    print(f"API: {API_PREFIX} | OpenAPI: {API_PREFIX}/openapi.json")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
