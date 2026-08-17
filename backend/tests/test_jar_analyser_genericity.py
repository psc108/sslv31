"""Genericity regression tests for the JAR Analyser.

All three real jar-of-jars uploads exercised in this instance are the same
product (DXC's "installation-package") at three versions — version distance,
not architectural distance. `events.py`'s cross-service event detection was
found to hardcode a package-depth assumption specific to that one product's
`com/dxc/ecs/<service>/...` convention (see
Documentation/jar_analyser_dissection_accuracy_plan.md, Stage 2). This test
proves the fix generalises to a different package convention/depth without
needing a second real jar-of-jars product — a synthetic fixture is enough,
because `_scan_consumer_classes` only reads ZIP entry *names*, never parses
bytecode content, so no real compiled .class bytes are required.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.services.jar_analyser.events import EventDefinitionExtractor


def _make_synthetic_jar(tmp_path: Path, entries: list[str]) -> Path:
    """A JAR-like zip containing only empty files at the given entry names —
    sufficient for consumer-class detection, which is purely name-based."""
    jar_path = tmp_path / "synthetic-service.jar"
    with zipfile.ZipFile(jar_path, "w") as zf:
        for name in entries:
            zf.writestr(name, b"")
    return jar_path


def test_cross_service_event_detected_under_shallow_package_convention(tmp_path):
    """`io/acme/ticketing/...` — two vendor-prefix segments (io, acme), not
    the three (com, dxc, ecs) the old hardcoded index assumed. A genuinely
    cross-service consumption (ticketing consuming fulfillment's event) must
    still be detected as cross-service."""
    jar = _make_synthetic_jar(tmp_path, [
        "content/lib/BOOT-INF/classes/io/acme/ticketing/service/event/fulfillment/OrderCreatedConsumer.class",
    ])
    result = EventDefinitionExtractor.from_jar(jar)
    filenames = {ed.filename for ed in result}
    assert "fulfillment-svc.consumed" in filenames, (
        f"cross-service event from a shallower package convention was not detected: {filenames}"
    )


def test_self_consumption_filtered_under_shallow_package_convention(tmp_path):
    """Same shallow convention, but the consumer's source package matches its
    own service name (`ticketing` consuming a `ticketing` event) — this must
    be filtered out as internal, not reported as cross-service. Under the old
    `own_segs[3]` hardcoded index, this shallower convention put the wrong
    segment ('service', the literal package word) at that position instead of
    'ticketing', so the self-consumption match failed and this was wrongly
    reported as a genuine cross-service dependency."""
    jar = _make_synthetic_jar(tmp_path, [
        "content/lib/BOOT-INF/classes/io/acme/ticketing/service/event/ticketing/SomeInternalConsumer.class",
    ])
    result = EventDefinitionExtractor.from_jar(jar)
    filenames = {ed.filename for ed in result}
    assert "ticketing-svc.consumed" not in filenames, (
        f"self-consumed event under a shallower package convention was wrongly "
        f"reported as cross-service: {filenames}"
    )


def test_both_cases_together_under_shallow_package_convention(tmp_path):
    """The realistic case: one service, two consumers, mixed internal/cross-service."""
    jar = _make_synthetic_jar(tmp_path, [
        "content/lib/BOOT-INF/classes/io/acme/ticketing/service/event/fulfillment/OrderCreatedConsumer.class",
        "content/lib/BOOT-INF/classes/io/acme/ticketing/service/event/ticketing/SomeInternalConsumer.class",
    ])
    result = EventDefinitionExtractor.from_jar(jar)
    filenames = {ed.filename for ed in result}
    assert "fulfillment-svc.consumed" in filenames
    assert "ticketing-svc.consumed" not in filenames


def test_original_deep_package_convention_still_works(tmp_path):
    """Regression guard for the original, still-real convention this was built
    against: com/dxc/ecs/<service>/... (three vendor prefix segments)."""
    jar = _make_synthetic_jar(tmp_path, [
        "content/lib/BOOT-INF/classes/com/dxc/ecs/catalog/service/event/customer/ContractCreatedConsumer.class",
        "content/lib/BOOT-INF/classes/com/dxc/ecs/catalog/service/event/catalog/SomeInternalConsumer.class",
    ])
    result = EventDefinitionExtractor.from_jar(jar)
    filenames = {ed.filename for ed in result}
    assert "customer-svc.consumed" in filenames
    assert "catalog-svc.consumed" not in filenames
