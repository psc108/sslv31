#!/usr/bin/env python3
"""One-off migration: copies the JAR Analyser's error-KB entries (previously
in the jar_kb_entries table) into the Docs feature, one Doc per entry,
organised into one Library per category (Keystone errors -> Keystone
library, RabbitMQ errors -> RabbitMQ library, etc.), each with a single
"Errors" shelf.

Runs entirely over the HTTP API with the master API key, matching this
project's established convention for KB import scripts (see memory
jar-analyser-kb-import) — not direct DB/sqlite3 writes, so JSON encoding
and id generation stay consistent with the API's own logic.

Idempotent: safe to re-run — reuses existing libraries/shelves by name, and
skips (rather than errors on) a doc name that already exists on its shelf.

Usage:
    BASE_URL=http://localhost API_KEY=... python backend/scripts/migrate_kb_to_docs.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("BASE_URL", "http://localhost")
API_KEY = os.environ["API_KEY"]
API = f"{BASE_URL}/api/v1"


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict | list | None]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    req.add_header("X-API-Key", API_KEY)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else None)


def render_kb_doc_content(
    severity: str, pattern: str, plain_english: str,
    causes: list[str], fix_steps: list[str], see_also_titles: list[str],
) -> str:
    """Mirrors app.services.docs_error_kb.render_kb_doc_content exactly —
    duplicated here (not imported) so this script stays a standalone HTTP
    client with no dependency on the backend's Python environment."""
    lines = [f"**Severity:** {severity}", f"**Pattern:** `{pattern}`", ""]
    if plain_english.strip():
        lines += [plain_english.strip(), ""]
    if causes:
        lines += ["## Likely Causes", ""]
        lines += [f"- {c}" for c in causes]
        lines += [""]
    if fix_steps:
        lines += ["## Fix Steps", ""]
        lines += [f"{i + 1}. {s}" for i, s in enumerate(fix_steps)]
        lines += [""]
    if see_also_titles:
        lines += ["## See Also", ""]
        lines += [f"- [[{t}]]" for t in see_also_titles]
        lines += [""]
    return "\n".join(lines).rstrip() + "\n"


def get_or_create_library(name: str, existing: list[dict]) -> str:
    for lib in existing:
        if lib["name"] == name:
            return lib["id"]
    status, body = call("POST", "/docs/libraries", {"name": name})
    if status != 201:
        raise RuntimeError(f"Failed to create library {name!r}: {status} {body}")
    print(f"  + library {name!r}")
    return body["id"]


def get_or_create_shelf(library_id: str, name: str) -> str:
    status, shelves = call("GET", f"/docs/libraries/{library_id}/shelves")
    if status != 200:
        raise RuntimeError(f"Failed to list shelves for {library_id}: {status} {shelves}")
    for shelf in shelves:
        if shelf["name"] == name:
            return shelf["id"]
    status, body = call("POST", "/docs/shelves", {"library_id": library_id, "name": name})
    if status != 201:
        raise RuntimeError(f"Failed to create shelf {name!r}: {status} {body}")
    print(f"    + shelf {name!r}")
    return body["id"]


def main() -> None:
    # The old GET /jar-analyser/error-kb (list) endpoint has already been
    # removed as part of this same migration (its data source, the
    # jar_kb_entries table, is superseded by Docs) — so the source data is
    # read from a one-off DB dump (backend/scripts/kb_dump.json, produced by
    # a read-only SELECT against jar_kb_entries) rather than over HTTP.
    dump_path = os.path.join(os.path.dirname(__file__), "kb_dump.json")
    with open(dump_path, encoding="utf-8") as f:
        kb = json.load(f)

    entries = kb["entries"]
    print(f"Loaded {len(entries)} KB entries from {dump_path} ({kb['static_count']} builtin, {kb['user_count']} user)")

    id_to_title = {e["id"]: e["title"] for e in entries}

    status, existing_libraries = call("GET", "/docs/libraries")
    if status != 200:
        print(f"Failed to list existing libraries: {status} {existing_libraries}", file=sys.stderr)
        sys.exit(1)

    library_ids: dict[str, str] = {}
    shelf_ids: dict[str, str] = {}
    created, skipped, failed = 0, 0, 0

    for entry in entries:
        category = entry["category"] or "Other"
        if category not in library_ids:
            library_ids[category] = get_or_create_library(category, existing_libraries)
            existing_libraries.append({"id": library_ids[category], "name": category})
        if category not in shelf_ids:
            shelf_ids[category] = get_or_create_shelf(library_ids[category], "Errors")

        see_also_titles = [id_to_title[ref] for ref in entry.get("see_also", []) if ref in id_to_title]
        content = render_kb_doc_content(
            entry["severity"], entry["pattern"], entry["plain_english"],
            entry.get("causes", []), entry.get("fix_steps", []), see_also_titles,
        )

        status, body = call("POST", "/docs", {
            "shelf_id": shelf_ids[category], "name": entry["title"], "content": content,
        })
        if status == 201:
            created += 1
            print(f"  [{category}] created: {entry['title']}")
        elif status == 409:
            skipped += 1
            print(f"  [{category}] already exists, skipped: {entry['title']}")
        else:
            failed += 1
            print(f"  [{category}] FAILED ({status}): {entry['title']} -> {body}", file=sys.stderr)

    print(f"\nDone: {created} created, {skipped} skipped (already existed), {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
