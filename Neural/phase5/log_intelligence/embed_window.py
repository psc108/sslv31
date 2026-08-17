"""
P5-02: Window embedding combiner.

Produces a single fixed-size vector per LogWindow by concatenating:
  - 64-dim message embedding  (MessageEmbedder)
  - 32-dim stack embedding    (StackEmbedder)
  -  6-dim scalar features    (hand-crafted signals)

Final shape: 102-dim float32 numpy array.

Scalar features (normalised):
  0  error_ratio      — ERROR+FATAL entries / total entries
  1  warn_ratio       — WARN entries / total entries
  2  stack_ratio      — entries with frames / total entries
  3  entity_key_count — number of distinct entity keys (log-scaled)
  4  duration_norm    — log1p(duration_ms) / 10.0
  5  entry_count_norm — log1p(entry count) / 5.0

Usage:
    from phase5.log_intelligence.embed_window import WindowEmbedder

    we = WindowEmbedder()
    we.fit(windows)
    vec = we.embed(window)          # np.ndarray shape (102,)
    matrix = we.embed_batch(windows) # np.ndarray shape (N, 102)
    we.save("window_embedder.pkl")
    we = WindowEmbedder.load("window_embedder.pkl")
"""

from __future__ import annotations

import pickle

import numpy as np

from .embedder import MessageEmbedder
from .log_windower import LogWindow
from .stack_embedder import StackEmbedder

SCALAR_DIM = 6


def _scalar_features(window: LogWindow) -> np.ndarray:
    n = max(len(window.entries), 1)
    error_ratio = sum(1 for e in window.entries if e.is_error) / n
    warn_ratio  = sum(1 for e in window.entries if e.is_warn)  / n
    stack_ratio = sum(1 for e in window.entries if e.has_stack) / n
    entity_count = np.log1p(len(window.entity_keys)) / 5.0
    duration     = np.log1p(window.duration_ms) / 10.0
    entry_norm   = np.log1p(n) / 5.0
    return np.array(
        [error_ratio, warn_ratio, stack_ratio, entity_count, duration, entry_norm],
        dtype=np.float32,
    )


class WindowEmbedder:
    MSG_DIM   = 64
    STACK_DIM = 32
    TOTAL_DIM = MSG_DIM + STACK_DIM + SCALAR_DIM  # 102

    def __init__(self):
        self._msg   = MessageEmbedder(dim=self.MSG_DIM)
        self._stack = StackEmbedder(dim=self.STACK_DIM)

    def fit(self, windows: list[LogWindow], epochs: int = 30) -> "WindowEmbedder":
        self._msg.fit(windows, epochs=epochs)
        self._stack.fit(windows)
        return self

    def embed(self, window: LogWindow) -> np.ndarray:
        msg_vec   = self._msg.embed(window)
        stack_vec = self._stack.embed(window)
        scalar    = _scalar_features(window)
        return np.concatenate([msg_vec, stack_vec, scalar])

    def embed_batch(self, windows: list[LogWindow]) -> np.ndarray:
        msg_mat   = self._msg.embed_batch(windows)
        stack_mat = self._stack.embed_batch(windows)
        scalar_mat = np.stack([_scalar_features(w) for w in windows])
        return np.concatenate([msg_mat, stack_mat, scalar_mat], axis=1)

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            pickle.dump({"msg": self._msg, "stack": self._stack}, f)

    @classmethod
    def load(cls, path: str) -> "WindowEmbedder":
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls()
        obj._msg   = data["msg"]
        obj._stack = data["stack"]
        return obj
