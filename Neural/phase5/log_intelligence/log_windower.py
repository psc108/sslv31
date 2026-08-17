"""
P5-01: Log windower.

Groups LogEntry objects into LogWindow sequences for ML consumption.

Windowing strategy (priority order):
  1. MDC correlation ID  — group all entries sharing the same non-blank ID
  2. Thread name         — fallback when MDC is blank; group by thread
  3. Timestamp proximity — merge adjacent same-key entries within gap_seconds

A window is emitted when:
  - The key changes, OR
  - The time gap between consecutive entries exceeds gap_seconds, OR
  - The window reaches max_entries
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Sequence

from .log_parser import LogEntry


@dataclass
class LogWindow:
    key: str                            # MDC ID or thread name
    entries: list[LogEntry] = field(default_factory=list)

    # Derived signals used by downstream ML
    @property
    def has_error(self) -> bool:
        return any(e.is_error for e in self.entries)

    @property
    def has_warn(self) -> bool:
        return any(e.is_warn for e in self.entries)

    @property
    def has_stack(self) -> bool:
        return any(e.has_stack for e in self.entries)

    @property
    def entity_keys(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for e in self.entries:
            for k in e.entity_keys:
                if k not in seen:
                    seen.add(k)
                    out.append(k)
        return out

    @property
    def level_sequence(self) -> list[str]:
        return [e.level for e in self.entries]

    @property
    def duration_ms(self) -> float:
        if len(self.entries) < 2:
            return 0.0
        delta = self.entries[-1].timestamp - self.entries[0].timestamp
        return delta.total_seconds() * 1000

    @property
    def error_entries(self) -> list[LogEntry]:
        return [e for e in self.entries if e.is_error or e.is_warn]

    def text_for_embedding(self) -> str:
        """Concatenated messages — fed to the embedding model in P5-02."""
        return " | ".join(e.message for e in self.entries)


def window_entries(
    entries: Sequence[LogEntry],
    gap_seconds: float = 5.0,
    max_entries: int = 200,
) -> list[LogWindow]:
    """
    Partition a flat list of LogEntry into LogWindow groups.

    Args:
        entries:     Parsed log entries in chronological order.
        gap_seconds: Max time gap within a window before splitting.
        max_entries: Hard cap on window size to bound memory.

    Returns:
        List of LogWindow objects, each representing one diagnostic context.
    """
    windows: list[LogWindow] = []
    current: LogWindow | None = None
    gap = timedelta(seconds=gap_seconds)

    for entry in entries:
        key = entry.window_key()

        if current is None:
            current = LogWindow(key=key, entries=[entry])
            continue

        time_gap = entry.timestamp - current.entries[-1].timestamp
        key_changed = key != current.key
        too_large = len(current.entries) >= max_entries
        gap_exceeded = time_gap > gap

        if key_changed or gap_exceeded or too_large:
            windows.append(current)
            current = LogWindow(key=key, entries=[entry])
        else:
            current.entries.append(entry)

    if current:
        windows.append(current)

    return windows
