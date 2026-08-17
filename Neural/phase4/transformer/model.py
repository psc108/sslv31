"""
GPT — minimal character-level language model.

Architecture (GPT-style decoder-only Transformer):

    token embedding  (vocab, d_model)
    + positional encoding (sinusoidal, fixed)
    → N × TransformerBlock (MHA + FF + residuals + LayerNorm)
    → LayerNorm
    → linear head (d_model, vocab)
    → cross-entropy loss

Positional encoding uses the fixed sinusoidal scheme from Vaswani et al.
(not learned) — simpler and works well for short contexts.
"""

import numpy as np
from phase4.transformer.layers import TransformerBlock, LayerNorm


# ---------------------------------------------------------------------------
# Sinusoidal positional encoding (fixed, not learned)
# ---------------------------------------------------------------------------
def _positional_encoding(T: int, d_model: int) -> np.ndarray:
    """Returns (T, d_model) positional encoding matrix."""
    pos = np.arange(T)[:, None]                           # (T, 1)
    dim = np.arange(0, d_model, 2)                        # even indices
    div = np.exp(dim * (-np.log(10000.0) / d_model))      # (d_model/2,)
    pe = np.zeros((T, d_model))
    pe[:, 0::2] = np.sin(pos * div)
    pe[:, 1::2] = np.cos(pos * div)
    return pe                                              # (T, d_model)


# ---------------------------------------------------------------------------
# GPT model
# ---------------------------------------------------------------------------
class GPT:
    """
    Parameters
    ----------
    vocab_size : number of tokens
    d_model    : embedding / hidden dimension
    n_heads    : attention heads per block (d_model must be divisible)
    n_layers   : number of Transformer blocks
    max_T      : maximum sequence length (for positional encoding)
    """

    def __init__(self, vocab_size: int, d_model: int,
                 n_heads: int, n_layers: int, max_T: int = 256):
        self.vocab_size = vocab_size
        self.d_model    = d_model

        # Token embedding table
        self.E = np.random.randn(vocab_size, d_model) * 0.02

        # Fixed positional encoding (not a parameter)
        self._pe = _positional_encoding(max_T, d_model)

        # Transformer blocks
        self.blocks = [TransformerBlock(d_model, n_heads) for _ in range(n_layers)]

        # Final layer norm + output projection
        self.ln_f  = LayerNorm(d_model)
        self.W_out = np.random.randn(d_model, vocab_size) * 0.02
        self.b_out = np.zeros(vocab_size)

        self._cache = None

    # ------------------------------------------------------------------
    # Forward
    # ------------------------------------------------------------------
    def forward(self, token_ids: list[int], training: bool = True) -> np.ndarray:
        """
        token_ids : list of T integer token indices
        Returns logits: (T, vocab_size)
        """
        T = len(token_ids)
        x = self.E[token_ids] + self._pe[:T]              # (T, d_model)

        for block in self.blocks:
            x = block.forward(x, training)

        x = self.ln_f.forward(x, training)
        logits = x @ self.W_out + self.b_out              # (T, vocab_size)

        if training:
            self._cache = (token_ids, x)
        return logits

    # ------------------------------------------------------------------
    # Backward
    # ------------------------------------------------------------------
    def backward(self, dlogits: np.ndarray):
        """
        dlogits : (T, vocab_size)
        Returns flat gradient dict for all parameters.
        """
        token_ids, x = self._cache

        dW_out = x.T @ dlogits                            # (d_model, vocab_size)
        db_out = dlogits.sum(axis=0)
        dx = dlogits @ self.W_out.T                       # (T, d_model)

        ln_f_grads, dx = self.ln_f.backward(dx)

        all_grads = {'W_out': dW_out, 'b_out': db_out}
        for k, v in ln_f_grads.items():
            all_grads[f'ln_f.{k}'] = v

        for i, block in enumerate(reversed(self.blocks)):
            block_grads, dx = block.backward(dx)
            for k, v in block_grads.items():
                all_grads[f'block{len(self.blocks)-1-i}.{k}'] = v

        # Embedding gradient
        dE = np.zeros_like(self.E)
        for t, tok in enumerate(token_ids):
            dE[tok] += dx[t]
        all_grads['E'] = dE

        return all_grads

    # ------------------------------------------------------------------
    # Params (flat dict — same keys as backward output)
    # ------------------------------------------------------------------
    def params(self):
        p = {'E': self.E, 'W_out': self.W_out, 'b_out': self.b_out}
        for k, v in self.ln_f.params().items():
            p[f'ln_f.{k}'] = v
        for i, block in enumerate(self.blocks):
            for k, v in block.params().items():
                p[f'block{i}.{k}'] = v
        return p

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------
    def sample(self, seed_ids: list[int], length: int,
               temperature: float = 1.0) -> list[int]:
        """
        Autoregressively sample `length` tokens starting from seed_ids.
        temperature < 1 → sharper / more deterministic
        temperature > 1 → flatter / more random
        """
        ids = list(seed_ids)
        max_T = self._pe.shape[0]
        for _ in range(length):
            ctx    = ids[-max_T:]                         # truncate to max context
            logits = self.forward(ctx, training=False)    # (T, vocab)
            last   = logits[-1] / temperature
            e = np.exp(last - last.max())
            p = e / e.sum()
            ids.append(np.random.choice(self.vocab_size, p=p))
        return ids[len(seed_ids):]
