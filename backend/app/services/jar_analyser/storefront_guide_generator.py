"""Storefront Developer Guide generator.

Produces a JS/TS guide aimed at developers building branded shop-front
experiences on top of the platform's public-facing APIs.  The output is a
single annotated source file with:

  - TypeScript interfaces for every DTO the storefront will touch
  - A lightweight ApiClient base class (fetch-based, no dependencies)
  - Per-domain service clients (Catalog, Request, Pricing, Customers,
    ServiceInstances, Fulfillment) containing only the public endpoints
  - Narrative multi-step code examples for the key storefront flows

Flow definitions are loaded from storefront_flows.yml in the same directory.
Edit that file to add, remove, or modify flows without touching this module.
The generator resolves actual method names, path params, and response shapes
from the live JAR report at render time, so the YAML stays version-agnostic.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import yaml

from app.services.jar_analyser.example_generator import build_example, _parse_constraints


# ---------------------------------------------------------------------------
# Flow definitions — loaded from storefront_flows.yml
# ---------------------------------------------------------------------------

_FLOWS_YAML = Path(__file__).with_name("storefront_flows.yml")


def _load_flows() -> list[dict]:
    """Load and normalise flow definitions from storefront_flows.yml."""
    try:
        doc = yaml.safe_load(_FLOWS_YAML.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"Cannot load storefront_flows.yml: {e}") from e
    flows = []
    for raw in (doc or {}).get("flows", []):
        steps = []
        for rs in raw.get("steps", []):
            steps.append({
                "domain":   str(rs.get("domain", "")),
                "verb":     str(rs.get("verb", "GET")).upper(),
                "fragment": str(rs.get("fragment", "")),
                "label":    str(rs.get("label", "")),
                "var":      rs.get("var"),
                "poll":     rs.get("poll"),
                "events":   list(rs.get("events") or []),
                "note":     rs.get("note"),
            })
        flows.append({
            "title":       str(raw.get("title", "")),
            "description": str(raw.get("description", "")).strip(),
            "steps":       steps,
        })
    return flows


# ---------------------------------------------------------------------------
# Domain classification
# ---------------------------------------------------------------------------

# Paths containing these fragments are internal/admin — skip them
_SKIP_PATH_FRAGMENTS = (
    "/admin/", "/integration/", "/cps/integration/", "/cps/",
    "/sync", "/cache-sync", "/full-text-sync", "/reindex",
    "/actuator", "/health", "/metrics", "/prometheus",
    "/internal/", "/system/", "/diagnostic",
)

# Map service name → storefront domain label
_SERVICE_DOMAIN = {
    "catalog":           "Catalog",
    "request":           "Request",
    "pricing":           "Pricing",
    "customers":         "Customers",
    "service-instances": "ServiceInstances",
    "fulfillment":       "Fulfillment",
}




# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_public(path: str) -> bool:
    lp = path.lower()
    return not any(f in lp for f in _SKIP_PATH_FRAGMENTS)


def _camel(name: str) -> str:
    parts = re.split(r"[-_\s]+", name)
    return parts[0].lower() + "".join(p.title() for p in parts[1:])


def _pascal(name: str) -> str:
    return "".join(p.title() for p in re.split(r"[-_\s]+", name))


def _path_to_template(path: str) -> str:
    return re.sub(r"\{([^}]+)\}", r"${\1}", path)


def _openapi_to_ts(openapi_type: str, fmt: str | None, simple_type: str, schema_names: set[str]) -> str:
    if openapi_type == "integer":
        return "number"
    if openapi_type == "number":
        return "number"
    if openapi_type == "boolean":
        return "boolean"
    if openapi_type == "array":
        return "unknown[]"
    if openapi_type == "object":
        if simple_type in schema_names:
            return simple_type
        return "Record<string, unknown>"
    if openapi_type == "null":
        return "void"
    if fmt == "uuid":
        return "string  // UUID"
    if fmt in ("date", "date-time"):
        return "string  // ISO-8601"
    return "string"


class _EndpointInfo(NamedTuple):
    domain: str
    method: str
    path: str
    method_name: str
    path_params: list[dict]
    query_params: list[dict]
    has_body: bool
    body_type: str | None
    return_type: str | None
    parsed_auth: dict | None
    deprecated: bool
    linked_tables: list[str]
    is_proxied: bool | None


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

class StorefrontGuideGenerator:

    @staticmethod
    def generate(
        version: str,
        services: list[dict],   # [{name, port, endpoints, schemas}]
        typescript: bool = True,
    ) -> str:
        ext = "ts" if typescript else "js"
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Build domain → endpoint list and schema map
        domain_endpoints: dict[str, list[_EndpointInfo]] = {}
        all_schemas: dict[str, dict] = {}  # simple_name → schema dict
        domain_port: dict[str, int] = {}
        # endpoint signature_key → linked tables (from table_linker)
        linked_tables_map: dict[str, list[str]] = {}

        for svc in services:
            svc_name = svc["name"]
            domain = _SERVICE_DOMAIN.get(svc_name)
            if not domain:
                continue
            domain_port[domain] = svc.get("port") or 8080
            for s in (svc.get("schemas") or []):
                all_schemas[s["simple_name"]] = s

            # Build linked_tables_map from endpoint dicts (already computed by persistence)
            for ep in (svc.get("endpoints") or []):
                lt = ep.get("linked_tables")
                if lt:
                    linked_tables_map[ep.get("signature_key", "")] = lt

            eps: list[_EndpointInfo] = []
            for ep in (svc.get("endpoints") or []):
                path = ep.get("full_path", "")
                if not _is_public(path):
                    continue
                params = ep.get("parameters") or []
                body = ep.get("request_body")
                ret = ep.get("return_type")
                sec = ep.get("security")
                parsed_auth = sec.get("parsed_auth") if sec else None
                eps.append(_EndpointInfo(
                    domain=domain,
                    method=ep.get("http_method", "GET"),
                    path=path,
                    method_name=ep.get("method_name") or "",
                    path_params=[p for p in params if p.get("location") == "path"],
                    query_params=[p for p in params if p.get("location") == "query"],
                    has_body=body is not None,
                    body_type=(body or {}).get("simple_type"),
                    return_type=(ret or {}).get("simple_type") if ret else None,
                    parsed_auth=parsed_auth,
                    deprecated=ep.get("is_deprecated", False),
                    linked_tables=ep.get("linked_tables") or [],
                    is_proxied=ep.get("is_proxied"),
                ))
                # carry signature_key on the NamedTuple isn't possible without changing it;
                # store in a side dict keyed by (domain, method_name, path)
            domain_endpoints[domain] = eps

        schema_names = set(all_schemas.keys())

        # Build published-event index: "entity/action" -> set of source service names
        # Used to validate flow step events against what the report actually publishes
        published_events: dict[str, set[str]] = {}  # e.g. "orderItem/stateUpdated" -> {"request"}
        for svc in services:
            svc_name = svc["name"]
            for ef in (svc.get("event_files") or []):
                for pub in (ef.get("published") or []):
                    entity = pub.get("entity", "")
                    for action in (pub.get("actions") or []):
                        key = f"{entity}/{action}"
                        published_events.setdefault(key, set()).add(svc_name)

        lines: list[str] = []

        # ---- File header ----
        lines += [
            f"// {'=' * 70}",
            f"// storefront-guide.{ext}",
            f"// Platform Storefront Developer Guide",
            f"// Version: {version}   Generated: {generated_at}",
            f"// Auto-generated from JAR bytecode analysis — DO NOT EDIT",
            f"// Regenerate via JAR Analyser → ⬇ Storefront Guide",
            f"// {'=' * 70}",
            f"//",
            f"// This file is a self-contained, dependency-free guide for developers",
            f"// building branded shop-front experiences on the platform.",
            f"//",
            f"// Contents:",
            f"//   1. TypeScript interfaces for all public-facing DTOs",
            f"//   2. ApiClient base class (fetch, JWT/API-key auth)",
            f"//   3. Per-domain service clients (only public endpoints)",
            f"//   4. Pagination helper and paginated endpoint list",
            f"//   5. Annotated multi-step code examples for key storefront flows",
            f"//   6. Auth requirements summary",
            f"//   7. Service topology (Mermaid diagram)",
            f"//   8. Event bus topology (Publisher \u2192 event \u2192 Consumer)",
            f"//   9. Environment variable catalogue",
            f"//  10. Database schema (per-service table listing)",
            f"// {'=' * 70}",
            "",
        ]

        # ---- Section 1: TypeScript interfaces ----
        if typescript:
            lines += [
                "// " + "─" * 68,
                "// SECTION 1 — TypeScript Interfaces",
                "// " + "─" * 68,
                "",
            ]
            # Collect types actually referenced by public endpoints
            referenced: set[str] = set()
            for eps in domain_endpoints.values():
                for ep in eps:
                    if ep.body_type and ep.body_type in schema_names:
                        referenced.add(ep.body_type)
                    if ep.return_type and ep.return_type in schema_names:
                        referenced.add(ep.return_type)
            # Also pull in field types one level deep
            extra: set[str] = set()
            for name in list(referenced):
                schema = all_schemas.get(name)
                if schema:
                    for f in (schema.get("fields") or []):
                        st = f.get("simple_type", "")
                        if st in schema_names:
                            extra.add(st)
            referenced |= extra

            emitted = 0
            for name in sorted(referenced):
                schema = all_schemas.get(name)
                if not schema:
                    continue
                if schema.get("is_enum"):
                    values = schema.get("enum_values") or []
                    serialised = [v.get("serialised_as") or v.get("name", "") for v in values]
                    if serialised:
                        union = " | ".join(f'"{v}"' for v in serialised[:20])
                        lines.append(f"export type {name} = {union}")
                        emitted += 1
                else:
                    fields = [f for f in (schema.get("fields") or []) if not f.get("json_ignored")]
                    if not fields:
                        continue
                    lines.append(f"export interface {name} {{")
                    for f in fields:
                        opt = "" if f.get("required") else "?"
                        ts_type = _openapi_to_ts(
                            f.get("openapi_type", "string"),
                            f.get("openapi_format"),
                            f.get("simple_type", ""),
                            schema_names,
                        )
                        st = f.get("simple_type", "")
                        if st in schema_names:
                            s2 = all_schemas[st]
                            if s2.get("is_enum"):
                                ts_type = st
                            elif f.get("openapi_type") == "object":
                                ts_type = st
                        if f.get("is_collection"):
                            elem = f.get("collection_element_type") or "unknown"
                            ts_type = f"{elem if elem in schema_names else 'unknown'}[]"
                        nullable = " | null" if f.get("nullable") else ""
                        # Emit JSDoc constraint comment if any constraints present
                        raw_constraints = f.get("constraints") or []
                        c = _parse_constraints(raw_constraints)
                        jsdoc_tags: list[str] = []
                        if f.get("required"):
                            jsdoc_tags.append("@required")
                        if c.get("minLength") is not None:
                            jsdoc_tags.append(f"@minLength {c['minLength']}")
                        if c.get("maxLength") is not None:
                            jsdoc_tags.append(f"@maxLength {c['maxLength']}")
                        if c.get("minimum") is not None:
                            jsdoc_tags.append(f"@min {c['minimum']}")
                        if c.get("maximum") is not None:
                            jsdoc_tags.append(f"@max {c['maximum']}")
                        if c.get("pattern"):
                            jsdoc_tags.append(f"@pattern {c['pattern']}")
                        # Detect @NotBlank / @NotNull / @Email from raw strings
                        for ann in raw_constraints:
                            ann_lower = ann.lower()
                            if "notblank" in ann_lower:
                                jsdoc_tags.append("@notBlank")
                            elif "notempty" in ann_lower:
                                jsdoc_tags.append("@notEmpty")
                            elif "notnull" in ann_lower and "@required" not in jsdoc_tags:
                                jsdoc_tags.append("@notNull")
                            elif "email" in ann_lower:
                                jsdoc_tags.append("@email")
                        if jsdoc_tags:
                            lines.append(f"  /** {' '.join(jsdoc_tags)} */")
                        lines.append(f"  {f['json_name']}{opt}: {ts_type}{nullable}")
                    lines.append("}")
                    emitted += 1
            if emitted == 0:
                lines.append("// (No DTO schemas found for public endpoints in this version)")
            lines.append("")

        # ---- Section 2: ApiClient base ----
        lines += [
            "// " + "─" * 68,
            "// SECTION 2 — ApiClient Base Class",
            "// " + "─" * 68,
            "//",
            "// Handles authentication (JWT bearer token or API key),",
            "// JSON serialisation, and error normalisation.",
            "//",
            "",
        ]

        if typescript:
            lines += [
                "export interface ApiClientConfig {",
                "  /** Base URL of the platform, e.g. http://platform.example.com */",
                "  baseUrl: string",
                "  /** JWT token obtained from POST /api/auth/login */",
                "  token?: string",
                "  /** Scoped API key (alternative to JWT) */",
                "  apiKey?: string",
                "}",
                "",
                "export class ApiError extends Error {",
                "  constructor(public status: number, public body: unknown, message: string) {",
                "    super(message)",
                "  }",
                "}",
                "",
                "export class ApiClient {",
                "  protected baseUrl: string",
                "  protected token?: string",
                "  protected apiKey?: string",
                "",
                "  constructor({ baseUrl, token, apiKey }: ApiClientConfig) {",
                "    this.baseUrl = baseUrl.replace(/\\/$/, '')",
                "    this.token = token",
                "    this.apiKey = apiKey",
                "  }",
                "",
                "  protected _headers(): Record<string, string> {",
                "    return {",
                "      'Content-Type': 'application/json',",
                "      ...(this.token  ? { Authorization: `Bearer ${this.token}` }  : {}),",
                "      ...(this.apiKey ? { 'X-API-Key': this.apiKey }               : {}),",
                "    }",
                "  }",
                "",
                "  protected async _request<T = unknown>(",
                "    method: string,",
                "    path: string,",
                "    { body, params }: { body?: unknown; params?: Record<string, unknown> } = {},",
                "  ): Promise<T> {",
                "    const url = new URL(this.baseUrl + path)",
                "    if (params) {",
                "      Object.entries(params).forEach(([k, v]) => {",
                "        if (v !== undefined && v !== null) url.searchParams.set(k, String(v))",
                "      })",
                "    }",
                "    const res = await fetch(url.toString(), {",
                "      method,",
                "      headers: this._headers(),",
                "      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),",
                "    })",
                "    if (!res.ok) {",
                "      const err = await res.json().catch(() => ({ message: res.statusText }))",
                "      throw new ApiError(res.status, err, err.message ?? res.statusText)",
                "    }",
                "    return res.status === 204 ? (null as T) : res.json()",
                "  }",
                "}",
                "",
            ]
        else:
            lines += [
                "class ApiError extends Error {",
                "  constructor(status, body, message) {",
                "    super(message)",
                "    this.status = status",
                "    this.body = body",
                "  }",
                "}",
                "",
                "class ApiClient {",
                "  constructor({ baseUrl, token, apiKey } = {}) {",
                "    this.baseUrl = (baseUrl ?? '').replace(/\\/$/, '')",
                "    this.token = token",
                "    this.apiKey = apiKey",
                "  }",
                "",
                "  _headers() {",
                "    return {",
                "      'Content-Type': 'application/json',",
                "      ...(this.token  ? { Authorization: `Bearer ${this.token}` }  : {}),",
                "      ...(this.apiKey ? { 'X-API-Key': this.apiKey }               : {}),",
                "    }",
                "  }",
                "",
                "  async _request(method, path, { body, params } = {}) {",
                "    const url = new URL(this.baseUrl + path)",
                "    if (params) {",
                "      Object.entries(params).forEach(([k, v]) => {",
                "        if (v !== undefined && v !== null) url.searchParams.set(k, String(v))",
                "      })",
                "    }",
                "    const res = await fetch(url.toString(), {",
                "      method,",
                "      headers: this._headers(),",
                "      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),",
                "    })",
                "    if (!res.ok) {",
                "      const err = await res.json().catch(() => ({ message: res.statusText }))",
                "      throw new ApiError(res.status, err, err.message ?? res.statusText)",
                "    }",
                "    return res.status === 204 ? null : res.json()",
                "  }",
                "}",
                "",
            ]

        # ---- Section 3: Per-domain service clients ----
        lines += [
            "// " + "─" * 68,
            "// SECTION 3 — Per-Domain Service Clients",
            "// " + "─" * 68,
            "//",
            "// Each client extends ApiClient and exposes only the public",
            "// endpoints relevant to storefront development.",
            "//",
        ]

        # Count deprecated endpoints across all domains
        total_deprecated = sum(
            1 for eps in domain_endpoints.values() for ep in eps if ep.deprecated
        )
        if total_deprecated:
            lines.append(f"// ⚠ {total_deprecated} deprecated endpoint{'s' if total_deprecated != 1 else ''} in this version — marked with @deprecated below.")
        lines.append("")

        domain_class_names: dict[str, str] = {}

        for domain, eps in domain_endpoints.items():
            if not eps:
                continue
            class_name = f"{domain}Client"
            domain_class_names[domain] = class_name
            port = domain_port.get(domain, 8080)

            lines += [
                f"// ── {domain} ──────────────────────────────────────────────────",
                "",
            ]

            if typescript:
                lines.append(f"export class {class_name} extends ApiClient {{")
            else:
                lines.append(f"class {class_name} extends ApiClient {{")

            for ep in eps:
                # Derive a readable method name from the Java method name or path
                mn = ep.method_name or ""
                if not mn:
                    segs = [s for s in ep.path.strip("/").split("/") if s and not s.startswith("{")]
                    mn = _camel("_".join(segs[-2:])) if len(segs) >= 2 else _camel(segs[-1] if segs else "call")
                    verb_map = {"GET": "get", "POST": "create", "PUT": "update", "PATCH": "patch", "DELETE": "delete"}
                    verb = verb_map.get(ep.method, ep.method.lower())
                    if not mn.lower().startswith(verb):
                        mn = verb + mn[0].upper() + mn[1:]

                # Signature parts
                sig_parts: list[str] = []
                for p in ep.path_params:
                    sig_parts.append(f"{p['name']}: string" if typescript else p["name"])
                if ep.has_body:
                    bt = ep.body_type or "unknown"
                    if typescript:
                        sig_parts.append(f"body: {bt if bt in schema_names else 'Record<string, unknown>'}")
                    else:
                        sig_parts.append("body")
                if ep.query_params:
                    if typescript:
                        qf = ", ".join(f"{p['name']}?: string" for p in ep.query_params[:6])
                        sig_parts.append(f"{{ {qf} }}: {{ {qf} }} = {{}}")
                    else:
                        qn = ", ".join(p["name"] for p in ep.query_params[:6])
                        sig_parts.append(f"{{ {qn} }} = {{}}")

                ret_ann = ""
                if typescript:
                    rt = ep.return_type
                    if rt and rt != "void" and rt in schema_names:
                        ret_ann = f": Promise<{rt}>"
                    else:
                        ret_ann = ": Promise<unknown>"

                sig = ", ".join(sig_parts)
                lines.append(f"  /** {ep.method} {ep.path}")
                if ep.deprecated:
                    lines.append(f"   * @deprecated This endpoint is marked @Deprecated in the source — do not use for new integrations.")
                if ep.is_proxied is False:
                    lines.append(f"   * @internal Not reachable via the Nginx proxy — do not call from external clients.")
                # Auth requirement comment
                pa = ep.parsed_auth
                if pa:
                    if pa.get("public"):
                        lines.append(f"   * @auth public (no authentication required)")
                    elif pa.get("deny_all"):
                        lines.append(f"   * @auth DENY ALL — this endpoint is always forbidden")
                    elif pa.get("authenticated_only"):
                        lines.append(f"   * @auth requires valid JWT / API key (any authenticated user)")
                    else:
                        if pa.get("roles"):
                            lines.append(f"   * @auth roles: {', '.join(pa['roles'])}")
                        if pa.get("authorities"):
                            lines.append(f"   * @auth authorities: {', '.join(pa['authorities'])}")
                else:
                    lines.append(f"   * @auth unknown — check server security configuration")
                # @touches — linked DB tables
                if ep.linked_tables:
                    lines.append(f"   * @touches {', '.join(ep.linked_tables)}")
                # Example request/response comments
                if ep.has_body and ep.body_type:
                    ex_req = build_example(ep.body_type, all_schemas)
                    if ex_req:
                        lines.append(f"   * @example request")
                        for ln in json.dumps(ex_req, indent=2).splitlines():
                            lines.append(f"   *   {ln}")
                if ep.return_type and ep.return_type in schema_names:
                    ex_res = build_example(ep.return_type, all_schemas)
                    if ex_res:
                        lines.append(f"   * @example response")
                        for ln in json.dumps(ex_res, indent=2).splitlines():
                            lines.append(f"   *   {ln}")
                lines.append(f"   */")
                lines.append(f"  {mn}({sig}){ret_ann} {{")

                has_path_vars = bool(ep.path_params)
                path_expr = f"`{_path_to_template(ep.path)}`" if has_path_vars else f"'{ep.path}'"
                extras: list[str] = []
                if ep.has_body:
                    extras.append("body")
                if ep.query_params:
                    qp_obj = "{ " + ", ".join(p["name"] for p in ep.query_params[:6]) + " }"
                    extras.append(f"params: {qp_obj}")
                call_extras = (", { " + ", ".join(extras) + " }") if extras else ""
                lines.append(f"    return this._request('{ep.method}', {path_expr}{call_extras})")
                lines.append("  }")

            lines += ["}", ""]

        # ---- Section 4: Storefront flows ----
        lines += [
            "// " + "─" * 68,
            "// SECTION 4 — Pagination",
            "// " + "─" * 68,
            "//",
            "// Endpoints that return Spring Page<T> accept the following query params:",
            "//   page  — zero-based page index (default: 0)",
            "//   size  — number of items per page (default: 20)",
            "//   sort  — field name and direction, e.g. sort=name,asc or sort=createdAt,desc",
            "//",
            "// The response is a Page<T> object with the structure below.",
            "// Always check totalPages before requesting the next page.",
            "//",
            "",
        ]

        if typescript:
            lines += [
                "export interface PaginatedResponse<T> {",
                "  content: T[]",
                "  totalElements: number",
                "  totalPages: number",
                "  number: number       // current page (zero-based)",
                "  size: number         // page size requested",
                "  first: boolean",
                "  last: boolean",
                "  empty: boolean",
                "}",
                "",
                "// Helper — iterate all pages of a paginated endpoint:",
                "async function* paginate<T>(",
                "  fetcher: (page: number, size: number) => Promise<PaginatedResponse<T>>,",
                "  size = 20,",
                "): AsyncGenerator<T[]> {",
                "  let page = 0",
                "  while (true) {",
                "    const res = await fetcher(page, size)",
                "    yield res.content",
                "    if (res.last) break",
                "    page++",
                "  }",
                "}",
                "",
            ]
        else:
            lines += [
                "// Helper — iterate all pages of a paginated endpoint:",
                "async function* paginate(fetcher, size = 20) {",
                "  let page = 0",
                "  while (true) {",
                "    const res = await fetcher(page, size)",
                "    yield res.content",
                "    if (res.last) break",
                "    page++",
                "  }",
                "}",
                "",
            ]

        # Collect paginated endpoints for the section
        paginated_eps: list[tuple[str, _EndpointInfo]] = []
        for domain, eps in domain_endpoints.items():
            for ep in eps:
                params_lower = {p["name"].lower() for p in ep.query_params}
                if "page" in params_lower or "size" in params_lower:
                    paginated_eps.append((domain, ep))

        if paginated_eps:
            lines += [
                "// Paginated endpoints in this version:",
                "//",
            ]
            for domain, ep in paginated_eps:
                size_param = next((p for p in ep.query_params if p["name"].lower() in ("size", "pagesize", "limit")), None)
                default_size = size_param.get("default_value") if size_param else None
                default_note = f" (default size: {default_size})" if default_size else ""
                lines.append(f"//   {ep.method} {ep.path}{default_note}")
            lines.append("")

        # ---- Section 5: Storefront flows ----
        lines += [
            "// " + "─" * 68,
            "// SECTION 5 — Storefront Code Examples",
            "// " + "─" * 68,
            "//",
            "// The examples below show realistic multi-step flows a storefront",
            "// application would perform.  They are generated from the actual",
            f"// scanned endpoints in version {version} of the platform.",
            "//",
            "// \u26a0 METHOD NAME CAVEAT",
            "// The method names used in these examples (e.g. getOptionsModel) are derived",
            "// from Java bytecode and do not always match the HTTP path. Bytecode method",
            "// names reflect the Java method signature, not the route, so a name like",
            "// getOptionsModel may actually serve /portal/catalog-items/{id}/options-model.",
            "// Always cross-reference with Section 3 (Service Clients) where each method",
            "// is annotated with its exact HTTP verb and path in the JSDoc comment above it.",
            "//",
            "// Usage:",
            "//   const platform = new PlatformClient({",
            "//     baseUrl: 'https://platform.example.com',",
            "//     token: '<jwt-from-login>',",
            "//   })",
            "//",
            "",
        ]

        # PlatformClient wrapper
        if typescript:
            lines += [
                "export interface PlatformClientConfig extends ApiClientConfig {}",
                "",
                "export class PlatformClient {",
            ]
            for domain, cls in domain_class_names.items():
                lines.append(f"  {_camel(domain)}: {cls}")
            lines += [
                "",
                "  constructor(config: PlatformClientConfig) {",
            ]
        else:
            lines += [
                "class PlatformClient {",
                "  constructor(config) {",
            ]

        for domain, cls in domain_class_names.items():
            lines.append(f"    this.{_camel(domain)} = new {cls}(config)")
        lines += ["  }", "}", ""]

        # Flow examples — loaded from storefront_flows.yml
        for flow in _load_flows():
            lines += [
                f"// {'─' * 68}",
                f"// {flow['title']}",
                f"// {flow['description']}",
                f"// {'─' * 68}",
                "",
            ]

            fn_name = _camel(re.sub(r"[^a-zA-Z0-9 ]", "", flow["title"].split("—")[-1].strip()))
            if typescript:
                lines.append(f"async function {fn_name}(platform: PlatformClient): Promise<void> {{")
            else:
                lines.append(f"async function {fn_name}(platform) {{")

            for step in flow["steps"]:
                domain = step["domain"]
                fragment = step["fragment"]
                verb = step["verb"]
                label = step["label"]
                var_name = step.get("var") or _camel(re.sub(r"[^a-zA-Z0-9 ]", "", label))
                poll_cond = step.get("poll")
                step_events = step.get("events") or []
                step_note = step.get("note")

                # Find the best matching real endpoint — prefer longest path match
                eps_for_domain = domain_endpoints.get(domain, [])
                candidates = [
                    e for e in eps_for_domain
                    if e.method == verb and fragment.lower() in e.path.lower()
                ]
                match = max(candidates, key=lambda e: len(e.path)) if candidates else None

                lines.append("")
                if step_note:
                    lines.append(f"  {step_note}")
                lines.append(f"  // Step: {label}")

                if step_events:
                    verified = [e for e in step_events if e in published_events]
                    missing  = [e for e in step_events if e not in published_events]
                    if verified:
                        lines.append(f"  // ⚡ Async events fired: {', '.join(verified)}")
                    if missing and published_events:  # only warn if we have event data at all
                        lines.append(f"  // ⚠ Events not found in this version: {', '.join(missing)}")

                if match:
                    prop = _camel(domain)
                    mn = match.method_name or "call"

                    # Build call arguments
                    args: list[str] = []
                    for p in match.path_params:
                        args.append("'<" + p["name"] + ">'")
                    if match.has_body:
                        bt = match.body_type
                        if bt and bt in all_schemas:
                            schema = all_schemas[bt]
                            req_fields = [
                                f for f in (schema.get("fields") or [])
                                if not f.get("json_ignored") and f.get("required")
                            ][:5]
                            all_fields = [
                                f for f in (schema.get("fields") or [])
                                if not f.get("json_ignored")
                            ][:5]
                            use_fields = req_fields or all_fields
                            body_obj = "{ " + ", ".join(
                                f["json_name"] + ": <" + f["json_name"] + ">"
                                for f in use_fields
                            ) + " }"
                        else:
                            body_obj = "{ /* request body */ }"
                        args.append(body_obj)

                    call = f"platform.{prop}.{mn}({', '.join(args)})"

                    if poll_cond:
                        # Emit a polling loop
                        lines.append(f"  let {var_name} = await {call}")
                        lines.append(f"  while ({poll_cond}) {{")
                        lines.append(f"    await new Promise(r => setTimeout(r, 3000))")
                        lines.append(f"    {var_name} = await {call}")
                        lines.append(f"  }}")
                    else:
                        lines.append(f"  const {var_name} = await {call}")

                    # Emit a schema-driven response shape comment for key return types
                    if match.return_type and match.return_type in all_schemas:
                        schema = all_schemas[match.return_type]
                        fields = [
                            f for f in (schema.get("fields") or [])
                            if not f.get("json_ignored")
                        ][:6]
                        if fields:
                            field_names = ", ".join(f["json_name"] for f in fields)
                            lines.append(f"  // → {match.return_type} {{ {field_names} }}")
                else:
                    lines.append(f"  // ⚠ Endpoint not found in v{version}: {verb} *{fragment}*")

            lines += ["", "}", ""]

        # ---- Section 6: Auth Requirements ----
        lines += [
            "// " + "─" * 68,
            "// SECTION 6 — Auth Requirements",
            "// " + "─" * 68,
            "//",
            "// Every endpoint's authentication requirement, derived from",
            "// @PreAuthorize / @Secured / @RolesAllowed annotations in the bytecode.",
            "//",
            "// Legend:",
            "//   PUBLIC          — no token required",
            "//   AUTHENTICATED   — any valid JWT / API key",
            "//   ROLE:<name>     — token must carry the named role",
            "//   AUTHORITY:<name>— token must carry the named authority/scope",
            "//   UNKNOWN         — no security annotation found; assume authenticated",
            "//",
            "",
        ]

        # Collect all unique roles and authorities across public endpoints
        all_roles: dict[str, list[str]] = {}   # role -> ["METHOD /path", ...]
        all_auths: dict[str, list[str]] = {}   # authority -> [...]
        public_eps: list[str] = []
        auth_only_eps: list[str] = []
        unknown_eps: list[str] = []

        for domain, eps in domain_endpoints.items():
            for ep in eps:
                label = f"{ep.method} {ep.path}"
                pa = ep.parsed_auth
                if not pa:
                    unknown_eps.append(label)
                elif pa.get("public"):
                    public_eps.append(label)
                elif pa.get("authenticated_only"):
                    auth_only_eps.append(label)
                else:
                    for role in pa.get("roles", []):
                        all_roles.setdefault(role, []).append(label)
                    for authority in pa.get("authorities", []):
                        all_auths.setdefault(authority, []).append(label)
                    if not pa.get("roles") and not pa.get("authorities"):
                        unknown_eps.append(label)

        if all_roles:
            lines.append("// Roles required:")
            for role, eps_list in sorted(all_roles.items()):
                lines.append(f"//   ROLE:{role} ({len(eps_list)} endpoint{'s' if len(eps_list) != 1 else ''})")
                for ep_label in eps_list:
                    lines.append(f"//     - {ep_label}")
            lines.append("//")

        if all_auths:
            lines.append("// Authorities / scopes required:")
            for authority, eps_list in sorted(all_auths.items()):
                lines.append(f"//   AUTHORITY:{authority} ({len(eps_list)} endpoint{'s' if len(eps_list) != 1 else ''})")
                for ep_label in eps_list:
                    lines.append(f"//     - {ep_label}")
            lines.append("//")

        if public_eps:
            lines.append(f"// Public endpoints (no auth): {len(public_eps)}")
            for ep_label in public_eps:
                lines.append(f"//   - {ep_label}")
            lines.append("//")

        if auth_only_eps:
            lines.append(f"// Authenticated (any role): {len(auth_only_eps)}")
            lines.append("//")

        if unknown_eps:
            lines.append(f"// Unknown / no annotation ({len(unknown_eps)} endpoints) — treat as requiring authentication.")
            lines.append("//")

        lines.append("")

        # ---- Section 7: Service Topology ----
        lines += [
            "// " + "─" * 68,
            "// SECTION 7 — Service Topology",
            "// " + "─" * 68,
            "//",
            "// The Mermaid diagram below shows inter-service dependencies derived from:",
            "//   • Consumed events (async messaging via RabbitMQ)",
            "//   • Nginx upstream proxy configuration",
            "//   • Frontend API URL configuration",
            "//",
            "// Paste into https://mermaid.live to render interactively.",
            "//",
            "",
        ]

        # Build graph from services data
        try:
            from app.services.jar_analyser.dependency_graph import build_dependency_graph, graph_to_mermaid
            graph = build_dependency_graph(services)
            mermaid = graph_to_mermaid(graph)
            lines.append("// ```mermaid")
            for mline in mermaid.splitlines():
                lines.append(f"// {mline}")
            lines.append("// ```")
            lines.append("//")
            # Text summary of edges
            event_edges = [e for e in graph["edges"] if e["via"] == "event"]
            nginx_edges = [e for e in graph["edges"] if e["via"] == "nginx"]
            api_edges = [e for e in graph["edges"] if e["via"] == "api_url"]
            if event_edges:
                lines.append(f"// Event dependencies ({len(event_edges)}):")
                for e in event_edges[:20]:
                    lbl = f" [{e['label']}]" if e.get("label") else ""
                    lines.append(f"//   {e['from']} → {e['to']}{lbl}")
                lines.append("//")
            if nginx_edges:
                lines.append(f"// Nginx proxy routes ({len(nginx_edges)}):")
                for e in nginx_edges[:20]:
                    lines.append(f"//   {e['from']} → {e['to']}")
                lines.append("//")
            if api_edges:
                lines.append(f"// Frontend API calls ({len(api_edges)}):")
                for e in api_edges[:20]:
                    lines.append(f"//   {e['from']} → {e['to']} ({e['label']})")
                lines.append("//")
        except Exception:
            lines.append("// (Topology data not available for this report)")

        lines.append("")

        # ---- Section 8: Event Bus ----
        lines += [
            "// " + "\u2500" * 68,
            "// SECTION 8 \u2014 Event Bus",
            "// " + "\u2500" * 68,
            "//",
            "// Cross-service RabbitMQ event topology extracted from bytecode and event YMLs.",
            "// Format: Publisher \u2192 entity/action \u2192 Consumer(s)",
            "// Payload class links to the TypeScript interface in Section 1 where available.",
            "//",
            "",
        ]

        # Build cross-service event topology from services data
        # publisher_map: service_name -> [(entity, action, payload_class, consumers[])]
        publisher_map: dict[str, list[tuple]] = {}
        for svc in services:
            svc_name = svc["name"]
            for ef in (svc.get("event_files") or []):
                for pub in (ef.get("published") or []):
                    entity = pub.get("entity", "")
                    payload_cls = pub.get("payload_class")
                    payload_simple = payload_cls.rsplit(".", 1)[-1] if payload_cls else None
                    consumers = pub.get("consumers") or []
                    for action in (pub.get("actions") or [""]):
                        publisher_map.setdefault(svc_name, []).append(
                            (entity, action, payload_simple, consumers)
                        )

        if publisher_map:
            for pub_svc in sorted(publisher_map):
                events = publisher_map[pub_svc]
                lines.append(f"// Publisher: {pub_svc}")
                for entity, action, payload_simple, consumers in events:
                    event_key = f"{entity}/{action}" if action else entity
                    payload_note = f"  [{payload_simple}]" if payload_simple and payload_simple in schema_names else ""
                    consumer_note = f"  \u2192 {', '.join(consumers)}" if consumers else "  \u2192 (no declared consumers)"
                    lines.append(f"//   {event_key:<50s}{payload_note}")
                    lines.append(f"//   {consumer_note}")
                lines.append("//")
        else:
            lines.append("// (No event definitions found in this version)")

        lines.append("")

        # ---- Section 9: Environment Variables ----
        lines += [
            "// " + "\u2500" * 68,
            "// SECTION 9 \u2014 Environment Variables",
            "// " + "\u2500" * 68,
            "//",
            "// All ${placeholder} variables found across every service config file.",
            "// Set these in your deployment environment before starting the platform.",
            "//",
            "",
        ]

        try:
            from app.services.jar_analyser.placeholder_catalogue import build_placeholder_catalogue
            catalogue = build_placeholder_catalogue(services)
            if catalogue:
                # Group by category; within each category mandatory vars come first
                by_cat: dict[str, list] = {}
                for entry in catalogue:
                    by_cat.setdefault(entry['category'], []).append(entry)
                for cat, entries in sorted(by_cat.items()):
                    mandatory = [e for e in entries if e['mandatory']]
                    optional  = [e for e in entries if not e['mandatory']]
                    lines.append(f"// [{cat.upper()}]")
                    for e in mandatory + optional:
                        svc_note = ', '.join(e['services'][:4])
                        if len(e['services']) > 4:
                            svc_note += f" +{len(e['services']) - 4} more"
                        if e['mandatory']:
                            lines.append(f"//   {e['var_name']:<55s}  // ⚠ REQUIRED — no default")
                        else:
                            default_note = f"  (default: {e['default_value']})"
                            lines.append(f"//   {e['var_name']:<55s}{default_note}")
                        lines.append(f"//     used by: {svc_note}")
                lines.append("//")
            else:
                lines.append("// (No placeholder variables found in this version)")
        except Exception:
            lines.append("// (Environment variable data not available)")

        lines.append("")

        # ---- Section 10: Database Schema ----
        lines += [
            "// " + "\u2500" * 68,
            "// SECTION 10 \u2014 Database Schema",
            "// " + "\u2500" * 68,
            "//",
            "// Current-state DB schema reconstructed by replaying Flyway migrations",
            "// in version order.  Only services with migration scripts are listed.",
            "//",
            "",
        ]

        try:
            from app.services.jar_analyser.schema_reconstructor import reconstruct_schema, schema_to_dict
            any_schema = False
            for svc in services:
                svc_name = svc["name"]
                migrations = svc.get("migration_scripts") or []
                if not migrations:
                    continue
                tables = reconstruct_schema(migrations)
                if not tables:
                    continue
                any_schema = True
                lines.append(f"// \u2500\u2500\u2500 {svc_name} ({'─' * max(0, 60 - len(svc_name))})")
                for tbl in schema_to_dict(tables):
                    pk_note = f"  PK: {', '.join(tbl['primary_key'])}" if tbl["primary_key"] else ""
                    lines.append(f"//   {tbl['table']}{pk_note}")
                    for col in tbl["columns"]:
                        null_note = "" if col["nullable"] else "  NOT NULL"
                        pk_flag = "  [PK]" if col["primary_key"] or col["name"] in tbl["primary_key"] else ""
                        default_note = f"  default={col['default']}" if col["default"] is not None else ""
                        lines.append(f"//     {col['name']:<30s} {col['type']:<20s}{null_note}{pk_flag}{default_note}")
                    if tbl["foreign_keys"]:
                        for fk in tbl["foreign_keys"]:
                            lines.append(f"//     FK ({', '.join(fk['columns'])}) \u2192 {fk['references']} ({', '.join(fk['ref_columns'])})")
                    lines.append("//")
            if not any_schema:
                lines.append("// (No Flyway migration scripts found in this version)")
        except Exception:
            lines.append("// (Database schema data not available)")

        lines.append("")

        # ---- Exports ----
        if typescript:
            export_names = list(domain_class_names.values()) + ["PlatformClient", "ApiClient", "ApiError"]
            lines += [
                "export {",
                *[f"  {n}," for n in export_names],
                "}",
                "",
                "export default PlatformClient",
            ]
        else:
            export_names = list(domain_class_names.values()) + ["PlatformClient", "ApiClient", "ApiError"]
            lines += [
                "module.exports = {",
                *[f"  {n}," for n in export_names],
                "}",
                "",
            ]

        return "\n".join(lines)
