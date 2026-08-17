"""
Scaled dot-product attention and multi-head attention — manual forward/backward.

Scaled dot-product attention (Vaswani et al. 2017):

    Attention(Q, K, V) = softmax(Q @ K.T / sqrt(d_k)) @ V

Multi-head attention projects Q, K, V into h separate subspaces, runs
attention in each, then concatenates and projects back:

    head_i = Attention(Q @ W_q_i, K @ W_k_i, V @ W_v_i)
    MHA(Q, K, V) = concat(head_0, ..., head_{h-1}) @ W_o

All shapes use (T, d) row-vector convention — one token per row — which
matches PyTorch and makes the matrix maths read naturally.
"""

import numpy as np


# ---------------------------------------------------------------------------
# Softmax (row-wise, numerically stable)
# ---------------------------------------------------------------------------
def _softmax(x: np.ndarray) -> np.ndarray:
    """Row-wise softmax. x: (..., T, T) → same shape."""
    e = np.exp(x - x.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


# ---------------------------------------------------------------------------
# Scaled dot-product attention
# ---------------------------------------------------------------------------
class ScaledDotProductAttention:
    """
    Forward:
        scores = Q @ K.T / sqrt(d_k)          (T, T)
        weights = softmax(scores)              (T, T)  — stored for backward
        out = weights @ V                      (T, d_v)

    Backward (given dout: (T, d_v)):
        dV      = weights.T @ dout
        dweights = dout @ V.T
        dscores = softmax_backward(dweights, weights) / sqrt(d_k)
        dQ      = dscores @ K
        dK      = dscores.T @ Q
    """

    def __init__(self, mask: bool = False):
        """mask=True applies a causal (lower-triangular) mask — used in decoders."""
        self.mask = mask
        self._cache = None

    def forward(self, Q: np.ndarray, K: np.ndarray, V: np.ndarray,
                training: bool = True) -> np.ndarray:
        """
        Q, K : (T, d_k)
        V    : (T, d_v)
        Returns out: (T, d_v)
        """
        T, d_k = Q.shape
        scale = np.sqrt(d_k)

        scores = Q @ K.T / scale                          # (T, T)

        if self.mask:
            # Causal mask: position i cannot attend to position j > i
            causal = np.triu(np.full((T, T), -1e9), k=1)
            scores = scores + causal

        weights = _softmax(scores)                        # (T, T)
        out = weights @ V                                 # (T, d_v)

        if training:
            self._cache = (Q, K, V, weights, scale)
        return out

    def backward(self, dout: np.ndarray):
        """
        dout : (T, d_v)
        Returns dQ, dK, dV each matching their forward input shapes.
        """
        Q, K, V, weights, scale = self._cache

        dV = weights.T @ dout                             # (T, d_v)
        dweights = dout @ V.T                             # (T, T)

        # Backward through row-wise softmax:
        #   ds_i = w_i * (dw_i - sum_j(dw_j * w_j))
        dscores = weights * (dweights - (dweights * weights).sum(axis=-1, keepdims=True))
        dscores /= scale

        dQ = dscores @ K                                  # (T, d_k)
        dK = dscores.T @ Q                                # (T, d_k)

        return dQ, dK, dV


# ---------------------------------------------------------------------------
# Multi-head attention
# ---------------------------------------------------------------------------
class MultiHeadAttention:
    """
    Projects Q, K, V into h heads of dimension d_k = d_model // h each,
    runs scaled dot-product attention in parallel, concatenates, and
    projects back with W_o.

    Parameters
    ----------
    d_model : total model dimension
    n_heads : number of attention heads (d_model must be divisible by n_heads)
    mask    : causal mask (True for decoder / language model use)
    """

    def __init__(self, d_model: int, n_heads: int, mask: bool = False):
        assert d_model % n_heads == 0, "d_model must be divisible by n_heads"
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_k = d_model // n_heads
        self.mask = mask

        scale = np.sqrt(2.0 / (d_model + self.d_k))
        # One combined projection for Q, K, V: (d_model, 3*d_model)
        self.W_qkv = np.random.randn(d_model, 3 * d_model) * scale
        self.b_qkv = np.zeros(3 * d_model)
        # Output projection: (d_model, d_model)
        self.W_o = np.random.randn(d_model, d_model) * np.sqrt(2.0 / d_model)
        self.b_o = np.zeros(d_model)

        self._heads = [ScaledDotProductAttention(mask=mask) for _ in range(n_heads)]
        self._cache = None

    def forward(self, x: np.ndarray, training: bool = True) -> np.ndarray:
        """
        x   : (T, d_model)  — same tensor used as Q, K, V (self-attention)
        out : (T, d_model)
        """
        T = x.shape[0]
        d_k = self.d_k

        # Project to Q, K, V in one shot
        qkv = x @ self.W_qkv + self.b_qkv                # (T, 3*d_model)
        Q = qkv[:, :self.d_model]                         # (T, d_model)
        K = qkv[:, self.d_model:2*self.d_model]
        V = qkv[:, 2*self.d_model:]

        # Split into heads and run attention
        head_outs = []
        Qs, Ks, Vs = [], [], []
        for i, head in enumerate(self._heads):
            q_i = Q[:, i*d_k:(i+1)*d_k]                  # (T, d_k)
            k_i = K[:, i*d_k:(i+1)*d_k]
            v_i = V[:, i*d_k:(i+1)*d_k]
            Qs.append(q_i); Ks.append(k_i); Vs.append(v_i)
            head_outs.append(head.forward(q_i, k_i, v_i, training))

        concat = np.concatenate(head_outs, axis=-1)       # (T, d_model)
        out = concat @ self.W_o + self.b_o                # (T, d_model)

        if training:
            self._cache = (x, Q, K, V, Qs, Ks, Vs, concat)
        return out

    def backward(self, dout: np.ndarray):
        """
        dout : (T, d_model)
        Returns dW_qkv, db_qkv, dW_o, db_o, dx
        """
        x, Q, K, V, Qs, Ks, Vs, concat = self._cache
        d_k = self.d_k

        # Backward through output projection
        dW_o = concat.T @ dout                            # (d_model, d_model)
        db_o = dout.sum(axis=0)
        dconcat = dout @ self.W_o.T                       # (T, d_model)

        # Backward through each head
        dQ = np.zeros_like(Q)
        dK = np.zeros_like(K)
        dV = np.zeros_like(V)
        for i, head in enumerate(self._heads):
            dhead = dconcat[:, i*d_k:(i+1)*d_k]          # (T, d_k)
            dq_i, dk_i, dv_i = head.backward(dhead)
            dQ[:, i*d_k:(i+1)*d_k] = dq_i
            dK[:, i*d_k:(i+1)*d_k] = dk_i
            dV[:, i*d_k:(i+1)*d_k] = dv_i

        # Backward through QKV projection
        dqkv = np.concatenate([dQ, dK, dV], axis=-1)     # (T, 3*d_model)
        dW_qkv = x.T @ dqkv                              # (d_model, 3*d_model)
        db_qkv = dqkv.sum(axis=0)
        dx = dqkv @ self.W_qkv.T                         # (T, d_model)

        return {'W_qkv': dW_qkv, 'b_qkv': db_qkv,
                'W_o': dW_o, 'b_o': db_o}, dx

    def params(self):
        return {'W_qkv': self.W_qkv, 'b_qkv': self.b_qkv,
                'W_o': self.W_o, 'b_o': self.b_o}
