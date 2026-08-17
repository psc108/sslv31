"""Installer metadata parser — parses part.yml, setup.properties, versions.yml."""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class PartYml:
    """Parsed content of a part.yml installer manifest."""
    name: str | None = None
    version: str | None = None
    install_path: str | None = None
    group: str | None = None
    templates: list[dict] = field(default_factory=list)
    chmod: list[dict] = field(default_factory=list)
    firewall_ports: list[int] = field(default_factory=list)
    build_info: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


@dataclass
class InstallerMetadata:
    """All installer-level metadata extracted from a JAR-of-JARs package."""
    # From setup.properties
    setup_properties: dict[str, str] = field(default_factory=dict)
    # From versions.yml
    service_versions: dict[str, str] = field(default_factory=dict)
    # From version.yml
    package_version: dict[str, str] = field(default_factory=dict)
    # From part.yml (for individual installer JARs)
    part_yml: PartYml | None = None


class InstallerMetadataParser:
    """Parse installer metadata files from a JAR or extracted directory.

    Handles:
    - ``part.yml``        — per-service installer manifest
    - ``setup.properties``— global installer configuration
    - ``versions.yml``    — service version manifest
    - ``version.yml``     — package-level version metadata
    """

    @staticmethod
    def from_jar(path: str | Path) -> InstallerMetadata:
        path = Path(path)
        with zipfile.ZipFile(path, "r") as zf:
            return InstallerMetadataParser.from_zip(zf)

    @staticmethod
    def from_zip(zf: zipfile.ZipFile) -> InstallerMetadata:
        names = set(zf.namelist())
        meta = InstallerMetadata()

        if "setup.properties" in names:
            raw = zf.read("setup.properties").decode("utf-8", errors="replace")
            meta.setup_properties = InstallerMetadataParser._parse_properties(raw)

        if "versions.yml" in names:
            raw = zf.read("versions.yml").decode("utf-8", errors="replace")
            meta.service_versions = InstallerMetadataParser._parse_yaml_flat(raw)

        if "version.yml" in names:
            raw = zf.read("version.yml").decode("utf-8", errors="replace")
            meta.package_version = InstallerMetadataParser._parse_yaml_flat(raw)

        if "part.yml" in names:
            raw = zf.read("part.yml").decode("utf-8", errors="replace")
            meta.part_yml = InstallerMetadataParser._parse_part_yml(raw)

        return meta

    @staticmethod
    def from_directory(directory: str | Path) -> InstallerMetadata:
        """Parse installer metadata from an already-extracted directory."""
        directory = Path(directory)
        meta = InstallerMetadata()

        setup = directory / "setup.properties"
        if setup.exists():
            meta.setup_properties = InstallerMetadataParser._parse_properties(
                setup.read_text(encoding="utf-8", errors="replace")
            )

        versions = directory / "versions.yml"
        if versions.exists():
            meta.service_versions = InstallerMetadataParser._parse_yaml_flat(
                versions.read_text(encoding="utf-8", errors="replace")
            )

        version = directory / "version.yml"
        if version.exists():
            meta.package_version = InstallerMetadataParser._parse_yaml_flat(
                version.read_text(encoding="utf-8", errors="replace")
            )

        part = directory / "part.yml"
        if part.exists():
            meta.part_yml = InstallerMetadataParser._parse_part_yml(
                part.read_text(encoding="utf-8", errors="replace")
            )

        return meta

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_properties(text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("!"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip()
        return result

    @staticmethod
    def _parse_yaml_flat(text: str) -> dict[str, str]:
        """Parse a simple flat YAML document into a string dict."""
        try:
            doc = yaml.safe_load(text)
            if isinstance(doc, dict):
                return {str(k): str(v) for k, v in doc.items() if v is not None}
        except Exception:
            pass
        return {}

    @staticmethod
    def _parse_part_yml(text: str) -> PartYml:
        try:
            doc = yaml.safe_load(text)
        except Exception:
            return PartYml()

        if not isinstance(doc, dict):
            return PartYml()

        # Extract firewall ports — may be a list of dicts or ints
        firewall_ports: list[int] = []
        for entry in doc.get("firewallPorts", []):
            if isinstance(entry, dict):
                port = entry.get("port")
                if port is not None:
                    try:
                        firewall_ports.append(int(port))
                    except (ValueError, TypeError):
                        pass
            elif isinstance(entry, int):
                firewall_ports.append(entry)

        return PartYml(
            name=doc.get("name"),
            version=doc.get("version"),
            install_path=doc.get("installPath"),
            group=doc.get("group"),
            templates=doc.get("templates", []),
            chmod=doc.get("chmod", []),
            firewall_ports=firewall_ports,
            build_info=doc.get("buildInfo", {}),
            raw=doc,
        )
