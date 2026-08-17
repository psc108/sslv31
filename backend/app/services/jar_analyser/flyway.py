"""Flyway migration script extractor.

Extracts Flyway migration scripts from BOOT-INF/classes/db/migration/
inside a Spring Boot fat JAR.  Parses version, description, DDL operations,
and affected table names from each script.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


# Matches V1__desc.sql, V2.4.0_6__desc.sql, R__desc.sql etc.
_MIGRATION_PREFIX = re.compile(r"^([VR])([\d._]+)?(?:__(.+))?\.sql$", re.IGNORECASE)
_DDL_KEYWORDS = ["CREATE TABLE", "ALTER TABLE", "DROP TABLE", "CREATE INDEX",
                 "DROP INDEX", "ADD COLUMN", "DROP COLUMN", "RENAME TABLE"]
_TABLE_RE = re.compile(
    r"(?:CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE|RENAME\s+TABLE)\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?[`\"]?(\w+)[`\"]?",
    re.IGNORECASE,
)


@dataclass
class MigrationScript:
    filename: str
    version: str | None
    description: str | None
    script_type: str          # versioned | repeatable
    size_bytes: int
    content: str
    statement_count: int
    ddl_operations: list[str] = field(default_factory=list)
    tables_affected: list[str] = field(default_factory=list)


class FlywayExtractor:
    """Extract Flyway migration scripts from a Spring Boot fat JAR."""

    _MIGRATION_PATHS = (
        "BOOT-INF/classes/db/migration/",
        "content/lib/BOOT-INF/classes/db/migration/",
        "db/migration/",
        "WEB-INF/classes/db/migration/",
    )

    @classmethod
    def from_jar(cls, jar_path: Path) -> list[MigrationScript]:
        scripts: list[MigrationScript] = []
        try:
            with zipfile.ZipFile(jar_path, "r") as zf:
                for entry in zf.namelist():
                    if not entry.lower().endswith(".sql"):
                        continue
                    if not any(entry.startswith(p) for p in cls._MIGRATION_PATHS):
                        continue
                    filename = entry.rsplit("/", 1)[-1]
                    content = zf.read(entry).decode("utf-8", errors="replace")
                    scripts.append(cls._parse(filename, content))
        except zipfile.BadZipFile:
            pass
        return sorted(scripts, key=lambda s: (s.script_type, s.version or ""))

    @classmethod
    def from_directory(cls, directory: Path) -> list[MigrationScript]:
        scripts: list[MigrationScript] = []
        for sql_file in directory.rglob("*.sql"):
            rel = sql_file.relative_to(directory).as_posix()
            if not any(rel.startswith(p.rstrip("/")) for p in cls._MIGRATION_PATHS):
                # Also accept files directly under db/migration
                if "db/migration" not in rel:
                    continue
            content = sql_file.read_text(encoding="utf-8", errors="replace")
            scripts.append(cls._parse(sql_file.name, content))
        return sorted(scripts, key=lambda s: (s.script_type, s.version or ""))

    @classmethod
    def _parse(cls, filename: str, content: str) -> MigrationScript:
        m = _MIGRATION_PREFIX.match(filename)
        if m:
            prefix, version, desc = m.group(1).upper(), m.group(2), m.group(3)
            script_type = "versioned" if prefix == "V" else "repeatable"
            description = desc.replace("_", " ") if desc else None
        else:
            version, description, script_type = None, None, "versioned"

        statements = [s.strip() for s in content.split(";") if s.strip()]
        ddl_ops = sorted({
            kw for kw in _DDL_KEYWORDS
            if re.search(kw.replace(" ", r"\s+"), content, re.IGNORECASE)
        })
        tables = list(dict.fromkeys(
            m.group(1).lower() for m in _TABLE_RE.finditer(content)
        ))

        return MigrationScript(
            filename=filename,
            version=version,
            description=description,
            script_type=script_type,
            size_bytes=len(content.encode("utf-8")),
            content=content,
            statement_count=len(statements),
            ddl_operations=ddl_ops,
            tables_affected=tables,
        )
