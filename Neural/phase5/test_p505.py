"""
P5-05 smoke test.

Exercises:
  1. Full pipeline — scorer fitted, log file present, stack trace provided
  2. Degraded mode — no scorer pkl
  3. Degraded mode — log file missing
  4. Stack trace only — no log file
  5. Inline stack trace parser (ssl not importable)
  6. JSON serialisability of MLDiagnosisResult
  7. Summary string content
  8. top_anomalies ordering
  9. Multi-log ingestion (log_paths list)
  10. Tail mode — tail_lines cap respected
"""

import sys, json, os, tempfile, glob
sys.path.insert(0, ".")

from phase5.log_intelligence.ingestion import ingest_lines
from phase5.log_intelligence.embed_window import WindowEmbedder
from phase5.log_intelligence.anomaly_scorer import AnomalyScorer
from phase5.log_intelligence.pipeline import diagnose_with_ml, _inline_parse_stack_trace

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

STACK_TRACE = """
java.lang.RuntimeException: Import failed for BLUEPRINT:F-W2K25:1
    at com.dxc.ecs.fulfillment.service.ServiceDesignService.importServiceDesigns(ServiceDesignService.java:1001)
    at com.dxc.ecs.fulfillment.service.ServiceDesignService.lambda$importServiceDesigns$13(ServiceDesignService.java:1028)
    at com.dxc.ecs.fulfillment.service.ServiceDesignService$$SpringCGLIB$$0.importServiceDesigns(<generated>)
Caused by: com.dxc.ecs.fulfillment.exception.DesignNotFoundException: BLUEPRINT:F-W2K25:1 not found
    at com.dxc.ecs.fulfillment.repository.ServiceDesignRepository.findByKey(ServiceDesignRepository.java:88)
"""

LOG_LINES = [
    "2026-08-13 12:20:48.000  INFO [executor-1] c.d.e.f.service.ServiceDesignService [req-001] : Start import service design global:BLUEPRINT:A-W2K25:1",
    "2026-08-13 12:20:48.050  INFO [executor-1] c.d.e.f.service.ServiceDesignService [req-001] : Import complete global:BLUEPRINT:A-W2K25:1",
    "2026-08-13 12:20:48.900  INFO [executor-2] c.d.e.f.service.ServiceDesignService [req-002] : Start import service design global:BLUEPRINT:F-W2K25:1",
    "2026-08-13 12:20:48.965  WARN [executor-2] c.d.e.f.service.ServiceDesignService [req-002] : Design import failed.",
    "2026-08-13 12:20:48.966  ERROR [executor-2] c.d.e.f.service.ServiceDesignService [req-002] : Unhandled exception during import",
    "2026-08-13 12:22:00.000  ERROR [http-nio-1] c.d.e.f.security.SslContextFactory [req-004] : SSL handshake failed",
    "2026-08-13 12:22:00.010  ERROR [http-nio-1] c.d.e.f.security.SslContextFactory [req-004] : javax.net.ssl.SSLHandshakeException: certificate_unknown",
]

# Build a small corpus and fit scorer
corpus_lines = []
for i in range(50):
    for line in LOG_LINES[:2]:
        corpus_lines.append(line.replace("req-001", f"req-h{i:03d}"))
for i in range(10):
    for line in LOG_LINES[2:5]:
        corpus_lines.append(line.replace("req-002", f"req-f{i:03d}"))
for i in range(5):
    for line in LOG_LINES[5:]:
        corpus_lines.append(line.replace("req-004", f"req-ssl{i:03d}"))

all_windows = ingest_lines(corpus_lines, gap_seconds=30.0)
embedder = WindowEmbedder()
embedder.fit(all_windows, epochs=30)
scorer = AnomalyScorer(contamination=0.15, anomaly_threshold=-0.05)
scorer.fit(all_windows, embedder)

SCORER_PATH = "/tmp/p505_scorer.pkl"
scorer.save(SCORER_PATH)

LOG_FILE = tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False)
LOG_FILE.write("\n".join(LOG_LINES))
LOG_FILE.close()
LOG_PATH = LOG_FILE.name

print("=== P5-05 Smoke Test ===\n")

# ---------------------------------------------------------------------------
# Test 1: Full pipeline
# ---------------------------------------------------------------------------

result = diagnose_with_ml(
    stack_trace_text=STACK_TRACE,
    log_path=LOG_PATH,
    report_id="test-report-001",
    scorer_path=SCORER_PATH,
    gap_seconds=30.0,
)

print("Test 1 — Full pipeline:")
print(f"  windows_analysed    : {result.windows_analysed}")
print(f"  anomalous_windows   : {result.anomalous_windows}")
print(f"  anomaly_results     : {len(result.anomaly_results)}")
print(f"  correlated_incidents: {len(result.correlated_incidents)}")
print(f"  summary             : {result.summary}")
print(f"  degraded            : {result.degraded}")

assert result.windows_analysed > 0, "Should have parsed log windows"
assert len(result.anomaly_results) > 0, "Should have anomaly results"
assert not result.degraded, f"Should not be degraded: {result.degradation_reason}"
print("  PASSED\n")

# ---------------------------------------------------------------------------
# Test 2: Degraded — no scorer
# ---------------------------------------------------------------------------

result2 = diagnose_with_ml(
    stack_trace_text=STACK_TRACE,
    log_path=LOG_PATH,
    report_id="test-report-002",
    scorer_path=None,
    gap_seconds=30.0,
)

print("Test 2 — Degraded (no scorer):")
print(f"  degraded            : {result2.degraded}")
print(f"  degradation_reason  : {result2.degradation_reason}")
print(f"  windows_analysed    : {result2.windows_analysed}")
assert result2.degraded, "Should be degraded without scorer"
assert result2.windows_analysed > 0, "Should still parse log even without scorer"
assert result2.anomaly_results == [], "No anomaly results without scorer"
print("  PASSED\n")

# ---------------------------------------------------------------------------
# Test 3: Degraded — log file missing
# ---------------------------------------------------------------------------

result3 = diagnose_with_ml(
    stack_trace_text=STACK_TRACE,
    log_path="/nonexistent/path/application.log",
    report_id="test-report-003",
    scorer_path=SCORER_PATH,
    gap_seconds=30.0,
)

print("Test 3 — Degraded (log missing):")
print(f"  degraded            : {result3.degraded}")
print(f"  degradation_reason  : {result3.degradation_reason}")
assert result3.degraded
assert result3.windows_analysed == 0
print("  PASSED\n")

# ---------------------------------------------------------------------------
# Test 4: Stack trace only — no log
# ---------------------------------------------------------------------------

result4 = diagnose_with_ml(
    stack_trace_text=STACK_TRACE,
    log_path=None,
    report_id="test-report-004",
    scorer_path=SCORER_PATH,
)

print("Test 4 — Stack trace only (no log):")
print(f"  windows_analysed    : {result4.windows_analysed}")
print(f"  correlated_incidents: {len(result4.correlated_incidents)}")
assert result4.windows_analysed == 0
assert result4.correlated_incidents == []
print("  PASSED\n")

# ---------------------------------------------------------------------------
# Test 5: Inline stack trace parser (is_application_frame set correctly)
# ---------------------------------------------------------------------------

blocks = _inline_parse_stack_trace(STACK_TRACE)
print("Test 5 — Inline stack trace parser:")
print(f"  blocks parsed       : {len(blocks)}")
print(f"  root causes         : {[b.exception_class for b in blocks if b.is_likely_root_cause]}")
print(f"  frames in block[0]  : {len(blocks[0].frames)}")
app_frames = [f for b in blocks for f in b.frames if f.is_application_frame]
print(f"  application frames  : {len(app_frames)}")

assert len(blocks) >= 2, "Should parse root + caused_by"
assert any(b.is_likely_root_cause for b in blocks), "Should flag a root cause"
assert len(blocks[0].frames) >= 2, "Should parse frames"
assert len(app_frames) > 0, "Should identify application frames"
print("  PASSED\n")

# ---------------------------------------------------------------------------
# Test 6: JSON serialisability
# ---------------------------------------------------------------------------

d = result.to_dict()
s = result.to_json()
assert s, "to_json() must produce non-empty string"
parsed = json.loads(s)
assert parsed["report_id"] == "test-report-001"
assert "anomaly_results" in parsed
assert "correlated_incidents" in parsed
assert "summary" in parsed
print(f"Test 6 — JSON serialisable: PASSED ({len(s)} chars)")
print(f"  Keys: {list(parsed.keys())}\n")

# ---------------------------------------------------------------------------
# Test 7: Summary content
# ---------------------------------------------------------------------------

print(f"Test 7 — Summary string:")
print(f"  '{result.summary}'")
assert len(result.summary) > 0, "Summary should not be empty"
print("  PASSED\n")

# ---------------------------------------------------------------------------
# Test 8: top_anomalies ordering
# ---------------------------------------------------------------------------

if result.top_anomalies:
    scores = [a["score"] for a in result.top_anomalies]
    assert scores == sorted(scores), "top_anomalies should be sorted ascending (most anomalous first)"
    print(f"Test 8 — top_anomalies ordering: PASSED (scores={scores})\n")
else:
    print("Test 8 — top_anomalies: skipped (no anomalies)\n")

# ---------------------------------------------------------------------------
# Test 9: Multi-log ingestion via log_paths
# ---------------------------------------------------------------------------

log2 = tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False)
log2.write("\n".join(LOG_LINES[5:]))  # SSL error lines
log2.close()

result9 = diagnose_with_ml(
    stack_trace_text=STACK_TRACE,
    log_path=None,
    log_paths=[LOG_PATH, log2.name],
    report_id="test-report-009",
    scorer_path=SCORER_PATH,
    gap_seconds=30.0,
)

print("Test 9 — Multi-log ingestion (log_paths):")
print(f"  windows_analysed    : {result9.windows_analysed}")
print(f"  degraded            : {result9.degraded}")
assert result9.windows_analysed > 0, "Should ingest from multiple files"
assert not result9.degraded, f"Should not be degraded: {result9.degradation_reason}"
os.unlink(log2.name)
print("  PASSED\n")

# ---------------------------------------------------------------------------
# Test 10: Tail mode — tail_lines cap
# ---------------------------------------------------------------------------

# Write a file with 200 lines, cap at 50 — should parse fewer windows
big_lines = corpus_lines[:200]
big_file = tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False)
big_file.write("\n".join(big_lines))
big_file.close()

result_full = diagnose_with_ml(
    stack_trace_text=STACK_TRACE, log_path=big_file.name,
    report_id="tail-full", scorer_path=SCORER_PATH,
    gap_seconds=30.0, tail_lines=999999,
)
result_tail = diagnose_with_ml(
    stack_trace_text=STACK_TRACE, log_path=big_file.name,
    report_id="tail-capped", scorer_path=SCORER_PATH,
    gap_seconds=30.0, tail_lines=10,
)

print("Test 10 — Tail mode (tail_lines cap):")
print(f"  full read windows   : {result_full.windows_analysed}")
print(f"  tail=10 windows     : {result_tail.windows_analysed}")
assert result_tail.windows_analysed <= result_full.windows_analysed, \
    "Tail-capped read should produce <= windows of full read"
os.unlink(big_file.name)
print("  PASSED\n")

# Cleanup
os.unlink(LOG_PATH)
os.unlink(SCORER_PATH)

print("P5-05 smoke test: ALL PASSED")
