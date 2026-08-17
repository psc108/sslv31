"""
P5-02: Log message embedder.

Two-stage pipeline:
  1. TF-IDF (sklearn) — sparse bag-of-words over log messages, vocabulary
     tuned for Java/Spring Boot tokens (package names, exception types, etc.)
  2. Linear projection (PyTorch) — maps TF-IDF sparse vector → dense 64-dim
     embedding, trained via tied-weight autoencoder reconstruction so the
     projection learns log-domain structure rather than staying random.

Usage:
    embedder = MessageEmbedder(dim=64, max_features=4096)
    embedder.fit(windows)           # builds TF-IDF vocab + trains projection
    vec = embedder.embed(window)    # np.ndarray shape (64,)
    embedder.save("msg_embedder.pkl")
    embedder = MessageEmbedder.load("msg_embedder.pkl")
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from sklearn.feature_extraction.text import TfidfVectorizer

from .log_windower import LogWindow


# ---------------------------------------------------------------------------
# Tokeniser — keeps Java package tokens intact
# ---------------------------------------------------------------------------

def _java_tokeniser(text: str) -> list[str]:
    """
    Split on whitespace and punctuation but preserve dot-separated tokens
    so 'c.d.e.f.service.ServiceDesignService' stays as one token and
    'ServiceDesignService' is also emitted as a sub-token.
    """
    import re
    tokens: list[str] = []
    for raw in re.split(r"[\s|,;\"'()\[\]{}<>]+", text):
        raw = raw.strip(".:~@#$%^&*+=")
        if not raw or len(raw) < 2:
            continue
        tokens.append(raw.lower())
        # also emit the last dotted segment as a standalone token
        if "." in raw:
            tokens.append(raw.split(".")[-1].lower())
    return tokens


# ---------------------------------------------------------------------------
# Projection network
# ---------------------------------------------------------------------------

class _ProjectionAE(nn.Module):
    """Tied-weight autoencoder: encode TF-IDF → dim, decode back to tfidf_dim."""

    def __init__(self, tfidf_dim: int, dim: int):
        super().__init__()
        self.encoder = nn.Linear(tfidf_dim, dim, bias=True)
        self.decoder = nn.Linear(dim, tfidf_dim, bias=True)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        z = torch.relu(self.encoder(x))
        recon = self.decoder(z)
        return z, recon


# ---------------------------------------------------------------------------
# MessageEmbedder
# ---------------------------------------------------------------------------

class MessageEmbedder:
    def __init__(self, dim: int = 64, max_features: int = 4096):
        self.dim = dim
        self.max_features = max_features
        self._tfidf: TfidfVectorizer | None = None
        self._net: _ProjectionAE | None = None

    # ------------------------------------------------------------------
    # Fit
    # ------------------------------------------------------------------

    def fit(
        self,
        windows: list[LogWindow],
        epochs: int = 30,
        lr: float = 1e-3,
        batch_size: int = 64,
    ) -> "MessageEmbedder":
        texts = [w.text_for_embedding() for w in windows]
        if not texts:
            raise ValueError("No windows to fit on")

        # Stage 1: TF-IDF
        self._tfidf = TfidfVectorizer(
            tokenizer=_java_tokeniser,
            token_pattern=None,
            max_features=self.max_features,
            sublinear_tf=True,
            min_df=1,
        )
        X_sparse = self._tfidf.fit_transform(texts)
        X = torch.tensor(X_sparse.toarray(), dtype=torch.float32)
        tfidf_dim = X.shape[1]

        # Stage 2: train projection AE
        self._net = _ProjectionAE(tfidf_dim, self.dim)
        opt = torch.optim.Adam(self._net.parameters(), lr=lr)
        loss_fn = nn.MSELoss()

        self._net.train()
        n = X.shape[0]
        for _ in range(epochs):
            idx = torch.randperm(n)
            for start in range(0, n, batch_size):
                batch = X[idx[start: start + batch_size]]
                _, recon = self._net(batch)
                loss = loss_fn(recon, batch)
                opt.zero_grad()
                loss.backward()
                opt.step()

        self._net.eval()
        return self

    # ------------------------------------------------------------------
    # Embed
    # ------------------------------------------------------------------

    def embed(self, window: LogWindow) -> np.ndarray:
        return self.embed_text(window.text_for_embedding())

    def embed_text(self, text: str) -> np.ndarray:
        if self._tfidf is None or self._net is None:
            raise RuntimeError("Call fit() before embed()")
        x_sparse = self._tfidf.transform([text])
        x = torch.tensor(x_sparse.toarray(), dtype=torch.float32)
        with torch.no_grad():
            z, _ = self._net(x)
        return z.squeeze(0).numpy()

    def embed_batch(self, windows: list[LogWindow]) -> np.ndarray:
        texts = [w.text_for_embedding() for w in windows]
        if self._tfidf is None or self._net is None:
            raise RuntimeError("Call fit() before embed()")
        x_sparse = self._tfidf.transform(texts)
        x = torch.tensor(x_sparse.toarray(), dtype=torch.float32)
        with torch.no_grad():
            z, _ = self._net(x)
        return z.numpy()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        net_state = self._net.state_dict() if self._net else None
        net_shape = (
            (self._net.encoder.in_features, self.dim) if self._net else None
        )
        with open(path, "wb") as f:
            pickle.dump(
                {"tfidf": self._tfidf, "net_state": net_state,
                 "net_shape": net_shape, "dim": self.dim,
                 "max_features": self.max_features},
                f,
            )

    @classmethod
    def load(cls, path: str) -> "MessageEmbedder":
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls(dim=data["dim"], max_features=data["max_features"])
        obj._tfidf = data["tfidf"]
        if data["net_state"] and data["net_shape"]:
            tfidf_dim, dim = data["net_shape"]
            obj._net = _ProjectionAE(tfidf_dim, dim)
            obj._net.load_state_dict(data["net_state"])
            obj._net.eval()
        return obj
