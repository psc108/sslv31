"""
P5-01: Spring Boot logback log parser.

Handles the format:
  2026-08-13 12:20:48.955  INFO [ventsExecutor73] c.d.e.f.service.Foo  [MDC_ID] : message
  <continuation>    at com.example.Foo.bar(Foo.java:42) ~[jar:version]
  <continuation>    Caused by: java.lang.RuntimeException: ...

File-prefixed lines (grep -n style) are also handled:
  /var/log/ecs/fulfillment/application.log:2026-08-13 ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Optional file prefix: "/path/to/file.log:"
_FILE_PREFIX = r"(?:[^\s:]+\.log:)?"

_HEADER = re.compile(
    _FILE_PREFIX
    + r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)"   # 1: timestamp
    + r"\s+(TRACE|DEBUG|INFO|WARN|ERROR|FATAL)"          # 2: level
    + r"\s+\[([^\]]*)\]"                                 # 3: thread
    + r"\s+([\w$.]+(?:\.[\w$]+)*)"                       # 4: logger (abbreviated ok)
    + r"\s+\[([^\]]*)\]"                                 # 5: MDC / correlation ID
    + r"\s*:\s*(.*)"                                     # 6: message
)

# Stack frame continuation lines (with optional file prefix)
_FRAME = re.compile(
    _FILE_PREFIX
    + r"\s+at\s+(\S+)\(([^)]*)\)"                       # class.method(File.java:N)
)

_CAUSED_BY = re.compile(
    _FILE_PREFIX + r"\s*(Caused by:|Suppressed:)\s*(.*)"
)

_ENTITY_KEY = re.compile(r"\b([A-Z][A-Z0-9_]*(?::[A-Z0-9_\-]+){2,})\b")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class StackFrame:
    raw: str
    class_method: str = ""
    location: str = ""          # "File.java:42"

    def __post_init__(self):
        m = _FRAME.search(self.raw)
        if m:
            self.class_method = m.group(1)
            self.location = m.group(2)


@dataclass
class LogEntry:
    timestamp: datetime
    level: str
    thread: str
    logger: str
    mdc_id: str                 # correlation ID — empty string when blank
    message: str
    frames: list[StackFrame] = field(default_factory=list)
    caused_by: list[str] = field(default_factory=list)
    entity_keys: list[str] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

    # Derived convenience
    @property
    def is_error(self) -> bool:
        return self.level in ("ERROR", "FATAL")

    @property
    def is_warn(self) -> bool:
        return self.level == "WARN"

    @property
    def has_stack(self) -> bool:
        return bool(self.frames)

    @property
    def root_logger_class(self) -> str:
        """Last segment of abbreviated logger, e.g. 'ServiceDesignService'."""
        return self.logger.split(".")[-1]

    def window_key(self) -> str:
        """Primary grouping key: MDC ID when present, else thread name."""
        return self.mdc_id.strip() if self.mdc_id.strip() else self.thread


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _strip_file_prefix(line: str) -> str:
    """Remove leading '/path/to/file.log:' if present."""
    if ".log:" in line:
        idx = line.index(".log:") + len(".log:")
        return line[idx:]
    return line


def parse_lines(lines: Iterator[str]) -> list[LogEntry]:
    """
    Parse an iterable of raw log lines into a list of LogEntry objects.
    Continuation lines (stack frames, Caused by) are attached to the
    preceding entry.
    """
    entries: list[LogEntry] = []
    current: LogEntry | None = None

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = _strip_file_prefix(line)

        m = _HEADER.match(line)
        if m:
            ts_str, level, thread, logger, mdc, message = m.groups()
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
            entity_keys = _ENTITY_KEY.findall(message)
            current = LogEntry(
                timestamp=ts,
                level=level,
                thread=thread,
                logger=logger,
                mdc_id=mdc,
                message=message,
                entity_keys=entity_keys,
                raw_lines=[line],
            )
            entries.append(current)
            continue

        if current is None:
            continue

        current.raw_lines.append(line)

        if _FRAME.search(stripped):
            current.frames.append(StackFrame(raw=stripped.strip()))
        elif _CAUSED_BY.match(stripped):
            current.caused_by.append(stripped.strip())

    return entries


def parse_file(path: str) -> list[LogEntry]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return parse_lines(fh)
