"""
P5-05: ML Diagnostic Pipeline.

The single public entry point for the entire Phase 5 ML layer:

    from phase5.log_intelligence.pipeline import diagnose_with_ml

    result = diagnose_with_ml(
        stack_trace_text = "...",
        log_path         = "/var/log/app/application.log",
        report_id        = "abc-123",
        scorer_path      = "anomaly_scorer.pkl",
    )

    # Multi-log / glob / directory:
    result = diagnose_with_ml(
        stack_trace_text = "...",
        log_paths        = ["/var/log/app/", "/var/log/gateway/*.log"],
        report_id        = "abc-123",
        scorer_path      = "anomaly_scorer.pkl",
    )

Pipeline steps:
  1. Parse stack trace  → list[ExceptionBlock]  (ssl stack_trace_parser)
  2. Ingest log file(s) → list[LogWindow]        (P5-01, tail mode)
  3. Score windows      → list[AnomalyResult]    (P5-03)
  4. Correlate signals  → list[CorrelatedIncident] (P5-04)
  5. Assemble result    → MLDiagnosisResult

Graceful degradation:
  - No log file/paths  → anomaly_results=[], correlated_incidents=[]
  - No scorer pkl      → anomaly_results=[], correlated_incidents=[]
  - No stack trace     → correlated_incidents=[] (anomaly scoring still runs)
  - ssl not importable → inline fallback parser
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any

from .anomaly_scorer import AnomalyResult, AnomalyScorer
from .correlator import CorrelatedIncident, correlate
from .ingestion import ingest_log_files, ingest_log_tail
from .log_windower import LogWindow


# ---------------------------------------------------------------------------
# Stack trace parsing — use ssl's parser (always available when installed
# inside ssl). Falls back to the inline parser only for standalone test runs.
# ---------------------------------------------------------------------------

def _parse_stack_trace(text: str) -> list:
    try:
        from app.services.stack_trace_parser import extract_stack_traces
        return extract_stack_traces(text)
    except ImportError:
        return _inline_parse_stack_trace(text)


def _inline_parse_stack_trace(text: str) -> list:
    """
    Minimal stack trace parser — same output shape as ssl's ExceptionBlock
    but implemented inline so P5-05 works standalone in tests.
    """
    import re
    from dataclasses import dataclass as _dc, field as _f

    @_dc
    class _Frame:
        class_name: str
        method_name: str
        file_name: str | None
        line_number: int | None
        is_native: bool = False
        is_application_frame: bool = True

    @_dc
    class _Block:
        kind: str
        exception_class: str | None
        message: str | None
        frames: list = _f(default_factory=list)
        is_likely_root_cause: bool = False

    _FRAMEWORK_PREFIXES = (
        "java.", "javax.", "jakarta.", "jdk.", "sun.", "com.sun.",
        "org.springframework.", "org.hibernate.", "org.apache.",
        "io.netty.", "reactor.", "kotlin.", "scala.",
    )
    _FRAME_RE = re.compile(r"^\s*at\s+(?:[\w.]+/{1,2})?([\w.$]+)\.([\w$<>]+)\(([^)]*)\)")
    _CAUSED_RE = re.compile(r"^\s*Caused by:\s*(.+)$")
    _HEADER_RE = re.compile(r"^([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+)(?::\s(.*))?$")
    _LOC_RE = re.compile(r"^([^:]+):(\d+)$")

    blocks: list[_Block] = []
    current: _Block | None = None

    for line in text.splitlines():
        line = line.rstrip()
        m = _FRAME_RE.match(line)
        if m:
            if current is None:
                current = _Block(kind="root", exception_class=None, message=None)
                blocks.append(current)
            cls, meth, loc = m.group(1), m.group(2), m.group(3)
            lm = _LOC_RE.match(loc)
            fn = lm.group(1) if lm else None
            ln = int(lm.group(2)) if lm else None
            is_app = not cls.startswith(_FRAMEWORK_PREFIXES)
            current.frames.append(_Frame(cls, meth, fn, ln, is_application_frame=is_app))
            continue
        cb = _CAUSED_RE.match(line)
        if cb:
            hm = _HEADER_RE.fullmatch(cb.group(1).strip())
            cls = hm.group(1) if hm else cb.group(1).strip()
            msg = hm.group(2) if hm else None
            current = _Block(kind="caused_by", exception_class=cls, message=msg)
            blocks.append(current)
            continue
        hm = _HEADER_RE.fullmatch(line.strip())
        if hm:
            current = _Block(kind="root", exception_class=hm.group(1), message=hm.group(2))
            blocks.append(current)
            continue

    run: list[_Block] = []

    def _flag(run: list[_Block]) -> None:
        for b in reversed(run):
            if b.kind in ("root", "caused_by"):
                b.is_likely_root_cause = True
                return

    for b in blocks:
        if b.kind == "root":
            _flag(run)
            run = [b]
        else:
            run.append(b)
    _flag(run)
    return blocks


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class MLDiagnosisResult:
    report_id: str
    log_path: str | None
    analysed_at: str
    windows_analysed: int
    anomalous_windows: int
    anomaly_results: list[dict]
    correlated_incidents: list[dict]
    top_anomalies: list[dict]
    summary: str
    degraded: bool = False
    degradation_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def diagnose_with_ml(
    stack_trace_text: str,
    log_path: str | None,
    report_id: str,
    scorer_path: str | None = None,
    gap_seconds: float = 5.0,
    log_paths: list[str] | None = None,
    tail_lines: int = 10_000,
    tail_minutes: int | None = None,
) -> MLDiagnosisResult:
    """
    Run the full ML diagnostic pipeline.

    Args:
        stack_trace_text: Raw pasted stack trace / error text.
        log_path:         Single log file path. Reads only the tail
                          (tail_lines / tail_minutes) to avoid loading
                          multi-GB production logs into memory.
        log_paths:        List of paths, globs, or directories to ingest
                          from multiple sources simultaneously. Takes
                          priority over log_path when both are supplied.
        tail_lines:       Max lines to read from the tail of a single log
                          file (default 10,000 ≈ 30–60 min of traffic).
        tail_minutes:     If set, further filters to entries within this
                          many minutes of now after the tail_lines cut.
        report_id:        JarDiagnosticRun.report_id for traceability.
        scorer_path:      Path to a fitted AnomalyScorer .pkl file.
        gap_seconds:      Log windowing gap.
    """
    analysed_at = datetime.utcnow().isoformat() + "Z"

    # ── Step 1: Parse stack trace ──────────────────────────────────────────
    exception_blocks = []
    if stack_trace_text and stack_trace_text.strip():
        try:
            exception_blocks = _parse_stack_trace(stack_trace_text)
        except Exception:
            exception_blocks = []

    # ── Step 2: Ingest log file(s) ─────────────────────────────────────────
    windows: list[LogWindow] = []
    degraded = False
    degradation_reason = ""

    # log_paths (multi-source) takes priority over log_path (single file)
    effective_paths: list[str] = log_paths if log_paths else (
        [log_path] if log_path else []
    )

    if effective_paths:
        try:
            multi = (
                len(effective_paths) > 1
                or os.path.isdir(effective_paths[0])
                or "*" in effective_paths[0]
            )
            if multi:
                windows = ingest_log_files(
                    effective_paths, gap_seconds=gap_seconds
                )
            else:
                p = effective_paths[0]
                if os.path.isfile(p):
                    windows = ingest_log_tail(
                        p,
                        tail_lines=tail_lines,
                        tail_minutes=tail_minutes,
                        gap_seconds=gap_seconds,
                    )
                else:
                    degraded = True
                    degradation_reason = f"log file not found: {p}"
        except Exception as e:
            degraded = True
            degradation_reason = f"log ingestion failed: {e}"

    # ── Step 3: Score windows ──────────────────────────────────────────────
    anomaly_results: list[AnomalyResult] = []

    if windows and scorer_path and os.path.isfile(scorer_path):
        try:
            scorer = AnomalyScorer.load(scorer_path)
            anomaly_results = scorer.score_batch(windows)
        except Exception as e:
            degraded = True
            degradation_reason = f"anomaly scoring failed: {e}"
    elif not scorer_path:
        degraded = True
        degradation_reason = "no scorer model configured — set ML_SCORER_PATH to enable anomaly detection"
    elif scorer_path and not os.path.isfile(scorer_path):
        degraded = True
        degradation_reason = f"scorer model not found: {scorer_path}"

    # ── Step 4: Correlate signals ──────────────────────────────────────────
    correlated_incidents: list[CorrelatedIncident] = []

    if exception_blocks and (anomaly_results or windows):
        try:
            correlated_incidents = correlate(exception_blocks, anomaly_results, windows)
        except Exception as e:
            degraded = True
            degradation_reason = f"correlation failed: {e}"

    # ── Step 5: Assemble result ────────────────────────────────────────────
    anomalous = [ar for ar in anomaly_results if ar.is_anomaly]
    top_anomalies = sorted(anomaly_results, key=lambda r: r.score)[:5]

    summary = _build_summary(
        exception_blocks, anomaly_results, correlated_incidents, degraded
    )

    return MLDiagnosisResult(
        report_id=report_id,
        log_path=log_path or (effective_paths[0] if effective_paths else None),
        analysed_at=analysed_at,
        windows_analysed=len(windows),
        anomalous_windows=len(anomalous),
        anomaly_results=[ar.to_dict() for ar in anomaly_results],
        correlated_incidents=[ci.to_dict() for ci in correlated_incidents],
        top_anomalies=[ar.to_dict() for ar in top_anomalies],
        summary=summary,
        degraded=degraded,
        degradation_reason=degradation_reason,
    )


def _build_summary(
    exception_blocks: list,
    anomaly_results: list[AnomalyResult],
    correlated_incidents: list[CorrelatedIncident],
    degraded: bool,
) -> str:
    parts: list[str] = []

    root_causes = [b for b in exception_blocks if b.is_likely_root_cause]
    if root_causes:
        rc = root_causes[0]
        exc = rc.exception_class or "unknown exception"
        msg = f": {rc.message[:60]}" if rc.message else ""
        parts.append(f"Root cause: {exc}{msg}")

    if anomaly_results:
        critical = sum(1 for r in anomaly_results if r.severity == "critical")
        warning  = sum(1 for r in anomaly_results if r.severity == "warning")
        if critical:
            parts.append(f"{critical} critical anomalous log window(s)")
        if warning:
            parts.append(f"{warning} warning log window(s)")

    high_conf = [ci for ci in correlated_incidents if ci.confidence >= 0.5]
    if high_conf:
        parts.append(
            f"{len(high_conf)} log window(s) correlated to stack trace "
            f"(confidence ≥ 0.5)"
        )

    if degraded:
        parts.append("(partial analysis — scorer or log unavailable)")

    return "; ".join(parts) if parts else "No anomalies detected"
