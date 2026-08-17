"""Nested JAR extractor — extracts nested JARs to a temp working directory."""
from __future__ import annotations

import io
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .detector import DetectionResult, JarType, JarTypeDetector
from .manifest import ManifestInfo, ManifestParser

MAX_DEPTH = 3  # Maximum recursion depth for nested JAR extraction


@dataclass
class NestedJarEntry:
    """Represents one extracted nested JAR and its analysis metadata."""
    filename: str                          # e.g. customers-installer-2.6.9.jar
    extracted_path: Path                   # path to the extracted JAR on disk
    extracted_dir: Path                    # path to the directory extracted from the JAR
    depth: int                             # nesting depth (1 = direct child of top-level)
    parent_jar: str | None                 # filename of the parent JAR (None for top-level)
    detection: DetectionResult
    manifest: ManifestInfo
    size_bytes: int
    # For installer JARs: the inner fat JAR path (content/lib/*.jar)
    fat_jar_path: Path | None = None
    fat_jar_detection: DetectionResult | None = None
    fat_jar_manifest: ManifestInfo | None = None
    # All entries found inside this JAR
    entry_names: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class NestedJarExtractor:
    """Extract nested JARs from a top-level JAR into a working directory.

    Usage::

        work_dir = Path(tempfile.mkdtemp())
        try:
            entries = NestedJarExtractor.extract(jar_path, work_dir)
            # process entries ...
        finally:
            shutil.rmtree(work_dir)
    """

    @staticmethod
    def extract(
        jar_path: str | Path,
        work_dir: str | Path,
        depth: int = 0,
        parent_jar: str | None = None,
    ) -> list[NestedJarEntry]:
        """Extract all nested JARs from jar_path into work_dir.

        Returns a flat list of NestedJarEntry — one per nested JAR found,
        recursing up to MAX_DEPTH levels deep.
        """
        jar_path = Path(jar_path)
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

        if depth >= MAX_DEPTH:
            return []

        entries: list[NestedJarEntry] = []

        try:
            with zipfile.ZipFile(jar_path, "r") as zf:
                all_names = zf.namelist()

                # Find root-level *.jar entries
                root_jars = [
                    n for n in all_names
                    if n.endswith(".jar") and "/" not in n.rstrip("/")
                ]

                for jar_name in root_jars:
                    entry = NestedJarExtractor._extract_one(
                        zf=zf,
                        jar_name=jar_name,
                        work_dir=work_dir,
                        depth=depth + 1,
                        parent_jar=jar_path.name,
                    )
                    if entry:
                        entries.append(entry)

                        # Recurse into JAR-of-JARs children
                        if (
                            entry.detection.jar_type == JarType.JAR_OF_JARS
                            and depth + 1 < MAX_DEPTH
                        ):
                            child_entries = NestedJarExtractor.extract(
                                jar_path=entry.extracted_path,
                                work_dir=entry.extracted_dir / "nested",
                                depth=depth + 1,
                                parent_jar=jar_name,
                            )
                            entries.extend(child_entries)

        except zipfile.BadZipFile as exc:
            # Return empty — caller handles corrupt JARs
            pass

        return entries

    @staticmethod
    def _extract_one(
        zf: zipfile.ZipFile,
        jar_name: str,
        work_dir: Path,
        depth: int,
        parent_jar: str | None,
    ) -> NestedJarEntry | None:
        try:
            jar_bytes = zf.read(jar_name)
            size_bytes = len(jar_bytes)

            # Write the nested JAR to disk
            jar_dest = work_dir / jar_name
            jar_dest.write_bytes(jar_bytes)

            # Extract the nested JAR's contents to a directory
            extract_dir = work_dir / jar_name.replace(".jar", "")
            extract_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(io.BytesIO(jar_bytes), "r") as nested_zf:
                nested_zf.extractall(extract_dir)
                entry_names = nested_zf.namelist()
                manifest = ManifestParser.from_zip(nested_zf)

            detection = JarTypeDetector.detect(jar_dest)

            # For installer JARs, locate the inner fat JAR at content/lib/*.jar
            fat_jar_path = None
            fat_jar_detection = None
            fat_jar_manifest = None

            fat_jar_candidates = list((extract_dir / "content" / "lib").glob("*.jar")) \
                if (extract_dir / "content" / "lib").exists() else []

            if fat_jar_candidates:
                fat_jar_path = fat_jar_candidates[0]
                try:
                    fat_jar_detection = JarTypeDetector.detect(fat_jar_path)
                    fat_jar_manifest = ManifestParser.from_jar(fat_jar_path)
                except Exception:
                    pass

            return NestedJarEntry(
                filename=jar_name,
                extracted_path=jar_dest,
                extracted_dir=extract_dir,
                depth=depth,
                parent_jar=parent_jar,
                detection=detection,
                manifest=manifest,
                size_bytes=size_bytes,
                fat_jar_path=fat_jar_path,
                fat_jar_detection=fat_jar_detection,
                fat_jar_manifest=fat_jar_manifest,
                entry_names=entry_names,
            )

        except Exception as exc:
            # Return None — caller skips and records a warning
            return None

    @staticmethod
    def cleanup(work_dir: str | Path) -> None:
        """Remove the working directory and all extracted content."""
        shutil.rmtree(work_dir, ignore_errors=True)
