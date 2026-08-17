"""Request / response example generator.

Builds realistic JSON example payloads from extracted DTO schemas.
Seed values are derived from field names so examples look plausible.
"""
from __future__ import annotations

import re
import uuid as _uuid

# ---------------------------------------------------------------------------
# Seed value heuristics — keyed on lowercase field-name fragments
# ---------------------------------------------------------------------------

_STRING_SEEDS: list[tuple[str, str]] = [
    ("email",       "user@example.com"),
    ("phone",       "+1-555-0100"),
    ("url",         "https://example.com"),
    ("uri",         "https://example.com/resource"),
    ("password",    "••••••••"),
    ("token",       "<bearer-token>"),
    ("secret",      "<secret>"),
    ("key",         "<api-key>"),
    ("uuid",        str(_uuid.UUID(int=0x3fa85f6457174562b3fc2c963f66afa6))),
    ("id",          str(_uuid.UUID(int=0x3fa85f6457174562b3fc2c963f66afa6))),
    ("name",        "Example Name"),
    ("title",       "Example Title"),
    ("description", "Example description text."),
    ("message",     "Example message."),
    ("code",        "EXAMPLE_CODE"),
    ("type",        "EXAMPLE_TYPE"),
    ("status",      "ACTIVE"),
    ("state",       "ACTIVE"),
    ("path",        "/example/path"),
    ("host",        "host.example.com"),
    ("address",     "123 Example Street"),
    ("city",        "Example City"),
    ("country",     "US"),
    ("locale",      "en-US"),
    ("currency",    "USD"),
    ("version",     "1.0.0"),
    ("tag",         "example-tag"),
    ("label",       "example-label"),
    ("note",        "Example note."),
    ("comment",     "Example comment."),
    ("reason",      "Example reason."),
    ("category",    "GENERAL"),
    ("group",       "default"),
    ("role",        "USER"),
    ("scope",       "read"),
    ("format",      "JSON"),
    ("encoding",    "UTF-8"),
    ("content",     "Example content."),
    ("text",        "Example text."),
    ("value",       "example-value"),
    ("data",        "example-data"),
    ("hash",        "a1b2c3d4e5f6"),
    ("checksum",    "a1b2c3d4e5f6"),
    ("date",        "2024-01-15"),
    ("time",        "12:00:00"),
    ("timestamp",   "2024-01-15T12:00:00Z"),
    ("created",     "2024-01-15T12:00:00Z"),
    ("updated",     "2024-01-15T12:00:00Z"),
    ("expires",     "2025-01-15T12:00:00Z"),
    ("start",       "2024-01-15T12:00:00Z"),
    ("end",         "2024-01-15T13:00:00Z"),
]

_INT_SEEDS: list[tuple[str, int]] = [
    ("port",     8080),
    ("count",    10),
    ("total",    100),
    ("size",     20),
    ("page",     1),
    ("limit",    50),
    ("offset",   0),
    ("index",    0),
    ("order",    1),
    ("priority", 1),
    ("quantity", 1),
    ("amount",   100),
    ("price",    9999),
    ("cost",     9999),
    ("age",      30),
    ("year",     2024),
    ("month",    1),
    ("day",      15),
    ("hour",     12),
    ("minute",   0),
    ("second",   0),
    ("timeout",  30),
    ("retry",    3),
    ("max",      100),
    ("min",      0),
]

_FLOAT_SEEDS: list[tuple[str, float]] = [
    ("price",     99.99),
    ("cost",      99.99),
    ("amount",    100.00),
    ("rate",      0.05),
    ("ratio",     1.0),
    ("factor",    1.0),
    ("weight",    1.0),
    ("score",     0.95),
    ("latitude",  51.5074),
    ("longitude", -0.1278),
]

# Constraint annotation parsers
_RE_SIZE_MAX = re.compile(r"@Size\s*\([^)]*\bmax\s*=\s*(\d+)", re.IGNORECASE)
_RE_SIZE_MIN = re.compile(r"@Size\s*\([^)]*\bmin\s*=\s*(\d+)", re.IGNORECASE)
_RE_MIN_VAL  = re.compile(r"@Min\s*\(\s*(?:value\s*=\s*)?(\d+)", re.IGNORECASE)
_RE_MAX_VAL  = re.compile(r"@Max\s*\(\s*(?:value\s*=\s*)?(\d+)", re.IGNORECASE)
_RE_PATTERN  = re.compile(r'@Pattern\s*\([^)]*regexp\s*=\s*["\']([^"\']+)', re.IGNORECASE)


def _parse_constraints(constraints: object) -> dict:
    """Normalise constraints into a plain dict regardless of source format.

    Constraints are stored as a list of annotation strings, e.g.
    ["@Size(max=255)", "@NotBlank"], but may also arrive as a dict from
    older data.
    """
    if not constraints:
        return {}
    if isinstance(constraints, dict):
        return constraints
    result: dict = {}
    for item in constraints:
        s = str(item)
        m = _RE_SIZE_MAX.search(s)
        if m:
            result["maxLength"] = int(m.group(1))
        m = _RE_SIZE_MIN.search(s)
        if m:
            result["minLength"] = int(m.group(1))
        m = _RE_MIN_VAL.search(s)
        if m:
            result["minimum"] = int(m.group(1))
        m = _RE_MAX_VAL.search(s)
        if m:
            result["maximum"] = int(m.group(1))
        m = _RE_PATTERN.search(s)
        if m:
            result["pattern"] = m.group(1)
    return result


def _seed_string(name: str, constraints: object) -> str:
    nl = name.lower()
    for fragment, value in _STRING_SEEDS:
        if fragment in nl:
            return value
    c = _parse_constraints(constraints)
    if c.get("pattern"):
        return "<matches: " + str(c["pattern"])[:30] + ">"
    max_len = c.get("maxLength")
    if max_len and int(max_len) < 10:
        return "x" * max(1, int(c.get("minLength", 1)))
    return f"<{name}>"


def _seed_int(name: str, constraints: object) -> int:
    nl = name.lower()
    for fragment, value in _INT_SEEDS:
        if fragment in nl:
            return value
    c = _parse_constraints(constraints)
    mn = c.get("minimum")
    if mn is not None:
        return int(mn)
    return 0


def _seed_float(name: str, constraints: object) -> float:
    nl = name.lower()
    for fragment, value in _FLOAT_SEEDS:
        if fragment in nl:
            return value
    c = _parse_constraints(constraints)
    mn = c.get("minimum")
    if mn is not None:
        return float(mn)
    return 0.0


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------

def build_example(
    type_name: str,
    all_schemas: dict[str, dict],
    _depth: int = 0,
) -> object:
    """Recursively build an example value for a given type name.

    Returns a Python object (dict/list/str/int/float/bool/None) suitable
    for JSON serialisation.
    """
    if _depth > 4:
        return {}

    schema = all_schemas.get(type_name)
    if not schema:
        return _primitive_for_type(type_name)

    if schema.get("is_enum"):
        values = schema.get("enum_values") or []
        if values:
            first = values[0]
            return first.get("serialised_as") or first.get("name") or type_name
        return type_name

    fields = [f for f in (schema.get("fields") or []) if not f.get("json_ignored")]
    if not fields:
        return {}

    obj: dict = {}
    for f in fields:
        name = f.get("json_name") or f.get("name") or "field"
        constraints = f.get("constraints") or []
        simple_type = f.get("simple_type") or ""
        openapi_type = f.get("openapi_type") or "string"
        openapi_format = f.get("openapi_format") or ""
        is_collection = f.get("is_collection", False)
        elem_type = f.get("collection_element_type") or ""
        is_map = f.get("is_map", False)

        if is_map:
            obj[name] = {}
            continue

        if is_collection:
            if elem_type and elem_type in all_schemas:
                obj[name] = [build_example(elem_type, all_schemas, _depth + 1)]
            elif elem_type:
                obj[name] = [_primitive_for_type(elem_type)]
            else:
                obj[name] = []
            continue

        # Nested DTO
        if openapi_type == "object" and simple_type in all_schemas:
            obj[name] = build_example(simple_type, all_schemas, _depth + 1)
            continue

        # Enum field
        if simple_type in all_schemas and all_schemas[simple_type].get("is_enum"):
            obj[name] = build_example(simple_type, all_schemas, _depth + 1)
            continue

        # Primitives
        if openapi_type == "integer":
            obj[name] = _seed_int(name, constraints)
        elif openapi_type == "number":
            obj[name] = _seed_float(name, constraints)
        elif openapi_type == "boolean":
            obj[name] = True
        elif openapi_type == "null":
            obj[name] = None
        elif openapi_format == "date-time":
            obj[name] = "2024-01-15T12:00:00Z"
        elif openapi_format == "date":
            obj[name] = "2024-01-15"
        elif openapi_format == "uuid":
            obj[name] = str(_uuid.UUID(int=0x3fa85f6457174562b3fc2c963f66afa6))
        else:
            obj[name] = _seed_string(name, constraints)

    return obj


def _primitive_for_type(type_name: str) -> object:
    t = (type_name or "").lower()
    if any(x in t for x in ("int", "long", "short", "byte")):
        return 0
    if any(x in t for x in ("float", "double", "decimal", "bigdecimal")):
        return 0.0
    if "bool" in t:
        return True
    if t in ("void", "null"):
        return None
    if any(x in t for x in ("list", "set", "collection", "[]")):
        return []
    if any(x in t for x in ("map", "object")):
        return {}
    return f"<{type_name}>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_examples(
    endpoint: dict,
    all_schemas: dict[str, dict],
) -> dict:
    """Return { request: obj|None, response: obj|None } for an endpoint dict."""
    request_example = None
    response_example = None

    body = endpoint.get("request_body")
    if body:
        bt = body.get("simple_type") or body.get("java_type") or ""
        if bt and bt != "void":
            request_example = build_example(bt, all_schemas)

    ret = endpoint.get("return_type")
    if ret:
        rt = ret.get("simple_type") or ret.get("java_type") or ""
        gp = ret.get("generic_parameter") or ""
        if rt and rt not in ("void", "Void", "ResponseEntity"):
            if rt in all_schemas:
                response_example = build_example(rt, all_schemas)
            elif gp and gp in all_schemas:
                response_example = build_example(gp, all_schemas)
            else:
                response_example = _primitive_for_type(rt)

    return {"request": request_example, "response": response_example}
