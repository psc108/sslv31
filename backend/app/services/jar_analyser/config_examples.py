"""Config/design document example discovery and synthesis.

Some services consume config/design documents (YAML/JSON) that aren't
ordinary REST request bodies — imported through a design-editor UI or file
upload rather than a typed controller method with a resolved request body
(e.g. fulfillment-installer-2.6.59.jar's CompositeDesign, discovered when
scripts/service-design.yml turned out to match it field-for-field). This
module surfaces examples of those documents for the developer guide:

- find_bundled_examples: a REAL example, if the jar itself ships one as a
  plain resource (many products of this shape ship a "reset to default"
  template) — always preferred when found, since it's the genuine article.
- synthesize_example: otherwise, a structurally-valid instance built purely
  from the already-resolved DtoSchema graph — required fields populated,
  real enum/discriminator values, annotation-sourced defaults verbatim
  where present. Never AI-generated (this product's own constraint) and
  never claims to be more than structurally valid — see the fidelity-ceiling
  discussion in Documentation/jar_analyser_config_document_examples_plan.md.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import yaml

from .dto_scanner import DtoField, DtoSchema

# Seed root classes to always attempt scanning/synthesis for, regardless of
# whether any endpoint's request body resolves to them. Curated, not
# heuristic — see Part G of the plan doc for why general "detect any
# document-root class" discovery is deliberately deferred (needs more than
# one proven case first, to avoid tuning a heuristic against a sample of one).
CURATED_ROOT_SEEDS: set[str] = {
    "com.dxc.ecs.fulfillment.composite.config.model.CompositeDesign",
}

_RESOURCE_EXTENSIONS = (".yml", ".yaml", ".json")
# Minimum overlapping top-level keys between a candidate resource and a root
# schema's own field names before calling it a genuine match — low enough to
# tolerate an example that omits some optional fields, high enough that an
# unrelated small YAML file doesn't false-positive.
_MIN_KEY_MATCHES = 4


def find_bundled_examples(
    jar_path: Path, root_class_names: set[str], schemas: dict[str, DtoSchema]
) -> dict[str, str]:
    """Look for a real, product-shipped example of a root document already
    sitting in the jar as a plain resource. A plain top-level zip namelist
    walk never sees inside a nested fat jar's own entries (those appear as
    one opaque binary entry, not exploded) — so this naturally never reaches
    into BOOT-INF/lib/*.jar vendor content without needing to special-case it.
    Returns {root_class_name: raw_file_text} for confirmed matches.
    """
    results: dict[str, str] = {}
    if not root_class_names:
        return results

    field_keys: dict[str, set[str]] = {}
    for root in root_class_names:
        schema = schemas.get(root)
        if schema:
            field_keys[root] = {f.json_name for f in schema.fields if not f.json_ignored}
    if not field_keys:
        return results

    try:
        with zipfile.ZipFile(jar_path) as zf:
            for name in zf.namelist():
                if not name.lower().endswith(_RESOURCE_EXTENSIONS):
                    continue
                try:
                    text = zf.read(name).decode("utf-8")
                    parsed = yaml.safe_load(text)  # safe_load also parses plain JSON
                except Exception:
                    continue
                if not isinstance(parsed, dict):
                    continue
                doc_keys = set(parsed.keys())
                for root, keys in field_keys.items():
                    if root in results or not keys:
                        continue
                    if len(doc_keys & keys) >= min(_MIN_KEY_MATCHES, len(keys)):
                        results[root] = text
    except Exception:
        pass
    return results


_MAX_SYNTH_DEPTH = 6


def synthesize_example(
    root_class_name: str,
    schemas: dict[str, DtoSchema],
    polymorphic_info: dict[str, tuple[str, str]],
) -> str | None:
    """Build a structurally-valid example instance (YAML text) for
    root_class_name, purely from its already-resolved DtoSchema graph.
    Returns None if root_class_name has no resolved schema to build from.
    """
    if root_class_name not in schemas:
        return None

    # base_class -> [(discriminator_value, concrete_subtype_class), ...]
    subtypes_by_base: dict[str, list[tuple[str, str]]] = {}
    for subtype, (base, disc) in polymorphic_info.items():
        subtypes_by_base.setdefault(base, []).append((disc, subtype))

    notes: list[str] = []

    def build(class_name: str, depth: int, stack: frozenset[str]) -> Any:
        schema = schemas.get(class_name)
        if not schema or depth > _MAX_SYNTH_DEPTH or class_name in stack:
            return None
        if schema.is_enum:
            return _pick_enum_value(schema)

        stack = stack | {class_name}
        obj: dict[str, Any] = {}
        for f in schema.fields:
            if f.json_ignored:
                continue
            # Keep the example focused and honest: always include required
            # fields and anything structural (collections, nested objects);
            # skip optional scalars rather than clutter the output with
            # placeholder junk for fields that don't shape the document.
            if not (f.required or f.is_collection or f.is_map or f.openapi_type == "object"):
                continue
            value = _build_field_value(f, depth, stack, schemas, subtypes_by_base, build, notes)
            if value is not None:
                obj[f.json_name] = value
        return obj

    root = build(root_class_name, 0, frozenset())
    if not isinstance(root, dict) or not root:
        return None

    header = (
        "# Synthesized example — structurally valid (required fields present,\n"
        "# real enum/discriminator values, no invented ones) but NOT derived from\n"
        "# any real deployment. Fields referencing another system's own catalog\n"
        "# (e.g. a design/blueprint ID registered elsewhere) are placeholders, not\n"
        "# real values — see the JAR Analyser docs for what this can and can't promise.\n"
    )
    if notes:
        header += "#\n# Polymorphic fields — one concrete option shown per slot:\n"
        for n in notes:
            header += f"#   {n}\n"

    body = yaml.dump(root, default_flow_style=False, sort_keys=False, allow_unicode=True, width=100)
    return header + "\n" + body


def _build_field_value(
    f: DtoField, depth: int, stack: frozenset[str],
    schemas: dict[str, DtoSchema], subtypes_by_base: dict[str, list[tuple[str, str]]],
    build, notes: list[str],
) -> Any:
    if f.default_value is not None:
        return f.default_value

    if f.is_collection:
        elem_type = f.collection_element_java
        if elem_type and elem_type in schemas:
            elem = _resolve_typed_value(elem_type, depth + 1, stack, schemas, subtypes_by_base, build, notes)
            return [elem] if elem is not None else []
        return []

    if f.is_map:
        return {}

    if f.java_type in schemas:
        return _resolve_typed_value(f.java_type, depth + 1, stack, schemas, subtypes_by_base, build, notes)

    return _placeholder_scalar(f)


def _resolve_typed_value(
    class_name: str, depth: int, stack: frozenset[str],
    schemas: dict[str, DtoSchema], subtypes_by_base: dict[str, list[tuple[str, str]]],
    build, notes: list[str],
) -> Any:
    alternatives = subtypes_by_base.get(class_name)
    if not alternatives:
        return build(class_name, depth, stack)

    # Pick one concrete subtype — enumerating every valid option inline would
    # produce something unreadable rather than a usable worked example.
    disc, chosen = alternatives[0]
    chosen_simple = chosen.rsplit(".", 1)[-1]
    others = ", ".join(f'"{d}" -> {c.rsplit(".", 1)[-1]}' for d, c in alternatives[1:])
    note = f'{class_name.rsplit(".", 1)[-1]}: used {chosen_simple} (discriminator "{disc}")'
    if others:
        note += f" — also valid: {others}"
    notes.append(note)

    result = build(chosen, depth, stack)
    if isinstance(result, dict):
        # Jackson needs the discriminator value present on the instance
        # itself to deserialize back to the right concrete subtype — without
        # it the example wouldn't round-trip through the real model. The
        # property name is assumed to be "type" (true for every case proven
        # so far) rather than parsed from @JsonTypeInfo's own `property`
        # attribute — a deliberate simplification worth revisiting once
        # there's a second real case where it might differ (see Part G).
        result = {"type": disc, **result}
    return result


def _pick_enum_value(schema: DtoSchema) -> str | None:
    if not schema.enum_values:
        return None
    first = schema.enum_values[0]
    return first.get("serialised_as") or first.get("name")


def _placeholder_scalar(f: DtoField) -> Any:
    """No structural signal to draw a real value from (no default annotation,
    not an enum, not a nested object) — a clearly-marked placeholder rather
    than a fabricated-looking real one."""
    t = f.openapi_type
    if t == "boolean":
        return False
    if t in ("integer", "number"):
        return 0
    if t == "array":
        return []
    if t == "object":
        return {}
    return f"<{f.simple_type}>"
