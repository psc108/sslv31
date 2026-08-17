"""
Transformer building blocks — LayerNorm, FeedForward, TransformerBlock.

Each component carries its own forward/backward and params() method so
the GPT model can compose them uniformly.
"""

import numpy as np
from phase4.transformer.attention import MultiHeadAttention


# ---------------------------------------------------------------------------
# Layer Normalisation
# ---------------------------------------------------------------------------
class LayerNorm:
    """
    Normalises each token's feature vector to zero mean, unit variance,
    then applies learnable scale (gamma) and shift (beta).

        x_hat = (x - mean) / sqrt(var + eps)
        out   = gamma * x_hat + beta

    gamma and beta are (d_model,) vectors, one per feature dimension.
    """

    def __init__(self, d_model: int, eps: float = 1e-5):
        self.gamma = np.ones(d_model)
        self.beta  = np.zeros(d_model)
        self.eps   = eps
        self._cache = None

    def forward(self, x: np.ndarray, training: bool = True) -> np.ndarray:
        # x: (T, d_model)
        mean = x.mean(axis=-1, keepdims=True)             # (T, 1)
        var  = x.var(axis=-1, keepdims=True)              # (T, 1)
        x_hat = (x - mean) / np.sqrt(var + self.eps)     # (T, d_model)
        out   = self.gamma * x_hat + self.beta
        if training:
            self._cache = (x, x_hat, mean, var)
        return out

    def backward(self, dout: np.ndarray):
        # dout: (T, d_model)
        x, x_hat, mean, var = self._cache
        T, D = x.shape
        std_inv = 1.0 / np.sqrt(var + self.eps)

        dgamma = (dout * x_hat).sum(axis=0)               # (d_model,)
        dbeta  = dout.sum(axis=0)

        # Backward through normalisation (Ioffe & Szegedy derivation)
        dx_hat = dout * self.gamma                        # (T, D)
        dvar   = (dx_hat * (x - mean) * -0.5 * std_inv**3).sum(axis=-1, keepdims=True)
        dmean  = (dx_hat * -std_inv).sum(axis=-1, keepdims=True) \
                 + dvar * (-2.0 * (x - mean)).mean(axis=-1, keepdims=True)
        dx = dx_hat * std_inv + dvar * 2.0 * (x - mean) / D + dmean / D

        return {'gamma': dgamma, 'beta': dbeta}, dx

    def params(self):
        return {'gamma': self.gamma, 'beta': self.beta}


# ---------------------------------------------------------------------------
# Feed-Forward sublayer
# ---------------------------------------------------------------------------
class FeedForward:
    """
    Two-layer MLP applied independently to each token position:

        h   = ReLU(x @ W1 + b1)
        out = h @ W2 + b2

    Inner dimension is 4 * d_model (standard Transformer ratio).
    """

    def __init__(self, d_model: int):
        d_ff = 4 * d_model
        self.W1 = np.random.randn(d_model, d_ff)  * np.sqrt(2.0 / d_model)
        self.b1 = np.zeros(d_ff)
        self.W2 = np.random.randn(d_ff, d_model)  * np.sqrt(2.0 / d_ff)
        self.b2 = np.zeros(d_model)
        self._cache = None

    def forward(self, x: np.ndarray, training: bool = True) -> np.ndarray:
        h   = np.maximum(0, x @ self.W1 + self.b1)       # (T, d_ff)  ReLU
        out = h @ self.W2 + self.b2                       # (T, d_model)
        if training:
            self._cache = (x, h)
        return out

    def backward(self, dout: np.ndarray):
        x, h = self._cache
        dW2 = h.T @ dout                                  # (d_ff, d_model)
        db2 = dout.sum(axis=0)
        dh  = dout @ self.W2.T                            # (T, d_ff)
        dh  = dh * (h > 0)                               # ReLU backward
        dW1 = x.T @ dh                                    # (d_model, d_ff)
        db1 = dh.sum(axis=0)
        dx  = dh @ self.W1.T                              # (T, d_model)
        return {'W1': dW1, 'b1': db1, 'W2': dW2, 'b2': db2}, dx

    def params(self):
        return {'W1': self.W1, 'b1': self.b1, 'W2': self.W2, 'b2': self.b2}


# ---------------------------------------------------------------------------
# Transformer Block
# ---------------------------------------------------------------------------
class TransformerBlock:
    """
    One Transformer decoder block (GPT-style pre-norm):

        x = x + MHA(LN1(x))
        x = x + FF(LN2(x))

    Pre-norm (LN before the sublayer) is more stable than the original
    post-norm formulation and is used in GPT-2 and most modern models.
    """

    def __init__(self, d_model: int, n_heads: int):
        self.ln1 = LayerNorm(d_model)
        self.mha = MultiHeadAttention(d_model, n_heads, mask=True)
        self.ln2 = LayerNorm(d_model)
        self.ff  = FeedForward(d_model)
        self._cache = None

    def forward(self, x: np.ndarray, training: bool = True) -> np.ndarray:
        # Attention sublayer with residual
        ln1_out = self.ln1.forward(x, training)
        attn_out = self.mha.forward(ln1_out, training)
        x = x + attn_out                                  # residual

        # Feed-forward sublayer with residual
        ln2_out = self.ln2.forward(x, training)
        ff_out  = self.ff.forward(ln2_out, training)
        x = x + ff_out                                    # residual

        if training:
            self._cache = (ln1_out, ln2_out, x - ff_out)  # x before ff residual
        return x

    def backward(self, dout: np.ndarray):
        ln1_out, ln2_out, x_mid = self._cache

        # Backward through FF residual: dout flows into both FF path and skip
        dff_out = dout                                    # skip connection
        ff_grads, dln2_out = self.ff.backward(dff_out)
        ln2_grads, dx_mid = self.ln2.backward(dln2_out)
        dx_mid = dx_mid + dout                            # add skip gradient

        # Backward through attention residual
        dattn_out = dx_mid
        mha_grads, dln1_out = self.mha.backward(dattn_out)
        ln1_grads, dx = self.ln1.backward(dln1_out)
        dx = dx + dx_mid                                  # add skip gradient

        grads = {}
        for k, v in ln1_grads.items():  grads[f'ln1.{k}'] = v
        for k, v in mha_grads.items():  grads[f'mha.{k}'] = v
        for k, v in ln2_grads.items():  grads[f'ln2.{k}'] = v
        for k, v in ff_grads.items():   grads[f'ff.{k}']  = v
        return grads, dx

    def params(self):
        p = {}
        for k, v in self.ln1.params().items(): p[f'ln1.{k}'] = v
        for k, v in self.mha.params().items(): p[f'mha.{k}'] = v
        for k, v in self.ln2.params().items(): p[f'ln2.{k}'] = v
        for k, v in self.ff.params().items():  p[f'ff.{k}']  = v
        return p
