"""Pagination pattern detector.

Inspects an endpoint's parameters and return type to determine whether it
uses Spring's Pageable contract (page / size / sort query params) and
whether the return type is a Page<T> wrapper.
"""
from __future__ import annotations

import re

# Query-param names that indicate Spring Pageable
_PAGE_NAMES  = {"page", "pageno", "pagenumber"}
_SIZE_NAMES  = {"size", "pagesize", "limit"}
_SORT_NAMES  = {"sort", "sortby", "orderby", "order"}

# Return-type simple names that indicate a paginated wrapper
_PAGE_TYPES  = {"page", "pageimpl", "slice", "pageresponse", "pagedresponse",
                "pagedresult", "pagedresults", "paginatedresponse", "paginatedresult"}

_DEFAULT_PAGE_SIZE_RE = re.compile(r"defaultValue\s*=\s*[\"']?(\d+)[\"']?")


def detect_pagination(endpoint: dict) -> dict:
    """Return pagination metadata for *endpoint* (as produced by _endpoint_dict).

    Returns a dict with keys:
        is_paginated      bool
        page_param        str | None
        size_param        str | None
        sort_param        str | None
        default_page_size int | None
    """
    params: list[dict] = endpoint.get("parameters") or []
    return_type: dict | None = endpoint.get("return_type")

    page_param: str | None = None
    size_param: str | None = None
    sort_param: str | None = None
    default_page_size: int | None = None

    for p in params:
        if p.get("location") != "query":
            continue
        name_lower = (p.get("name") or "").lower().replace("-", "").replace("_", "")
        if name_lower in _PAGE_NAMES:
            page_param = p["name"]
        elif name_lower in _SIZE_NAMES:
            size_param = p["name"]
            # Try to extract default value
            dv = p.get("default_value")
            if dv and str(dv).isdigit():
                default_page_size = int(dv)
        elif name_lower in _SORT_NAMES:
            sort_param = p["name"]

    # Also check return type for Page<T>
    return_is_page = False
    if return_type:
        simple = (return_type.get("simple_type") or "").lower()
        if simple in _PAGE_TYPES:
            return_is_page = True

    is_paginated = (page_param is not None or size_param is not None) or return_is_page

    return {
        "is_paginated": is_paginated,
        "page_param": page_param,
        "size_param": size_param,
        "sort_param": sort_param,
        "default_page_size": default_page_size,
    }
