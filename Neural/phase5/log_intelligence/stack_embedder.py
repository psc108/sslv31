"""
P5-02: Stack trace embedder.

Stack frames have a very different token distribution from log messages —
they are dense with Java package/class/method names and almost no natural
language. A separate vocabulary and embedding is warranted.

Approach:
  - Build a vocabulary of class.method tokens seen across all frames
  - Represent each frame as a one-hot over that vocab
  - Mean-pool across all frames in a window → fixed-size vector
  - Project through a small Linear layer → 32-dim stack embedding

Windows with no stack frames get a zero vector.
"""

from __future__ import annotations

import pickle
import re
from collections import Counter

import numpy as np
import torch
import torch.nn as nn

from .log_windower import LogWindow


def _frame_tokens(class_method: str) -> list[str]:
    """
    'com.dxc.ecs.fulfillment.service.ServiceDesignService.importServiceDesigns'
    → ['com', 'dxc', 'ecs', 'fulfillment', 'service', 'servicedesignservice',
       'importservicedesigns', 'servicedesignservice.importservicedesigns']
    """
    parts = class_method.lower().split(".")
    tokens = list(parts)
    if len(parts) >= 2:
        tokens.append(f"{parts[-2]}.{parts[-1]}")
    return tokens


class StackEmbedder:
    def __init__(self, dim: int = 32, max_vocab: int = 2048):
        self.dim = dim
        self.max_vocab = max_vocab
        self._vocab: dict[str, int] = {}
        self._net: nn.Linear | None = None

    # ------------------------------------------------------------------
    # Fit
    # ------------------------------------------------------------------

    def fit(self, windows: list[LogWindow]) -> "StackEmbedder":
        counter: Counter = Counter()
        for w in windows:
            for e in w.entries:
                for f in e.frames:
                    counter.update(_frame_tokens(f.class_method))

        top = [tok for tok, _ in counter.most_common(self.max_vocab)]
        self._vocab = {tok: i for i, tok in enumerate(top)}

        vocab_size = len(self._vocab)
        if vocab_size == 0:
            # No stack frames in corpus — projection stays None, embed returns zeros
            return self

        self._net = nn.Linear(vocab_size, self.dim, bias=False)
        nn.init.xavier_uniform_(self._net.weight)
        return self

    # ------------------------------------------------------------------
    # Embed
    # ------------------------------------------------------------------

    def _window_to_vec(self, window: LogWindow) -> np.ndarray:
        if not self._vocab:
            return np.zeros(self.dim, dtype=np.float32)

        vocab_size = len(self._vocab)
        frame_vecs: list[np.ndarray] = []

        for entry in window.entries:
            for frame in entry.frames:
                vec = np.zeros(vocab_size, dtype=np.float32)
                for tok in _frame_tokens(frame.class_method):
                    if tok in self._vocab:
                        vec[self._vocab[tok]] = 1.0
                frame_vecs.append(vec)

        if not frame_vecs:
            return np.zeros(self.dim, dtype=np.float32)

        mean_vec = np.mean(frame_vecs, axis=0)
        return mean_vec

    def embed(self, window: LogWindow) -> np.ndarray:
        if self._net is None:
            return np.zeros(self.dim, dtype=np.float32)
        raw = self._window_to_vec(window)
        x = torch.tensor(raw, dtype=torch.float32).unsqueeze(0)
        with torch.no_grad():
            z = torch.relu(self._net(x))
        return z.squeeze(0).numpy()

    def embed_batch(self, windows: list[LogWindow]) -> np.ndarray:
        if self._net is None:
            return np.zeros((len(windows), self.dim), dtype=np.float32)
        raws = np.stack([self._window_to_vec(w) for w in windows])
        x = torch.tensor(raws, dtype=torch.float32)
        with torch.no_grad():
            z = torch.relu(self._net(x))
        return z.numpy()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        net_state = self._net.state_dict() if self._net else None
        net_shape = (
            (self._net.in_features, self.dim) if self._net else None
        )
        with open(path, "wb") as f:
            pickle.dump(
                {"vocab": self._vocab, "net_state": net_state,
                 "net_shape": net_shape, "dim": self.dim,
                 "max_vocab": self.max_vocab},
                f,
            )

    @classmethod
    def load(cls, path: str) -> "StackEmbedder":
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls(dim=data["dim"], max_vocab=data["max_vocab"])
        obj._vocab = data["vocab"]
        if data["net_state"] and data["net_shape"]:
            in_f, dim = data["net_shape"]
            obj._net = nn.Linear(in_f, dim, bias=False)
            obj._net.load_state_dict(data["net_state"])
            obj._net.eval()
        return obj
