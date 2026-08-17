"""Outbound HTTP integration discovery — which external systems a service
calls out to, found statically from Feign client declarations and
@Value-injected config keys that look like URL/host/endpoint targets.

Companion to endpoints.py and the string-constant extraction in job.py:
Endpoints covers INBOUND REST endpoints a service exposes; this covers
OUTBOUND calls a service makes to systems outside the analysed bundle (e.g.
a Feign client pointed at a third-party API like vRA), so "which service
talks to vRA, at what URL" is answerable without runtime tracing.

Two independent sources, since Feign clients are unambiguous (an
annotation with explicit target attributes) while @Value config injection
is a heuristic correlation — a String field annotated with @Value whose
placeholder key merely *looks* like a URL/host config key is a strong
signal, not proof the field is ever actually used to build an outbound
call (that would need reading the method body, which this tool's
structural parser deliberately never does — see classfile.py's own
docstring, and Section 36's Decompilation for why that's a separate,
heavier, on-demand feature):

  - Feign clients: @FeignClient(name=..., url=..., value=...) on an
    interface — name/value identify the logical target, url is the literal
    or placeholder-expressed base URL.
  - @Value-injected fields: any field carrying @Value("${some.key}") where
    the key matches the same url|uri|host|address heuristic already used by
    placeholder_catalogue.py's own category inference, resolved against
    this service's own config files when the value is actually set there.

Deliberately does NOT filter Feign clients to only those with a literal
`url` — a client declared with only `name` (resolved via Eureka/service
discovery at runtime) still tells you "this class integrates with a
logical service named X", even without a resolvable literal URL.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.jar_analyser.classfile import ClassInfo

FEIGN_CLIENT = "Lorg/springframework/cloud/openfeign/FeignClient;"
VALUE_ANNOTATION = "Lorg/springframework/beans/factory/annotation/Value;"

# Same heuristic as placeholder_catalogue.py's own "url" category rule —
# duplicated locally (one short regex) rather than importing across modules,
# matching this codebase's existing tolerance for small duplicated
# heuristics over cross-module coupling for a single pattern.
_URL_KEY_RE = re.compile(r"url|uri|host|address", re.I)
_PLACEHOLDER_RE = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")


@dataclass
class OutboundIntegration:
    kind: str              # "feign_client" | "config_value"
    class_name: str        # dotted (java_class_name)
    target: str            # Feign client's declared name/value, or the field name
    config_key: str | None
    raw_value: str | None       # the literal annotation value / placeholder expression
    resolved_value: str | None  # looked up from this service's own config, if found


def extract_outbound_integrations(
    classes: list[ClassInfo], config_lookup: dict[str, str]
) -> list[OutboundIntegration]:
    results: list[OutboundIntegration] = []
    for c in classes:
        for ann in c.annotations:
            if ann.descriptor != FEIGN_CLIENT:
                continue
            name = ann.get("name") or ann.get("value")
            url = ann.get("url")
            raw = url or name
            results.append(OutboundIntegration(
                kind="feign_client", class_name=c.java_class_name,
                target=str(name or url or c.simple_name),
                config_key=_placeholder_key(raw) if isinstance(raw, str) else None,
                raw_value=raw if isinstance(raw, str) else None,
                resolved_value=_resolve(raw, config_lookup) if isinstance(raw, str) else None,
            ))

        for f in c.fields:
            for ann in f.annotations:
                if ann.descriptor != VALUE_ANNOTATION:
                    continue
                raw = ann.get("value")
                if not isinstance(raw, str):
                    continue
                key = _placeholder_key(raw)
                if not key or not _URL_KEY_RE.search(key):
                    continue
                results.append(OutboundIntegration(
                    kind="config_value", class_name=c.java_class_name,
                    target=f.name, config_key=key, raw_value=raw,
                    resolved_value=_resolve(raw, config_lookup),
                ))
    return results


def _placeholder_key(value: str | None) -> str | None:
    if not value:
        return None
    m = _PLACEHOLDER_RE.search(value)
    return m.group(1) if m else None


def _resolve(raw: str | None, config_lookup: dict[str, str]) -> str | None:
    if not raw:
        return None
    m = _PLACEHOLDER_RE.search(raw)
    if not m:
        return raw  # already a literal, not a placeholder
    key, default = m.group(1), m.group(2)
    return config_lookup.get(key) or default
