"""Spring Cloud Gateway route extractor.

Extracts route definitions from three sources, in order of reliability:

1. YAML/properties config  — spring.cloud.gateway.routes[*]
   Confidence: HIGH.  The route id, predicates (Path, Method, Host),
   filters, and target URI are all present verbatim.

2. Java RouteLocator @Bean — @Configuration class with a @Bean method
   returning RouteLocator, built via RouteLocatorBuilder DSL.
   Confidence: MEDIUM.  We scan the constant pool of the class file for
   string literals that look like paths/URIs and correlate them with the
   method name.  We cannot reconstruct the full predicate chain without
   executing the code, but we can extract the path patterns and lb:// URIs.

3. RouterFunction @Bean — Spring WebFlux functional routing.
   Confidence: MEDIUM.  Same constant-pool string scan approach.

Results are returned as Endpoint objects with:
  - controller_class  = the config class or "GatewayConfig (YAML)"
  - http_method       = extracted from Method predicate, or "ANY"
  - full_path         = extracted from Path predicate
  - source_annotation = "SCG:yaml" | "SCG:bean" | "SCG:router"
  - confidence        = "HIGH" | "MEDIUM"
  - base_path         = the lb:// or http:// target URI (stored in base_path
                        field so it's visible without schema changes)
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from .endpoints import Endpoint, ReturnType
from .classfile import ClassFileParser

# ---------------------------------------------------------------------------
# Annotation descriptors for gateway-related beans
# ---------------------------------------------------------------------------
_CONFIGURATION  = "Lorg/springframework/context/annotation/Configuration;"
_BEAN           = "Lorg/springframework/context/annotation/Bean;"
_COMPONENT      = "Lorg/springframework/stereotype/Component;"

# Return type descriptors that indicate a gateway bean
_ROUTE_LOCATOR_DESC  = "Lorg/springframework/cloud/gateway/route/RouteLocator;"
_ROUTER_FUNCTION_DESC = "Lorg/springframework/web/reactive/function/server/RouterFunction;"

# Patterns for path-like strings in constant pools
_PATH_RE   = re.compile(r"^(/[a-zA-Z0-9_\-/{}*?]+)$")
_LB_URI_RE = re.compile(r"^(lb://[a-zA-Z0-9_\-]+|https?://[^\s]+)$")
_METHOD_RE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$")

# YAML key patterns
_GATEWAY_ROUTES_KEY = re.compile(r"^spring\.cloud\.gateway\.routes")


class GatewayRouteExtractor:

    @classmethod
    def from_jar(cls, jar_path: Path) -> list[Endpoint]:
        """Extract all gateway routes from a JAR file."""
        endpoints: list[Endpoint] = []
        try:
            with zipfile.ZipFile(jar_path, "r") as zf:
                endpoints.extend(cls._from_yaml(zf))
                endpoints.extend(cls._from_bytecode(zf))
        except (zipfile.BadZipFile, Exception):
            pass
        return endpoints

    # ------------------------------------------------------------------
    # Source 1: YAML config
    # ------------------------------------------------------------------

    @classmethod
    def _from_yaml(cls, zf: zipfile.ZipFile) -> list[Endpoint]:
        endpoints: list[Endpoint] = []
        if not _YAML_AVAILABLE:
            return endpoints

        yaml_entries = [
            n for n in zf.namelist()
            if n.endswith((".yml", ".yaml"))
            and ("application" in n.lower() or "bootstrap" in n.lower())
        ]

        for entry in yaml_entries:
            try:
                content = zf.read(entry).decode("utf-8", errors="replace")
                doc = _yaml.safe_load(content)
                if not isinstance(doc, dict):
                    continue
                routes = _deep_get(doc, ["spring", "cloud", "gateway", "routes"])
                if not isinstance(routes, list):
                    continue
                for route in routes:
                    eps = cls._parse_yaml_route(route, entry)
                    endpoints.extend(eps)
            except Exception:
                continue

        return endpoints

    @classmethod
    def _parse_yaml_route(cls, route: Any, source_file: str) -> list[Endpoint]:
        if not isinstance(route, dict):
            return []

        route_id  = str(route.get("id", "unknown"))
        uri       = str(route.get("uri", ""))
        predicates = route.get("predicates") or []
        filters    = route.get("filters") or []

        # Extract paths and methods from predicates
        paths:   list[str] = []
        methods: list[str] = []

        for pred in predicates:
            pred_str = str(pred)
            # Path=... or Path=/foo/**
            m = re.match(r"Path\s*=\s*(.+)", pred_str)
            if m:
                for p in m.group(1).split(","):
                    p = p.strip()
                    if p:
                        paths.append(p)
                continue
            # Method=GET,POST
            m = re.match(r"Method\s*=\s*(.+)", pred_str)
            if m:
                for meth in m.group(1).split(","):
                    meth = meth.strip().upper()
                    if meth:
                        methods.append(meth)
                continue
            # Dict-style: {Path: /foo}
            if isinstance(pred, dict):
                if "Path" in pred:
                    val = pred["Path"]
                    for p in (val if isinstance(val, list) else [val]):
                        paths.append(str(p))
                if "Method" in pred:
                    val = pred["Method"]
                    for meth in (val if isinstance(val, list) else [val]):
                        methods.append(str(meth).upper())

        if not paths:
            paths = [f"/gateway-route/{route_id}"]

        if not methods:
            methods = ["ANY"]

        # Build filter summary for the method_name field
        filter_summary = "; ".join(str(f) for f in filters[:5]) if filters else ""

        result: list[Endpoint] = []
        for path in paths:
            for method in methods:
                result.append(Endpoint(
                    controller_class=f"GatewayConfig (YAML:{source_file})",
                    controller_simple="GatewayConfig",
                    http_method=method,
                    path=path,
                    full_path=path,
                    base_path=uri,          # lb://service-name stored here
                    method_name=route_id,
                    parameters=[],
                    request_body=None,
                    return_type=ReturnType("RouteLocator", "RouteLocator"),
                    security=None,
                    confidence="HIGH",
                    source_annotation="SCG:yaml",
                ))
        return result

    # ------------------------------------------------------------------
    # Source 2 & 3: Bytecode constant-pool scan
    # ------------------------------------------------------------------

    @classmethod
    def _from_bytecode(cls, zf: zipfile.ZipFile) -> list[Endpoint]:
        endpoints: list[Endpoint] = []

        class_entries = [
            n for n in zf.namelist()
            if n.endswith(".class") and not n.endswith("module-info.class")
            and not any(n.startswith(skip) for skip in (
                "org/springframework/", "com/google/", "org/apache/",
                "io/netty/", "com/fasterxml/", "reactor/",
            ))
        ]

        for entry in class_entries:
            try:
                data = zf.read(entry)
                eps = cls._scan_class_bytes(data, entry)
                endpoints.extend(eps)
            except Exception:
                continue

        return endpoints

    @classmethod
    def _scan_class_bytes(cls, data: bytes, entry: str) -> list[Endpoint]:
        """Scan a class file for gateway bean methods."""
        try:
            ci = ClassFileParser.parse(data)
        except Exception:
            return []

        # Must be a @Configuration or @Component class
        ann_descs = {a.descriptor for a in ci.annotations}
        if not (_CONFIGURATION in ann_descs or _COMPONENT in ann_descs):
            return []

        endpoints: list[Endpoint] = []

        for method in ci.methods:
            method_ann_descs = {a.descriptor for a in method.annotations}
            if _BEAN not in method_ann_descs:
                continue

            # Check return type
            ret_desc = method.descriptor.rsplit(")", 1)[-1] if ")" in method.descriptor else ""
            is_route_locator  = _ROUTE_LOCATOR_DESC.rstrip(";") in ret_desc
            is_router_function = _ROUTER_FUNCTION_DESC.rstrip(";") in ret_desc

            if not (is_route_locator or is_router_function):
                continue

            source_tag = "SCG:bean" if is_route_locator else "SCG:router"

            # Extract string constants from the raw class bytes that look
            # like paths or lb:// URIs.  We scan the whole class constant
            # pool (already parsed) for Utf8 entries matching our patterns.
            # This is imprecise but catches the common DSL patterns:
            #   .route(r -> r.path("/api/foo/**").uri("lb://foo-service"))
            paths, uris, methods = cls._extract_strings_from_pool(data)

            if not paths:
                # No path found — emit a placeholder so the route is visible
                paths = [f"/{ci.simple_name}/{method.name}"]

            uri = uris[0] if uris else ""
            http_methods = methods if methods else ["ANY"]

            for path in paths:
                for http_method in http_methods:
                    endpoints.append(Endpoint(
                        controller_class=ci.java_class_name,
                        controller_simple=ci.simple_name,
                        http_method=http_method,
                        path=path,
                        full_path=path,
                        base_path=uri,
                        method_name=method.name,
                        parameters=[],
                        request_body=None,
                        return_type=ReturnType("RouteLocator", "RouteLocator"),
                        security=None,
                        confidence="MEDIUM",
                        source_annotation=source_tag,
                    ))

        return endpoints

    @classmethod
    def _extract_strings_from_pool(
        cls, data: bytes
    ) -> tuple[list[str], list[str], list[str]]:
        """
        Re-read the constant pool from raw bytes and collect Utf8 strings
        that look like paths, lb:// URIs, or HTTP method names.

        We re-read rather than using the already-parsed ClassInfo because
        ClassFileParser only exposes strings that appear in annotations —
        we need all Utf8 constants including those in the Code attribute.
        """
        paths:   list[str] = []
        uris:    list[str] = []
        methods: list[str] = []

        try:
            import struct
            pos = 8  # skip magic + minor + major
            count = struct.unpack_from(">H", data, pos)[0]
            pos += 2
            i = 1
            while i < count:
                tag = data[pos]
                pos += 1
                if tag == 1:  # Utf8
                    length = struct.unpack_from(">H", data, pos)[0]
                    pos += 2
                    s = data[pos:pos + length].decode("utf-8", errors="replace")
                    pos += length
                    if _PATH_RE.match(s) and len(s) > 1:
                        paths.append(s)
                    elif _LB_URI_RE.match(s):
                        uris.append(s)
                    elif _METHOD_RE.match(s):
                        methods.append(s)
                elif tag in (5, 6):  # Long, Double — take two slots
                    pos += 8
                    i += 1
                elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
                    pos += 4
                elif tag in (7, 8, 16, 19, 20):
                    pos += 2
                elif tag == 15:
                    pos += 3
                else:
                    break  # unknown tag — stop
                i += 1
        except Exception:
            pass

        # Deduplicate, filter out descriptor-like strings (contain semicolons/brackets)
        paths  = [p for p in dict.fromkeys(paths)  if ";" not in p and "[" not in p]
        uris   = list(dict.fromkeys(uris))
        methods = list(dict.fromkeys(methods))

        return paths, uris, methods


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deep_get(d: dict, keys: list[str]) -> Any:
    """Safely traverse a nested dict."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur
