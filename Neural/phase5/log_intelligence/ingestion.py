"""
P5-01: Log ingestion entry point.

Public API used by all downstream Phase 5 tasks:

    from phase5.log_intelligence.ingestion import (
        ingest_log_file, ingest_log_files, ingest_log_tail, ingest_lines
    )

    # Single file — full read
    windows = ingest_log_file("/var/log/app/application.log")

    # Multiple files / glob / directory — merged and re-sorted by timestamp
    windows = ingest_log_files(["/var/log/app/*.log"])
    windows = ingest_log_files(["/var/log/app/"])   # all *.log in dir

    # Tail mode — last N lines or last N minutes (production default)
    windows = ingest_log_tail("/var/log/app/application.log", tail_lines=10_000)
    windows = ingest_log_tail("/var/log/app/application.log", tail_minutes=30)
"""

from __future__ import annotations

import glob
import os
from collections import deque
from datetime import datetime, timedelta
from typing import Iterator, Sequence

from .log_parser import LogEntry, parse_file, parse_lines
from .log_windower import LogWindow, window_entries


def ingest_log_file(
    path: str,
    gap_seconds: float = 5.0,
    max_entries_per_window: int = 200,
) -> list[LogWindow]:
    entries = parse_file(path)
    return window_entries(entries, gap_seconds, max_entries_per_window)


def ingest_log_files(
    paths: list[str],
    gap_seconds: float = 5.0,
    max_entries_per_window: int = 200,
) -> list[LogWindow]:
    """
    Ingest multiple log files, a glob pattern, or a directory path.
    Entries from all sources are merged and re-sorted by timestamp before
    windowing, so MDC correlation works correctly across service boundaries.

    Each element of `paths` may be:
      - An exact file path          e.g. "/var/log/app/service-a.log"
      - A glob pattern              e.g. "/var/log/app/*.log"
      - A directory path            e.g. "/var/log/app/"  (reads all *.log files)
    """
    resolved: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            resolved.extend(sorted(glob.glob(os.path.join(p, "*.log"))))
        else:
            expanded = sorted(glob.glob(p))
            resolved.extend(expanded if expanded else ([p] if os.path.isfile(p) else []))

    all_entries: list[LogEntry] = []
    for path in resolved:
        try:
            all_entries.extend(parse_file(path))
        except OSError:
            continue

    # Re-sort by timestamp so windows spanning multiple files are coherent
    all_entries.sort(key=lambda e: e.timestamp)
    return window_entries(all_entries, gap_seconds, max_entries_per_window)


def ingest_log_tail(
    path: str,
    tail_lines: int = 10_000,
    tail_minutes: int | None = None,
    gap_seconds: float = 5.0,
    max_entries_per_window: int = 200,
) -> list[LogWindow]:
    """
    Read only the tail of a log file — the last `tail_lines` lines, or
    all lines within the last `tail_minutes` minutes if specified.
    Avoids loading multi-GB production logs into memory on every request.

    `tail_minutes` takes priority over `tail_lines` when both are given.
    """
    raw_lines = _tail_file(path, tail_lines)
    entries = parse_lines(iter(raw_lines))

    if tail_minutes is not None:
        cutoff = datetime.utcnow() - timedelta(minutes=tail_minutes)
        entries = [e for e in entries if e.timestamp >= cutoff]

    return window_entries(entries, gap_seconds, max_entries_per_window)


def _tail_file(path: str, n: int) -> list[str]:
    """Return the last `n` lines of a file efficiently using a deque,
    without loading the entire file into memory."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        return list(deque(fh, maxlen=n))


def ingest_lines(
    lines: Iterator[str] | Sequence[str],
    gap_seconds: float = 5.0,
    max_entries_per_window: int = 200,
) -> list[LogWindow]:
    entries = parse_lines(iter(lines))
    return window_entries(entries, gap_seconds, max_entries_per_window)
