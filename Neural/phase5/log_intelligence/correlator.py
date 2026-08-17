"""
P5-04: Cross-signal correlator.

Joins two independent diagnostic signals:
  1. Stack trace  — list[ExceptionBlock] from ssl's stack_trace_parser.py
  2. Log windows  — list[AnomalyResult] + list[LogWindow] from P5-01/P5-03

The join is multi-key, scored, and produces a CorrelatedIncident per
exception block that carries the best-matching windows and the evidence
used to link them.

Join keys (tried in priority order, scores are additive):
  CLASS_MATCH   — ExceptionBlock frame class_name suffix-matches a LogWindow
                  entry's logger or frame class_method  (+0.5)
  ENTITY_MATCH  — An entity key from AnomalyResult appears in the exception
                  message or class name                 (+0.3)
  THREAD_MATCH  — LogWindow.key matches a thread hint extracted from the
                  exception message                     (+0.2)
  ANOMALY_BOOST — The matched window is itself anomalous (is_anomaly=True)  (+0.2)
  SEVERITY_BOOST— Matched window severity is "critical"                     (+0.1)

Thread-awareness (detect_thread_issues):
  Analyses all windows together to flag potential concurrency problems:
  - INTERLEAVED_ERRORS  — same thread name appears in ERROR windows with
    different MDC IDs (request context switching mid-operation)
  - CONCURRENT_MOD      — ConcurrentModificationException in stack frames
  - LOCK_CONTENTION     — multiple windows blocked on the same lock token
  - THREAD_POOL_SATURATION — RejectedExecutionException across windows

Confidence is clamped to [0.0, 1.0].

Output: list[CorrelatedIncident], JSON-serialisable, ready for
JarDiagnosticRun.log_findings_json alongside AnomalyResult payloads.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import TYPE_CHECKING

from .anomaly_scorer import AnomalyResult
from .log_windower import LogWindow

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Thread-issue detection patterns
# ---------------------------------------------------------------------------

_CONCURRENT_MOD_RE = re.compile(
    r"ConcurrentModificationException", re.IGNORECASE
)
_LOCK_CONTENTION_RE = re.compile(
    r"LockAcquisitionException|lock.*timeout|waiting.*lock|BLOCKED", re.IGNORECASE
)
_THREAD_POOL_RE = re.compile(
    r"RejectedExecutionException|ThreadPoolExecutor.*rejected", re.IGNORECASE
)
_DEADLOCK_RE = re.compile(
    r"deadlock|Found one Java-level deadlock", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Abbreviated logger expansion
# ---------------------------------------------------------------------------

def _logger_suffix_matches(abbreviated: str, full_class: str) -> bool:
    """
    'c.d.e.f.service.ServiceDesignService' matches
    'com.dxc.ecs.fulfillment.service.ServiceDesignService'

    Strategy: split both on '.', check that the last N segments of the
    abbreviated form match the last N segments of the full class name,
    where N = number of segments in the abbreviated form that are longer
    than 1 character (single-char segments are package abbreviations).
    """
    abbr_parts = abbreviated.split(".")
    full_parts = full_class.split(".")

    # Collect the meaningful (non-abbreviated) tail segments
    meaningful = [p for p in abbr_parts if len(p) > 1]
    if not meaningful:
        return False

    full_tail = full_parts[-len(meaningful):]
    return [p.lower() for p in meaningful] == [p.lower() for p in full_tail]


def _class_in_window(class_name: str, window: LogWindow) -> bool:
    """True if class_name matches any logger or frame in the window."""
    for entry in window.entries:
        if _logger_suffix_matches(entry.logger, class_name):
            return True
        for frame in entry.frames:
            # frame.class_method is fully qualified from the log
            if frame.class_method.startswith(class_name):
                return True
            if class_name.endswith(frame.class_method.split(".")[-1]):
                return True
    return False


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CorrelationEvidence:
    class_matches: list[str] = field(default_factory=list)
    entity_matches: list[str] = field(default_factory=list)
    thread_match: str | None = None
    anomaly_score: float = 0.0
    anomaly_severity: str = "normal"


@dataclass
class ThreadIssue:
    """A concurrency/threading problem detected across the log window set."""
    kind: str           # INTERLEAVED_ERRORS | CONCURRENT_MOD | LOCK_CONTENTION
                        # | THREAD_POOL_SATURATION | DEADLOCK
    severity: str       # critical | high | medium
    description: str
    thread_names: list[str] = field(default_factory=list)
    window_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CorrelatedIncident:
    exception_class: str | None
    exception_message: str | None
    exception_kind: str
    is_likely_root_cause: bool
    matched_windows: list[str]
    confidence: float
    evidence: CorrelationEvidence
    anomaly_results: list[dict]
    thread_issues: list[dict] = field(default_factory=list)  # ThreadIssue.to_dict()

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def detect_thread_issues(windows: list[LogWindow]) -> list[ThreadIssue]:
    """
    Analyse all windows together to surface concurrency problems that are
    only visible when looking across multiple windows simultaneously.
    """
    issues: list[ThreadIssue] = []

    # Build per-thread-name index: thread_name → list of (window, is_error)
    # Window key is MDC ID when present; thread name is the raw thread field
    # on each entry. We need the thread name, not the window key.
    thread_to_windows: dict[str, list[LogWindow]] = defaultdict(list)
    for w in windows:
        threads_in_window = {e.thread for e in w.entries}
        for t in threads_in_window:
            thread_to_windows[t].append(w)

    # 1. INTERLEAVED_ERRORS — same thread name appears in ERROR windows
    #    with different MDC/window keys (context switching mid-operation)
    interleaved_threads: list[str] = []
    for thread, wlist in thread_to_windows.items():
        error_windows = [w for w in wlist if w.has_error]
        if len(error_windows) >= 2:
            keys = {w.key for w in error_windows}
            if len(keys) >= 2:  # same thread, different request contexts
                interleaved_threads.append(thread)
    if interleaved_threads:
        issues.append(ThreadIssue(
            kind="INTERLEAVED_ERRORS",
            severity="high",
            description=(
                f"{len(interleaved_threads)} thread(s) produced errors across "
                f"multiple request contexts — possible thread-local state leak "
                f"or request context not properly isolated."
            ),
            thread_names=interleaved_threads[:5],
            window_keys=[
                w.key for t in interleaved_threads[:3]
                for w in thread_to_windows[t] if w.has_error
            ][:10],
        ))

    # 2. CONCURRENT_MOD — ConcurrentModificationException in any window
    cme_windows = [
        w for w in windows
        if any(
            _CONCURRENT_MOD_RE.search(f.class_method)
            for e in w.entries for f in e.frames
        ) or any(
            _CONCURRENT_MOD_RE.search(e.message)
            for e in w.entries
        )
    ]
    if cme_windows:
        issues.append(ThreadIssue(
            kind="CONCURRENT_MOD",
            severity="high",
            description=(
                f"ConcurrentModificationException detected in "
                f"{len(cme_windows)} window(s) — a collection is being "
                f"modified while being iterated, likely from multiple threads."
            ),
            window_keys=[w.key for w in cme_windows[:5]],
        ))

    # 3. LOCK_CONTENTION — multiple windows with lock-related errors
    lock_windows = [
        w for w in windows
        if any(
            _LOCK_CONTENTION_RE.search(e.message)
            for e in w.entries if e.is_error or e.is_warn
        )
    ]
    if len(lock_windows) >= 2:
        issues.append(ThreadIssue(
            kind="LOCK_CONTENTION",
            severity="critical" if len(lock_windows) >= 5 else "high",
            description=(
                f"Lock contention detected across {len(lock_windows)} windows — "
                f"multiple threads competing for the same lock. "
                f"Check for deadlock or excessive lock hold time."
            ),
            window_keys=[w.key for w in lock_windows[:5]],
        ))

    # 4. DEADLOCK — explicit deadlock message in any window
    deadlock_windows = [
        w for w in windows
        if any(_DEADLOCK_RE.search(e.message) for e in w.entries)
    ]
    if deadlock_windows:
        issues.append(ThreadIssue(
            kind="DEADLOCK",
            severity="critical",
            description=(
                f"Deadlock signature detected in {len(deadlock_windows)} "
                f"window(s) — threads are mutually blocked. Take a thread dump "
                f"immediately: jstack <pid> or kill -3 <pid>."
            ),
            window_keys=[w.key for w in deadlock_windows[:5]],
        ))

    # 5. THREAD_POOL_SATURATION — RejectedExecutionException across windows
    pool_windows = [
        w for w in windows
        if any(_THREAD_POOL_RE.search(e.message) for e in w.entries)
    ]
    if pool_windows:
        issues.append(ThreadIssue(
            kind="THREAD_POOL_SATURATION",
            severity="critical" if len(pool_windows) >= 3 else "high",
            description=(
                f"Thread pool saturation in {len(pool_windows)} window(s) — "
                f"tasks are being rejected. Increase pool size or add backpressure."
            ),
            window_keys=[w.key for w in pool_windows[:5]],
        ))

    return issues


# ---------------------------------------------------------------------------
# Correlator
# ---------------------------------------------------------------------------

class SignalCorrelator:
    """
    Stateless — no fit() needed. Call correlate() directly.
    """

    def correlate(
        self,
        exception_blocks: list,
        anomaly_results: list[AnomalyResult],
        windows: list[LogWindow],
    ) -> list[CorrelatedIncident]:
        """
        For each ExceptionBlock, find the best-matching LogWindows and
        return a CorrelatedIncident with confidence score, evidence, and
        any thread-safety issues detected across the full window set.
        """
        # Detect thread issues once across all windows
        thread_issues = detect_thread_issues(windows)
        thread_issue_dicts = [ti.to_dict() for ti in thread_issues]
        # Build a lookup: window_key → (LogWindow, AnomalyResult)
        window_map: dict[str, tuple[LogWindow, AnomalyResult | None]] = {}
        for w in windows:
            window_map[w.key] = (w, None)
        for ar in anomaly_results:
            if ar.window_key in window_map:
                w, _ = window_map[ar.window_key]
                window_map[ar.window_key] = (w, ar)

        incidents: list[CorrelatedIncident] = []

        for block in exception_blocks:
            scored: list[tuple[float, str, CorrelationEvidence]] = []

            for wkey, (window, ar) in window_map.items():
                score = 0.0
                evidence = CorrelationEvidence(
                    anomaly_score=ar.score if ar else 0.0,
                    anomaly_severity=ar.severity if ar else "normal",
                )

                # 1. Class name match
                frame_classes = [f.class_name for f in block.frames]
                for cls in frame_classes:
                    if _class_in_window(cls, window):
                        score += 0.5
                        short = cls.split(".")[-1]
                        if short not in evidence.class_matches:
                            evidence.class_matches.append(short)
                        break  # one match per window is enough

                # 2. Entity key match — exception message or class contains key
                exc_text = " ".join(filter(None, [block.exception_class, block.message]))
                for ek in (ar.entity_keys if ar else []):
                    if ek in exc_text:
                        score += 0.3
                        evidence.entity_matches.append(ek)

                # 3. Thread match — window key appears in exception message
                if wkey and wkey in exc_text:
                    score += 0.2
                    evidence.thread_match = wkey

                # 4. Anomaly boost
                if ar and ar.is_anomaly:
                    score += 0.2

                # 5. Severity boost
                if ar and ar.severity == "critical":
                    score += 0.1

                if score > 0:
                    scored.append((score, wkey, evidence))

            # Sort by score descending, take top 3
            scored.sort(key=lambda x: x[0], reverse=True)
            top = scored[:3]

            best_score = top[0][0] if top else 0.0
            confidence = min(best_score, 1.0)

            best_evidence = top[0][2] if top else CorrelationEvidence()
            matched_keys = [wkey for _, wkey, _ in top]

            matched_ar_dicts = [
                window_map[wkey][1].to_dict()
                for wkey in matched_keys
                if window_map.get(wkey) and window_map[wkey][1]
            ]

            incidents.append(CorrelatedIncident(
                exception_class=block.exception_class,
                exception_message=block.message,
                exception_kind=block.kind,
                is_likely_root_cause=block.is_likely_root_cause,
                matched_windows=matched_keys,
                confidence=round(confidence, 3),
                evidence=best_evidence,
                anomaly_results=matched_ar_dicts,
                thread_issues=thread_issue_dicts,
            ))

        return incidents


def correlate(
    exception_blocks: list,
    anomaly_results: list[AnomalyResult],
    windows: list[LogWindow],
) -> list[CorrelatedIncident]:
    """Module-level convenience wrapper."""
    return SignalCorrelator().correlate(exception_blocks, anomaly_results, windows)
