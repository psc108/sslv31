"""Flyway schema reconstructor.

Processes Flyway migration scripts in version order to reconstruct the
current logical database schema: tables, columns, data types, primary keys,
foreign keys, and indexes.

No external dependencies — pure regex-based SQL parsing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ColumnDef:
    name: str
    data_type: str
    nullable: bool = True
    primary_key: bool = False
    default_value: str | None = None
    comment: str | None = None


@dataclass
class IndexDef:
    name: str
    columns: list[str]
    unique: bool = False


@dataclass
class ForeignKeyDef:
    name: str | None
    columns: list[str]
    ref_table: str
    ref_columns: list[str]


@dataclass
class TableDef:
    name: str
    columns: list[ColumnDef] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    indexes: list[IndexDef] = field(default_factory=list)
    foreign_keys: list[ForeignKeyDef] = field(default_factory=list)

    def column(self, name: str) -> ColumnDef | None:
        nl = name.lower()
        return next((c for c in self.columns if c.name.lower() == nl), None)


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_STRIP_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_IDENTIFIER = r"[`\"\[]?(\w+)[`\"\]]?"

_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?" + _IDENTIFIER + r"\s*\((.+)\)",
    re.IGNORECASE | re.DOTALL,
)
_ALTER_ADD_COLUMN = re.compile(
    r"ALTER\s+TABLE\s+" + _IDENTIFIER + r"\s+ADD\s+(?:COLUMN\s+)?" + _IDENTIFIER + r"\s+([^,;]+)",
    re.IGNORECASE,
)
_ALTER_DROP_COLUMN = re.compile(
    r"ALTER\s+TABLE\s+" + _IDENTIFIER + r"\s+DROP\s+(?:COLUMN\s+)?" + _IDENTIFIER,
    re.IGNORECASE,
)
_ALTER_MODIFY_COLUMN = re.compile(
    r"ALTER\s+TABLE\s+" + _IDENTIFIER + r"\s+(?:MODIFY|ALTER\s+COLUMN)\s+(?:COLUMN\s+)?" + _IDENTIFIER + r"\s+([^,;]+)",
    re.IGNORECASE,
)
_ALTER_RENAME_TABLE = re.compile(
    r"(?:ALTER\s+TABLE\s+" + _IDENTIFIER + r"\s+RENAME\s+TO\s+" + _IDENTIFIER +
    r"|RENAME\s+TABLE\s+" + _IDENTIFIER + r"\s+TO\s+" + _IDENTIFIER + r")",
    re.IGNORECASE,
)
_DROP_TABLE = re.compile(
    r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?" + _IDENTIFIER,
    re.IGNORECASE,
)
_CREATE_INDEX = re.compile(
    r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?" + _IDENTIFIER +
    r"\s+ON\s+" + _IDENTIFIER + r"\s*\(([^)]+)\)",
    re.IGNORECASE,
)
_DROP_INDEX = re.compile(
    r"DROP\s+INDEX\s+(?:IF\s+EXISTS\s+)?" + _IDENTIFIER + r"(?:\s+ON\s+" + _IDENTIFIER + r")?",
    re.IGNORECASE,
)
_ADD_CONSTRAINT_FK = re.compile(
    r"ALTER\s+TABLE\s+" + _IDENTIFIER +
    r"\s+ADD\s+(?:CONSTRAINT\s+" + _IDENTIFIER + r"\s+)?FOREIGN\s+KEY\s*\(([^)]+)\)\s+REFERENCES\s+" +
    _IDENTIFIER + r"\s*\(([^)]+)\)",
    re.IGNORECASE,
)
_ADD_PK = re.compile(
    r"ALTER\s+TABLE\s+" + _IDENTIFIER +
    r"\s+ADD\s+(?:CONSTRAINT\s+\w+\s+)?PRIMARY\s+KEY\s*\(([^)]+)\)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Column definition parser
# ---------------------------------------------------------------------------

def _parse_column_def(col_text: str) -> ColumnDef | None:
    """Parse a single column definition line from a CREATE TABLE body."""
    col_text = col_text.strip()
    if not col_text:
        return None
    # Skip constraint lines
    upper = col_text.upper()
    if any(upper.startswith(kw) for kw in (
        "PRIMARY KEY", "UNIQUE", "INDEX", "KEY ", "CONSTRAINT",
        "FOREIGN KEY", "CHECK", "FULLTEXT",
    )):
        return None

    # name  type  [modifiers...]
    m = re.match(r"[`\"\[]?(\w+)[`\"\]]?\s+(\S+)(.*)", col_text, re.IGNORECASE | re.DOTALL)
    if not m:
        return None

    name = m.group(1)
    data_type = m.group(2).upper()
    rest = m.group(3)

    # Absorb type parameters e.g. VARCHAR(255), DECIMAL(10,2)
    if rest.lstrip().startswith("("):
        paren_m = re.match(r"\s*\([^)]*\)(.*)", rest, re.DOTALL)
        if paren_m:
            data_type += re.match(r"\s*(\([^)]*\))", rest).group(1)  # type: ignore[union-attr]
            rest = paren_m.group(1)

    rest_upper = rest.upper()
    nullable = "NOT NULL" not in rest_upper
    primary_key = "PRIMARY KEY" in rest_upper

    default_value: str | None = None
    dv_m = re.search(r"DEFAULT\s+(\S+)", rest, re.IGNORECASE)
    if dv_m:
        default_value = dv_m.group(1).strip("'\"")

    return ColumnDef(
        name=name,
        data_type=data_type,
        nullable=nullable,
        primary_key=primary_key,
        default_value=default_value,
    )


def _parse_create_table_body(body: str) -> tuple[list[ColumnDef], list[str]]:
    """Return (columns, primary_key_columns) from a CREATE TABLE body."""
    columns: list[ColumnDef] = []
    pk_cols: list[str] = []

    # Split on commas that are not inside parentheses
    depth = 0
    current: list[str] = []
    parts: list[str] = []
    for ch in body:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())

    for part in parts:
        part = part.strip()
        upper = part.upper()
        # PRIMARY KEY constraint
        pk_m = re.match(r"(?:CONSTRAINT\s+\w+\s+)?PRIMARY\s+KEY\s*\(([^)]+)\)", part, re.IGNORECASE)
        if pk_m:
            pk_cols = [c.strip().strip("`\"[]") for c in pk_m.group(1).split(",")]
            continue
        col = _parse_column_def(part)
        if col:
            columns.append(col)
            if col.primary_key:
                pk_cols.append(col.name)

    return columns, pk_cols


# ---------------------------------------------------------------------------
# Main reconstructor
# ---------------------------------------------------------------------------

def reconstruct_schema(migration_scripts: list[dict]) -> dict[str, TableDef]:
    """
    Process migration scripts in version order and return the current-state
    schema as a dict of table_name (lower) -> TableDef.

    Each script dict must have: version (str|None), content (str).
    """
    # Sort: versioned scripts by version string, repeatable last
    def _sort_key(s: dict) -> tuple:
        v = s.get("version") or ""
        parts = re.split(r"[._]", v)
        nums: list[int] = []
        for p in parts:
            try:
                nums.append(int(p))
            except ValueError:
                nums.append(0)
        return (0 if v else 1, nums)

    scripts = sorted(migration_scripts, key=_sort_key)

    tables: dict[str, TableDef] = {}  # lower-name -> TableDef

    for script in scripts:
        content = script.get("content") or ""
        _apply_script(content, tables)

    return tables


def _apply_script(sql: str, tables: dict[str, TableDef]) -> None:
    """Apply one migration script to the running schema state."""
    # Strip comments
    sql = _STRIP_COMMENTS.sub(" ", sql)

    # Split into statements
    statements = [s.strip() for s in sql.split(";") if s.strip()]

    for stmt in statements:
        stmt_upper = stmt.upper().lstrip()

        # CREATE TABLE
        m = _CREATE_TABLE.search(stmt)
        if m:
            tname = m.group(1).lower()
            body = m.group(2)
            cols, pk = _parse_create_table_body(body)
            tables[tname] = TableDef(name=tname, columns=cols, primary_key=pk)
            continue

        # DROP TABLE
        m = _DROP_TABLE.search(stmt)
        if m:
            tname = m.group(1).lower()
            tables.pop(tname, None)
            continue

        # RENAME TABLE
        m = _ALTER_RENAME_TABLE.search(stmt)
        if m:
            groups = [g for g in m.groups() if g]
            if len(groups) >= 2:
                old, new = groups[0].lower(), groups[1].lower()
                if old in tables:
                    tbl = tables.pop(old)
                    tbl.name = new
                    tables[new] = tbl
            continue

        # ALTER TABLE ADD COLUMN
        m = _ALTER_ADD_COLUMN.search(stmt)
        if m:
            tname = m.group(1).lower()
            col_name = m.group(2)
            col_def_text = f"{col_name} {m.group(3)}"
            col = _parse_column_def(col_def_text)
            if col and tname in tables:
                # Replace if already exists (idempotent re-run)
                tables[tname].columns = [c for c in tables[tname].columns if c.name.lower() != col.name.lower()]
                tables[tname].columns.append(col)
            continue

        # ALTER TABLE DROP COLUMN
        m = _ALTER_DROP_COLUMN.search(stmt)
        if m:
            tname = m.group(1).lower()
            col_name = m.group(2).lower()
            if tname in tables:
                tables[tname].columns = [c for c in tables[tname].columns if c.name.lower() != col_name]
            continue

        # ALTER TABLE MODIFY / ALTER COLUMN
        m = _ALTER_MODIFY_COLUMN.search(stmt)
        if m:
            tname = m.group(1).lower()
            col_name = m.group(2)
            col_def_text = f"{col_name} {m.group(3)}"
            col = _parse_column_def(col_def_text)
            if col and tname in tables:
                tables[tname].columns = [c for c in tables[tname].columns if c.name.lower() != col.name.lower()]
                tables[tname].columns.append(col)
            continue

        # ALTER TABLE ADD PRIMARY KEY
        m = _ADD_PK.search(stmt)
        if m:
            tname = m.group(1).lower()
            pk_cols = [c.strip().strip("`\"[]") for c in m.group(2).split(",")]
            if tname in tables:
                tables[tname].primary_key = pk_cols
            continue

        # ALTER TABLE ADD FOREIGN KEY
        m = _ADD_CONSTRAINT_FK.search(stmt)
        if m:
            tname = m.group(1).lower()
            fk_name = m.group(2)  # may be None if no CONSTRAINT clause
            fk_cols = [c.strip().strip("`\"[]") for c in m.group(3).split(",")]
            ref_table = m.group(4).lower()
            ref_cols = [c.strip().strip("`\"[]") for c in m.group(5).split(",")]
            if tname in tables:
                tables[tname].foreign_keys.append(ForeignKeyDef(
                    name=fk_name, columns=fk_cols,
                    ref_table=ref_table, ref_columns=ref_cols,
                ))
            continue

        # CREATE INDEX
        m = _CREATE_INDEX.search(stmt)
        if m:
            unique = bool(m.group(1))
            idx_name = m.group(2)
            tname = m.group(3).lower()
            idx_cols = [c.strip().strip("`\"[]") for c in m.group(4).split(",")]
            if tname in tables:
                tables[tname].indexes.append(IndexDef(name=idx_name, columns=idx_cols, unique=unique))
            continue

        # DROP INDEX
        m = _DROP_INDEX.search(stmt)
        if m:
            idx_name = m.group(1)
            tname_hint = (m.group(2) or "").lower()
            for tbl in tables.values():
                if tname_hint and tbl.name != tname_hint:
                    continue
                tbl.indexes = [ix for ix in tbl.indexes if ix.name.lower() != idx_name.lower()]


# ---------------------------------------------------------------------------
# Schema diff
# ---------------------------------------------------------------------------

def diff_schemas(
    schema_a: dict[str, TableDef],
    schema_b: dict[str, TableDef],
) -> list[dict]:
    """
    Compare two reconstructed schemas and return a list of change dicts.

    Each entry has:
      change: TABLE_ADDED | TABLE_DROPPED | COLUMN_ADDED | COLUMN_DROPPED |
              TYPE_CHANGED | CONSTRAINT_CHANGED | INDEX_CHANGED | FK_CHANGED
      table: str
      column: str | None
      detail: dict
      risk: "high" | "medium" | "low"
    """
    changes: list[dict] = []

    tables_a = set(schema_a)
    tables_b = set(schema_b)

    for t in sorted(tables_b - tables_a):
        changes.append({"change": "TABLE_ADDED", "table": t, "column": None,
                        "detail": {"columns": len(schema_b[t].columns)}, "risk": "low"})

    for t in sorted(tables_a - tables_b):
        changes.append({"change": "TABLE_DROPPED", "table": t, "column": None,
                        "detail": {}, "risk": "high"})

    for t in sorted(tables_a & tables_b):
        ta, tb = schema_a[t], schema_b[t]

        cols_a = {c.name.lower(): c for c in ta.columns}
        cols_b = {c.name.lower(): c for c in tb.columns}

        for col in sorted(set(cols_b) - set(cols_a)):
            c = cols_b[col]
            not_null_no_default = not c.nullable and c.default_value is None
            changes.append({
                "change": "COLUMN_ADDED", "table": t, "column": c.name,
                "detail": {"type": c.data_type, "nullable": c.nullable, "default": c.default_value},
                "risk": "high" if not_null_no_default else "low",
            })

        for col in sorted(set(cols_a) - set(cols_b)):
            changes.append({
                "change": "COLUMN_DROPPED", "table": t, "column": cols_a[col].name,
                "detail": {"type": cols_a[col].data_type},
                "risk": "high",
            })

        for col in sorted(set(cols_a) & set(cols_b)):
            ca, cb = cols_a[col], cols_b[col]
            if ca.data_type != cb.data_type:
                changes.append({
                    "change": "TYPE_CHANGED", "table": t, "column": ca.name,
                    "detail": {"from": ca.data_type, "to": cb.data_type},
                    "risk": "high",
                })
            elif ca.nullable != cb.nullable:
                changes.append({
                    "change": "CONSTRAINT_CHANGED", "table": t, "column": ca.name,
                    "detail": {"nullable_from": ca.nullable, "nullable_to": cb.nullable},
                    "risk": "medium" if cb.nullable else "high",
                })

        # Primary key changes
        if sorted(ta.primary_key) != sorted(tb.primary_key):
            changes.append({
                "change": "INDEX_CHANGED", "table": t, "column": None,
                "detail": {"pk_from": ta.primary_key, "pk_to": tb.primary_key, "kind": "primary_key"},
                "risk": "high",
            })

        # Index changes
        idx_a = {ix.name.lower(): ix for ix in ta.indexes}
        idx_b = {ix.name.lower(): ix for ix in tb.indexes}
        for name in sorted(set(idx_b) - set(idx_a)):
            ix = idx_b[name]
            changes.append({
                "change": "INDEX_CHANGED", "table": t, "column": None,
                "detail": {"kind": "added", "name": ix.name, "columns": ix.columns, "unique": ix.unique},
                "risk": "low",
            })
        for name in sorted(set(idx_a) - set(idx_b)):
            ix = idx_a[name]
            changes.append({
                "change": "INDEX_CHANGED", "table": t, "column": None,
                "detail": {"kind": "dropped", "name": ix.name, "columns": ix.columns},
                "risk": "medium",
            })

        # FK changes (by name where available, else by column set)
        fk_a = {(fk.name or "").lower() or str(fk.columns): fk for fk in ta.foreign_keys}
        fk_b = {(fk.name or "").lower() or str(fk.columns): fk for fk in tb.foreign_keys}
        for key in sorted(set(fk_b) - set(fk_a)):
            fk = fk_b[key]
            changes.append({
                "change": "FK_CHANGED", "table": t, "column": None,
                "detail": {"kind": "added", "name": fk.name, "columns": fk.columns,
                           "references": fk.ref_table, "ref_columns": fk.ref_columns},
                "risk": "low",
            })
        for key in sorted(set(fk_a) - set(fk_b)):
            fk = fk_a[key]
            changes.append({
                "change": "FK_CHANGED", "table": t, "column": None,
                "detail": {"kind": "dropped", "name": fk.name, "columns": fk.columns,
                           "references": fk.ref_table},
                "risk": "medium",
            })

    return changes


# ---------------------------------------------------------------------------
# Migration risk scoring
# ---------------------------------------------------------------------------

def score_migration_risk(
    script: dict,
    schema_before: dict[str, TableDef],
) -> dict:
    """
    Score a single migration script for deployment risk.

    Returns { risk: "high"|"medium"|"low", reasons: [str] }

    Risk factors:
    - ADD COLUMN NOT NULL without DEFAULT on an existing table → high
    - DROP COLUMN / DROP TABLE → high
    - MODIFY/ALTER COLUMN on a column referenced by FKs → high
    - Structural change on a table with many FK references → medium
    - New FK added → medium
    - Any DDL on a large/heavily-referenced table → medium
    """
    reasons: list[str] = []
    risk_level = "low"

    def _escalate(level: str) -> None:
        nonlocal risk_level
        if level == "high" or (level == "medium" and risk_level == "low"):
            risk_level = level

    sql = _STRIP_COMMENTS.sub(" ", script.get("content") or "")
    statements = [s.strip() for s in sql.split(";") if s.strip()]

    # Build a reverse FK map: table -> how many other tables reference it
    fk_ref_count: dict[str, int] = {}
    for tbl in schema_before.values():
        for fk in tbl.foreign_keys:
            fk_ref_count[fk.ref_table] = fk_ref_count.get(fk.ref_table, 0) + 1

    for stmt in statements:
        # DROP TABLE
        m = _DROP_TABLE.search(stmt)
        if m:
            tname = m.group(1).lower()
            reasons.append(f"DROP TABLE `{tname}` — irreversible data loss")
            _escalate("high")
            continue

        # DROP COLUMN
        m = _ALTER_DROP_COLUMN.search(stmt)
        if m:
            tname, col = m.group(1).lower(), m.group(2)
            reasons.append(f"DROP COLUMN `{tname}.{col}` — irreversible data loss")
            _escalate("high")
            continue

        # ADD COLUMN NOT NULL without DEFAULT
        m = _ALTER_ADD_COLUMN.search(stmt)
        if m:
            tname = m.group(1).lower()
            col_name = m.group(2)
            col_def = f"{col_name} {m.group(3)}"
            col = _parse_column_def(col_def)
            if col and not col.nullable and col.default_value is None:
                if tname in schema_before:  # existing table — will fail on non-empty
                    reasons.append(
                        f"ADD COLUMN `{tname}.{col.name}` NOT NULL without DEFAULT "
                        f"— will fail on non-empty table"
                    )
                    _escalate("high")
            continue

        # MODIFY / ALTER COLUMN — check if any FK points to this column
        m = _ALTER_MODIFY_COLUMN.search(stmt)
        if m:
            tname = m.group(1).lower()
            col_name = m.group(2).lower()
            # Check if any FK in schema_before references this table+column
            for other_tbl in schema_before.values():
                for fk in other_tbl.foreign_keys:
                    if fk.ref_table == tname and col_name in [c.lower() for c in fk.ref_columns]:
                        reasons.append(
                            f"MODIFY `{tname}.{col_name}` — FK from "
                            f"`{other_tbl.name}` references this column; constraint violation risk"
                        )
                        _escalate("high")
            continue

        # ADD FOREIGN KEY
        m = _ADD_CONSTRAINT_FK.search(stmt)
        if m:
            tname = m.group(1).lower()
            ref_table = m.group(4).lower()
            reasons.append(
                f"ADD FOREIGN KEY on `{tname}` → `{ref_table}` "
                f"— existing rows must satisfy constraint"
            )
            _escalate("medium")
            continue

        # Structural change on a heavily-referenced table
        m = _CREATE_TABLE.search(stmt)
        if not m:
            # Any ALTER on a table with many FK references
            for pattern in (_ALTER_ADD_COLUMN, _ALTER_DROP_COLUMN, _ALTER_MODIFY_COLUMN):
                m2 = pattern.search(stmt)
                if m2:
                    tname = m2.group(1).lower()
                    refs = fk_ref_count.get(tname, 0)
                    if refs >= 3:
                        reasons.append(
                            f"Structural change on `{tname}` which has {refs} FK references "
                            f"— potential lock contention on large table"
                        )
                        _escalate("medium")
                    break

    return {"risk": risk_level, "reasons": reasons}


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------

def schema_to_dict(tables: dict[str, TableDef]) -> list[dict]:
    """Convert reconstructed schema to a JSON-serialisable list."""
    result = []
    for tname in sorted(tables):
        tbl = tables[tname]
        result.append({
            "table": tbl.name,
            "columns": [
                {
                    "name": c.name,
                    "type": c.data_type,
                    "nullable": c.nullable,
                    "primary_key": c.primary_key or c.name in tbl.primary_key,
                    "default": c.default_value,
                }
                for c in tbl.columns
            ],
            "primary_key": tbl.primary_key,
            "indexes": [
                {"name": ix.name, "columns": ix.columns, "unique": ix.unique}
                for ix in tbl.indexes
            ],
            "foreign_keys": [
                {
                    "name": fk.name,
                    "columns": fk.columns,
                    "references": fk.ref_table,
                    "ref_columns": fk.ref_columns,
                }
                for fk in tbl.foreign_keys
            ],
        })
    return result
