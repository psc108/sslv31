"""Java class file parser.

Parses compiled .class files to extract:
- Class name, superclass, interfaces
- Class-level RuntimeVisibleAnnotations
- Method signatures and their RuntimeVisibleAnnotations
- Field names and descriptors

Implements the Java Virtual Machine Specification class file format
(JVMS §4) for Java 8–21 (class file versions 52–65).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AnnotationElement:
    name: str
    value: Any  # str | list[str] | list[AnnotationElement]


@dataclass
class AnnotationInfo:
    descriptor: str          # e.g. "Lorg/springframework/web/bind/annotation/GetMapping;"
    elements: list[AnnotationElement] = field(default_factory=list)

    @property
    def simple_name(self) -> str:
        return self.descriptor.rstrip(";").rsplit("/", 1)[-1].lstrip("L")

    def get(self, name: str, default: Any = None) -> Any:
        for el in self.elements:
            if el.name == name:
                return el.value
        return default


@dataclass
class MethodInfo:
    name: str
    descriptor: str
    annotations: list[AnnotationInfo] = field(default_factory=list)
    parameter_annotations: list[list[AnnotationInfo]] = field(default_factory=list)


@dataclass
class FieldInfo:
    name: str
    descriptor: str
    annotations: list[AnnotationInfo] = field(default_factory=list)
    # Raw JVMS Signature attribute string, e.g. "Ljava/util/List<Lcom/foo/Bar;>;"
    # — present only when the field's declared type uses generics. The plain
    # `descriptor` above always erases generics (List<Flow> and a raw List
    # both descriptor to "Ljava/util/List;"), so this is the only way to
    # recover a collection's element type from bytecode.
    signature: str | None = None


@dataclass
class ClassInfo:
    class_name: str          # e.g. "com/dxc/ecs/customers/controller/CustomerController"
    superclass: str | None
    interfaces: list[str]
    annotations: list[AnnotationInfo]
    methods: list[MethodInfo]
    fields: list[FieldInfo]
    class_file_version: int  # major version, e.g. 61 = Java 17
    # String literals this class's compiled code actually uses (ldc'd in a
    # method body, or a string-valued annotation element / static final
    # field initialiser) — resolved from the constant pool's CONSTANT_String
    # entries, not a raw dump of every CONSTANT_Utf8 (which is mostly
    # method/field descriptors and internal type names, not real literals).
    # See _string_constants() below. Empty for classes with none.
    string_constants: list[str] = field(default_factory=list)

    @property
    def java_class_name(self) -> str:
        return self.class_name.replace("/", ".")

    @property
    def simple_name(self) -> str:
        return self.class_name.rsplit("/", 1)[-1]

    @property
    def package_name(self) -> str:
        parts = self.class_name.rsplit("/", 1)
        return parts[0].replace("/", ".") if len(parts) > 1 else ""

    @property
    def java_version(self) -> str:
        return _MAJOR_TO_JAVA.get(self.class_file_version, str(self.class_file_version))


_MAJOR_TO_JAVA = {52: "8", 53: "9", 54: "10", 55: "11", 56: "12", 57: "13",
                  58: "14", 59: "15", 60: "16", 61: "17", 62: "18", 63: "19",
                  64: "20", 65: "21"}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class ClassFileParser:
    """Parse a Java .class file from bytes."""

    MAGIC = 0xCAFEBABE

    @classmethod
    def parse(cls, data: bytes) -> ClassInfo:
        p = _Parser(data)
        magic = p.u4()
        if magic != cls.MAGIC:
            raise ValueError(f"Not a Java class file (magic=0x{magic:08X})")
        _minor = p.u2()
        major = p.u2()
        pool = _read_constant_pool(p)
        _access_flags = p.u2()
        this_idx = p.u2()
        super_idx = p.u2()
        iface_count = p.u2()
        interfaces = [_class_name(pool, p.u2()) for _ in range(iface_count)]
        superclass = _class_name(pool, super_idx) if super_idx else None
        class_name = _class_name(pool, this_idx)
        fields = _read_members(p, pool)
        methods = _read_members(p, pool)
        class_attrs = _read_attributes(p, pool)

        class_annotations = _extract_annotations(class_attrs, pool)
        method_infos = [
            MethodInfo(
                name=_utf8(pool, m["name_idx"]),
                descriptor=_utf8(pool, m["desc_idx"]),
                annotations=_extract_annotations(m["attrs"], pool),
                parameter_annotations=_extract_param_annotations(m["attrs"], pool),
            )
            for m in methods
        ]
        field_infos = [
            FieldInfo(
                name=_utf8(pool, f["name_idx"]),
                descriptor=_utf8(pool, f["desc_idx"]),
                annotations=_extract_annotations(f["attrs"], pool),
                signature=_extract_signature(f["attrs"], pool),
            )
            for f in fields
        ]
        return ClassInfo(
            class_name=class_name,
            superclass=superclass,
            interfaces=interfaces,
            annotations=class_annotations,
            methods=method_infos,
            fields=field_infos,
            class_file_version=major,
            string_constants=_string_constants(pool),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _Parser:
    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def u1(self) -> int:
        v = self._data[self._pos]
        self._pos += 1
        return v

    def u2(self) -> int:
        v = struct.unpack_from(">H", self._data, self._pos)[0]
        self._pos += 2
        return v

    def u4(self) -> int:
        v = struct.unpack_from(">I", self._data, self._pos)[0]
        self._pos += 4
        return v

    def read(self, n: int) -> bytes:
        v = self._data[self._pos:self._pos + n]
        self._pos += n
        return v

    def skip(self, n: int) -> None:
        self._pos += n

    def sub(self, n: int) -> "_Parser":
        return _Parser(self.read(n))


def _read_constant_pool(p: _Parser) -> list:
    count = p.u2()
    pool: list = [None] * count  # 1-indexed; pool[0] unused
    i = 1
    while i < count:
        tag = p.u1()
        if tag == 1:    # Utf8
            length = p.u2()
            pool[i] = ("Utf8", p.read(length).decode("utf-8", errors="replace"))
        elif tag == 3:  # Integer
            pool[i] = ("Integer", struct.unpack(">i", p.read(4))[0])
        elif tag == 4:  # Float
            pool[i] = ("Float", struct.unpack(">f", p.read(4))[0])
        elif tag == 5:  # Long
            pool[i] = ("Long", struct.unpack(">q", p.read(8))[0])
            i += 1  # longs/doubles take two slots
            pool[i] = None
        elif tag == 6:  # Double
            pool[i] = ("Double", struct.unpack(">d", p.read(8))[0])
            i += 1
            pool[i] = None
        elif tag == 7:  # Class
            pool[i] = ("Class", p.u2())
        elif tag == 8:  # String
            pool[i] = ("String", p.u2())
        elif tag in (9, 10, 11):  # Fieldref, Methodref, InterfaceMethodref
            pool[i] = (tag, p.u2(), p.u2())
        elif tag == 12:  # NameAndType
            pool[i] = ("NameAndType", p.u2(), p.u2())
        elif tag == 15:  # MethodHandle
            pool[i] = ("MethodHandle", p.u1(), p.u2())
        elif tag == 16:  # MethodType
            pool[i] = ("MethodType", p.u2())
        elif tag == 17:  # Dynamic
            pool[i] = ("Dynamic", p.u2(), p.u2())
        elif tag == 18:  # InvokeDynamic
            pool[i] = ("InvokeDynamic", p.u2(), p.u2())
        elif tag == 19:  # Module
            pool[i] = ("Module", p.u2())
        elif tag == 20:  # Package
            pool[i] = ("Package", p.u2())
        else:
            raise ValueError(f"Unknown constant pool tag {tag} at index {i}")
        i += 1
    return pool


def _utf8(pool: list, idx: int) -> str:
    if idx == 0 or idx >= len(pool):
        return ""
    entry = pool[idx]
    if entry and entry[0] == "Utf8":
        return entry[1]
    return ""


def _string_constants(pool: list) -> list[str]:
    """Every CONSTANT_String entry's resolved text, deduped, order-preserved.
    A class's constant pool gets exactly one String-tag entry per distinct
    literal the compiler emitted an ldc for (or used as an annotation/field
    constant value) — the pool is already deduped by the compiler itself, so
    no further work is needed to avoid repeats from the same class."""
    seen: set[str] = set()
    out: list[str] = []
    for entry in pool:
        if entry and entry[0] == "String":
            value = _utf8(pool, entry[1])
            if value and value not in seen:
                seen.add(value)
                out.append(value)
    return out


def _class_name(pool: list, idx: int) -> str:
    if idx == 0 or idx >= len(pool):
        return ""
    entry = pool[idx]
    if entry and entry[0] == "Class":
        return _utf8(pool, entry[1])
    return ""


def _read_members(p: _Parser, pool: list) -> list[dict]:
    count = p.u2()
    members = []
    for _ in range(count):
        _access = p.u2()
        name_idx = p.u2()
        desc_idx = p.u2()
        attrs = _read_attributes(p, pool)
        members.append({"name_idx": name_idx, "desc_idx": desc_idx, "attrs": attrs})
    return members


def _read_attributes(p: _Parser, pool: list) -> dict[str, bytes]:
    count = p.u2()
    attrs: dict[str, bytes] = {}
    for _ in range(count):
        name_idx = p.u2()
        length = p.u4()
        data = p.read(length)
        name = _utf8(pool, name_idx)
        attrs[name] = data
    return attrs


def _extract_signature(attrs: dict[str, bytes], pool: list) -> str | None:
    """JVMS §4.7.9 Signature attribute: just a u2 constant-pool index into a
    UTF8 entry holding the generic signature string. Absent for non-generic
    fields (a raw `List` with no <T>, or a plain scalar)."""
    data = attrs.get("Signature")
    if not data or len(data) < 2:
        return None
    idx = (data[0] << 8) | data[1]
    return _utf8(pool, idx)


def _extract_annotations(attrs: dict[str, bytes], pool: list) -> list[AnnotationInfo]:
    data = attrs.get("RuntimeVisibleAnnotations")
    if not data:
        return []
    return _parse_annotations_table(data, pool)


def _extract_param_annotations(attrs: dict[str, bytes], pool: list) -> list[list[AnnotationInfo]]:
    data = attrs.get("RuntimeVisibleParameterAnnotations")
    if not data:
        return []
    p = _Parser(data)
    num_params = p.u1()
    result = []
    for _ in range(num_params):
        num_ann = p.u2()
        anns = []
        for _ in range(num_ann):
            ann = _parse_one_annotation(p, pool)
            if ann:
                anns.append(ann)
        result.append(anns)
    return result


def _parse_annotations_table(data: bytes, pool: list) -> list[AnnotationInfo]:
    p = _Parser(data)
    count = p.u2()
    result = []
    for _ in range(count):
        ann = _parse_one_annotation(p, pool)
        if ann:
            result.append(ann)
    return result


def _parse_one_annotation(p: _Parser, pool: list) -> AnnotationInfo | None:
    try:
        type_idx = p.u2()
        descriptor = _utf8(pool, type_idx)
        num_pairs = p.u2()
        elements = []
        for _ in range(num_pairs):
            name_idx = p.u2()
            name = _utf8(pool, name_idx)
            value = _parse_element_value(p, pool)
            elements.append(AnnotationElement(name=name, value=value))
        return AnnotationInfo(descriptor=descriptor, elements=elements)
    except Exception:
        return None


def _parse_element_value(p: _Parser, pool: list) -> Any:
    tag = chr(p.u1())
    if tag in "BCDFIJSZs":  # primitive or String
        idx = p.u2()
        entry = pool[idx] if idx < len(pool) else None
        if entry:
            if entry[0] == "Utf8":
                return entry[1]
            if entry[0] in ("Integer", "Long", "Float", "Double"):
                return entry[1]
            if entry[0] == "String":
                return _utf8(pool, entry[1])
        return None
    elif tag == "e":  # enum
        _type_idx = p.u2()
        const_idx = p.u2()
        return _utf8(pool, const_idx)
    elif tag == "c":  # class
        idx = p.u2()
        return _utf8(pool, idx)
    elif tag == "@":  # nested annotation
        ann = _parse_one_annotation(p, pool)
        return ann
    elif tag == "[":  # array
        count = p.u2()
        return [_parse_element_value(p, pool) for _ in range(count)]
    return None
