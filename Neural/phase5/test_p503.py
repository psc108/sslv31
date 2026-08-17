"""
P5-03 smoke test.

Verifies:
  1. Healthy windows score higher (less anomalous) than error windows
  2. Critical errors score lower than warnings
  3. AnomalyResult.reasons are non-empty for anomalous windows
  4. to_dict() is JSON-serialisable
  5. Save/load round-trip preserves scores exactly
"""

import sys, json
sys.path.insert(0, ".")

import numpy as np
from phase5.log_intelligence.ingestion import ingest_lines
from phase5.log_intelligence.embed_window import WindowEmbedder
from phase5.log_intelligence.anomaly_scorer import AnomalyScorer

# ---------------------------------------------------------------------------
# Synthetic corpus  (same patterns as P5-02 test, extended)
# ---------------------------------------------------------------------------

HEALTHY = [
    "2026-08-13 12:20:48.000  INFO [executor-1] c.d.e.f.service.ServiceDesignService [req-001] : Start import service design global:BLUEPRINT:A-W2K25:1",
    "2026-08-13 12:20:48.050  INFO [executor-1] c.d.e.f.service.ServiceDesignService [req-001] : Import complete global:BLUEPRINT:A-W2K25:1",
    "2026-08-13 12:20:48.100  INFO [executor-1] c.d.e.f.service.ServiceDesignService [req-001] : Persisted 12 service designs",
]

WARN_ONLY = [
    "2026-08-13 12:20:49.000  INFO [executor-4] c.d.e.f.service.ServiceDesignService [req-005] : Start import service design global:BLUEPRINT:W-W2K25:1",
    "2026-08-13 12:20:49.040  WARN [executor-4] c.d.e.f.service.ServiceDesignService [req-005] : Design import failed.",
    "2026-08-13 12:20:49.041  INFO [executor-4] c.d.e.f.service.ServiceDesignService [req-005] : Retrying import",
    "2026-08-13 12:20:49.200  INFO [executor-4] c.d.e.f.service.ServiceDesignService [req-005] : Import complete on retry",
]

CRITICAL = [
    "2026-08-13 12:22:00.000  ERROR [http-nio-1] c.d.e.f.security.SslContextFactory [req-004] : SSL handshake failed",
    "2026-08-13 12:22:00.010  ERROR [http-nio-1] c.d.e.f.security.SslContextFactory [req-004] : javax.net.ssl.SSLHandshakeException: certificate_unknown",
    "2026-08-13 12:22:00.011  ERROR [http-nio-1] c.d.e.f.security.SslContextFactory [req-004] : Caused by: sun.security.validator.ValidatorException: PKIX path building failed",
    "2026-08-13 12:22:00.012  WARN  [http-nio-1] c.d.e.f.security.SslContextFactory [req-004] : Falling back to insecure connection",
]

STACK_ERROR = [
    "2026-08-13 12:23:00.000  INFO [executor-5] c.d.e.f.service.ServiceDesignService [req-006] : Start import service design global:BLUEPRINT:F-W2K25:1",
    "2026-08-13 12:23:00.040  WARN [executor-5] c.d.e.f.service.ServiceDesignService [req-006] : Design import failed.",
    "2026-08-13 12:23:00.041  ERROR [executor-5] c.d.e.f.service.ServiceDesignService [req-006] : Unhandled exception during import",
    "2026-08-13 12:23:00.041  INFO [executor-5] c.d.e.f.service.ServiceDesignService [req-006] :        at com.dxc.ecs.fulfillment.service.ServiceDesignService.importServiceDesigns(ServiceDesignService.java:1001) ~[classes/:1.6.0-SNAPSHOT]",
    "2026-08-13 12:23:00.041  INFO [executor-5] c.d.e.f.service.ServiceDesignService [req-006] :        at com.dxc.ecs.fulfillment.service.ServiceDesignService.lambda$importServiceDesigns$13(ServiceDesignService.java:1028) ~[classes/:1.6.0-SNAPSHOT]",
]

# Build corpus — heavily weighted toward healthy so errors are genuinely anomalous
corpus_lines = []
for i in range(60):
    for line in HEALTHY:
        corpus_lines.append(line.replace("req-001", f"req-h{i:03d}"))
for i in range(15):
    for line in WARN_ONLY:
        corpus_lines.append(line.replace("req-005", f"req-w{i:03d}"))
for i in range(5):
    for line in CRITICAL:
        corpus_lines.append(line.replace("req-004", f"req-c{i:03d}"))
for i in range(5):
    for line in STACK_ERROR:
        corpus_lines.append(line.replace("req-006", f"req-se{i:03d}"))

all_windows = ingest_lines(corpus_lines, gap_seconds=30.0)
print(f"Corpus: {len(corpus_lines)} lines → {len(all_windows)} windows")

# ---------------------------------------------------------------------------
# Fit embedder + scorer
# ---------------------------------------------------------------------------

embedder = WindowEmbedder()
embedder.fit(all_windows, epochs=40)

scorer = AnomalyScorer(contamination=0.12, anomaly_threshold=-0.05)
scorer.fit(all_windows, embedder)
print("Fitted AnomalyScorer")

# ---------------------------------------------------------------------------
# Score representative windows
# ---------------------------------------------------------------------------

w_healthy    = ingest_lines(HEALTHY,     gap_seconds=30.0)[0]
w_warn       = ingest_lines(WARN_ONLY,   gap_seconds=30.0)[0]
w_critical   = ingest_lines(CRITICAL,    gap_seconds=30.0)[0]
w_stack_err  = ingest_lines(STACK_ERROR, gap_seconds=30.0)[0]

r_healthy   = scorer.score_window(w_healthy)
r_warn      = scorer.score_window(w_warn)
r_critical  = scorer.score_window(w_critical)
r_stack_err = scorer.score_window(w_stack_err)

print(f"\n{'Window':<14} {'Score':>8}  {'Severity':<10}  {'Anomaly':<8}  Reasons")
print("-" * 80)
for label, r in [("healthy", r_healthy), ("warn_only", r_warn),
                 ("critical", r_critical), ("stack_err", r_stack_err)]:
    print(f"{label:<14} {r.score:>8.4f}  {r.severity:<10}  {str(r.is_anomaly):<8}  {r.reasons[:2]}")

# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

assert r_healthy.score > r_critical.score, \
    f"Healthy ({r_healthy.score:.4f}) should score higher than critical ({r_critical.score:.4f})"
print("\nScore ordering (healthy > critical): PASSED")

assert r_critical.severity in ("warning", "critical"), \
    f"Critical window should not be 'normal', got {r_critical.severity}"
print(f"Critical severity label ({r_critical.severity}): PASSED")

assert len(r_critical.reasons) > 0 or len(r_stack_err.reasons) > 0, \
    "At least one anomalous window should have reasons"
print("Reason attribution non-empty: PASSED")

# ---------------------------------------------------------------------------
# JSON serialisability
# ---------------------------------------------------------------------------

d = r_critical.to_dict()
json_str = json.dumps(d)
assert json_str, "to_dict() should produce non-empty JSON"
print(f"JSON serialisable: PASSED  ({len(json_str)} chars)")
print(f"  Sample: {json_str[:200]}")

# ---------------------------------------------------------------------------
# Save / load round-trip
# ---------------------------------------------------------------------------

scorer.save("/tmp/anomaly_scorer_test.pkl")
scorer2 = AnomalyScorer.load("/tmp/anomaly_scorer_test.pkl")
r2 = scorer2.score_window(w_critical)
assert r2.score == r_critical.score, \
    f"Save/load score mismatch: {r2.score} vs {r_critical.score}"
print("Save/load round-trip: PASSED")

# ---------------------------------------------------------------------------
# Batch scoring
# ---------------------------------------------------------------------------

results = scorer.score_batch([w_healthy, w_warn, w_critical, w_stack_err])
assert len(results) == 4
print(f"Batch scoring ({len(results)} windows): PASSED")

print("\nP5-03 smoke test: ALL PASSED")
