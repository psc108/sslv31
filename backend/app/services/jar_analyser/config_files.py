"""Configuration file extractor — extracts and analyses config files from JARs."""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

# File patterns to extract, mapped to their type label
_CONFIG_PATTERNS: list[tuple[str, str]] = [
    # (glob-style suffix or exact name, file_type)
    ("application.properties",          "properties"),
    ("application.yml",                 "yaml"),
    ("application.yaml",                "yaml"),
    ("bootstrap.properties",            "properties"),
    ("bootstrap.yml",                   "yaml"),
    ("bootstrap.yaml",                  "yaml"),
    ("logback-spring.xml",              "xml"),
    ("logback.xml",                     "xml"),
    ("setup.properties",                "properties"),
    ("versions.yml",                    "yaml"),
    ("version.yml",                     "yaml"),
]

# Regex patterns for profile-specific files
_PROFILE_PROPS_RE = re.compile(r"^application-(.+)\.properties$")
_PROFILE_YAML_RE  = re.compile(r"^application-(.+)\.ya?ml$")
_EVENT_YML_RE     = re.compile(r"^.+\.event\.ya?ml$")
_NGINX_CONF_RE    = re.compile(r"^.+\.conf$")
_SYSTEMD_RE       = re.compile(r"^.+\.service$")
_LOGROTATE_RE     = re.compile(r"^.+logrotate.*$")

# Key category patterns
_SSL_KEYS    = re.compile(r"ssl|keystore|truststore|tls", re.I)
_DB_KEYS     = re.compile(r"datasource|jdbc|db\.", re.I)
_MQ_KEYS     = re.compile(r"rabbitmq|amqp", re.I)
_ENC_VALUE   = re.compile(r"^ENC\(.+\)$")
_PLACEHOLDER = re.compile(r"\$\{.+?\}")


@dataclass
class ConfigKeyInfo:
    key: str
    value: str
    is_encrypted: bool
    is_placeholder: bool
    category: str   # server | database | ssl | messaging | logging | other


@dataclass
class ConfigFileInfo:
    filename: str
    path_in_jar: str
    file_type: str          # properties | yaml | xml | conf | service | logrotate
    profile: str | None     # e.g. "backend" for application-backend.properties
    content: str
    key_count: int
    encrypted_count: int
    placeholder_count: int
    ssl_key_count: int
    db_key_count: int
    mq_key_count: int
    declared_port: int | None   # value of server.port if present
    keys: list[ConfigKeyInfo] = field(default_factory=list)


class ConfigFileExtractor:
    """Extract and analyse configuration files from a JAR or extracted directory."""

    @staticmethod
    def from_jar(path: str | Path) -> list[ConfigFileInfo]:
        path = Path(path)
        with zipfile.ZipFile(path, "r") as zf:
            return ConfigFileExtractor.from_zip(zf)

    @staticmethod
    def from_zip(zf: zipfile.ZipFile) -> list[ConfigFileInfo]:
        results: list[ConfigFileInfo] = []
        for entry_name in zf.namelist():
            info = ConfigFileExtractor._match_entry(entry_name)
            if info is None:
                continue
            file_type, profile = info
            try:
                content = zf.read(entry_name).decode("utf-8", errors="replace")
            except Exception:
                continue
            filename = PurePosixPath(entry_name).name
            results.append(ConfigFileExtractor._analyse(
                filename=filename,
                path_in_jar=entry_name,
                file_type=file_type,
                profile=profile,
                content=content,
            ))
        return results

    @staticmethod
    def from_directory(directory: str | Path) -> list[ConfigFileInfo]:
        """Extract config files from an already-extracted JAR directory."""
        directory = Path(directory)
        results: list[ConfigFileInfo] = []
        for file_path in directory.rglob("*"):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(directory).as_posix()
            info = ConfigFileExtractor._match_entry(rel)
            if info is None:
                continue
            file_type, profile = info
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            results.append(ConfigFileExtractor._analyse(
                filename=file_path.name,
                path_in_jar=rel,
                file_type=file_type,
                profile=profile,
                content=content,
            ))
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _match_entry(entry_name: str) -> tuple[str, str | None] | None:
        """Return (file_type, profile) if this entry should be extracted, else None."""
        name = PurePosixPath(entry_name).name

        # Exact matches
        for pattern, file_type in _CONFIG_PATTERNS:
            if name == pattern:
                return file_type, None

        # Profile-specific properties
        m = _PROFILE_PROPS_RE.match(name)
        if m:
            return "properties", m.group(1)

        # Profile-specific YAML
        m = _PROFILE_YAML_RE.match(name)
        if m:
            return "yaml", m.group(1)

        # Event definition YAMLs
        if _EVENT_YML_RE.match(name):
            return "yaml", "event"

        # Bundle files
        if "bundle/" in entry_name or entry_name.startswith("bundle/"):
            if _NGINX_CONF_RE.match(name):
                return "conf", None
            if _SYSTEMD_RE.match(name):
                return "service", None
            if _LOGROTATE_RE.match(name):
                return "logrotate", None

        # Any YAML/properties directly under config/ (e.g. portalui-frontend.yml)
        if entry_name.startswith("config/") and entry_name.count("/") == 1:
            if name.endswith((".yml", ".yaml")):
                return "yaml", None
            if name.endswith(".properties"):
                return "properties", None

        return None

    @staticmethod
    def _analyse(
        filename: str,
        path_in_jar: str,
        file_type: str,
        profile: str | None,
        content: str,
    ) -> ConfigFileInfo:
        keys: list[ConfigKeyInfo] = []
        declared_port: int | None = None

        if file_type == "properties":
            keys = ConfigFileExtractor._parse_properties(content)
        elif file_type == "yaml":
            keys = ConfigFileExtractor._parse_yaml(content)

        # Extract server.port
        for k in keys:
            if k.key == "server.port":
                try:
                    declared_port = int(k.value)
                except ValueError:
                    pass

        encrypted_count  = sum(1 for k in keys if k.is_encrypted)
        placeholder_count = sum(1 for k in keys if k.is_placeholder)
        ssl_key_count    = sum(1 for k in keys if _SSL_KEYS.search(k.key))
        db_key_count     = sum(1 for k in keys if _DB_KEYS.search(k.key))
        mq_key_count     = sum(1 for k in keys if _MQ_KEYS.search(k.key))

        return ConfigFileInfo(
            filename=filename,
            path_in_jar=path_in_jar,
            file_type=file_type,
            profile=profile,
            content=content,
            key_count=len(keys),
            encrypted_count=encrypted_count,
            placeholder_count=placeholder_count,
            ssl_key_count=ssl_key_count,
            db_key_count=db_key_count,
            mq_key_count=mq_key_count,
            declared_port=declared_port,
            keys=keys,
        )

    @staticmethod
    def _parse_properties(text: str) -> list[ConfigKeyInfo]:
        keys: list[ConfigKeyInfo] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("!"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
            elif ":" in line:
                k, _, v = line.partition(":")
            else:
                continue
            key = k.strip()
            value = v.strip()
            keys.append(ConfigFileExtractor._make_key(key, value))
        return keys

    @staticmethod
    def _parse_yaml(text: str) -> list[ConfigKeyInfo]:
        """Flatten a YAML document into dotted key=value pairs."""
        keys: list[ConfigKeyInfo] = []
        try:
            doc = yaml.safe_load(text)
            if isinstance(doc, dict):
                for flat_key, value in ConfigFileExtractor._flatten_yaml(doc):
                    keys.append(ConfigFileExtractor._make_key(flat_key, str(value) if value is not None else ""))
        except Exception:
            pass
        return keys

    @staticmethod
    def _flatten_yaml(
        obj: dict,
        prefix: str = "",
    ):
        """Recursively flatten a nested dict into (dotted.key, value) pairs."""
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                yield from ConfigFileExtractor._flatten_yaml(v, full_key)
            elif isinstance(v, list):
                yield full_key, str(v)
            else:
                yield full_key, v if v is not None else ""

    @staticmethod
    def _make_key(key: str, value: str) -> ConfigKeyInfo:
        is_encrypted  = bool(_ENC_VALUE.match(value))
        is_placeholder = bool(_PLACEHOLDER.search(value))
        category = ConfigFileExtractor._categorise_key(key)
        return ConfigKeyInfo(
            key=key,
            value=value,
            is_encrypted=is_encrypted,
            is_placeholder=is_placeholder,
            category=category,
        )

    @staticmethod
    def _categorise_key(key: str) -> str:
        key_lower = key.lower()
        if _SSL_KEYS.search(key_lower):
            return "ssl"
        if _DB_KEYS.search(key_lower):
            return "database"
        if _MQ_KEYS.search(key_lower):
            return "messaging"
        if key_lower.startswith("server."):
            return "server"
        if key_lower.startswith("logging.") or "logback" in key_lower:
            return "logging"
        if key_lower.startswith("management.") or key_lower.startswith("spring.actuator"):
            return "actuator"
        return "other"
