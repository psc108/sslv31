# Neural — ML Intelligence Layer for ssl

Phase 5 of the Neural project adds an ML diagnostic pipeline on top of ssl's
existing rule-based JAR analysis and KB-backed error diagnostics.

## Repository layout

```
ssl/
  backend/          ← ssl backend (FastAPI)
  Neural/           ← this directory — ships inside the ssl repo
    phase5/
      log_intelligence/   ← the importable package
      test_p50[1-6].py
    pyproject.toml
```

## Installation into ssl's venv

From the ssl backend directory, install Neural as an editable package:

```bash
cd /path/to/ssl/backend
source .venv/bin/activate          # or however ssl's venv is activated
pip install -e ../Neural           # editable install — no copy, live source
```

This makes `from phase5.log_intelligence.pipeline import diagnose_with_ml`
work from anywhere inside ssl's venv.

## Configuration (ssl .env)

```env
# Path to a fitted AnomalyScorer .pkl — if unset, anomaly scoring is skipped
# and the pipeline runs in stack-trace-only mode (correlation still works).
ML_SCORER_PATH=/var/lib/certmanager/models/anomaly_scorer.pkl

# Path to the live application log file for log ingestion.
# If unset, log windowing is skipped.
ML_LOG_PATH=/var/log/ecs/fulfillment/application.log
```

Both settings default to `None` — the pipeline degrades gracefully when
either is absent, so ssl starts cleanly before any model has been trained.

## Training the scorer (first-time setup)

Run this once on a machine that has access to real production logs:

```python
from phase5.log_intelligence.ingestion import ingest_log_file
from phase5.log_intelligence.embed_window import WindowEmbedder
from phase5.log_intelligence.anomaly_scorer import AnomalyScorer

windows = ingest_log_file("/var/log/ecs/fulfillment/application.log")

embedder = WindowEmbedder()
embedder.fit(windows, epochs=40)

# Set contamination to the expected anomaly rate in your corpus (e.g. 0.05)
scorer = AnomalyScorer(contamination=0.05, anomaly_threshold=-0.05)
scorer.fit(windows, embedder)

scorer.save("/var/lib/certmanager/models/anomaly_scorer.pkl")
```

See `phase5/test_p506.py` for a full evaluation harness with labelled
synthetic data and precision/recall metrics.

## Integration points in ssl

| Endpoint | Where ML result appears |
|---|---|
| `POST /api/v1/docs/error-kb/decode` | `response.ml_analysis` |
| `POST /api/v1/jar-analyser/reports/{id}/diagnose` | `response.ml_analysis` |
| `POST /api/v1/jar-analyser/reports/{id}/diagnostics` (bundle upload) | `JarDiagnosticRun.log_findings_json["ml"]` |

All three degrade silently — `ml_analysis: null` — if Neural is not installed
or no scorer model is present.

## Phase summary

| Phase | What was built |
|---|---|
| P5-01 | Log parser + windower (Spring Boot logback format, MDC correlation) |
| P5-02 | WindowEmbedder — TF-IDF + AE projection → 102-dim vectors |
| P5-03 | AnomalyScorer — IsolationForest + z-score attribution |
| P5-04 | SignalCorrelator — joins stack trace frames to anomalous log windows |
| P5-05 | `diagnose_with_ml()` — single entry point, graceful degradation |
| P5-06 | Synthetic corpus (500 labelled windows) + evaluation harness |
