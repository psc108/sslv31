"""
P5-03: Log window anomaly scorer.

Wraps sklearn IsolationForest trained on 102-dim WindowEmbedder vectors.
Produces an AnomalyResult per window containing:
  - score       : float in [-1, 1], negative = anomaly (IF convention)
  - is_anomaly  : bool  (score < threshold, default -0.05)
  - severity    : "normal" | "warning" | "critical"
  - reasons     : list[str] — human-readable attribution

Attribution strategy:
  - Scalar dims (96-101) are z-scored against training distribution;
    dims > 2.5 std from mean are flagged with their feature name.
  - Structural signals (has_stack, error/warn ratio) are checked directly
    from the LogWindow rather than inferred from the embedding.
  - Message embedding distance from the training centroid flags
    out-of-vocabulary / novel message patterns.

The AnomalyResult is JSON-serialisable and maps directly to the
JarDiagnosticRun.log_findings_json schema in the ssl backend.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field, asdict

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from .embed_window import WindowEmbedder, _scalar_features
from .log_windower import LogWindow

# Names for the 6 scalar feature dims (indices 96-101 in the 102-dim vector)
_SCALAR_NAMES = [
    "error_ratio",
    "warn_ratio",
    "stack_ratio",
    "entity_key_count",
    "duration_ms",
    "entry_count",
]

_SEVERITY_THRESHOLDS = {
    "critical": -0.15,
    "warning":  -0.05,
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class AnomalyResult:
    window_key: str
    score: float                        # raw IF score, lower = more anomalous
    is_anomaly: bool
    severity: str                       # "normal" | "warning" | "critical"
    reasons: list[str] = field(default_factory=list)
    entity_keys: list[str] = field(default_factory=list)
    level_sequence: list[str] = field(default_factory=list)
    entry_count: int = 0
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

class AnomalyScorer:
    def __init__(
        self,
        contamination: float = 0.1,
        n_estimators: int = 200,
        anomaly_threshold: float = -0.05,
    ):
        self.contamination = contamination
        self.n_estimators = n_estimators
        self.anomaly_threshold = anomaly_threshold

        self._embedder: WindowEmbedder | None = None
        self._forest: IsolationForest | None = None
        self._scaler: StandardScaler | None = None   # fitted on scalar dims only
        self._msg_centroid: np.ndarray | None = None  # mean of msg dims (0-63)

    # ------------------------------------------------------------------
    # Fit
    # ------------------------------------------------------------------

    def fit(
        self,
        windows: list[LogWindow],
        embedder: WindowEmbedder,
        embed_epochs: int = 30,
    ) -> "AnomalyScorer":
        self._embedder = embedder

        # Embed the full corpus
        X = embedder.embed_batch(windows)           # (N, 102)

        # Fit scaler on scalar dims for attribution z-scores
        self._scaler = StandardScaler()
        self._scaler.fit(X[:, 96:])                 # scalar dims only

        # Store message embedding centroid for novelty detection
        self._msg_centroid = X[:, :64].mean(axis=0)

        # Fit Isolation Forest on full 102-dim vectors
        self._forest = IsolationForest(
            n_estimators=self.n_estimators,
            contamination=self.contamination,
            random_state=42,
        )
        self._forest.fit(X)
        return self

    # ------------------------------------------------------------------
    # Score
    # ------------------------------------------------------------------

    def score_window(self, window: LogWindow) -> AnomalyResult:
        if self._forest is None or self._embedder is None:
            raise RuntimeError("Call fit() before score_window()")

        vec = self._embedder.embed(window)           # (102,)
        raw_score = float(self._forest.score_samples(vec.reshape(1, -1))[0])
        is_anomaly = raw_score < self.anomaly_threshold

        severity = "normal"
        if raw_score < _SEVERITY_THRESHOLDS["critical"]:
            severity = "critical"
        elif raw_score < _SEVERITY_THRESHOLDS["warning"]:
            severity = "warning"

        reasons = self._attribute(window, vec, raw_score)

        return AnomalyResult(
            window_key=window.key,
            score=round(raw_score, 4),
            is_anomaly=is_anomaly,
            severity=severity,
            reasons=reasons,
            entity_keys=window.entity_keys,
            level_sequence=window.level_sequence,
            entry_count=len(window.entries),
            duration_ms=round(window.duration_ms, 1),
        )

    def score_batch(self, windows: list[LogWindow]) -> list[AnomalyResult]:
        return [self.score_window(w) for w in windows]

    # ------------------------------------------------------------------
    # Attribution
    # ------------------------------------------------------------------

    def _attribute(
        self, window: LogWindow, vec: np.ndarray, score: float
    ) -> list[str]:
        reasons: list[str] = []

        # 1. Scalar feature z-scores
        scalar = vec[96:].reshape(1, -1)
        z = self._scaler.transform(scalar)[0]
        for i, (name, zi) in enumerate(zip(_SCALAR_NAMES, z)):
            if abs(zi) > 2.5:
                direction = "elevated" if zi > 0 else "suppressed"
                reasons.append(f"{name} {direction} (z={zi:.1f})")

        # 2. Direct structural signals from the window
        n = max(len(window.entries), 1)
        error_ratio = sum(1 for e in window.entries if e.is_error) / n
        if error_ratio > 0.3:
            reasons.append(
                f"high error rate ({error_ratio:.0%} of entries are ERROR/FATAL)"
            )

        if window.has_stack:
            frame_classes = {
                f.class_method.split(".")[-1]
                for e in window.entries
                for f in e.frames
            }
            if frame_classes:
                reasons.append(
                    f"stack trace present — top frames: {', '.join(sorted(frame_classes)[:3])}"
                )

        # 3. Message novelty — distance from training centroid
        msg_vec = vec[:64]
        centroid_dist = float(np.linalg.norm(msg_vec - self._msg_centroid))
        # threshold: mean + 2 std of training distances (approximated as 2x mean norm)
        centroid_norm = float(np.linalg.norm(self._msg_centroid))
        if centroid_dist > centroid_norm * 1.5:
            reasons.append("message pattern not seen in training corpus")

        # 4. Entity key anomaly — multiple distinct keys in one window
        if len(window.entity_keys) > 3:
            reasons.append(
                f"unusually many entity keys in one window ({len(window.entity_keys)})"
            )

        if not reasons and score < self.anomaly_threshold:
            reasons.append("anomalous embedding — no single dominant signal")

        return reasons

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            pickle.dump({
                "forest": self._forest,
                "scaler": self._scaler,
                "msg_centroid": self._msg_centroid,
                "embedder": self._embedder,
                "contamination": self.contamination,
                "n_estimators": self.n_estimators,
                "anomaly_threshold": self.anomaly_threshold,
            }, f)

    @classmethod
    def load(cls, path: str) -> "AnomalyScorer":
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls(
            contamination=data["contamination"],
            n_estimators=data["n_estimators"],
            anomaly_threshold=data["anomaly_threshold"],
        )
        obj._forest        = data["forest"]
        obj._scaler        = data["scaler"]
        obj._msg_centroid  = data["msg_centroid"]
        obj._embedder      = data["embedder"]
        return obj
