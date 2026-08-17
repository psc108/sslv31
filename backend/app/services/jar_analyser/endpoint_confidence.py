"""Stage 5 of the dissection accuracy plan — honest confidence & opacity flagging.

Endpoint confidence today (endpoints.py) is derived purely from annotation
clarity: whether the mapping annotation's path parsed cleanly. It says
nothing about whether the *payload shape* is actually known. A fully-resolved
DTO and a raw `ResponseEntity<?>` currently get reported identically.

Bytecode method descriptors erase generics (JVMS §4.3.3) — a return type of
`ResponseEntity<CustomerDto>` and `ResponseEntity<?>` produce the exact same
descriptor tail. `endpoints.py`'s `ReturnType.generic_parameter` is therefore
always "unknown" in practice; the wrapped payload type for any generic
container is fundamentally unrecoverable from the descriptor alone. This
module makes that boundary visible instead of reporting those endpoints as
fully characterised.
"""
from __future__ import annotations

# Concrete JDK/wrapper scalar types whose "shape" needs no further resolution.
_WELL_KNOWN_SCALARS = {
    "string", "integer", "int", "long", "boolean", "double", "float",
    "bigdecimal", "biginteger", "uuid", "localdate", "localdatetime",
    "localtime", "instant", "date", "offsetdatetime", "zoneddatetime",
    "byte", "short", "char", "character", "void",
}

# Generic containers whose element/wrapped type is erased at the bytecode
# level and can never be recovered from the method descriptor — always opaque
# regardless of what's written between the angle brackets in source.
_OPAQUE_CONTAINERS = {
    "responseentity", "response", "list", "collection", "set", "map",
    "optional", "iterable", "page", "slice", "stream", "completablefuture",
    "mono", "flux",
}

# Directly opaque payload types — no shape information at all.
_OPAQUE_DIRECT = {"object", "jsonnode", "objectnode", "void"}


def _is_resolved(simple_type: str | None, known_dto_names: set[str]) -> bool:
    """Whether a payload's shape is actually knowable from static extraction."""
    if not simple_type:
        return True  # no type at all (e.g. void return) — nothing to characterise
    base = simple_type[:-2] if simple_type.endswith("[]") else simple_type
    key = base.lower()
    if key in _OPAQUE_CONTAINERS or key in _OPAQUE_DIRECT:
        return False
    if key in _WELL_KNOWN_SCALARS:
        return True
    return base in known_dto_names


def refine_endpoint_confidence(endpoints: list[dict], dto_schemas: list[dict]) -> None:
    """Mutate each endpoint dict in place.

    Combines the existing annotation-clarity confidence with return-type and
    request-body resolution into a confidence that reflects what's actually
    known versus assumed, and adds an explicit `payload_shape_known` flag
    (false when either direction is an unresolvable/opaque type). Only ever
    downgrades — a clean annotation with resolved payloads keeps its original
    rating, consistent with this tool's conservative, high-confidence-only
    approach to flagging elsewhere in the pipeline.
    """
    known_dto_names = {s["simple_name"] for s in dto_schemas if s.get("simple_name")}

    for ep in endpoints:
        ret = ep.get("return_type")
        body = ep.get("request_body")

        opaque_count = 0
        if ret and ret.get("java_type") != "void":
            if not _is_resolved(ret.get("simple_type"), known_dto_names):
                opaque_count += 1
        if body:
            if not _is_resolved(body.get("simple_type"), known_dto_names):
                opaque_count += 1

        ep["payload_shape_known"] = opaque_count == 0

        base_confidence = ep.get("confidence", "HIGH")
        if opaque_count == 0:
            continue
        if opaque_count == 1:
            ep["confidence"] = "MEDIUM" if base_confidence == "HIGH" else base_confidence
        else:
            ep["confidence"] = "LOW"
