"""Endpoint → Database Table Linkage.

Heuristic matching of controller class names against reconstructed schema
table names to annotate each endpoint with the tables it is likely to touch.

Approach:
  1. Strip common suffixes from the controller simple name
     (Controller, Resource, Api, Rest, Handler, Facade, Service).
  2. Normalise to lower-case tokens split on camel-case and underscores.
  3. For each table name, check whether any token from the controller name
     appears as a substring of the table name or vice-versa.
  4. Supplement with tables_affected already recorded on migration scripts
     for the same service — any table that appears in a migration whose
     description contains the controller token is also included.
"""
from __future__ import annotations

import re


_STRIP_SUFFIXES = re.compile(
    r"(Controller|Resource|Api|Rest|Handler|Facade|Service|Endpoint|Impl)$",
    re.IGNORECASE,
)


def _tokens(name: str) -> list[str]:
    """Split a CamelCase or snake_case name into lower-case tokens."""
    # Insert underscore before uppercase runs
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return [t.lower() for t in re.split(r"[_\-\s]+", s) if t]


def _controller_tokens(controller_simple: str) -> list[str]:
    """Return meaningful tokens from a controller class simple name."""
    stripped = _STRIP_SUFFIXES.sub("", controller_simple)
    return _tokens(stripped)


def link_tables(
    endpoints: list[dict],
    migration_scripts: list[dict],
) -> dict[str, list[str]]:
    """Return a mapping of endpoint signature_key → sorted list of likely table names.

    Args:
        endpoints: list of endpoint dicts (must have signature_key, controller_simple,
                   full_path, http_method).
        migration_scripts: list of migration script dicts (tables_affected, description).

    Returns:
        dict mapping signature_key → [table_name, ...]
    """
    if not migration_scripts:
        return {}

    # Collect all known table names from migrations
    all_tables: set[str] = set()
    for ms in migration_scripts:
        for t in (ms.get("tables_affected") or []):
            if t:
                all_tables.add(t.lower())

    if not all_tables:
        return {}

    # Build migration description → tables index for supplemental matching
    # desc_tokens -> set of tables mentioned in that migration
    mig_desc_tables: list[tuple[list[str], set[str]]] = []
    for ms in migration_scripts:
        desc = ms.get("description") or ""
        tables = {t.lower() for t in (ms.get("tables_affected") or []) if t}
        if desc and tables:
            mig_desc_tables.append((_tokens(desc), tables))

    result: dict[str, list[str]] = {}

    for ep in endpoints:
        sig = ep.get("signature_key", "")
        ctrl = ep.get("controller_simple", "")
        if not sig or not ctrl:
            continue

        ctrl_tokens = _controller_tokens(ctrl)
        if not ctrl_tokens:
            continue

        matched: set[str] = set()

        for table in all_tables:
            table_tokens = _tokens(table)
            # Match if any controller token appears in the table name or vice-versa
            for ct in ctrl_tokens:
                if len(ct) < 3:
                    continue
                if ct in table or any(ct in tt for tt in table_tokens):
                    matched.add(table)
                    break
                if any(tt in ct for tt in table_tokens if len(tt) >= 3):
                    matched.add(table)
                    break

        # Supplement: migration descriptions that share tokens with the controller
        for desc_tokens, tables in mig_desc_tables:
            for ct in ctrl_tokens:
                if len(ct) < 3:
                    continue
                if any(ct in dt or dt in ct for dt in desc_tokens if len(dt) >= 3):
                    matched |= tables
                    break

        if matched:
            result[sig] = sorted(matched)

    return result
