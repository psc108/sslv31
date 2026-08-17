"""
P4-05 — Attention mechanism verification and demo.

1. Numerical gradient check: confirms backward pass matches finite differences
   for both ScaledDotProductAttention and MultiHeadAttention.

2. Sequence copy task: trains a single MHA layer to copy a short integer
   sequence, demonstrating that attention learns to route information
   from the correct source positions to each output position.

Usage:
    python3 -m phase4.attention_test
"""

import numpy as np
from phase4.transformer.attention import ScaledDotProductAttention, MultiHeadAttention


# ---------------------------------------------------------------------------
# Numerical gradient check
# ---------------------------------------------------------------------------
def numerical_grad(f, x: np.ndarray, eps: float = 1e-5) -> np.ndarray:
    grad = np.zeros_like(x)
    it = np.nditer(x, flags=['multi_index'])
    while not it.finished:
        idx = it.multi_index
        orig = x[idx]
        x[idx] = orig + eps; fp = f(x)
        x[idx] = orig - eps; fm = f(x)
        x[idx] = orig
        grad[idx] = (fp - fm) / (2 * eps)
        it.iternext()
    return grad


def check_sdpa():
    np.random.seed(0)
    T, d = 4, 8
    Q = np.random.randn(T, d) * 0.1
    K = np.random.randn(T, d) * 0.1
    V = np.random.randn(T, d) * 0.1
    dout = np.random.randn(T, d)

    attn = ScaledDotProductAttention()
    attn.forward(Q, K, V)
    dQ_an, dK_an, dV_an = attn.backward(dout)

    def loss_Q(q): return (ScaledDotProductAttention().forward(q, K, V) * dout).sum()
    def loss_K(k): return (ScaledDotProductAttention().forward(Q, k, V) * dout).sum()
    def loss_V(v): return (ScaledDotProductAttention().forward(Q, K, v) * dout).sum()

    dQ_num = numerical_grad(loss_Q, Q.copy())
    dK_num = numerical_grad(loss_K, K.copy())
    dV_num = numerical_grad(loss_V, V.copy())

    errs = {
        'dQ': np.abs(dQ_an - dQ_num).max(),
        'dK': np.abs(dK_an - dK_num).max(),
        'dV': np.abs(dV_an - dV_num).max(),
    }
    print("ScaledDotProductAttention gradient check:")
    for name, err in errs.items():
        status = "✓" if err < 1e-5 else "✗"
        print(f"  {status} max|{name}_analytic - {name}_numeric| = {err:.2e}")
    return all(e < 1e-5 for e in errs.values())


def check_mha():
    np.random.seed(1)
    T, d_model, n_heads = 5, 8, 2
    x = np.random.randn(T, d_model) * 0.1
    dout = np.random.randn(T, d_model)

    mha = MultiHeadAttention(d_model, n_heads)
    mha.forward(x)
    grads, dx_an = mha.backward(dout)

    def loss_x(xi):
        m = MultiHeadAttention(d_model, n_heads)
        m.W_qkv[:] = mha.W_qkv
        m.b_qkv[:] = mha.b_qkv
        m.W_o[:]   = mha.W_o
        m.b_o[:]   = mha.b_o
        return (m.forward(xi) * dout).sum()

    dx_num = numerical_grad(loss_x, x.copy())
    err = np.abs(dx_an - dx_num).max()
    status = "✓" if err < 1e-4 else "✗"
    print(f"\nMultiHeadAttention gradient check:")
    print(f"  {status} max|dx_analytic - dx_numeric| = {err:.2e}")
    return err < 1e-4


# ---------------------------------------------------------------------------
# Sequence copy task
# ---------------------------------------------------------------------------
def softmax(x):
    e = np.exp(x - x.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


def train_copy_task():
    """
    Task: given a sequence of one-hot tokens, predict the same sequence
    shifted by one position (next-token prediction on a fixed pattern).
    A single MHA layer + linear head must learn to attend to the right
    source position for each output.
    """
    np.random.seed(42)
    vocab      = 8
    T          = 6       # sequence length
    d_model    = 32
    n_heads    = 2
    lr         = 0.01
    n_iters    = 3000

    # Fixed training sequence: [1, 3, 5, 2, 4, 6]
    seq = [1, 3, 5, 2, 4, 6]
    targets = seq[1:] + [seq[0]]   # next-token targets (circular)

    # Input embeddings: learned (vocab, d_model)
    E = np.random.randn(vocab, d_model) * 0.1
    # Output projection: (d_model, vocab)
    W_out = np.random.randn(d_model, vocab) * 0.1
    b_out = np.zeros(vocab)

    mha = MultiHeadAttention(d_model, n_heads, mask=True)
    mem = {k: np.zeros_like(v) for k, v in {**mha.params(),
           'E': E, 'W_out': W_out, 'b_out': b_out}.items()}

    for it in range(1, n_iters + 1):
        # Forward
        x = E[seq]                                        # (T, d_model)
        h = mha.forward(x)                                # (T, d_model)
        logits = h @ W_out + b_out                        # (T, vocab)
        probs = softmax(logits)

        # Cross-entropy loss
        loss = -np.log(probs[np.arange(T), targets] + 1e-8).mean()

        # Backward
        dlogits = probs.copy()
        dlogits[np.arange(T), targets] -= 1.0
        dlogits /= T

        dW_out = h.T @ dlogits                            # (d_model, vocab)
        db_out = dlogits.sum(axis=0)
        dh = dlogits @ W_out.T                            # (T, d_model)

        mha_grads, dx = mha.backward(dh)

        # Embedding gradient: scatter dx back to token rows
        dE = np.zeros_like(E)
        for t, tok in enumerate(seq):
            dE[tok] += dx[t]

        all_grads = {**mha_grads, 'E': dE, 'W_out': dW_out, 'b_out': db_out}
        all_params = {**mha.params(), 'E': E, 'W_out': W_out, 'b_out': b_out}

        # Adagrad
        for k in all_params:
            np.clip(all_grads[k], -1, 1, out=all_grads[k])
            mem[k] += all_grads[k] ** 2
            all_params[k] -= lr * all_grads[k] / (np.sqrt(mem[k]) + 1e-8)

        if it % 500 == 0 or it == 1:
            preds = probs.argmax(axis=-1).tolist()
            print(f"iter {it:>5}  loss {loss:.4f}  "
                  f"targets {targets}  preds {preds}  "
                  f"{'✓' if preds == targets else '✗'}")

    return preds == targets


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    ok1 = check_sdpa()
    ok2 = check_mha()
    print()
    print("--- Sequence copy task (causal MHA) ---")
    ok3 = train_copy_task()
    print()
    print("All checks passed." if (ok1 and ok2 and ok3) else "Some checks FAILED.")
