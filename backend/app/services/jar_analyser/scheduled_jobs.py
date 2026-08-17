"""Scheduled job extraction — @Scheduled (and repeatable @Schedules) methods.

Same bytecode-annotation technique used for endpoint extraction (annotation
element values survive compilation) applied to Spring's @Scheduled instead of
@RequestMapping. This reveals background/batch work that nothing else in this
tool surfaces: what runs on a timer, how often, and in which class — useful
for the Perceived Purpose narrative and for operators who need to know what
periodic work a service does without reading its source.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .classfile import ClassInfo, AnnotationInfo
from .annotations import SCHEDULED, SCHEDULES

_PLACEHOLDER_RE = re.compile(r"\$\{")


@dataclass
class ScheduledJob:
    declaring_class: str
    declaring_class_simple: str
    method_name: str
    cron: str | None = None
    fixed_rate_ms: int | None = None
    fixed_delay_ms: int | None = None
    initial_delay_ms: int | None = None
    zone: str | None = None
    # True when any schedule element is a Spring placeholder (${...}) rather
    # than a literal value — the actual cadence is only known at deploy time.
    is_config_driven: bool = False
    # Pre-rendered readable summary of the schedule, e.g. "cron: 0 0 2 * * *"
    # or "every 3600000ms (fixed rate)" — computed once so callers (API,
    # frontend, Perceived Purpose) don't need to re-derive the same logic.
    display: str = ""


def _is_placeholder(v: str | None) -> bool:
    return bool(v) and bool(_PLACEHOLDER_RE.search(v))


def _build_job(ci: ClassInfo, method_name: str, ann: AnnotationInfo) -> ScheduledJob:
    cron = ann.get("cron") or None
    fixed_rate = ann.get("fixedRate")
    fixed_rate_str = ann.get("fixedRateString") or None
    fixed_delay = ann.get("fixedDelay")
    fixed_delay_str = ann.get("fixedDelayString") or None
    initial_delay = ann.get("initialDelay")
    initial_delay_str = ann.get("initialDelayString") or None
    zone = ann.get("zone") or None

    # -1 is @Scheduled's own "not set" sentinel for the numeric long variants;
    # defensive since an explicitly-absent element already returns None.
    if fixed_rate in (None, -1):
        fixed_rate = None
    if fixed_delay in (None, -1):
        fixed_delay = None
    if initial_delay in (None, -1):
        initial_delay = None

    is_config_driven = any(
        _is_placeholder(v) for v in (cron, fixed_rate_str, fixed_delay_str, initial_delay_str)
    )

    if cron:
        display = f"cron: {cron}" + (f" ({zone})" if zone else "")
    elif fixed_rate is not None:
        display = f"every {fixed_rate}ms (fixed rate)"
    elif fixed_rate_str:
        display = f"every {fixed_rate_str} (fixed rate, config-driven)"
    elif fixed_delay is not None:
        display = f"every {fixed_delay}ms after previous run completes (fixed delay)"
    elif fixed_delay_str:
        display = f"every {fixed_delay_str} after previous run completes (fixed delay, config-driven)"
    else:
        display = "schedule not statically resolvable"

    return ScheduledJob(
        declaring_class=ci.java_class_name,
        declaring_class_simple=ci.simple_name,
        method_name=method_name,
        cron=cron,
        fixed_rate_ms=fixed_rate,
        fixed_delay_ms=fixed_delay,
        initial_delay_ms=initial_delay,
        zone=zone,
        is_config_driven=is_config_driven,
        display=display,
    )


def extract_scheduled_jobs(classes: list[ClassInfo]) -> list[ScheduledJob]:
    """Scan every class's methods for @Scheduled/@Schedules.

    Unlike endpoint extraction (scoped to @RestController/@Controller
    classes), @Scheduled can appear on any Spring-managed bean, so this scans
    every class already parsed for this JAR — no extra bytecode parsing, just
    an extra pass over structures already in memory.
    """
    jobs: list[ScheduledJob] = []
    for ci in classes:
        for method in ci.methods:
            for ann in method.annotations:
                if ann.descriptor == SCHEDULED:
                    jobs.append(_build_job(ci, method.name, ann))
                elif ann.descriptor == SCHEDULES:
                    nested = ann.get("value")
                    if isinstance(nested, list):
                        for n in nested:
                            if isinstance(n, AnnotationInfo):
                                jobs.append(_build_job(ci, method.name, n))
    return jobs
