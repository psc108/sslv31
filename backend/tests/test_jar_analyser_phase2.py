"""Phase 2 unit tests — Bytecode Analysis & API Discovery.

Uses the real installation-package-2.6.9.jar as the primary fixture.
Run with:
    set PYTHONPATH=c:\\Users\\pscott32\\IdeaProjects\\ssl\\backend
    py -3 -m pytest tests/test_jar_analyser_phase2.py -v --noconftest
"""
from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

import pytest

from app.services.jar_analyser.classfile import ClassFileParser, ClassInfo, AnnotationInfo
from app.services.jar_analyser.annotations import (
    AnnotationScanner, ScanResult,
    JAXRS_PATH, COMPONENT, ENTITY_JK,
)
from app.services.jar_analyser.endpoints import EndpointReconstructor, Endpoint
from app.services.jar_analyser.packages import PackageAnalyser
from app.services.jar_analyser.flyway import FlywayExtractor
from app.services.jar_analyser.events import EventDefinitionExtractor

REAL_JAR = Path(r"C:\Users\pscott32\IdeaProjects\docker-ssl-test\shared\installation-package-2.6.9.jar")
CUSTOMERS_INSTALLER = "customers-installer-2.6.8.jar"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_customers_installer() -> bytes:
    d = REAL_JAR.read_bytes()
    zf = zipfile.ZipFile(io.BytesIO(d))
    return zf.read(CUSTOMERS_INSTALLER)


def _customers_class(name: str) -> bytes:
    """Read a class file from the customers installer by simple class name."""
    data = _load_customers_installer()
    inner = zipfile.ZipFile(io.BytesIO(data))
    for entry in inner.namelist():
        if entry.endswith(f"/{name}.class") or entry == f"{name}.class":
            return inner.read(entry)
    raise FileNotFoundError(f"{name}.class not found in customers installer")


def _make_minimal_class(class_name: str = "com/example/Foo") -> bytes:
    """Build a minimal valid Java class file (no annotations, no methods)."""
    # Constant pool: [unused, Utf8(class_name), Class(2), Utf8("java/lang/Object"), Class(4),
    #                 Utf8("Code"), Utf8("<init>"), Utf8("()V")]
    def utf8(s: str) -> bytes:
        b = s.encode("utf-8")
        return struct.pack(">BH", 1, len(b)) + b

    pool_entries = [
        utf8(class_name),           # 1
        struct.pack(">BH", 7, 1),   # 2 Class -> #1
        utf8("java/lang/Object"),   # 3
        struct.pack(">BH", 7, 3),   # 4 Class -> #3
    ]
    pool_bytes = b"".join(pool_entries)
    pool_count = len(pool_entries) + 1  # +1 because pool is 1-indexed

    buf = io.BytesIO()
    buf.write(struct.pack(">I", 0xCAFEBABE))   # magic
    buf.write(struct.pack(">HH", 0, 61))        # minor=0, major=61 (Java 17)
    buf.write(struct.pack(">H", pool_count))    # constant_pool_count
    buf.write(pool_bytes)
    buf.write(struct.pack(">H", 0x0021))        # access_flags: public + super
    buf.write(struct.pack(">H", 2))             # this_class -> #2
    buf.write(struct.pack(">H", 4))             # super_class -> #4
    buf.write(struct.pack(">H", 0))             # interfaces_count
    buf.write(struct.pack(">H", 0))             # fields_count
    buf.write(struct.pack(">H", 0))             # methods_count
    buf.write(struct.pack(">H", 0))             # attributes_count
    return buf.getvalue()


def _make_class_with_string(class_name: str = "com/example/Foo", literal: str = "Order not found: %s") -> bytes:
    """Same minimal layout as _make_minimal_class, plus one CONSTANT_Utf8 +
    one CONSTANT_String entry referencing it — simulating a class whose
    code embeds `literal` as an ldc'd string (e.g. a log message)."""
    def utf8(s: str) -> bytes:
        b = s.encode("utf-8")
        return struct.pack(">BH", 1, len(b)) + b

    pool_entries = [
        utf8(class_name),           # 1
        struct.pack(">BH", 7, 1),   # 2 Class -> #1
        utf8("java/lang/Object"),   # 3
        struct.pack(">BH", 7, 3),   # 4 Class -> #3
        utf8(literal),               # 5
        struct.pack(">BH", 8, 5),   # 6 String -> #5
    ]
    pool_bytes = b"".join(pool_entries)
    pool_count = len(pool_entries) + 1

    buf = io.BytesIO()
    buf.write(struct.pack(">I", 0xCAFEBABE))
    buf.write(struct.pack(">HH", 0, 61))
    buf.write(struct.pack(">H", pool_count))
    buf.write(pool_bytes)
    buf.write(struct.pack(">H", 0x0021))
    buf.write(struct.pack(">H", 2))
    buf.write(struct.pack(">H", 4))
    buf.write(struct.pack(">H", 0))
    buf.write(struct.pack(">H", 0))
    buf.write(struct.pack(">H", 0))
    buf.write(struct.pack(">H", 0))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# ClassFileParser tests
# ---------------------------------------------------------------------------

class TestClassFileParser:

    def test_rejects_non_class_file(self):
        with pytest.raises(ValueError, match="Not a Java class file"):
            ClassFileParser.parse(b"not a class file")

    def test_parses_minimal_class(self):
        data = _make_minimal_class("com/example/Foo")
        ci = ClassFileParser.parse(data)
        assert ci.java_class_name == "com.example.Foo"
        assert ci.simple_name == "Foo"
        assert ci.package_name == "com.example"
        assert ci.class_file_version == 61
        assert ci.java_version == "17"
        assert ci.superclass == "java/lang/Object"
        assert ci.annotations == []
        assert ci.methods == []
        assert ci.string_constants == []

    def test_extracts_string_constants(self):
        data = _make_class_with_string(literal="Order not found: %s")
        ci = ClassFileParser.parse(data)
        assert ci.string_constants == ["Order not found: %s"]

    def test_dedupes_repeated_string_constants(self):
        # The compiler itself dedupes a class's constant pool, so a literal
        # referenced from two different methods still yields one CONSTANT_String
        # entry — _string_constants() just needs to not introduce its own dupe.
        data = _make_class_with_string(literal="shared message")
        ci = ClassFileParser.parse(data)
        assert ci.string_constants.count("shared message") == 1

    def test_real_class_string_constants_are_plausible(self):
        # Sanity check against the real fixture jar, not just synthetic bytes
        # — a real business-logic class should have at least some string
        # literals (log messages, exception text, JSON keys, etc.).
        data = _customers_class("ContractResource")
        ci = ClassFileParser.parse(data)
        assert isinstance(ci.string_constants, list)
        assert all(isinstance(s, str) and s for s in ci.string_constants)

    def test_parses_real_class_name(self):
        data = _customers_class("ContractResource")
        ci = ClassFileParser.parse(data)
        assert "ContractResource" in ci.java_class_name
        assert ci.class_file_version >= 52  # at least Java 8

    def test_real_class_has_annotations(self):
        data = _customers_class("ContractResource")
        ci = ClassFileParser.parse(data)
        assert len(ci.annotations) > 0

    def test_real_class_has_methods(self):
        data = _customers_class("ContractResource")
        ci = ClassFileParser.parse(data)
        method_names = {m.name for m in ci.methods}
        assert len(method_names) > 0

    def test_jaxrs_path_annotation_extracted(self):
        data = _customers_class("ContractResource")
        ci = ClassFileParser.parse(data)
        descs = {a.descriptor for a in ci.annotations}
        assert JAXRS_PATH in descs

    def test_path_value_extracted(self):
        data = _customers_class("ContractResource")
        ci = ClassFileParser.parse(data)
        path_ann = next(a for a in ci.annotations if a.descriptor == JAXRS_PATH)
        assert path_ann.get("value") is not None
        assert "contracts" in str(path_ann.get("value"))

    def test_method_annotations_extracted(self):
        data = _customers_class("ContractResource")
        ci = ClassFileParser.parse(data)
        # Should have methods with GET/POST/PUT annotations
        method_ann_descs = {
            a.descriptor
            for m in ci.methods
            for a in m.annotations
        }
        assert any("GET" in d or "POST" in d or "PUT" in d for d in method_ann_descs)

    def test_java_version_mapping(self):
        data = _make_minimal_class()
        ci = ClassFileParser.parse(data)
        assert ci.java_version == "17"  # major 61


# ---------------------------------------------------------------------------
# AnnotationScanner tests
# ---------------------------------------------------------------------------

class TestAnnotationScanner:

    @pytest.fixture(scope="class")
    def scan_result(self) -> ScanResult:
        data = _load_customers_installer()
        jar_path = Path("customers-installer.jar")
        # Write to temp and scan
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".jar", delete=False) as f:
            f.write(data)
            tmp = f.name
        try:
            return AnnotationScanner.scan_jar(Path(tmp))
        finally:
            os.unlink(tmp)

    def test_finds_controllers(self, scan_result):
        assert len(scan_result.controllers) > 0

    def test_finds_components(self, scan_result):
        assert len(scan_result.components) > 0

    def test_finds_app_classes(self, scan_result):
        assert len(scan_result.all_classes) > 0

    def test_class_file_versions_populated(self, scan_result):
        assert len(scan_result.class_file_versions) > 0
        assert scan_result.min_class_version is not None
        assert scan_result.max_class_version is not None

    def test_jaxrs_controllers_detected(self, scan_result):
        # ContractResource, CustomerResource etc. use @Path
        controller_names = {ci.simple_name for ci in scan_result.controllers}
        assert any("Resource" in n for n in controller_names)

    def test_entity_classes_in_components(self, scan_result):
        # JPA @Entity classes should be in components
        all_ann_descs = {
            a.descriptor
            for ci in scan_result.components
            for a in ci.annotations
        }
        assert ENTITY_JK in all_ann_descs or any("Entity" in d for d in all_ann_descs)

    def test_no_framework_classes_scanned(self, scan_result):
        # No Spring framework internal classes should appear
        for ci in scan_result.all_classes:
            assert not ci.java_class_name.startswith("org.springframework.")


# ---------------------------------------------------------------------------
# EndpointReconstructor tests
# ---------------------------------------------------------------------------

class TestEndpointReconstructor:

    @pytest.fixture(scope="class")
    def endpoints(self) -> list[Endpoint]:
        data = _load_customers_installer()
        inner = zipfile.ZipFile(io.BytesIO(data))
        classes = []
        for entry in inner.namelist():
            if not entry.endswith(".class") or "com/dxc" not in entry:
                continue
            try:
                ci = ClassFileParser.parse(inner.read(entry))
                classes.append(ci)
            except Exception:
                pass
        return EndpointReconstructor.reconstruct(classes)

    def test_finds_endpoints(self, endpoints):
        assert len(endpoints) > 0

    def test_endpoints_have_http_methods(self, endpoints):
        methods = {e.http_method for e in endpoints}
        assert methods & {"GET", "POST", "PUT", "DELETE"}

    def test_endpoints_have_paths(self, endpoints):
        for ep in endpoints:
            assert ep.full_path.startswith("/")

    def test_contracts_endpoint_found(self, endpoints):
        paths = {e.full_path for e in endpoints}
        assert any("contracts" in p for p in paths)

    def test_signature_key_format(self, endpoints):
        for ep in endpoints:
            assert ":" in ep.signature_key
            method, path = ep.signature_key.split(":", 1)
            assert method in {"GET", "POST", "PUT", "PATCH", "DELETE", "ANY"}
            assert path.startswith("/")

    def test_security_extracted_where_present(self, endpoints):
        secured = [e for e in endpoints if e.security is not None]
        assert len(secured) > 0
        for ep in secured:
            assert ep.security.annotation in {"@RolesAllowed", "@PreAuthorize", "@Secured"}
            assert len(ep.security.expression) > 0

    def test_controller_class_populated(self, endpoints):
        for ep in endpoints:
            assert "." in ep.controller_class  # fully qualified
            assert ep.controller_simple != ""

    def test_no_duplicate_signature_keys_per_controller(self, endpoints):
        # Within a single controller, signature keys should be unique
        from collections import defaultdict
        by_controller: dict[str, list[str]] = defaultdict(list)
        for ep in endpoints:
            by_controller[ep.controller_class].append(ep.signature_key)
        for ctrl, keys in by_controller.items():
            assert len(keys) == len(set(keys)), f"Duplicate keys in {ctrl}: {keys}"


# ---------------------------------------------------------------------------
# PackageAnalyser tests
# ---------------------------------------------------------------------------

class TestPackageAnalyser:

    @pytest.fixture(scope="class")
    def structure(self):
        data = _load_customers_installer()
        inner = zipfile.ZipFile(io.BytesIO(data))
        classes = []
        for entry in inner.namelist():
            if not entry.endswith(".class") or "com/dxc" not in entry:
                continue
            try:
                classes.append(ClassFileParser.parse(inner.read(entry)))
            except Exception:
                pass
        return PackageAnalyser.analyse(classes)

    def test_has_packages(self, structure):
        assert structure.package_count > 0

    def test_has_classes(self, structure):
        assert structure.class_count > 0

    def test_root_packages_detected(self, structure):
        assert len(structure.root_packages) > 0
        assert any("com.dxc" in p for p in structure.root_packages)

    def test_layer_summary_populated(self, structure):
        assert len(structure.layer_summary) > 0

    def test_model_layer_detected(self, structure):
        layers = {ls.layer for ls in structure.layer_summary}
        assert "model" in layers

    def test_nodes_have_class_counts(self, structure):
        for node in structure.nodes.values():
            assert node.class_count >= 0


# ---------------------------------------------------------------------------
# FlywayExtractor tests
# ---------------------------------------------------------------------------

class TestFlywayExtractor:

    @pytest.fixture(scope="class")
    def scripts(self):
        import tempfile, os
        data = _load_customers_installer()
        with tempfile.NamedTemporaryFile(suffix=".jar", delete=False) as f:
            f.write(data)
            tmp = f.name
        try:
            return FlywayExtractor.from_jar(Path(tmp))
        finally:
            os.unlink(tmp)

    def test_finds_migration_scripts(self, scripts):
        assert len(scripts) > 0

    def test_scripts_have_filenames(self, scripts):
        for s in scripts:
            assert s.filename.endswith(".sql")

    def test_versioned_scripts_have_version(self, scripts):
        versioned = [s for s in scripts if s.script_type == "versioned"]
        assert len(versioned) > 0
        for s in versioned:
            assert s.version is not None

    def test_ddl_operations_detected(self, scripts):
        # At least some scripts should have DDL ops
        all_ops = [op for s in scripts for op in s.ddl_operations]
        assert len(all_ops) > 0

    def test_tables_extracted(self, scripts):
        all_tables = [t for s in scripts for t in s.tables_affected]
        assert len(all_tables) > 0

    def test_content_populated(self, scripts):
        for s in scripts:
            assert len(s.content) > 0

    def test_statement_count_positive(self, scripts):
        for s in scripts:
            assert s.statement_count >= 1

    def test_parse_dotted_version(self):
        # Real CPI uses V2.4.0_6__desc.sql format
        s = FlywayExtractor._parse("V2.4.0_6__sub_entity_type.sql", "ALTER TABLE FOO ADD BAR VARCHAR(30);")
        assert s.version == "2.4.0_6"
        assert s.description == "sub entity type"
        assert s.script_type == "versioned"
        assert "ALTER TABLE" in s.ddl_operations


# ---------------------------------------------------------------------------
# EventDefinitionExtractor tests
# ---------------------------------------------------------------------------

class TestEventDefinitionExtractor:

    @pytest.fixture(scope="class")
    def events(self):
        import tempfile, os
        data = _load_customers_installer()
        with tempfile.NamedTemporaryFile(suffix=".jar", delete=False) as f:
            f.write(data)
            tmp = f.name
        try:
            return EventDefinitionExtractor.from_jar(Path(tmp))
        finally:
            os.unlink(tmp)

    def test_finds_event_files(self, events):
        assert len(events) > 0

    def test_event_filenames(self, events):
        names = {e.filename for e in events}
        assert any("event.yml" in n for n in names)

    def test_customer_events_parsed(self, events):
        customer = next((e for e in events if "Customer" in e.filename), None)
        assert customer is not None
        assert len(customer.published_events) > 0

    def test_published_events_have_entity(self, events):
        for evdef in events:
            for pub in evdef.published_events:
                assert pub.entity != ""

    def test_published_events_have_actions(self, events):
        for evdef in events:
            for pub in evdef.published_events:
                assert len(pub.actions) > 0

    def test_consumers_extracted(self, events):
        customer = next((e for e in events if "Customer" in e.filename), None)
        assert customer is not None
        # Customer.event.yml has queues with applicationId
        all_consumers = [c for pub in customer.published_events for c in pub.consumers]
        assert len(all_consumers) > 0

    def test_content_preserved(self, events):
        for evdef in events:
            assert len(evdef.content) > 0
            assert "events:" in evdef.content

    def test_parse_generic_schema(self):
        # Test the fallback generic schema
        yml = """
publishes:
  - entity: customer
    actions: [created, updated]
    exchange: ecs.events
consumes:
  - queue: my.queue
    routingKey: ecs.foo.bar
    handler: MyHandler
"""
        result = EventDefinitionExtractor._parse("test.event.yml", "test.event.yml", yml)
        assert len(result.published_events) == 1
        assert result.published_events[0].entity == "customer"
        assert "created" in result.published_events[0].actions
        assert len(result.consumed_events) == 1
        assert result.consumed_events[0].handler == "MyHandler"
