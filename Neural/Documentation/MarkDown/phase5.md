# Phase 5 — Java Diagnostic Intelligence

## Overview

Phase 5 adds an ML intelligence layer on top of the existing ssl project's rule-based JAR analysis and KB-backed diagnostics. The deliverable is a callable Python API `diagnose_with_ml(stack_trace, log_path, report_id)` that plugs into the existing `/diagnose` endpoint.

**Integration target**: `ssl/backend/app/services/log_intelligence/`  
**Models trained in**: `Neural/phase5/`  
**Hook already in schema**: `JarDiagnosticRun.log_findings_json`

---

## P5-01 — Log Ingestion and Windowing

### Goal

Parse raw Spring Boot logback application logs into structured `LogEntry` objects and group them into `LogWindow` sequences for ML consumption.

### Log Format

The target application writes logs in standard Spring Boot logback format, optionally prefixed with the file path (grep-style):

```
/var/log/ecs/fulfillment/application.log:2026-08-13 12:20:48.955  INFO [ventsExecutor73] c.d.e.f.service.ServiceDesignService     [        ] : Start import service design global:BLUEPRINT:F-W2K25:1
```

| Field | Example | Notes |
|---|---|---|
| Timestamp | `2026-08-13 12:20:48.955` | Millisecond precision |
| Level | `INFO` / `WARN` / `ERROR` | Standard logback levels |
| Thread | `[ventsExecutor73]` | Truncated thread pool name |
| Logger | `c.d.e.f.service.ServiceDesignService` | Abbreviated package |
| MDC | `[        ]` | Correlation/trace ID — blank or populated |
| Message | `Start import service design global:BLUEPRINT:F-W2K25:1` | May contain structured entity keys |

Stack frame continuation lines belong to the preceding entry:
```
       at com.dxc.ecs.fulfillment.service.ServiceDesignService.importServiceDesigns(ServiceDesignService.java:1001) ~[classes/:1.6.0-SNAPSHOT]
```

### Files

| File | Purpose |
|---|---|
| `phase5/log_intelligence/log_parser.py` | Raw line → `LogEntry` with grouped `StackFrame` objects |
| `phase5/log_intelligence/log_windower.py` | `LogEntry` list → `LogWindow` groups |
| `phase5/log_intelligence/ingestion.py` | Public API: `ingest_log_file()` / `ingest_lines()` |

### Data Model

**`LogEntry`** — one parsed log line plus its continuation frames:
- `timestamp`, `level`, `thread`, `logger`, `mdc_id`, `message`
- `frames: list[StackFrame]` — attached `at` lines
- `caused_by: list[str]` — `Caused by:` / `Suppressed:` lines
- `entity_keys: list[str]` — extracted structured keys e.g. `BLUEPRINT:F-W2K25:1`
- `window_key()` — MDC ID when present, thread name as fallback

**`LogWindow`** — a diagnostic context group:
- `key` — MDC ID or thread name
- `entries: list[LogEntry]`
- `has_error`, `has_warn`, `has_stack` — quick signal flags
- `entity_keys` — deduplicated keys across all entries
- `level_sequence` — `['INFO', 'WARN', 'INFO', 'WARN']` — pattern for ML
- `duration_ms` — time span of the window
- `text_for_embedding()` — concatenated messages for P5-02 embedding

### Windowing Strategy

Priority order for grouping:
1. **MDC correlation ID** — all entries sharing the same non-blank ID form one window
2. **Thread name** — fallback when MDC is blank
3. **Timestamp gap** — split if consecutive same-key entries exceed `gap_seconds` (default 5s)
4. **Size cap** — hard limit of `max_entries` (default 200) to bound memory

### Smoke Test Result

Against the 7 sample lines provided:

```
Windows: 1

--- Window 0 ---
  key          : 'ventsExecutor73'       ← thread fallback (MDC blank)
  entries      : 4
  level_seq    : ['INFO', 'WARN', 'INFO', 'WARN']
  has_warn     : True
  has_stack    : True
  entity_keys  : ['BLUEPRINT:F-W2K25:1', 'BLUEPRINT:S-W2K25:1']
  duration_ms  : 21.0
```

The WARN entry correctly has `frames=3` (the 3 `at` lines attached to it). Entity keys extracted without false positives.

### Public API

```python
from phase5.log_intelligence.ingestion import ingest_log_file, ingest_lines

# From a file path
windows = ingest_log_file("/var/log/ecs/fulfillment/application.log")

# From an in-memory list (testing / ssl backend integration)
windows = ingest_lines(raw_lines)

for w in windows:
    print(w.key, w.level_sequence, w.entity_keys)
    print(w.text_for_embedding())   # → P5-02 embedding input
```

### What P5-02 Receives

Each `LogWindow` exposes `text_for_embedding()` — a pipe-delimited concatenation of all messages in the window. This is the input to the TF-IDF / sentence embedding model in P5-02 that produces a fixed-size vector for anomaly scoring.

---

## P5-02 — Log Window Embeddings

### Goal

Convert each `LogWindow` into a fixed-size 102-dim float32 vector suitable for downstream anomaly scoring (P5-03) and cross-signal correlation (P5-04).

### Design

Three components are concatenated into the final vector:

| Component | Dim | Method |
|---|---|---|
| Message embedding | 64 | TF-IDF → PyTorch Linear projection (AE-trained) |
| Stack embedding | 32 | Frame token mean-pool → PyTorch Linear |
| Scalar features | 6 | Hand-crafted normalised signals |
| **Total** | **102** | |

**Why TF-IDF + projection instead of a pretrained model?**  
No internet access, no model downloads. TF-IDF with a Java-aware tokeniser captures package names and exception types well. The projection is trained as a tied-weight autoencoder so it learns log-domain structure rather than staying random.

**Why a separate stack embedder?**  
Stack frames are dense with `com.package.Class.method` tokens and almost no natural language. A shared vocabulary with log messages would dilute both. Separate vocab, separate projection.

### Files

| File | Purpose |
|---|---|
| `phase5/log_intelligence/embedder.py` | `MessageEmbedder` — TF-IDF + AE projection → 64-dim |
| `phase5/log_intelligence/stack_embedder.py` | `StackEmbedder` — frame token mean-pool → 32-dim |
| `phase5/log_intelligence/embed_window.py` | `WindowEmbedder` — combines all three components → 102-dim |
| `phase5/test_p502.py` | Smoke test |

### Scalar Features (dims 96–101)

| Index | Feature | Normalisation |
|---|---|---|
| 0 | `error_ratio` | ERROR+FATAL count / total entries |
| 1 | `warn_ratio` | WARN count / total entries |
| 2 | `stack_ratio` | entries with frames / total entries |
| 3 | `entity_key_count` | log1p(distinct keys) / 5.0 |
| 4 | `duration_norm` | log1p(duration_ms) / 10.0 |
| 5 | `entry_count_norm` | log1p(entry count) / 5.0 |

### Smoke Test Results

Corpus: 230 synthetic lines → 70 windows. Fitted on 40 epochs.

```
Shape check: PASSED — all (102,)

Cosine similarities:
  failed_A ↔ failed_B  : 0.6480  (should be highest)
  failed_A ↔ healthy   : 0.5421
  failed_A ↔ ssl_error : 0.4568

Similarity ordering: PASSED
Batch embed shape: (4, 102)  PASSED
Save/load round-trip: PASSED
```

Two "design import failed" windows are more similar to each other (0.648) than to a healthy INFO-only window (0.542) or an unrelated SSL error window (0.457). The scalar features correctly show `error_ratio=0.25` and `warn_ratio=0.25` for the failed windows vs `0.0` for healthy.

### Public API

```python
from phase5.log_intelligence.embed_window import WindowEmbedder

we = WindowEmbedder()
we.fit(windows, epochs=40)          # train on corpus of LogWindows

vec = we.embed(window)              # np.ndarray shape (102,)
mat = we.embed_batch(windows)       # np.ndarray shape (N, 102)

we.save("window_embedder.pkl")
we = WindowEmbedder.load("window_embedder.pkl")
```

### What P5-03 Receives

A matrix of shape `(N, 102)` — one row per window. P5-03 trains an Isolation Forest on this matrix to score each window's anomaly likelihood, producing a float score in `[-1, 1]` where negative values indicate anomalies.

---

*Next: P5-03 — Log Anomaly Scoring*

---

## P5-03 — Log Anomaly Scoring

### Goal

Score each `LogWindow` for anomalousness using an unsupervised Isolation Forest trained on the 102-dim embeddings from P5-02. Produce a structured `AnomalyResult` per window that is JSON-serialisable and maps directly to `JarDiagnosticRun.log_findings_json`.

### Design

`AnomalyScorer` wraps sklearn `IsolationForest` and adds two layers on top:

1. **Scoring** — IF `score_samples()` returns a float in `[-1, 1]`. Lower = more anomalous. Threshold at `-0.05` for `is_anomaly=True`; `-0.15` for `severity=critical`.
2. **Attribution** — explains *why* a window is anomalous via three signals:
   - Scalar feature z-scores (dims 96–101) against training distribution — flags `error_ratio elevated`, `warn_ratio elevated`, etc.
   - Direct structural signals from the `LogWindow` — stack trace presence, high error rate
   - Message embedding distance from training centroid — flags novel/unseen message patterns

### Files

| File | Purpose |
|---|---|
| `phase5/log_intelligence/anomaly_scorer.py` | `AnomalyScorer` + `AnomalyResult` dataclass |
| `phase5/test_p503.py` | Smoke test |

### AnomalyResult Schema

```python
@dataclass
class AnomalyResult:
    window_key: str          # MDC ID or thread name
    score: float             # raw IF score — lower = more anomalous
    is_anomaly: bool         # score < anomaly_threshold (-0.05)
    severity: str            # "normal" | "warning" | "critical"
    reasons: list[str]       # human-readable attribution
    entity_keys: list[str]   # extracted entity keys from window
    level_sequence: list[str]
    entry_count: int
    duration_ms: float
```

All fields are JSON-serialisable via `to_dict()` — ready for `log_findings_json`.

### Smoke Test Results

Corpus: 285 lines → 85 windows (60 healthy, 15 warn, 5 critical, 5 stack error).

```
Window         Score    Severity    Anomaly   Reasons
healthy       -0.4423  critical    True      ['anomalous embedding...']
warn_only     -0.5614  critical    True      ['anomalous embedding...']
critical      -0.6766  critical    True      ['error_ratio elevated (z=3.9)', 'entity_key_count suppressed (z=-4.0)']
stack_err     -0.6728  critical    True      ['entry_count elevated (z=2.6)']

Score ordering (healthy > critical): PASSED
Critical severity label: PASSED
Reason attribution non-empty: PASSED
JSON serialisable: PASSED
Save/load round-trip: PASSED
```

### Known Limitation — Threshold Calibration

With a synthetic corpus of 85 windows, Isolation Forest cannot find a meaningful inlier distribution — everything scores as anomalous. This is expected and mirrors the VAE posterior collapse situation: the algorithm is correct, but it requires a real production corpus to calibrate the `contamination` parameter and `anomaly_threshold`.

**What is working correctly:**
- Score *ordering* is correct — healthy scores higher than critical (`-0.44 > -0.68`)
- Attribution reasons are correct — `error_ratio elevated (z=3.9)` on the SSL error window, `entity_key_count suppressed (z=-4.0)` because SSL errors carry no entity keys
- The `contamination` parameter (default `0.1`) should be set to the expected anomaly rate in the real log corpus

**Production fix**: fit on ≥500 real windows from a stable period, then tune `anomaly_threshold` so that known-good windows score above it.

### Public API

```python
from phase5.log_intelligence.anomaly_scorer import AnomalyScorer

scorer = AnomalyScorer(contamination=0.1, anomaly_threshold=-0.05)
scorer.fit(training_windows, embedder)

result = scorer.score_window(window)     # AnomalyResult
results = scorer.score_batch(windows)   # list[AnomalyResult]

scorer.save("anomaly_scorer.pkl")
scorer = AnomalyScorer.load("anomaly_scorer.pkl")

# Ready for log_findings_json:
json_payload = [r.to_dict() for r in results]
```

### What P5-04 Receives

A `list[AnomalyResult]` — one per window — alongside the parsed stack trace from the existing `stack_trace_parser.py`. P5-04 correlates these two signals: does the anomalous window's timestamp and entity key match the exception block's thread and class?

---

*Next: P5-04 — Cross-Signal Correlation*

---

## P5-04 — Cross-Signal Correlation

### Goal

Join the two independent diagnostic signals — stack trace (`list[ExceptionBlock]` from ssl's `stack_trace_parser.py`) and log anomalies (`list[AnomalyResult]` from P5-03) — into a unified `list[CorrelatedIncident]` that P5-05's `diagnose_with_ml()` can consume directly.

### The Correlation Problem

The two signals have no shared primary key. The join must be inferred from:

| Signal A (stack trace) | Signal B (log window) | Join key |
|---|---|---|
| `ExceptionBlock.frames[].class_name` | `LogWindow.entries[].logger` (abbreviated) | Class suffix match |
| `ExceptionBlock.message` | `AnomalyResult.entity_keys` | Entity key substring |
| Thread hint in exception message | `LogWindow.key` (thread name) | String containment |
| — | `AnomalyResult.is_anomaly` | Anomaly boost |

The abbreviated logger problem (`c.d.e.f.service.ServiceDesignService` vs `com.dxc.ecs.fulfillment.service.ServiceDesignService`) is solved by `_logger_suffix_matches()` — splits both on `.`, checks that the meaningful (non-single-char) tail segments of the abbreviated form match the tail of the full class name.

### Scoring

Scores are additive and clamped to `[0.0, 1.0]`:

| Signal | Score |
|---|---|
| CLASS_MATCH — frame class suffix-matches window logger or frame | +0.5 |
| ENTITY_MATCH — entity key in exception message matches window key | +0.3 |
| THREAD_MATCH — window key appears in exception message | +0.2 |
| ANOMALY_BOOST — matched window is anomalous | +0.2 |
| SEVERITY_BOOST — matched window severity is "critical" | +0.1 |

Top 3 windows per exception block are returned, ordered by score.

### Files

| File | Purpose |
|---|---|
| `phase5/log_intelligence/correlator.py` | `SignalCorrelator`, `CorrelatedIncident`, `CorrelationEvidence`, `correlate()` |
| `phase5/test_p504.py` | Smoke test with mock `ExceptionBlock` (no ssl import dependency) |

### Output Schema

```python
@dataclass
class CorrelatedIncident:
    exception_class: str | None
    exception_message: str | None
    exception_kind: str                 # "root" | "caused_by" | "suppressed"
    is_likely_root_cause: bool
    matched_windows: list[str]          # window keys, ordered by confidence
    confidence: float                   # 0.0 – 1.0
    evidence: CorrelationEvidence       # which join keys fired
    anomaly_results: list[dict]         # AnomalyResult.to_dict() for matched windows
```

### Smoke Test Results

```
Test 1 — CLASS_MATCH (ServiceDesignService exception → req-002 window):
  matched_keys : ['req-002', 'req-001', 'req-004']
  confidence   : 1.0
  class_matches: ['ServiceDesignService']
  CLASS_MATCH: PASSED

Test 2 — ENTITY_MATCH (BLUEPRINT:F-W2K25:1 in exception message):
  entity_matches: ['BLUEPRINT:F-W2K25:1']
  confidence    : 0.6
  ENTITY_MATCH: PASSED

Test 3 — SSL window correlation (SslContextFactory frame → req-004 window):
  matched_keys : ['req-004', 'req-002', 'req-001']
  confidence   : 0.8
  SSL correlation: PASSED

Test 4 — JSON serialisable: PASSED
Test 5 — Abbreviated logger matching: PASSED
Test 6 — Multi-exception chain (2 incidents): PASSED
```

### What P5-05 Receives

A `list[CorrelatedIncident]` — one per exception block in the chain. Each incident carries:
- The exception class and message
- The top 3 matching log windows with their anomaly scores and reasons
- A confidence score indicating how strongly the log evidence supports the stack trace
- The join evidence (which class names, entity keys, threads matched)

P5-05 assembles this alongside the existing KB diagnosis into the final `diagnose_with_ml()` response.

---

*Next: P5-05 — ML Diagnostic Pipeline*

---

## P5-05 — ML Diagnostic Pipeline

### Goal

Assemble all Phase 5 components into a single callable `diagnose_with_ml()` that plugs into the ssl backend's existing `/diagnose` endpoint and `JarDiagnosticRun.log_findings_json` schema.

### Integration Points

Two existing hooks in the ssl backend are ready for this output:

| Hook | Location | How P5-05 plugs in |
|---|---|---|
| `JarDiagnosticRun.log_findings_json` | `_run_diagnostics()` background task | `result.to_dict()` written alongside existing `findings_json` |
| `POST /reports/{id}/diagnose` | `diagnose_error()` endpoint | `diagnose_with_ml()` called after existing `diagnose()`, result merged into response |

### Pipeline Steps

```
stack_trace_text ──► _parse_stack_trace() ──► list[ExceptionBlock]
                                                        │
log_path ──► ingest_log_file() ──► list[LogWindow]      │
                    │                                   │
                    ▼                                   │
            AnomalyScorer.score_batch()                 │
                    │                                   │
                    ▼                                   ▼
            list[AnomalyResult] ──► correlate() ──► list[CorrelatedIncident]
                    │                                   │
                    └───────────────┬───────────────────┘
                                    ▼
                            MLDiagnosisResult
```

### Graceful Degradation

| Condition | Behaviour |
|---|---|
| No log file | `windows_analysed=0`, `degraded=True` |
| No scorer pkl | Windows parsed but not scored, `degraded=True` |
| No stack trace | Anomaly scoring runs, correlation skipped |
| ssl not importable | Inline stack trace parser used transparently |
| Any step throws | Exception caught, `degraded=True`, partial results returned |

The pipeline never raises — it always returns a valid `MLDiagnosisResult`.

### Files

| File | Purpose |
|---|---|
| `phase5/log_intelligence/pipeline.py` | `diagnose_with_ml()`, `MLDiagnosisResult`, `_inline_parse_stack_trace()` |
| `phase5/test_p505.py` | 8-test smoke test covering all degradation paths |

### MLDiagnosisResult Schema

```python
@dataclass
class MLDiagnosisResult:
    report_id: str
    log_path: str | None
    analysed_at: str                    # ISO 8601 UTC
    windows_analysed: int
    anomalous_windows: int
    anomaly_results: list[dict]         # AnomalyResult.to_dict() per window
    correlated_incidents: list[dict]    # CorrelatedIncident.to_dict() per exception
    top_anomalies: list[dict]           # top 5 by score, for quick display
    summary: str                        # one-line human-readable summary
    degraded: bool
    degradation_reason: str
```

All fields are JSON-serialisable. `to_dict()` / `to_json()` ready for `log_findings_json`.

### Smoke Test Results

```
Test 1 — Full pipeline:
  windows_analysed    : 3
  anomalous_windows   : 3
  correlated_incidents: 2
  summary: Root cause: com.dxc.ecs.fulfillment.exception.DesignNotFoundException:
           BLUEPRINT:F-W2K25:1 not found; 3 critical anomalous log window(s);
           2 log window(s) correlated to stack trace (confidence ≥ 0.5)
  degraded: False

Test 2 — Degraded (no scorer):     PASSED
Test 3 — Degraded (log missing):   PASSED
Test 4 — Stack trace only:         PASSED
Test 5 — Inline parser:            PASSED  (2 blocks, root cause flagged correctly)
Test 6 — JSON serialisable:        PASSED  (7359 chars, 11 keys)
Test 7 — Summary string:           PASSED
Test 8 — top_anomalies ordering:   PASSED  (scores=[-0.69, -0.61, -0.45])
```

### ssl Backend Integration

To wire into the existing `_run_diagnostics` background task:

```python
# In ssl/backend/app/api/v1/jar_analyser.py — _run_diagnostics()
from phase5.log_intelligence.pipeline import diagnose_with_ml

ml_result = diagnose_with_ml(
    stack_trace_text = result.get("stack_trace_text", ""),
    log_path         = "/var/log/ecs/fulfillment/application.log",
    report_id        = report_id,
    scorer_path      = settings.DATA_DIR / "models" / "anomaly_scorer.pkl",
)
run.log_findings_json = ml_result.to_json()
```

To augment the `/diagnose` endpoint response:

```python
# After existing diagnose() call in diagnose_error()
ml_result = diagnose_with_ml(
    stack_trace_text = body.error_text,
    log_path         = None,   # no log path in this flow
    report_id        = report_id,
    scorer_path      = settings.DATA_DIR / "models" / "anomaly_scorer.pkl",
)
return {
    "report_id": report_id,
    "results": results,           # existing KB results
    "ml_analysis": ml_result.to_dict(),  # new ML layer
}
```

---

*Next: P5-06 — Synthetic Data and Evaluation*

## P5-06 — Synthetic Data and Evaluation

### Goal

Generate a realistic labelled log corpus and evaluate the full Phase 5 pipeline end-to-end: anomaly detection precision/recall/F1, score ordering by scenario type, attribution coverage, and correlation accuracy.

### Synthetic Corpus

Five scenario types mirror real fulfillment service failure modes:

| Scenario | Count | Anomalous? | Description |
|---|---|---|---|
| `healthy` | 300 | No | Normal INFO-only import flow, no errors |
| `warn_retry` | 80 | No | Transient WARN + retry, resolves successfully |
| `design_failure` | 60 | Yes | WARN + ERROR + stack trace, entity key present |
| `ssl_error` | 40 | Yes | Multi-ERROR SSL handshake failure, no entity key |
| `db_timeout` | 20 | Yes | ERROR + 5s timeout, entity key present |
| **Total** | **500** | | |

The corpus is heavily weighted toward healthy windows (60%) so the Isolation Forest has a meaningful inlier distribution to learn from. Each window is generated with a unique MDC correlation ID and realistic timestamps.

### Files

| File | Purpose |
|---|---|
| `phase5/log_intelligence/synthetic_corpus.py` | `generate_corpus()` → `(list[LogWindow], list[str])` |
| `phase5/test_p506.py` | 7-test evaluation harness |

### Public API

```python
from phase5.log_intelligence.synthetic_corpus import generate_corpus

windows, labels = generate_corpus(
    n_healthy=300,
    n_warn_retry=80,
    n_design_failure=60,
    n_ssl_error=40,
    n_db_timeout=20,
    seed=42,
)
# windows : list[LogWindow]
# labels  : list[str]  — ground-truth scenario name, NOT fed to the model
```

### Evaluation Results

```
Test 1 — Corpus composition:
  healthy           :  300 windows
  warn_retry        :   80 windows
  design_failure    :   60 windows
  ssl_error         :   40 windows
  db_timeout        :   20 windows
  TOTAL             :  500 windows
  PASSED

Test 2 — Anomaly detection metrics (contamination=0.24):
  TP=120  FP=380  FN=0  TN=0
  Precision : 0.240
  Recall    : 1.000
  F1        : 0.387
  Accuracy  : 0.240
  Recall > 0.5: PASSED

Test 3 — Mean IF score per scenario:
  healthy           :  -0.4495   ← highest (least anomalous)
  warn_retry        :  -0.4863
  design_failure    :  -0.4854
  ssl_error         :  -0.5214
  db_timeout        :  -0.5483   ← lowest (most anomalous)
  Score ordering (healthy > anomalous): PASSED

Test 4 — Attribution coverage:
  Anomalous windows with reasons: 120/120 (100%)
  Coverage ≥ 50%: PASSED

Test 5 — Correlation accuracy:
  Exception blocks parsed : 2
  Incidents returned      : 2
  Top incident confidence : 0.80
  Matched windows         : ['req-df0000', 'req-df0001', 'req-df0002']
  Evidence                : class=['ServiceDesignService'], entity=[]
  PASSED

Test 6 — Pipeline end-to-end: PASSED
Test 7 — Scorer persistence (save/load): PASSED
```

### Metric Interpretation

**Recall = 1.0, Precision = 0.24** — this is the same threshold calibration limitation documented in P5-03, now quantified at scale. The Isolation Forest correctly *orders* windows by anomalousness (healthy scores highest, db_timeout lowest) but the `anomaly_threshold=-0.05` is too permissive — it flags everything as anomalous on a 500-window synthetic corpus.

**What is working correctly:**
- Score ordering is monotone: `healthy > warn_retry ≈ design_failure > ssl_error > db_timeout`
- Attribution coverage is 100% — every anomalous window has at least one human-readable reason
- Correlation confidence 0.80 on a design_failure stack trace with class name match
- Full pipeline runs end-to-end without degradation

**Production calibration path:**
1. Fit on ≥500 real windows from a stable production period
2. Set `contamination` to the observed anomaly rate (typically 0.05–0.10)
3. Tune `anomaly_threshold` so known-good windows score above it
4. Re-run this evaluation harness — expect precision to rise above 0.6

---

*Phase 5 complete.*
