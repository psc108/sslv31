"""Error response catalogue extractor.

Scans @ControllerAdvice / @RestControllerAdvice classes for @ExceptionHandler
methods and extracts the HTTP status, exception class, and return type (the
error response DTO).  Uses the same ClassFileParser infrastructure as the
annotation scanner.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .classfile import ClassFileParser
from .annotations import (
    CONTROLLER_ADVICE_ANNOTATIONS,
    EXCEPTION_HANDLER,
    RESPONSE_STATUS,
    _SKIP_PREFIXES,
)

# HTTP status codes from @ResponseStatus(HttpStatus.XXX) enum constant names
_HTTP_STATUS_MAP: dict[str, int] = {
    "OK": 200, "CREATED": 201, "ACCEPTED": 202, "NO_CONTENT": 204,
    "BAD_REQUEST": 400, "UNAUTHORIZED": 401, "FORBIDDEN": 403,
    "NOT_FOUND": 404, "METHOD_NOT_ALLOWED": 405, "CONFLICT": 409,
    "GONE": 410, "UNPROCESSABLE_ENTITY": 422, "TOO_MANY_REQUESTS": 429,
    "INTERNAL_SERVER_ERROR": 500, "NOT_IMPLEMENTED": 501,
    "BAD_GATEWAY": 502, "SERVICE_UNAVAILABLE": 503,
}

_CLASS_ROOTS = (
    "content/lib/BOOT-INF/classes/",
    "BOOT-INF/classes/",
    "WEB-INF/classes/",
)


@dataclass
class ErrorHandlerInfo:
    http_status: int | None          # e.g. 400, 404, 500
    exception_class: str | None      # simple name of the exception
    response_schema_class: str | None  # simple name of the return DTO
    scope: str                       # "global" | "controller"
    controller_class: str | None     # FQN of the @ControllerAdvice class
    fields: list[dict] = field(default_factory=list)  # from DTO scanner (populated later)


class ErrorCatalogueExtractor:

    @classmethod
    def from_jar(cls, jar_path: Path) -> list[ErrorHandlerInfo]:
        results: list[ErrorHandlerInfo] = []
        try:
            with zipfile.ZipFile(jar_path, "r") as zf:
                entries = zf.namelist()
                for entry in entries:
                    if not entry.endswith(".class") or "$" in entry:
                        continue
                    if any(entry.startswith(skip) for skip in _SKIP_PREFIXES):
                        continue
                    # Must be under a known class root
                    if not any(entry.startswith(r) for r in _CLASS_ROOTS):
                        continue
                    try:
                        data = zf.read(entry)
                        info = ClassFileParser.parse(data)
                    except Exception:
                        continue

                    ann_descs = {a.descriptor for a in info.annotations}
                    if not (ann_descs & CONTROLLER_ADVICE_ANNOTATIONS):
                        continue

                    # Found a @ControllerAdvice class — scan its methods
                    controller_fqn = info.java_class_name
                    for method in info.methods:
                        method_ann_descs = {a.descriptor for a in method.annotations}
                        if EXCEPTION_HANDLER not in method_ann_descs:
                            continue

                        # Extract exception class from @ExceptionHandler(value=...)
                        exception_class: str | None = None
                        for ann in method.annotations:
                            if ann.descriptor == EXCEPTION_HANDLER:
                                val = ann.get("value")
                                if isinstance(val, list) and val:
                                    raw = val[0]
                                    if isinstance(raw, str):
                                        exception_class = _descriptor_to_simple(raw)
                                elif isinstance(val, str):
                                    exception_class = _descriptor_to_simple(val)
                                break

                        # Extract HTTP status from @ResponseStatus on the method
                        http_status: int | None = None
                        for ann in method.annotations:
                            if ann.descriptor == RESPONSE_STATUS:
                                # value or code element holds the HttpStatus enum constant
                                for elem_name in ("value", "code"):
                                    raw_status = ann.get(elem_name)
                                    if isinstance(raw_status, str):
                                        http_status = _HTTP_STATUS_MAP.get(raw_status)
                                        if http_status:
                                            break
                                break

                        # Infer status from exception name if not explicit
                        if http_status is None and exception_class:
                            http_status = _infer_status_from_name(exception_class)

                        # Return type from method descriptor — first object after ')'
                        return_simple = _return_type_from_descriptor(method.descriptor)

                        results.append(ErrorHandlerInfo(
                            http_status=http_status,
                            exception_class=exception_class,
                            response_schema_class=return_simple,
                            scope="global",
                            controller_class=controller_fqn,
                        ))

        except zipfile.BadZipFile:
            pass

        return results


def _descriptor_to_simple(desc: str) -> str:
    """Convert a class descriptor or internal name to a simple class name."""
    # e.g. "Lcom/example/NotFoundException;" -> "NotFoundException"
    # or   "com/example/NotFoundException"   -> "NotFoundException"
    clean = desc.lstrip("L").rstrip(";")
    return clean.rsplit("/", 1)[-1]


def _return_type_from_descriptor(descriptor: str) -> str | None:
    """Extract the return type simple name from a method descriptor.

    e.g. "(Lcom/example/SomeException;)Lcom/example/ErrorResponse;" -> "ErrorResponse"
    """
    # Find the part after the closing ')'
    m = re.search(r"\)L([^;]+);", descriptor)
    if m:
        return m.group(1).rsplit("/", 1)[-1]
    # void or primitive
    after = descriptor.rsplit(")", 1)[-1] if ")" in descriptor else descriptor
    if after in ("V", ""):
        return None
    return None


def _infer_status_from_name(name: str) -> int | None:
    """Heuristic: infer HTTP status from exception class name."""
    n = name.lower()
    if "notfound" in n or "doesnotexist" in n:
        return 404
    if "unauthorized" in n or "unauthenticated" in n:
        return 401
    if "forbidden" in n or "accessdenied" in n:
        return 403
    if "conflict" in n or "duplicate" in n or "alreadyexists" in n:
        return 409
    if "validation" in n or "invalid" in n or "badrequest" in n or "illegalargument" in n:
        return 400
    if "unprocessable" in n or "quota" in n:
        return 422
    if "toomanyrequests" in n or "ratelimit" in n:
        return 429
    return None
