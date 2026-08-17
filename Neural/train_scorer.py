"""
train_scorer.py — train and save an AnomalyScorer from the synthetic corpus.

Produces a scorer .pkl that can be deployed immediately without production
logs, giving a working baseline model. Replace with a real-log trained model
once production log data is available.

Usage (from the Neural directory):
    docker exec ssl-cert-manager \\
        /opt/certmanager/venv/bin/python /opt/certmanager/Neural/train_scorer.py \\
        --output /data/models/anomaly_scorer.pkl

    # Then set in docker-compose.yml:
    #   ML_SCORER_PATH=/data/models/anomaly_scorer.pkl

Options:
    --output PATH       Where to write the .pkl  [default: /tmp/anomaly_scorer.pkl]
    --epochs N          Autoencoder training epochs  [default: 40]
    --contamination F   Expected anomaly fraction  [default: auto from corpus]
    --threshold F       IF score threshold for anomaly flag  [default: -0.05]
    --log-path PATH     If supplied, also ingest this log file and add its
                        windows to the training corpus (real + synthetic mix).
    --evaluate          Print precision/recall/F1 on the synthetic corpus after
                        training (uses held-out labels, not fed to the model).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Neural AnomalyScorer")
    parser.add_argument("--output", default="/tmp/anomaly_scorer.pkl")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--contamination", type=float, default=None)
    parser.add_argument("--threshold", type=float, default=-0.05)
    parser.add_argument("--log-path", default=None)
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()

    from phase5.log_intelligence.synthetic_corpus import generate_corpus, ANOMALOUS_LABELS
    from phase5.log_intelligence.embed_window import WindowEmbedder
    from phase5.log_intelligence.anomaly_scorer import AnomalyScorer

    print("Generating synthetic corpus...")
    windows, labels = generate_corpus()
    print(f"  Synthetic corpus: {len(windows)} windows")

    # Optionally mix in real log windows (unlabelled — treated as healthy)
    if args.log_path:
        from phase5.log_intelligence.ingestion import ingest_log_tail
        if os.path.isfile(args.log_path):
            real_windows = ingest_log_tail(args.log_path, tail_lines=20_000)
            print(f"  Real log windows:  {len(real_windows)} (from {args.log_path})")
            windows = windows + real_windows
            labels = labels + ["healthy"] * len(real_windows)
        else:
            print(f"  Warning: --log-path {args.log_path!r} not found, skipping.")

    # Auto-compute contamination from corpus composition
    contamination = args.contamination
    if contamination is None:
        n_anomalous = sum(1 for lbl in labels if lbl in ANOMALOUS_LABELS)
        contamination = round(n_anomalous / len(windows), 3)
        contamination = max(0.01, min(contamination, 0.49))
    print(f"  Contamination: {contamination}")

    print(f"\nFitting WindowEmbedder (epochs={args.epochs})...")
    embedder = WindowEmbedder()
    embedder.fit(windows, epochs=args.epochs)

    print(f"Fitting AnomalyScorer (threshold={args.threshold})...")
    scorer = AnomalyScorer(
        contamination=contamination,
        anomaly_threshold=args.threshold,
    )
    scorer.fit(windows, embedder)

    # Evaluate on synthetic corpus if requested
    if args.evaluate:
        print("\nEvaluating on synthetic corpus...")
        results = scorer.score_batch(windows)
        y_true = [1 if lbl in ANOMALOUS_LABELS else 0 for lbl in labels]
        y_pred = [1 if r.is_anomaly else 0 for r in results]
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
        tn = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 0)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        print(f"  TP={tp}  FP={fp}  FN={fn}  TN={tn}")
        print(f"  Precision : {precision:.3f}")
        print(f"  Recall    : {recall:.3f}")
        print(f"  F1        : {f1:.3f}")

    # Save
    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    scorer.save(args.output)
    print(f"\nScorer saved to: {args.output}")
    print(f"\nTo activate, add to docker-compose.yml environment:")
    print(f"  - ML_SCORER_PATH={args.output}")


if __name__ == "__main__":
    main()
