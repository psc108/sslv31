"""MANIFEST.MF parser — extracts all attributes from any JAR manifest."""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ManifestInfo:
    main_class: str | None = None
    start_class: str | None = None
    spring_boot_version: str | None = None
    spring_boot_classes: str | None = None
    spring_boot_lib: str | None = None
    implementation_title: str | None = None
    implementation_version: str | None = None
    implementation_vendor: str | None = None
    built_by: str | None = None
    build_jdk: str | None = None
    build_jdk_spec: str | None = None
    created_by: str | None = None
    multi_release: bool = False
    class_path: str | None = None
    all_attributes: dict[str, str] = field(default_factory=dict)


class ManifestParser:
    """Parse META-INF/MANIFEST.MF from a JAR file or raw bytes."""

    @staticmethod
    def from_jar(path: str | Path) -> ManifestInfo:
        with zipfile.ZipFile(Path(path), "r") as zf:
            return ManifestParser.from_zip(zf)

    @staticmethod
    def from_zip(zf: zipfile.ZipFile) -> ManifestInfo:
        try:
            raw = zf.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
        except KeyError:
            return ManifestInfo()
        return ManifestParser.from_text(raw)

    @staticmethod
    def from_bytes(data: bytes) -> ManifestInfo:
        return ManifestParser.from_text(data.decode("utf-8", errors="replace"))

    @staticmethod
    def from_text(text: str) -> ManifestInfo:
        attrs = ManifestParser._parse_attributes(text)
        return ManifestParser._build(attrs)

    @staticmethod
    def _parse_attributes(text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        current_key: str | None = None
        current_val: list[str] = []
        for line in text.splitlines():
            if not line:
                if current_key:
                    result[current_key] = "".join(current_val)
                    current_key = None
                    current_val = []
                break
            if line.startswith(" ") and current_key:
                current_val.append(line[1:])
            elif ":" in line:
                if current_key:
                    result[current_key] = "".join(current_val)
                key, _, val = line.partition(":")
                current_key = key.strip()
                current_val = [val.strip()]
        if current_key:
            result[current_key] = "".join(current_val)
        return result

    @staticmethod
    def _build(attrs: dict[str, str]) -> ManifestInfo:
        def get(key: str) -> str | None:
            return attrs.get(key) or None

        return ManifestInfo(
            main_class=get("Main-Class"),
            start_class=get("Start-Class"),
            spring_boot_version=get("Spring-Boot-Version"),
            spring_boot_classes=get("Spring-Boot-Classes"),
            spring_boot_lib=get("Spring-Boot-Lib"),
            implementation_title=get("Implementation-Title"),
            implementation_version=get("Implementation-Version"),
            implementation_vendor=get("Implementation-Vendor"),
            built_by=get("Built-By"),
            build_jdk=get("Build-Jdk"),
            build_jdk_spec=get("Build-Jdk-Spec"),
            created_by=get("Created-By"),
            multi_release=(attrs.get("Multi-Release", "").lower() == "true"),
            class_path=get("Class-Path"),
            all_attributes=dict(attrs),
        )
