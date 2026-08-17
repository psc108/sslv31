"""Dependency extractor — inventories BOOT-INF/lib/*.jar dependencies."""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

# Category rules: list of (tokens_to_match, category_name)
# Each token is matched against the combined search string:
#   "<group_id> <artifact_id> <filename>" (all lowercased)
# Tokens may be group ID prefixes OR filename fragments.
_CATEGORY_RULES: list[tuple[tuple[str, ...], str]] = [
    (("org.springframework.boot", "spring-boot-"),           "spring_boot"),
    (("org.springframework.cloud", "spring-cloud-"),         "spring_cloud"),
    (("org.springframework.security", "spring-security-"),   "spring_security"),
    (("org.springframework",),                               "spring_framework"),
    (("com.mysql", "mysql-connector", "org.postgresql",
      "postgresql-", "com.oracle", "ojdbc"),                 "database"),
    (("org.flywaydb", "flyway-"),                            "database"),
    (("com.zaxxer", "hikaricp"),                             "database"),
    (("com.rabbitmq", "amqp-client", "org.apache.kafka",
      "kafka-"),                                             "messaging"),
    (("org.bouncycastle", "bcprov-", "bcpkix-"),             "cryptography"),
    (("com.github.ulisesbocchio", "jasypt-"),                "cryptography"),
    (("com.fasterxml.jackson", "jackson-", "com.google.gson",
      "gson-"),                                              "serialisation"),
    (("org.apache.httpcomponents", "httpclient-",
      "com.squareup.okhttp3", "okhttp-"),                    "http_client"),
    (("io.micrometer", "micrometer-", "io.prometheus",
      "prometheus-"),                                        "observability"),
    (("org.junit", "junit-", "org.mockito", "mockito-",
      "org.assertj", "assertj-"),                            "testing"),
    (("ch.qos.logback", "logback-", "org.apache.logging",
      "log4j-", "org.slf4j", "slf4j-"),                     "logging"),
    (("software.amazon.awssdk", "aws-java-sdk",
      "com.amazonaws"),                                      "cloud_sdk"),
    (("com.azure", "azure-"),                                "cloud_sdk"),
    (("com.google.cloud", "google-cloud-"),                  "cloud_sdk"),
]

# Regex to parse Maven-style filenames: artifactId-version.jar
_FILENAME_RE = re.compile(
    r"^(?P<artifact>.+?)-(?P<version>\d[\w.\-]*)\.jar$"
)


@dataclass
class DependencyInfo:
    filename: str
    group_id: str | None
    artifact_id: str | None
    version: str | None
    category: str
    size_bytes: int
    maven_coordinates: str | None
    source_path: str
    manifest_title: str | None
    manifest_vendor: str | None
    coordinates_source: str           # "pom.properties" | "manifest" | "filename_parse"


class DependencyExtractor:
    """Extract and categorise dependencies from a Spring Boot fat JAR.

    Scans BOOT-INF/lib/ (or WEB-INF/lib/ for WARs) and returns one
    DependencyInfo per dependency JAR found.
    """

    @staticmethod
    def from_jar(path: str | Path) -> list[DependencyInfo]:
        with zipfile.ZipFile(Path(path), "r") as zf:
            return DependencyExtractor.from_zip(zf)

    @staticmethod
    def from_zip(zf: zipfile.ZipFile) -> list[DependencyInfo]:
        names = zf.namelist()

        if any(n.startswith("BOOT-INF/lib/") for n in names):
            lib_prefix = "BOOT-INF/lib/"
        elif any(n.startswith("WEB-INF/lib/") for n in names):
            lib_prefix = "WEB-INF/lib/"
        else:
            return []

        dep_entries = [
            n for n in names
            if n.startswith(lib_prefix) and n.endswith(".jar") and n != lib_prefix
        ]

        results: list[DependencyInfo] = []
        for entry_path in dep_entries:
            info = DependencyExtractor._analyse_entry(zf, entry_path, lib_prefix)
            if info:
                results.append(info)

        return sorted(results, key=lambda d: (d.group_id or "", d.artifact_id or ""))

    @staticmethod
    def _analyse_entry(
        zf: zipfile.ZipFile,
        entry_path: str,
        lib_prefix: str,
    ) -> DependencyInfo | None:
        filename = entry_path[len(lib_prefix):]
        if not filename or "/" in filename:
            return None

        try:
            dep_bytes = zf.read(entry_path)
        except Exception:
            return None

        size_bytes = len(dep_bytes)
        group_id: str | None = None
        artifact_id: str | None = None
        version: str | None = None
        manifest_title: str | None = None
        manifest_vendor: str | None = None
        coordinates_source = "filename_parse"

        try:
            with zipfile.ZipFile(io.BytesIO(dep_bytes), "r") as dep_zf:
                dep_names = dep_zf.namelist()

                # 1. Try pom.properties (most reliable)
                pom_entries = [
                    n for n in dep_names
                    if n.startswith("META-INF/maven/") and n.endswith("pom.properties")
                ]
                if pom_entries:
                    pom_text = dep_zf.read(pom_entries[0]).decode("utf-8", errors="replace")
                    pom = DependencyExtractor._parse_properties(pom_text)
                    group_id = pom.get("groupId")
                    artifact_id = pom.get("artifactId")
                    version = pom.get("version")
                    coordinates_source = "pom.properties"

                # 2. Try MANIFEST.MF for title/vendor
                try:
                    mf_text = dep_zf.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
                    mf = DependencyExtractor._parse_manifest_simple(mf_text)
                    manifest_title = mf.get("Implementation-Title") or mf.get("Bundle-Name")
                    manifest_vendor = mf.get("Implementation-Vendor") or mf.get("Bundle-Vendor")
                    if not group_id:
                        bsn = mf.get("Bundle-SymbolicName")
                        if bsn:
                            group_id = bsn.split(";")[0].strip()
                            coordinates_source = "manifest"
                except KeyError:
                    pass

        except zipfile.BadZipFile:
            pass

        # 3. Parse filename as last resort for artifact_id / version
        if not artifact_id:
            m = _FILENAME_RE.match(filename)
            if m:
                artifact_id = m.group("artifact")
                version = version or m.group("version")

        maven_coordinates = None
        if group_id and artifact_id and version:
            maven_coordinates = f"{group_id}:{artifact_id}:{version}"

        category = DependencyExtractor._categorise(group_id, artifact_id, filename)

        return DependencyInfo(
            filename=filename,
            group_id=group_id,
            artifact_id=artifact_id,
            version=version,
            category=category,
            size_bytes=size_bytes,
            maven_coordinates=maven_coordinates,
            source_path=entry_path,
            manifest_title=manifest_title,
            manifest_vendor=manifest_vendor,
            coordinates_source=coordinates_source,
        )

    @staticmethod
    def _categorise(group_id: str | None, artifact_id: str | None, filename: str) -> str:
        # Build a single search string from all available identifiers
        search = " ".join(
            p.lower() for p in [group_id or "", artifact_id or "", filename] if p
        )
        for tokens, category in _CATEGORY_RULES:
            for token in tokens:
                if token.lower() in search:
                    return category
        return "other"

    @staticmethod
    def _parse_properties(text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip()
        return result

    @staticmethod
    def _parse_manifest_simple(text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        current_key: str | None = None
        current_val: list[str] = []
        for line in text.splitlines():
            if not line:
                break
            if line.startswith(" ") and current_key:
                current_val.append(line[1:])
            elif ":" in line:
                if current_key:
                    result[current_key] = "".join(current_val)
                k, _, v = line.partition(":")
                current_key = k.strip()
                current_val = [v.strip()]
        if current_key:
            result[current_key] = "".join(current_val)
        return result
