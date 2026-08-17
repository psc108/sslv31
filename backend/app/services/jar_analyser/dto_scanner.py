"""DTO Schema Scanner.

Scans Java DTO / request / response classes referenced by discovered endpoints
and extracts field-level schema information: names, types, validation constraints,
JSON property overrides, and enum values.

Operates purely on bytecode — no source code required.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .classfile import ClassFileParser, ClassInfo, AnnotationInfo, FieldInfo as ClassFieldInfo

# ---------------------------------------------------------------------------
# Annotation descriptors relevant to DTOs
# ---------------------------------------------------------------------------
_JSON_PROPERTY   = "Lcom/fasterxml/jackson/annotation/JsonProperty;"
_JSON_IGNORE     = "Lcom/fasterxml/jackson/annotation/JsonIgnore;"
_JSON_VALUE      = "Lcom/fasterxml/jackson/annotation/JsonValue;"
# OpenAPI 3 / springdoc — developer-authored description text, the only real
# explanation bytecode can offer. See Stage 4 of the accuracy plan.
_SCHEMA          = "Lio/swagger/v3/oas/annotations/media/Schema;"
# com.kjetland:jackson-jsonSchema — a JSON-Schema generator some products use
# to drive a design/config-document editor UI (see e.g. CompositeDesign's own
# schemagen class). Its @JsonSchemaDefault is a free, authoritative example
# value straight off the field, not something this tool has to guess at.
_JSON_SCHEMA_DEFAULT = "Lcom/kjetland/jackson/jsonSchema/annotations/JsonSchemaDefault;"
_NOT_NULL        = "Ljavax/validation/constraints/NotNull;"
_NOT_NULL_JK     = "Ljakarta/validation/constraints/NotNull;"
_NOT_BLANK       = "Ljavax/validation/constraints/NotBlank;"
_NOT_BLANK_JK    = "Ljakarta/validation/constraints/NotBlank;"
_NOT_EMPTY       = "Ljavax/validation/constraints/NotEmpty;"
_NOT_EMPTY_JK    = "Ljakarta/validation/constraints/NotEmpty;"
_SIZE            = "Ljavax/validation/constraints/Size;"
_SIZE_JK         = "Ljakarta/validation/constraints/Size;"
_MIN             = "Ljavax/validation/constraints/Min;"
_MIN_JK          = "Ljakarta/validation/constraints/Min;"
_MAX             = "Ljavax/validation/constraints/Max;"
_MAX_JK          = "Ljakarta/validation/constraints/Max;"
_PATTERN         = "Ljavax/validation/constraints/Pattern;"
_PATTERN_JK      = "Ljakarta/validation/constraints/Pattern;"
_EMAIL           = "Ljavax/validation/constraints/Email;"
_EMAIL_JK        = "Ljakarta/validation/constraints/Email;"
_NULLABLE        = "Ljavax/annotation/Nullable;"
_NULLABLE_SP     = "Lorg/springframework/lang/Nullable;"
_NON_NULL        = "Lorg/springframework/lang/NonNull;"
_LOMBOK_DATA     = "Llombok/Data;"
_LOMBOK_VALUE    = "Llombok/Value;"
_LOMBOK_BUILDER  = "Llombok/Builder;"

# Polymorphic dispatch — a base class (e.g. Flow, Activity) declares its
# concrete subtypes and discriminator values via @JsonSubTypes; @JsonTypeInfo
# itself isn't parsed for its property-name attribute here (that's cosmetic —
# what matters structurally is the subtype ↔ discriminator mapping).
_JSON_TYPE_INFO  = "Lcom/fasterxml/jackson/annotation/JsonTypeInfo;"
_JSON_SUBTYPES   = "Lcom/fasterxml/jackson/annotation/JsonSubTypes;"

_REQUIRED_ANNOTATIONS = {_NOT_NULL, _NOT_NULL_JK, _NOT_BLANK, _NOT_BLANK_JK,
                          _NOT_EMPTY, _NOT_EMPTY_JK, _NON_NULL}
_NULLABLE_ANNOTATIONS = {_NULLABLE, _NULLABLE_SP}

_CONSTRAINT_DESCRIPTORS = {
    _SIZE, _SIZE_JK, _MIN, _MIN_JK, _MAX, _MAX_JK,
    _PATTERN, _PATTERN_JK, _EMAIL, _EMAIL_JK,
}

# Java class file ACC_ENUM flag
_ACC_ENUM = 0x4000

# Descriptor prefixes for collection / map types
_COLLECTION_CLASSES = {
    "java.util.List", "java.util.ArrayList", "java.util.LinkedList",
    "java.util.Set", "java.util.HashSet", "java.util.LinkedHashSet",
    "java.util.Collection", "java.util.Queue", "java.util.Deque",
}
_MAP_CLASSES = {
    "java.util.Map", "java.util.HashMap", "java.util.LinkedHashMap",
    "java.util.TreeMap", "java.util.SortedMap",
}

# Types we never recurse into (primitives, JDK types, Spring types, loader internals)
_SKIP_RECURSE_PREFIXES = (
    "java.", "javax.", "jakarta.", "org.springframework.", "com.fasterxml.",
    "org.hibernate.", "com.google.", "org.apache.", "io.", "reactor.",
    "kotlin.", "scala.",
    "content.lib.",   # Spring Boot fat-JAR loader classes stored under content/lib/
    "BOOT-INF.", "WEB-INF.",
)


# ---------------------------------------------------------------------------
# Output data classes
# ---------------------------------------------------------------------------

@dataclass
class DtoField:
    name: str                          # Java field name
    json_name: str                     # @JsonProperty value, or same as name
    java_type: str                     # fully qualified Java type
    simple_type: str                   # short name
    openapi_type: str                  # string | integer | number | boolean | array | object
    openapi_format: str | None         # date-time | uuid | etc.
    required: bool
    nullable: bool
    constraints: list[str]             # ["@NotBlank", "@Size(max=255)"]
    is_collection: bool
    collection_element_type: str | None   # simple name of element type
    collection_element_java: str | None   # fqn of element type
    is_map: bool
    map_value_type: str | None
    json_ignored: bool
    is_enum_type: bool = False
    description: str | None = None     # @Schema(description=...) on the field — developer-authored
    default_value: str | None = None   # @JsonSchemaDefault(...) — authored, verbatim, not inferred


@dataclass
class DtoSchema:
    class_name: str                    # fully qualified
    simple_name: str
    fields: list[DtoField]
    is_enum: bool = False
    enum_values: list[dict] = field(default_factory=list)  # [{name, serialised_as, display}]
    is_lombok: bool = False
    source_note: str | None = None     # e.g. "lombok-generated — fields inferred from getters"
    description: str | None = None     # @Schema(description=...) on the class — developer-authored


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

class DtoScanner:
    """
    Given a JAR path and a set of seed class names (from endpoint parameters /
    return types), extracts DtoSchema for each reachable DTO class up to
    MAX_DEPTH levels of nesting.
    """

    MAX_DEPTH = 5

    def __init__(self, jar_path: Path):
        self._jar_path = jar_path
        self._class_bytes: dict[str, bytes] = {}   # internal_name -> bytes
        self._loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self, seed_class_names: set[str]) -> tuple[dict[str, DtoSchema], dict[str, tuple[str, str]]]:
        """
        Returns (schemas, polymorphic_info):
        - schemas: fully-qualified-class-name -> DtoSchema for all reachable
          DTO classes starting from seed_class_names.
        - polymorphic_info: subtype fully-qualified-class-name -> (base_class,
          discriminator_value), for every concrete subtype discovered via a
          base class's @JsonSubTypes (e.g. Flow -> {"CREATE": CreateFlow, ...}).
          A subtype only lands here if some base class it's registered under
          was itself reached during this scan.
        """
        self._ensure_loaded()
        results: dict[str, DtoSchema] = {}
        polymorphic_info: dict[str, tuple[str, str]] = {}
        queue: list[tuple[str, int]] = [(n, 0) for n in seed_class_names]
        visited: set[str] = set()

        while queue:
            class_name, depth = queue.pop(0)
            if class_name in visited or depth > self.MAX_DEPTH:
                continue
            visited.add(class_name)

            if _should_skip(class_name):
                continue

            internal = class_name.replace(".", "/")
            data = self._class_bytes.get(internal)
            if not data:
                continue

            try:
                ci = ClassFileParser.parse(data)
                schema = self._parse_class(ci, data, class_name)
            except Exception:
                continue

            results[class_name] = schema

            # Queue referenced types for recursive scanning
            if not schema.is_enum:
                for f in schema.fields:
                    if not f.json_ignored:
                        if f.collection_element_java:
                            queue.append((f.collection_element_java, depth + 1))
                        elif f.map_value_type:
                            queue.append((f.map_value_type, depth + 1))
                        elif not _should_skip(f.java_type) and f.openapi_type == "object":
                            queue.append((f.java_type, depth + 1))

            # Polymorphic subtype resolution — @JsonSubTypes on a base class
            # (Flow, Activity, ...) declares its concrete subtypes and their
            # discriminator strings. Queue each subtype for scanning like any
            # other referenced type, and record the mapping for the synthesizer.
            for ann in ci.annotations:
                if ann.descriptor != _JSON_SUBTYPES:
                    continue
                for sub_ann in (ann.get("value") or []):
                    if not isinstance(sub_ann, AnnotationInfo):
                        continue
                    subtype_class = sub_ann.get("value")
                    discriminator = sub_ann.get("name")
                    if not subtype_class or not discriminator:
                        continue
                    subtype_fqcn = str(subtype_class).replace("/", ".")
                    polymorphic_info[subtype_fqcn] = (class_name, str(discriminator))
                    if subtype_fqcn not in visited:
                        queue.append((subtype_fqcn, depth + 1))

        return results, polymorphic_info

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            with zipfile.ZipFile(self._jar_path) as zf:
                for name in zf.namelist():
                    if name.endswith(".class") and not name.endswith("module-info.class"):
                        # Strip common prefixes to get internal class name
                        internal = name
                        for prefix in ("BOOT-INF/classes/", "WEB-INF/classes/",
                                       "content/lib/BOOT-INF/classes/"):
                            if internal.startswith(prefix):
                                internal = internal[len(prefix):]
                                break
                        internal = internal[:-6]  # strip .class
                        self._class_bytes[internal] = zf.read(name)
        except Exception:
            pass
        self._loaded = True

    def _parse_class(self, ci: ClassInfo, data: bytes, class_name: str) -> DtoSchema:
        ann_descs = {a.descriptor for a in ci.annotations}
        is_enum = _is_enum_class(data)
        is_lombok = bool(ann_descs & {_LOMBOK_DATA, _LOMBOK_VALUE, _LOMBOK_BUILDER})

        if is_enum:
            return self._parse_enum(ci, class_name, is_lombok)
        return self._parse_dto(ci, class_name, is_lombok)

    def _parse_enum(self, ci: ClassInfo, class_name: str, is_lombok: bool) -> DtoSchema:
        # Enum constants appear as static fields with the same type as the class
        simple = class_name.rsplit(".", 1)[-1]
        internal_type = "L" + ci.class_name + ";"
        constants = [
            f.name for f in ci.fields
            if f.descriptor == internal_type and not f.name.startswith("$")
        ]

        # Look for @JsonValue method — if present, serialised value comes from it
        has_json_value = any(
            any(a.descriptor == _JSON_VALUE for a in m.annotations)
            for m in ci.methods
        )

        # Look for String fields that might hold code/display values
        str_fields = [f.name for f in ci.fields if f.descriptor == "Ljava/lang/String;"]

        enum_values = []
        for c in constants:
            entry: dict = {"name": c, "serialised_as": c}
            if has_json_value and str_fields:
                entry["serialised_as"] = f"<{str_fields[0]} value>"
            if len(str_fields) > 1:
                entry["display"] = f"<{str_fields[1]} value>"
            enum_values.append(entry)

        return DtoSchema(
            class_name=class_name,
            simple_name=simple,
            fields=[],
            is_enum=True,
            enum_values=enum_values,
            is_lombok=is_lombok,
            description=_extract_schema_description(ci.annotations),
        )

    def _parse_dto(self, ci: ClassInfo, class_name: str, is_lombok: bool) -> DtoSchema:
        simple = class_name.rsplit(".", 1)[-1]
        dto_fields: list[DtoField] = []

        for f in ci.fields:
            # Skip synthetic, static-looking fields
            if f.name.startswith("$") or f.name.startswith("this$"):
                continue

            ann_descs = {a.descriptor for a in f.annotations}

            if _JSON_IGNORE in ann_descs:
                dto_fields.append(_make_ignored_field(f.name))
                continue

            # JSON name
            json_name = f.name
            for a in f.annotations:
                if a.descriptor == _JSON_PROPERTY:
                    val = a.get("value")
                    if val:
                        json_name = str(val)

            # Required / nullable
            required = bool(ann_descs & _REQUIRED_ANNOTATIONS)
            nullable = bool(ann_descs & _NULLABLE_ANNOTATIONS)

            # Constraints
            constraints = _extract_constraints(f.annotations)

            # Type info
            java_type = _descriptor_to_java_type(f.descriptor)
            simple_type = java_type.rsplit(".", 1)[-1]
            is_collection, elem_java, is_map, map_val = _classify_collection(f.descriptor, java_type, f.signature)
            elem_simple = elem_java.rsplit(".", 1)[-1] if elem_java else None
            openapi_type, openapi_format = _java_to_openapi(java_type, is_collection, is_map)

            # Check if the type is itself an enum (we'll know after scanning it)
            dto_fields.append(DtoField(
                name=f.name,
                json_name=json_name,
                java_type=java_type,
                simple_type=simple_type,
                openapi_type=openapi_type,
                openapi_format=openapi_format,
                required=required,
                nullable=nullable,
                constraints=constraints,
                is_collection=is_collection,
                collection_element_type=elem_simple,
                collection_element_java=elem_java,
                is_map=is_map,
                map_value_type=map_val,
                json_ignored=False,
                description=_extract_schema_description(f.annotations),
                default_value=_extract_default_value(f.annotations),
            ))

        note = "lombok-generated — fields inferred from declared fields" if is_lombok else None
        return DtoSchema(
            class_name=class_name,
            simple_name=simple,
            fields=dto_fields,
            is_lombok=is_lombok,
            source_note=note,
            description=_extract_schema_description(ci.annotations),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_enum_class(data: bytes) -> bool:
    """Check ACC_ENUM flag in class file access_flags."""
    try:
        # magic(4) + minor(2) + major(2) = 8 bytes, then constant pool
        # We need to skip the constant pool to reach access_flags.
        # Use ClassFileParser which already does this.
        import struct
        # Quick check: parse just enough to get access_flags
        # After magic+minor+major = 8 bytes, constant pool count at offset 8
        if len(data) < 10:
            return False
        cp_count = struct.unpack_from(">H", data, 8)[0]
        # Rather than re-implementing CP skip, parse the full class and check
        # the raw bytes for the enum flag position — use the parser instead
        ci = ClassFileParser.parse(data)
        # Re-read access flags: they come right after the constant pool
        # We can infer from the class name pattern or check fields
        # Reliable: check if any field has the same descriptor as the class itself
        internal = "L" + ci.class_name + ";"
        return any(f.descriptor == internal for f in ci.fields)
    except Exception:
        return False


def _should_skip(class_name: str) -> bool:
    return any(class_name.startswith(p) for p in _SKIP_RECURSE_PREFIXES)


def _descriptor_to_java_type(desc: str) -> str:
    """Convert a JVM field descriptor to a Java type name."""
    if desc.startswith("["):
        inner = _descriptor_to_java_type(desc[1:])
        return inner + "[]"
    if desc.startswith("L") and desc.endswith(";"):
        return desc[1:-1].replace("/", ".")
    primitives = {
        "B": "byte", "C": "char", "D": "double", "F": "float",
        "I": "int", "J": "long", "S": "short", "Z": "boolean", "V": "void",
    }
    return primitives.get(desc, desc)


def _generic_type_params(signature: str | None) -> list[str]:
    """Extract the top-level type-parameter descriptors from a field's
    generic Signature attribute, e.g. "Ljava/util/Map<Ljava/lang/String;Lfoo/Bar;>;"
    -> ["Ljava/lang/String;", "Lfoo/Bar;"]. Returns [] for a raw/non-generic
    declaration (no Signature attribute at all) or anything unparseable.
    Tracks bracket depth so a nested generic (List<List<Foo>>) stays as one
    top-level parameter rather than splitting on its own inner ';'."""
    if not signature:
        return []
    start = signature.find("<")
    end = signature.rfind(">")
    if start == -1 or end == -1 or end <= start:
        return []
    params: list[str] = []
    depth = 0
    current = ""
    for c in signature[start + 1:end]:
        current += c
        if c == "<":
            depth += 1
        elif c == ">":
            depth -= 1
        elif c == ";" and depth == 0:
            params.append(current)
            current = ""
    return params


def _generic_param_to_java_type(param: str) -> str | None:
    """A single top-level generic type-parameter descriptor -> Java type.
    None for anything this doesn't attempt to resolve: an unbounded
    wildcard (?, descriptor "*"), or an unresolved type variable (a generic
    class's own <T>, descriptor "TT;") — bounded wildcards (? extends X /
    ? super X, descriptor "+X"/"-X") resolve to the bound itself."""
    param = param.lstrip("+-")
    if not param or param == "*" or (param.startswith("T") and param.endswith(";")):
        return None
    return _descriptor_to_java_type(param)


def _classify_collection(
    descriptor: str, java_type: str, signature: str | None = None
) -> tuple[bool, str | None, bool, str | None]:
    """
    Returns (is_collection, element_java_type, is_map, map_value_type).
    Plain descriptors erase generics — List<Flow> and a raw List both
    descriptor to "Ljava/util/List;" — so the element/value type can only
    be recovered from the field's Signature attribute (see classfile.py),
    when the compiler emitted one (always does, for a generic declaration).
    """
    if java_type in _COLLECTION_CLASSES or java_type.endswith("[]"):
        if java_type.endswith("[]"):
            return True, java_type[:-2], False, None
        params = _generic_type_params(signature)
        elem = _generic_param_to_java_type(params[0]) if params else None
        return True, elem, False, None
    if java_type in _MAP_CLASSES:
        params = _generic_type_params(signature)
        val = _generic_param_to_java_type(params[1]) if len(params) > 1 else None
        return False, None, True, val
    return False, None, False, None


def _java_to_openapi(
    java_type: str, is_collection: bool, is_map: bool
) -> tuple[str, str | None]:
    """Map a Java type to an OpenAPI type + optional format."""
    if is_collection or java_type.endswith("[]"):
        return "array", None
    if is_map:
        return "object", None
    t = java_type.lower()
    last = java_type.rsplit(".", 1)[-1].lower()
    if last in ("string", "charsequence"):
        return "string", None
    if last in ("int", "integer", "short", "byte"):
        return "integer", "int32"
    if last in ("long", "biginteger"):
        return "integer", "int64"
    if last in ("float"):
        return "number", "float"
    if last in ("double", "bigdecimal"):
        return "number", "double"
    if last in ("boolean"):
        return "boolean", None
    if last in ("localdate",):
        return "string", "date"
    if last in ("localdatetime", "zoneddatetime", "offsetdatetime", "instant", "date"):
        return "string", "date-time"
    if last in ("uuid",):
        return "string", "uuid"
    if last in ("void",):
        return "null", None
    if _should_skip(java_type):
        return "object", None
    return "object", None


def _extract_constraints(annotations: list) -> list[str]:
    parts = []
    for a in annotations:
        if a.descriptor not in _CONSTRAINT_DESCRIPTORS:
            continue
        name = a.descriptor.rstrip(";").rsplit("/", 1)[-1].lstrip("L")
        attrs = []
        for el in a.elements:
            if el.name in ("min", "max", "value", "regexp"):
                attrs.append(f"{el.name}={el.value}")
        parts.append(f"@{name}({', '.join(attrs)})" if attrs else f"@{name}")
    return parts


def _extract_schema_description(annotations: list) -> str | None:
    """@Schema(description=...) — developer-authored text. See Stage 4 of
    the accuracy plan. None if the class/field has no @Schema, or it has no
    description element."""
    for a in annotations:
        if a.descriptor == _SCHEMA:
            desc = a.get("description")
            return desc or None
    return None


def _extract_default_value(annotations: list) -> str | None:
    """@JsonSchemaDefault(...) (com.kjetland:jackson-jsonSchema) — an authored
    example/default value straight off the annotation, verbatim, not inferred.
    Used by the config-example synthesizer as authoritative field content."""
    for a in annotations:
        if a.descriptor == _JSON_SCHEMA_DEFAULT:
            val = a.get("value")
            return str(val) if val else None
    return None


def _make_ignored_field(name: str) -> DtoField:
    return DtoField(
        name=name, json_name=name, java_type="", simple_type="",
        openapi_type="string", openapi_format=None,
        required=False, nullable=True, constraints=[],
        is_collection=False, collection_element_type=None,
        collection_element_java=None, is_map=False,
        map_value_type=None, json_ignored=True,
    )


# ---------------------------------------------------------------------------
# Enum sweep — scan ALL enum classes in the JAR regardless of endpoint refs
# ---------------------------------------------------------------------------

def scan_all_enums(jar_path: Path) -> dict[str, DtoSchema]:
    """
    Sweep every class file in the JAR and return DtoSchema for each enum class.
    This is independent of endpoint seed classes — it surfaces all enums even
    those not directly referenced by any endpoint parameter or return type.
    """
    scanner = DtoScanner(jar_path)
    scanner._ensure_loaded()
    results: dict[str, DtoSchema] = {}
    for internal, data in scanner._class_bytes.items():
        class_name = internal.replace("/", ".")
        if _should_skip(class_name):
            continue
        try:
            if not _is_enum_class(data):
                continue
            ci = ClassFileParser.parse(data)
            schema = scanner._parse_enum(ci, class_name, False)
            if schema.enum_values:  # skip empty / synthetic enums
                results[class_name] = schema
        except Exception:
            continue
    return results


# ---------------------------------------------------------------------------
# Seed extraction — pull referenced class names from endpoint data
# ---------------------------------------------------------------------------

def collect_seed_classes(endpoints: list[dict]) -> set[str]:
    """
    Given a list of endpoint dicts (as stored in SubReportData.endpoints),
    return the set of Java class names that should be scanned as DTOs.
    """
    seeds: set[str] = set()
    for ep in endpoints:
        body = ep.get("request_body")
        if body:
            _add_type(seeds, body.get("java_type"))
        ret = ep.get("return_type")
        if ret:
            _add_type(seeds, ret.get("java_type"))
        for p in ep.get("parameters", []):
            _add_type(seeds, p.get("java_type"))
    return seeds


def _add_type(seeds: set[str], java_type: str | None) -> None:
    if not java_type:
        return
    # Strip array suffix
    java_type = java_type.rstrip("[]")
    if not java_type or _should_skip(java_type):
        return
    seeds.add(java_type)
