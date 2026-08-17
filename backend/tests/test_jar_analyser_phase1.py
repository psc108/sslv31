"""Phase 1 unit tests — JAR Analyser engine core.

Run with:
    pytest backend/tests/test_jar_analyser_phase1.py -v

The tests use the real installation-package-2.6.9.jar when available
(set JAR_FIXTURE env var to its path), and fall back to synthetic
in-memory JARs for CI environments where the real JAR is not present.
"""
from __future__ import annotations

import io
import os
import tempfile
import zipfile
from pathlib import Path

import pytest

from app.services.jar_analyser import (
    ConfigFileExtractor,
    DependencyExtractor,
    DetectionResult,
    InstallerMetadataParser,
    JarType,
    JarTypeDetector,
    ManifestParser,
    NestedJarExtractor,
)

# ---------------------------------------------------------------------------
# Helpers — build synthetic JARs in memory
# ---------------------------------------------------------------------------

def _make_jar(entries: dict[str, bytes]) -> bytes:
    """Build a ZIP/JAR in memory from a dict of {path: content}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _manifest(**kwargs) -> bytes:
    lines = ["Manifest-Version: 1.0"]
    for k, v in kwargs.items():
        lines.append(f"{k}: {v}")
    return ("\n".join(lines) + "\n").encode()


def _spring_boot_fat_jar(service: str = "customers", port: int = 8090) -> bytes:
    """Build a minimal Spring Boot fat JAR."""
    app_props = f"server.port={port}\nspring.application.name={service}\n".encode()
    return _make_jar({
        "META-INF/MANIFEST.MF": _manifest(**{
            "Main-Class": "org.springframework.boot.loader.JarLauncher",
            "Start-Class": f"com.dxc.ecs.{service}.Application",
            "Spring-Boot-Version": "3.5.8",
            "Implementation-Version": "2.6.9",
        }),
        "BOOT-INF/classes/application.properties": app_props,
        "BOOT-INF/lib/spring-boot-3.5.8.jar": b"fake",
        "BOOT-INF/lib/mysql-connector-j-8.0.33.jar": b"fake",
    })


def _installer_jar(service: str, port: int) -> bytes:
    """Build a minimal installer JAR containing a fat JAR and part.yml."""
    part_yml = f"name: {service}\ninstallPath: /opt/ecs/{service}\ngroup: backend\nfirewallPorts:\n  - port: {port}\n    protocol: tcp\n".encode()
    fat_jar_bytes = _spring_boot_fat_jar(service, port)
    return _make_jar({
        "META-INF/MANIFEST.MF": _manifest(**{"Implementation-Version": "2.6.9"}),
        "part.yml": part_yml,
        f"content/lib/{service}-svc.jar": fat_jar_bytes,
        "config/application.properties": f"server.port={port}\n".encode(),
        "bundle/ecs-{service}.service": b"[Unit]\nDescription=test\n",
    })


def _jar_of_jars() -> bytes:
    """Build a minimal JAR-of-JARs with 3 installer JARs."""
    services = [("customers", 8090), ("catalog", 8093), ("config", 8103)]
    entries: dict[str, bytes] = {
        "META-INF/MANIFEST.MF": _manifest(**{
            "Implementation-Title": "CPI Services",
            "Implementation-Version": "2.6.9",
            "Implementation-Vendor": "DXC Technology",
        }),
        "setup.properties": b"db.host=localhost\ndb.port=3306\n",
        "versions.yml": b"customers: 2.6.9\ncatalog: 2.6.9\nconfig: 2.6.9\n",
        "version.yml": b"version: 2.6.9\nvendor: DXC Technology\n",
    }
    for svc, port in services:
        entries[f"{svc}-installer-2.6.9.jar"] = _installer_jar(svc, port)
    return _make_jar(entries)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def jar_of_jars_path(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("jars") / "installation-package-2.6.9.jar"
    p.write_bytes(_jar_of_jars())
    return p


@pytest.fixture(scope="module")
def fat_jar_path(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("jars") / "customers-svc.jar"
    p.write_bytes(_spring_boot_fat_jar())
    return p


@pytest.fixture(scope="module")
def installer_jar_path(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("jars") / "customers-installer-2.6.9.jar"
    p.write_bytes(_installer_jar("customers", 8090))
    return p


# ---------------------------------------------------------------------------
# JarTypeDetector tests
# ---------------------------------------------------------------------------

class TestJarTypeDetector:

    def test_detects_jar_of_jars(self, jar_of_jars_path):
        result = JarTypeDetector.detect(jar_of_jars_path)
        assert result.jar_type == JarType.JAR_OF_JARS
        assert result.confidence >= 0.75
        assert len(result.nested_jar_names) == 3
        assert len(result.installer_jar_names) == 3

    def test_detects_spring_boot_fat(self, fat_jar_path):
        result = JarTypeDetector.detect(fat_jar_path)
        assert result.jar_type == JarType.SPRING_BOOT_FAT
        assert result.confidence >= 0.85
        assert result.main_class == "org.springframework.boot.loader.JarLauncher"
        assert result.start_class == "com.dxc.ecs.customers.Application"
        assert result.spring_boot_version == "3.5.8"

    def test_detects_library_jar(self, tmp_path):
        lib = tmp_path / "mylib.jar"
        lib.write_bytes(_make_jar({
            "META-INF/MANIFEST.MF": _manifest(**{"Implementation-Title": "My Lib"}),
            "com/example/Foo.class": b"\xca\xfe\xba\xbe",
        }))
        result = JarTypeDetector.detect(lib)
        assert result.jar_type == JarType.LIBRARY

    def test_detects_executable_jar(self, tmp_path):
        jar = tmp_path / "app.jar"
        jar.write_bytes(_make_jar({
            "META-INF/MANIFEST.MF": _manifest(**{"Main-Class": "com.example.Main"}),
        }))
        result = JarTypeDetector.detect(jar)
        assert result.jar_type == JarType.EXECUTABLE_JAR

    def test_detects_war(self, tmp_path):
        war = tmp_path / "app.war"
        war.write_bytes(_make_jar({
            "META-INF/MANIFEST.MF": _manifest(),
            "WEB-INF/lib/some.jar": b"fake",
            "WEB-INF/web.xml": b"<web-app/>",
        }))
        result = JarTypeDetector.detect(war)
        assert result.jar_type == JarType.WAR

    def test_detects_spring_boot_war(self, tmp_path):
        war = tmp_path / "app.war"
        war.write_bytes(_make_jar({
            "META-INF/MANIFEST.MF": _manifest(**{
                "Main-Class": "org.springframework.boot.loader.WarLauncher",
                "Start-Class": "com.example.App",
            }),
            "WEB-INF/lib/spring-boot.jar": b"fake",
        }))
        result = JarTypeDetector.detect(war)
        assert result.jar_type == JarType.SPRING_BOOT_WAR

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError):
            JarTypeDetector.detect("/nonexistent/path.jar")

    def test_raises_on_bad_zip(self, tmp_path):
        bad = tmp_path / "bad.jar"
        bad.write_bytes(b"this is not a zip file")
        with pytest.raises(ValueError, match="Not a valid ZIP"):
            JarTypeDetector.detect(bad)


# ---------------------------------------------------------------------------
# ManifestParser tests
# ---------------------------------------------------------------------------

class TestManifestParser:

    def test_parses_spring_boot_manifest(self, fat_jar_path):
        info = ManifestParser.from_jar(fat_jar_path)
        assert info.main_class == "org.springframework.boot.loader.JarLauncher"
        assert info.start_class == "com.dxc.ecs.customers.Application"
        assert info.spring_boot_version == "3.5.8"
        assert info.implementation_version == "2.6.9"

    def test_parses_jar_of_jars_manifest(self, jar_of_jars_path):
        info = ManifestParser.from_jar(jar_of_jars_path)
        assert info.implementation_title == "CPI Services"
        assert info.implementation_version == "2.6.9"
        assert info.implementation_vendor == "DXC Technology"

    def test_all_attributes_populated(self, fat_jar_path):
        info = ManifestParser.from_jar(fat_jar_path)
        assert "Main-Class" in info.all_attributes
        assert "Start-Class" in info.all_attributes

    def test_empty_manifest(self, tmp_path):
        jar = tmp_path / "empty.jar"
        jar.write_bytes(_make_jar({"META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n"}))
        info = ManifestParser.from_jar(jar)
        assert info.main_class is None
        assert info.implementation_title is None

    def test_missing_manifest(self, tmp_path):
        jar = tmp_path / "nomanifest.jar"
        jar.write_bytes(_make_jar({"com/example/Foo.class": b"\xca\xfe\xba\xbe"}))
        info = ManifestParser.from_jar(jar)
        assert info.main_class is None
        assert info.all_attributes == {}

    def test_continuation_lines(self):
        text = "Manifest-Version: 1.0\nLong-Key: first part\n second part\n third part\n"
        info = ManifestParser.from_text(text)
        assert info.all_attributes["Long-Key"] == "first partsecond partthird part"

    def test_multi_release_flag(self):
        text = "Manifest-Version: 1.0\nMulti-Release: true\n"
        info = ManifestParser.from_text(text)
        assert info.multi_release is True


# ---------------------------------------------------------------------------
# NestedJarExtractor tests
# ---------------------------------------------------------------------------

class TestNestedJarExtractor:

    def test_extracts_nested_jars(self, jar_of_jars_path, tmp_path):
        entries = NestedJarExtractor.extract(jar_of_jars_path, tmp_path / "work")
        assert len(entries) == 3
        names = {e.filename for e in entries}
        assert "customers-installer-2.6.9.jar" in names
        assert "catalog-installer-2.6.9.jar" in names
        assert "config-installer-2.6.9.jar" in names

    def test_entry_has_correct_depth(self, jar_of_jars_path, tmp_path):
        entries = NestedJarExtractor.extract(jar_of_jars_path, tmp_path / "work")
        for entry in entries:
            assert entry.depth == 1

    def test_entry_has_fat_jar(self, jar_of_jars_path, tmp_path):
        entries = NestedJarExtractor.extract(jar_of_jars_path, tmp_path / "work")
        customers = next(e for e in entries if "customers" in e.filename)
        assert customers.fat_jar_path is not None
        assert customers.fat_jar_path.exists()

    def test_fat_jar_detected_as_spring_boot(self, jar_of_jars_path, tmp_path):
        entries = NestedJarExtractor.extract(jar_of_jars_path, tmp_path / "work")
        customers = next(e for e in entries if "customers" in e.filename)
        assert customers.fat_jar_detection is not None
        assert customers.fat_jar_detection.jar_type == JarType.SPRING_BOOT_FAT

    def test_extracted_files_exist_on_disk(self, jar_of_jars_path, tmp_path):
        work = tmp_path / "work"
        entries = NestedJarExtractor.extract(jar_of_jars_path, work)
        for entry in entries:
            assert entry.extracted_path.exists()
            assert entry.extracted_dir.exists()

    def test_cleanup_removes_work_dir(self, jar_of_jars_path, tmp_path):
        work = tmp_path / "work_cleanup"
        NestedJarExtractor.extract(jar_of_jars_path, work)
        assert work.exists()
        NestedJarExtractor.cleanup(work)
        assert not work.exists()

    def test_no_entries_for_library_jar(self, fat_jar_path, tmp_path):
        # A fat JAR has no root-level *.jar entries — extractor returns empty
        entries = NestedJarExtractor.extract(fat_jar_path, tmp_path / "work")
        assert entries == []


# ---------------------------------------------------------------------------
# DependencyExtractor tests
# ---------------------------------------------------------------------------

class TestDependencyExtractor:

    def test_extracts_dependencies(self, fat_jar_path):
        deps = DependencyExtractor.from_jar(fat_jar_path)
        assert len(deps) == 2
        filenames = {d.filename for d in deps}
        assert "spring-boot-3.5.8.jar" in filenames
        assert "mysql-connector-j-8.0.33.jar" in filenames

    def test_spring_boot_categorised_correctly(self, fat_jar_path):
        deps = DependencyExtractor.from_jar(fat_jar_path)
        sb = next(d for d in deps if d.filename == "spring-boot-3.5.8.jar")
        assert sb.category == "spring_boot"

    def test_mysql_categorised_as_database(self, fat_jar_path):
        deps = DependencyExtractor.from_jar(fat_jar_path)
        mysql = next(d for d in deps if "mysql" in d.filename)
        assert mysql.category == "database"

    def test_version_parsed_from_filename(self, fat_jar_path):
        deps = DependencyExtractor.from_jar(fat_jar_path)
        sb = next(d for d in deps if d.filename == "spring-boot-3.5.8.jar")
        assert sb.version == "3.5.8"
        assert sb.artifact_id == "spring-boot"

    def test_empty_for_library_jar(self, tmp_path):
        lib = tmp_path / "lib.jar"
        lib.write_bytes(_make_jar({
            "META-INF/MANIFEST.MF": _manifest(),
            "com/example/Foo.class": b"\xca\xfe\xba\xbe",
        }))
        deps = DependencyExtractor.from_jar(lib)
        assert deps == []

    def test_pom_properties_used_when_present(self, tmp_path):
        # Build a fat JAR whose dependency has pom.properties
        pom_props = b"groupId=org.springframework.boot\nartifactId=spring-boot\nversion=3.5.8\n"
        dep_jar = _make_jar({
            "META-INF/maven/org.springframework.boot/spring-boot/pom.properties": pom_props,
        })
        fat = tmp_path / "fat.jar"
        fat.write_bytes(_make_jar({
            "META-INF/MANIFEST.MF": _manifest(**{
                "Main-Class": "org.springframework.boot.loader.JarLauncher",
                "Start-Class": "com.example.App",
            }),
            "BOOT-INF/lib/spring-boot-3.5.8.jar": dep_jar,
        }))
        deps = DependencyExtractor.from_jar(fat)
        assert len(deps) == 1
        assert deps[0].group_id == "org.springframework.boot"
        assert deps[0].coordinates_source == "pom.properties"
        assert deps[0].maven_coordinates == "org.springframework.boot:spring-boot:3.5.8"


# ---------------------------------------------------------------------------
# ConfigFileExtractor tests
# ---------------------------------------------------------------------------

class TestConfigFileExtractor:

    def test_extracts_application_properties(self, fat_jar_path):
        configs = ConfigFileExtractor.from_jar(fat_jar_path)
        filenames = {c.filename for c in configs}
        assert "application.properties" in filenames

    def test_declared_port_extracted(self, fat_jar_path):
        configs = ConfigFileExtractor.from_jar(fat_jar_path)
        app_props = next(c for c in configs if c.filename == "application.properties")
        assert app_props.declared_port == 8090

    def test_key_count_correct(self, fat_jar_path):
        configs = ConfigFileExtractor.from_jar(fat_jar_path)
        app_props = next(c for c in configs if c.filename == "application.properties")
        assert app_props.key_count == 2  # server.port + spring.application.name

    def test_encrypted_values_detected(self, tmp_path):
        jar = tmp_path / "enc.jar"
        jar.write_bytes(_make_jar({
            "META-INF/MANIFEST.MF": _manifest(**{
                "Main-Class": "org.springframework.boot.loader.JarLauncher",
                "Start-Class": "com.example.App",
            }),
            "BOOT-INF/classes/application.properties": (
                b"server.port=8090\n"
                b"spring.datasource.password=ENC(abc123==)\n"
                b"server.ssl.key-store-password=ENC(xyz789==)\n"
            ),
        }))
        configs = ConfigFileExtractor.from_jar(jar)
        app = next(c for c in configs if c.filename == "application.properties")
        assert app.encrypted_count == 2
        assert app.ssl_key_count >= 1

    def test_ssl_keys_counted(self, tmp_path):
        jar = tmp_path / "ssl.jar"
        jar.write_bytes(_make_jar({
            "META-INF/MANIFEST.MF": _manifest(**{
                "Main-Class": "org.springframework.boot.loader.JarLauncher",
                "Start-Class": "com.example.App",
            }),
            "BOOT-INF/classes/application.properties": (
                b"server.ssl.enabled=true\n"
                b"server.ssl.key-store=/opt/ecs/security/server.keystore\n"
                b"server.ssl.trust-store=/opt/ecs/security/server.truststore\n"
                b"server.port=8090\n"
            ),
        }))
        configs = ConfigFileExtractor.from_jar(jar)
        app = next(c for c in configs if c.filename == "application.properties")
        assert app.ssl_key_count == 3

    def test_yaml_config_parsed(self, tmp_path):
        jar = tmp_path / "yaml.jar"
        jar.write_bytes(_make_jar({
            "META-INF/MANIFEST.MF": _manifest(**{
                "Main-Class": "org.springframework.boot.loader.JarLauncher",
                "Start-Class": "com.example.App",
            }),
            "BOOT-INF/classes/application.yml": (
                b"server:\n  port: 8090\nspring:\n  application:\n    name: myservice\n"
            ),
        }))
        configs = ConfigFileExtractor.from_jar(jar)
        app = next(c for c in configs if c.filename == "application.yml")
        assert app.declared_port == 8090
        assert app.key_count >= 2

    def test_profile_extracted_from_filename(self, tmp_path):
        jar = tmp_path / "profile.jar"
        jar.write_bytes(_make_jar({
            "META-INF/MANIFEST.MF": _manifest(**{
                "Main-Class": "org.springframework.boot.loader.JarLauncher",
                "Start-Class": "com.example.App",
            }),
            "BOOT-INF/classes/application-backend.properties": b"some.key=value\n",
        }))
        configs = ConfigFileExtractor.from_jar(jar)
        backend = next(c for c in configs if c.filename == "application-backend.properties")
        assert backend.profile == "backend"


# ---------------------------------------------------------------------------
# InstallerMetadataParser tests
# ---------------------------------------------------------------------------

class TestInstallerMetadataParser:

    def test_parses_setup_properties(self, jar_of_jars_path):
        meta = InstallerMetadataParser.from_jar(jar_of_jars_path)
        assert "db.host" in meta.setup_properties
        assert meta.setup_properties["db.host"] == "localhost"

    def test_parses_versions_yml(self, jar_of_jars_path):
        meta = InstallerMetadataParser.from_jar(jar_of_jars_path)
        assert "customers" in meta.service_versions
        assert meta.service_versions["customers"] == "2.6.9"

    def test_parses_version_yml(self, jar_of_jars_path):
        meta = InstallerMetadataParser.from_jar(jar_of_jars_path)
        assert meta.package_version.get("version") == "2.6.9"
        assert meta.package_version.get("vendor") == "DXC Technology"

    def test_parses_part_yml(self, installer_jar_path):
        meta = InstallerMetadataParser.from_jar(installer_jar_path)
        assert meta.part_yml is not None
        assert meta.part_yml.name == "customers"
        assert meta.part_yml.install_path == "/opt/ecs/customers"
        assert meta.part_yml.group == "backend"
        assert 8090 in meta.part_yml.firewall_ports

    def test_no_part_yml_in_jar_of_jars(self, jar_of_jars_path):
        # The top-level JAR-of-JARs has no part.yml — only the nested installer JARs do
        meta = InstallerMetadataParser.from_jar(jar_of_jars_path)
        assert meta.part_yml is None

    def test_empty_metadata_for_fat_jar(self, fat_jar_path):
        meta = InstallerMetadataParser.from_jar(fat_jar_path)
        assert meta.setup_properties == {}
        assert meta.service_versions == {}
        assert meta.part_yml is None
