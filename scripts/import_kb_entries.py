"""Import JAR Analyser error-KB entries from a JSON file via the running API.

Reusable for any future complex issue: write a JSON file of entries (see
scripts/kb_entries/rca_cso_portal_shop_404.json for the shape) and run:

    BASE_URL=http://localhost API_KEY=... python scripts/import_kb_entries.py \
        scripts/kb_entries/rca_cso_portal_shop_404.json

Each entry may include a local-only "key" field so entries in the same file
can cross-reference each other in "see_also" before their real DB ids exist;
the script resolves those keys to the created ids in a second pass. If no
"key" is given but the entry has an "id" (e.g. exported from GET /error-kb
on another instance), that id is used as the key — so re-importing entries
that reference each other by their old ids still resolves correctly against
the new ones. References to ids not present in this batch (e.g. stable
builtin ids like "ks-002") are left unchanged.

When exporting entries from another instance to feed into this script
(e.g. GET /error-kb), write the response straight to a file with curl's
-o flag rather than piping it through a shell/python step that decodes
stdin with a non-UTF-8 codepage (a real risk on Windows) — that silently
double-encodes multi-byte characters like em-dashes before they ever
reach this script.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("BASE_URL", "https://localhost").rstrip("/")
API_KEY = os.environ.get("API_KEY", "")
ENDPOINT = f"{BASE_URL}/api/v1/jar-analyser/error-kb"


def _request(method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-API-Key", API_KEY)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {url} -> {e.code}: {detail}") from None


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python import_kb_entries.py <entries.json>", file=sys.stderr)
        sys.exit(1)
    if not API_KEY:
        print("ERROR: API_KEY not set (export API_KEY=... or pass it inline).", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        entries = json.load(f)

    key_to_id: dict[str, str] = {}
    created: list[tuple[dict, dict]] = []  # (source entry, created row)

    for entry in entries:
        key = entry.pop("key", None) or entry.get("id")
        payload = {k: v for k, v in entry.items() if k not in ("id", "source", "origin", "created_by", "created_at", "updated_at")}
        row = _request("POST", ENDPOINT, payload)
        print(f"created {row['id']}  [{row['category']}] {row['title']}")
        if key:
            key_to_id[key] = row["id"]
        created.append((entry, row))

    # Second pass: resolve any see_also entries that referenced a local key.
    for entry, row in created:
        see_also = entry.get("see_also", [])
        resolved = [key_to_id.get(ref, ref) for ref in see_also]
        if resolved != see_also:
            entry["see_also"] = resolved
            _request("PUT", f"{ENDPOINT}/{row['id']}", entry)
            print(f"updated {row['id']} see_also -> {resolved}")

    print(f"\nDone — imported {len(created)} entries.")


if __name__ == "__main__":
    main()
