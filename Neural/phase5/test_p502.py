"""
P5-02 smoke test.

Builds a synthetic corpus of LogWindows that mimics the fulfillment service
log format, fits the WindowEmbedder, then verifies:
  1. Output shape is (102,) per window
  2. Two "design import failed" windows are more similar to each other
     than to a healthy INFO-only window
  3. Save/load round-trip preserves embeddings exactly
"""

import sys
sys.path.insert(0, ".")

import numpy as np
from phase5.log_intelligence.ingestion import ingest_lines
from phase5.log_intelligence.embed_window import WindowEmbedder

# ---------------------------------------------------------------------------
# Synthetic log corpus
# ---------------------------------------------------------------------------

HEALTHY = [
    "2026-08-13 12:20:48.000  INFO [executor-1] c.d.e.f.service.ServiceDesignService [req-001] : Start import service design global:BLUEPRINT:A-W2K25:1",
    "2026-08-13 12:20:48.050  INFO [executor-1] c.d.e.f.service.ServiceDesignService [req-001] : Import complete global:BLUEPRINT:A-W2K25:1",
    "2026-08-13 12:20:48.100  INFO [executor-1] c.d.e.f.service.ServiceDesignService [req-001] : Persisted 12 service designs",
]

FAILED_A = [
    "2026-08-13 12:20:48.900  INFO [executor-2] c.d.e.f.service.ServiceDesignService [req-002] : Start import service design global:BLUEPRINT:F-W2K25:1",
    "2026-08-13 12:20:48.965  WARN [executor-2] c.d.e.f.service.ServiceDesignService [req-002] : Design import failed.",
    "2026-08-13 12:20:48.965  INFO [executor-2] c.d.e.f.service.ServiceDesignService [req-002] :        at com.dxc.ecs.fulfillment.service.ServiceDesignService.importServiceDesigns(ServiceDesignService.java:1001) ~[classes/:1.6.0-SNAPSHOT]",
    "2026-08-13 12:20:48.966  ERROR [executor-2] c.d.e.f.service.ServiceDesignService [req-002] : Unhandled exception during import",
]

FAILED_B = [
    "2026-08-13 12:21:10.000  INFO [executor-3] c.d.e.f.service.ServiceDesignService [req-003] : Start import service design global:BLUEPRINT:S-W2K25:1",
    "2026-08-13 12:21:10.040  WARN [executor-3] c.d.e.f.service.ServiceDesignService [req-003] : Design import failed.",
    "2026-08-13 12:21:10.041  ERROR [executor-3] c.d.e.f.service.ServiceDesignService [req-003] : Retry limit exceeded for BLUEPRINT:S-W2K25:1",
]

SSL_ERROR = [
    "2026-08-13 12:22:00.000  ERROR [http-nio-1] c.d.e.f.security.SslContextFactory [req-004] : SSL handshake failed",
    "2026-08-13 12:22:00.010  ERROR [http-nio-1] c.d.e.f.security.SslContextFactory [req-004] : javax.net.ssl.SSLHandshakeException: certificate_unknown",
    "2026-08-13 12:22:00.011  WARN  [http-nio-1] c.d.e.f.security.SslContextFactory [req-004] : Falling back to insecure connection",
]

# Build a larger corpus for fitting (repeat patterns with variation)
corpus_lines = []
for i in range(20):
    for line in HEALTHY:
        corpus_lines.append(line.replace("req-001", f"req-h{i:03d}"))
for i in range(20):
    for line in FAILED_A:
        corpus_lines.append(line.replace("req-002", f"req-fa{i:03d}"))
for i in range(20):
    for line in FAILED_B:
        corpus_lines.append(line.replace("req-003", f"req-fb{i:03d}"))
for i in range(10):
    for line in SSL_ERROR:
        corpus_lines.append(line.replace("req-004", f"req-ssl{i:03d}"))

all_windows = ingest_lines(corpus_lines, gap_seconds=30.0)
print(f"Corpus: {len(corpus_lines)} lines → {len(all_windows)} windows")

# ---------------------------------------------------------------------------
# Fit
# ---------------------------------------------------------------------------

we = WindowEmbedder()
we.fit(all_windows, epochs=40)
print(f"Fitted. Total embedding dim: {WindowEmbedder.TOTAL_DIM}")

# ---------------------------------------------------------------------------
# Embed the 4 representative windows
# ---------------------------------------------------------------------------

w_healthy  = ingest_lines(HEALTHY,  gap_seconds=30.0)[0]
w_failed_a = ingest_lines(FAILED_A, gap_seconds=30.0)[0]
w_failed_b = ingest_lines(FAILED_B, gap_seconds=30.0)[0]
w_ssl      = ingest_lines(SSL_ERROR, gap_seconds=30.0)[0]

v_healthy  = we.embed(w_healthy)
v_failed_a = we.embed(w_failed_a)
v_failed_b = we.embed(w_failed_b)
v_ssl      = we.embed(w_ssl)

assert v_healthy.shape  == (102,), f"Bad shape: {v_healthy.shape}"
assert v_failed_a.shape == (102,), f"Bad shape: {v_failed_a.shape}"
print(f"Shape check: PASSED — all (102,)")

# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------

def cosine(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

sim_fail_fail = cosine(v_failed_a, v_failed_b)
sim_fail_heal = cosine(v_failed_a, v_healthy)
sim_fail_ssl  = cosine(v_failed_a, v_ssl)

print(f"\nCosine similarities:")
print(f"  failed_A ↔ failed_B  : {sim_fail_fail:.4f}  (should be highest)")
print(f"  failed_A ↔ healthy   : {sim_fail_heal:.4f}")
print(f"  failed_A ↔ ssl_error : {sim_fail_ssl:.4f}")

assert sim_fail_fail > sim_fail_heal, "FAIL: similar errors should be closer than healthy"
print(f"\nSimilarity ordering: PASSED")

# ---------------------------------------------------------------------------
# Scalar features sanity check
# ---------------------------------------------------------------------------

print(f"\nScalar features (last 6 dims):")
print(f"  healthy  : {v_healthy[-6:]}")
print(f"  failed_a : {v_failed_a[-6:]}")
print(f"  ssl_err  : {v_ssl[-6:]}")

# ---------------------------------------------------------------------------
# Batch embed
# ---------------------------------------------------------------------------

batch = [w_healthy, w_failed_a, w_failed_b, w_ssl]
mat = we.embed_batch(batch)
assert mat.shape == (4, 102), f"Bad batch shape: {mat.shape}"
print(f"\nBatch embed shape: {mat.shape}  PASSED")

# ---------------------------------------------------------------------------
# Save / load round-trip
# ---------------------------------------------------------------------------

we.save("/tmp/window_embedder_test.pkl")
we2 = WindowEmbedder.load("/tmp/window_embedder_test.pkl")
v2 = we2.embed(w_failed_a)
assert np.allclose(v_failed_a, v2, atol=1e-5), "Save/load mismatch"
print(f"Save/load round-trip: PASSED")

print("\nP5-02 smoke test: ALL PASSED")
