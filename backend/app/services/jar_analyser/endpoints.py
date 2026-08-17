"""Endpoint reconstructor.

Supports both Spring MVC (@GetMapping etc.) and JAX-RS (@GET + @Path).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .classfile import ClassInfo, AnnotationInfo, MethodInfo
from .annotations import (
    REST_CONTROLLER, CONTROLLER, REQUEST_MAPPING,
    GET_MAPPING, POST_MAPPING, PUT_MAPPING, PATCH_MAPPING, DELETE_MAPPING,
    PATH_VARIABLE, REQUEST_PARAM, REQUEST_BODY, REQUEST_HEADER,
    PRE_AUTHORIZE, SECURED,
    ROLES_ALLOWED, ROLES_ALLOWED_JAKARTA,
    JAXRS_PATH, JAXRS_PATH_JAVAX,
    JAXRS_GET, JAXRS_GET_JAVAX, JAXRS_POST, JAXRS_POST_JAVAX,
    JAXRS_PUT, JAXRS_PUT_JAVAX, JAXRS_DELETE, JAXRS_DELETE_JAVAX,
    JAXRS_PATCH, JAXRS_PATCH_JAVAX,
    CONTROLLER_ANNOTATIONS, MAPPING_ANNOTATIONS, JAXRS_PATH_ANNOTATIONS,
    JAXRS_METHOD_ANNOTATIONS, DEPRECATED, OPERATION,
    JAXRS_PATH_PARAM, JAXRS_PATH_PARAM_JAVAX, JAXRS_QUERY_PARAM, JAXRS_QUERY_PARAM_JAVAX,
    JAXRS_HEADER_PARAM, JAXRS_HEADER_PARAM_JAVAX, JAXRS_COOKIE_PARAM, JAXRS_COOKIE_PARAM_JAVAX,
    JAXRS_MATRIX_PARAM, JAXRS_MATRIX_PARAM_JAVAX, JAXRS_FORM_PARAM, JAXRS_FORM_PARAM_JAVAX,
    JAXRS_CONTEXT, JAXRS_CONTEXT_JAVAX, JAXRS_SUSPENDED, JAXRS_SUSPENDED_JAVAX,
    JAXRS_BEAN_PARAM, JAXRS_BEAN_PARAM_JAVAX,
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EndpointParameter:
    name: str
    location: str          # path | query | body | header
    java_type: str
    simple_type: str
    required: bool = True
    default_value: str | None = None


@dataclass
class ReturnType:
    java_type: str
    simple_type: str
    generic_parameter: str = "unknown"


@dataclass
class SecurityInfo:
    annotation: str
    expression: str
    parsed_auth: dict | None = None


@dataclass
class Endpoint:
    controller_class: str
    controller_simple: str
    http_method: str
    path: str
    full_path: str
    base_path: str
    method_name: str
    parameters: list[EndpointParameter] = field(default_factory=list)
    request_body: EndpointParameter | None = None
    return_type: ReturnType | None = None
    security: SecurityInfo | None = None
    produces: list[str] = field(default_factory=list)
    consumes: list[str] = field(default_factory=list)
    confidence: str = "HIGH"
    source_annotation: str = ""
    deprecated: bool = False
    # Developer-authored text from @Operation(summary=..., description=...) —
    # the only source of real explanation bytecode can offer (Javadoc/comments
    # don't survive compilation). None if the endpoint has no @Operation.
    doc_summary: str | None = None
    doc_description: str | None = None

    @property
    def signature_key(self) -> str:
        return f"{self.http_method}:{self.full_path}"


# ---------------------------------------------------------------------------
# Annotation → HTTP method maps
# ---------------------------------------------------------------------------

_SPRING_TO_METHOD = {
    GET_MAPPING: "GET", POST_MAPPING: "POST", PUT_MAPPING: "PUT",
    PATCH_MAPPING: "PATCH", DELETE_MAPPING: "DELETE",
}
_JAXRS_TO_METHOD = {
    JAXRS_GET: "GET",    JAXRS_GET_JAVAX: "GET",
    JAXRS_POST: "POST",  JAXRS_POST_JAVAX: "POST",
    JAXRS_PUT: "PUT",    JAXRS_PUT_JAVAX: "PUT",
    JAXRS_DELETE: "DELETE", JAXRS_DELETE_JAVAX: "DELETE",
    JAXRS_PATCH: "PATCH", JAXRS_PATCH_JAVAX: "PATCH",
}
_REQUEST_METHOD_ENUM = {
    "GET": "GET", "POST": "POST", "PUT": "PUT", "PATCH": "PATCH",
    "DELETE": "DELETE", "HEAD": "HEAD", "OPTIONS": "OPTIONS",
}


class EndpointReconstructor:

    @classmethod
    def reconstruct(cls, classes: list[ClassInfo]) -> list[Endpoint]:
        endpoints: list[Endpoint] = []
        for ci in classes:
            ann_descs = {a.descriptor for a in ci.annotations}
            if not (ann_descs & CONTROLLER_ANNOTATIONS):
                continue
            is_jaxrs = bool(ann_descs & JAXRS_PATH_ANNOTATIONS)
            base_paths = _extract_base_paths(ci.annotations, is_jaxrs)
            if not base_paths:
                base_paths = [""]
            for method in ci.methods:
                endpoints.extend(cls._process_method(ci, method, base_paths, is_jaxrs))
        return endpoints

    @classmethod
    def _process_method(
        cls, ci: ClassInfo, method: MethodInfo, base_paths: list[str], is_jaxrs: bool
    ) -> list[Endpoint]:
        if is_jaxrs:
            http_method = _jaxrs_http_method(method.annotations)
            if not http_method:
                return []
            method_paths = _jaxrs_method_paths(method.annotations)
            confidence = "HIGH"
        else:
            mapping_ann = _find_spring_mapping(method.annotations)
            if not mapping_ann:
                return []
            http_method, method_paths, confidence = _spring_http_method_and_paths(mapping_ann)

        security = _extract_security(method.annotations, ci.annotations)
        params, body = _extract_parameters(method, is_jaxrs)
        return_type = _parse_return_type(method.descriptor)
        source_ann = f"@{http_method}" if is_jaxrs else _source_ann_name(method.annotations)
        deprecated = any(a.descriptor == DEPRECATED for a in method.annotations)
        doc_summary, doc_description = _extract_operation_doc(method.annotations)

        endpoints = []
        for base in base_paths:
            for mp in method_paths:
                full = _normalise_path(base + "/" + mp)
                endpoints.append(Endpoint(
                    controller_class=ci.java_class_name,
                    controller_simple=ci.simple_name,
                    http_method=http_method,
                    path=mp or "/",
                    full_path=full,
                    base_path=base or "/",
                    method_name=method.name,
                    parameters=params,
                    request_body=body,
                    return_type=return_type,
                    security=security,
                    confidence=confidence,
                    source_annotation=source_ann,
                    deprecated=deprecated,
                    doc_summary=doc_summary,
                    doc_description=doc_description,
                ))
        return endpoints


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_base_paths(annotations: list[AnnotationInfo], is_jaxrs: bool) -> list[str]:
    for ann in annotations:
        if is_jaxrs and ann.descriptor in JAXRS_PATH_ANNOTATIONS:
            val = ann.get("value")
            return [str(val)] if val else [""]
        if not is_jaxrs and ann.descriptor == REQUEST_MAPPING:
            return _ann_paths(ann)
    return []


def _jaxrs_http_method(annotations: list[AnnotationInfo]) -> str | None:
    for ann in annotations:
        if ann.descriptor in _JAXRS_TO_METHOD:
            return _JAXRS_TO_METHOD[ann.descriptor]
    return None


def _jaxrs_method_paths(annotations: list[AnnotationInfo]) -> list[str]:
    for ann in annotations:
        if ann.descriptor in JAXRS_PATH_ANNOTATIONS:
            val = ann.get("value")
            return [str(val)] if val else [""]
    return [""]


def _find_spring_mapping(annotations: list[AnnotationInfo]) -> AnnotationInfo | None:
    for ann in annotations:
        if ann.descriptor in _SPRING_TO_METHOD or ann.descriptor == REQUEST_MAPPING:
            return ann
    return None


def _spring_http_method_and_paths(ann: AnnotationInfo) -> tuple[str, list[str], str]:
    if ann.descriptor in _SPRING_TO_METHOD:
        http_method = _SPRING_TO_METHOD[ann.descriptor]
    else:
        method_val = ann.get("method")
        if method_val is None:
            http_method = "ANY"
        elif isinstance(method_val, list):
            http_method = _REQUEST_METHOD_ENUM.get(method_val[0], "ANY") if method_val else "ANY"
        else:
            http_method = _REQUEST_METHOD_ENUM.get(str(method_val), "ANY")

    paths = _ann_paths(ann)
    confidence = "HIGH" if paths and paths[0].startswith("/") else "MEDIUM"
    return http_method, paths or [""], confidence


def _ann_paths(ann: AnnotationInfo) -> list[str]:
    val = ann.get("value") or ann.get("path")
    if val is None:
        return [""]
    if isinstance(val, list):
        return [v for v in val if isinstance(v, str)] or [""]
    return [str(val)]


def _extract_security(
    method_anns: list[AnnotationInfo], class_anns: list[AnnotationInfo]
) -> SecurityInfo | None:
    from .security_parser import parse_expression
    for ann in method_anns + class_anns:
        if ann.descriptor == PRE_AUTHORIZE:
            expr = str(ann.get("value") or "")
            si = SecurityInfo("@PreAuthorize", expr)
            si.parsed_auth = parse_expression("@PreAuthorize", expr)
            return si
        if ann.descriptor == SECURED:
            roles = ann.get("value") or []
            expr = ", ".join(roles) if isinstance(roles, list) else str(roles)
            si = SecurityInfo("@Secured", expr)
            si.parsed_auth = parse_expression("@Secured", expr)
            return si
        if ann.descriptor in (ROLES_ALLOWED, ROLES_ALLOWED_JAKARTA):
            roles = ann.get("value") or []
            expr = ", ".join(roles) if isinstance(roles, list) else str(roles)
            si = SecurityInfo("@RolesAllowed", expr)
            si.parsed_auth = parse_expression("@RolesAllowed", expr)
            return si
    return None


_JAXRS_SIMPLE_PARAMS = {
    JAXRS_PATH_PARAM: "path", JAXRS_PATH_PARAM_JAVAX: "path",
    JAXRS_QUERY_PARAM: "query", JAXRS_QUERY_PARAM_JAVAX: "query",
    JAXRS_HEADER_PARAM: "header", JAXRS_HEADER_PARAM_JAVAX: "header",
    JAXRS_COOKIE_PARAM: "query", JAXRS_COOKIE_PARAM_JAVAX: "query",
    JAXRS_MATRIX_PARAM: "query", JAXRS_MATRIX_PARAM_JAVAX: "query",
    JAXRS_FORM_PARAM: "query", JAXRS_FORM_PARAM_JAVAX: "query",
}
_JAXRS_INJECTED_PARAMS = {
    JAXRS_CONTEXT, JAXRS_CONTEXT_JAVAX, JAXRS_SUSPENDED, JAXRS_SUSPENDED_JAVAX,
    JAXRS_BEAN_PARAM, JAXRS_BEAN_PARAM_JAVAX,
}


def _extract_parameters(method: MethodInfo, is_jaxrs: bool = False) -> tuple[list[EndpointParameter], EndpointParameter | None]:
    params: list[EndpointParameter] = []
    body: EndpointParameter | None = None
    param_types = _parse_param_types(method.descriptor)

    for i, param_anns in enumerate(method.parameter_annotations):
        java_type = param_types[i] if i < len(param_types) else "Object"
        simple = _simple_type(java_type)
        matched = False
        for ann in param_anns:
            if ann.descriptor == PATH_VARIABLE:
                name = ann.get("value") or ann.get("name") or f"param{i}"
                params.append(EndpointParameter(str(name), "path", java_type, simple, True))
                matched = True
            elif ann.descriptor == REQUEST_PARAM:
                name = ann.get("value") or ann.get("name") or f"param{i}"
                req = ann.get("required")
                params.append(EndpointParameter(
                    str(name), "query", java_type, simple,
                    required=req is not False and req != "false",
                    default_value=str(d) if (d := ann.get("defaultValue")) is not None else None,
                ))
                matched = True
            elif ann.descriptor == REQUEST_BODY:
                req = ann.get("required")
                body = EndpointParameter("body", "body", java_type, simple,
                                         required=req is not False and req != "false")
                matched = True
            elif ann.descriptor == REQUEST_HEADER:
                name = ann.get("value") or ann.get("name") or f"header{i}"
                params.append(EndpointParameter(str(name), "header", java_type, simple))
                matched = True
            elif ann.descriptor in _JAXRS_SIMPLE_PARAMS:
                name = ann.get("value") or f"param{i}"
                params.append(EndpointParameter(str(name), _JAXRS_SIMPLE_PARAMS[ann.descriptor], java_type, simple, required=False))
                matched = True
            elif ann.descriptor in _JAXRS_INJECTED_PARAMS:
                # Framework-injected (UriInfo/SecurityContext/AsyncResponse/an
                # aggregate @BeanParam holder) — recognized so it's excluded
                # below without being surfaced as a request param.
                matched = True
        # JAX-RS convention is the inverse of Spring's: a parameter with none
        # of the annotations above is the implicit request entity, not an
        # ignorable extra argument (Spring requires an explicit @RequestBody
        # instead). Only the first unannotated parameter can be the body in
        # valid JAX-RS usage — body is None here for every subsequent one.
        if is_jaxrs and not matched and body is None:
            body = EndpointParameter("body", "body", java_type, simple, required=True)
    return params, body


def _parse_return_type(descriptor: str) -> ReturnType:
    idx = descriptor.rfind(")")
    if idx == -1:
        return ReturnType("void", "void")
    ret = descriptor[idx + 1:]
    java_type = _descriptor_to_type(ret)
    return ReturnType(java_type, _simple_type(java_type))


def _parse_param_types(descriptor: str) -> list[str]:
    idx = descriptor.find("(")
    end = descriptor.find(")")
    if idx == -1 or end == -1:
        return []
    s = descriptor[idx + 1:end]
    types, i = [], 0
    while i < len(s):
        t, consumed = _read_one_type(s, i)
        types.append(t)
        i += consumed
    return types


def _read_one_type(s: str, i: int) -> tuple[str, int]:
    c = s[i]
    if c == "L":
        end = s.index(";", i)
        return _descriptor_to_type(s[i:end + 1]), end - i + 1
    if c == "[":
        inner, consumed = _read_one_type(s, i + 1)
        return inner + "[]", consumed + 1
    primitives = {"B": "byte", "C": "char", "D": "double", "F": "float",
                  "I": "int", "J": "long", "S": "short", "Z": "boolean", "V": "void"}
    return primitives.get(c, c), 1


def _descriptor_to_type(desc: str) -> str:
    if desc.startswith("L") and desc.endswith(";"):
        return desc[1:-1].replace("/", ".")
    if desc == "V":
        return "void"
    primitives = {"B": "byte", "C": "char", "D": "double", "F": "float",
                  "I": "int", "J": "long", "S": "short", "Z": "boolean"}
    return primitives.get(desc, desc)


def _simple_type(java_type: str) -> str:
    return java_type.rsplit(".", 1)[-1]


def _source_ann_name(annotations: list[AnnotationInfo]) -> str:
    for ann in annotations:
        if ann.descriptor in _SPRING_TO_METHOD or ann.descriptor == REQUEST_MAPPING:
            return "@" + ann.simple_name
    return ""


def _extract_operation_doc(annotations: list[AnnotationInfo]) -> tuple[str | None, str | None]:
    """@Operation(summary=..., description=...) — developer-authored text,
    the only real explanation bytecode can offer. See Stage 4 of the
    accuracy plan. Returns (summary, description), either possibly None."""
    for ann in annotations:
        if ann.descriptor == OPERATION:
            summary = ann.get("summary")
            description = ann.get("description")
            return (summary or None, description or None)
    return (None, None)


def _normalise_path(path: str) -> str:
    path = re.sub(r"/+", "/", path)
    if not path.startswith("/"):
        path = "/" + path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return path
