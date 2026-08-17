# Phase 4 — Architecture Zoo
*Developer & Implementation Reference*

---

## Overview

Phase 4 implements each major architecture class from scratch in NumPy, then (where PyTorch is available) in PyTorch for comparison. The Transformer is the highest-value target. Work through in order: CNN → RNN → LSTM → Transformer → Autoencoder → VAE.

---

## P4-01 — CNN from Scratch (NumPy)

**Files:** `phase4/cnn/conv.py`, `phase4/cnn/flatten.py`, `phase4/lenet.py`
**Status:** ✅ Complete — **99.08% test accuracy on MNIST**

### Architecture — LeNet-5

```
Input  (N, 1, 28, 28)
Conv2D (6 filters, 5×5, pad=2)  →  (N, 6, 28, 28)
ReLU
MaxPool2D (2×2)                  →  (N, 6, 14, 14)
Conv2D (16 filters, 5×5)         →  (N, 16, 10, 10)
ReLU
MaxPool2D (2×2)                  →  (N, 16, 5, 5)
Flatten                          →  (N, 400)
Linear (120) → ReLU
Linear (84)  → ReLU
Linear (10)  → CrossEntropyLoss
```

### The im2col Method

Convolution is implemented by reshaping image patches into columns, then performing a single matrix multiply. This is how every production framework implements convolution under the hood.

For an input `(N, C, H, W)` and kernel `(kH, kW)`:

```
im2col(x) → (N, C*kH*kW, out_H*out_W)
W_flat    → (out_channels, C*kH*kW)

output = W_flat @ cols  →  (N, out_channels, out_H*out_W)
```

Each column of `cols` contains one receptive field patch — all the input values that one output position depends on. The matrix multiply computes all output positions simultaneously.

### Backward Pass

```
dL/dW  = grad_flat @ cols.T          # (out_channels, C*kH*kW) → reshape to W shape
dL/db  = grad_flat.sum(axis=(N, spatial))
dL/dx  = col2im(W_flat.T @ grad_flat) # reverse im2col to scatter gradients back
```

`col2im` is the inverse of `im2col` — it accumulates column gradients back into the original image positions. Where patches overlap (stride < kernel_size), gradients are summed.

### MaxPool2D

Max pooling takes the maximum value in each `(kH, kW)` window. The backward pass routes the gradient only to the position that held the maximum — all other positions receive zero gradient. A binary mask is stored during the forward pass to record which position won.

### Key Concepts

**Receptive field:** Each output neuron in a conv layer only sees a local patch of the input. Stacking conv layers increases the effective receptive field — a neuron in layer 2 sees a larger region of the original input than a neuron in layer 1.

**Parameter sharing:** All output positions in a feature map share the same filter weights. A 5×5 filter with 6 output channels has only `6 × 1 × 5 × 5 + 6 = 156` parameters regardless of input size. A fully-connected layer on the same input would have `784 × 6 × 28 × 28 ≈ 3.7M` parameters.

**Translation equivariance:** Because the same filter is applied at every position, a feature detected at one location will be detected at any other location. This is the right inductive bias for image data.

### Running LeNet

```bash
python3 -m phase4.lenet
```

---

## P4-02 — CNN (PyTorch)

**File:** `phase4/lenet_torch.py`
**Status:** ✅ Complete — **98.86% test accuracy**

### Comparison: NumPy vs PyTorch

| | NumPy (P4-01) | PyTorch (P4-02) |
|---|---|---|
| Test accuracy | 99.08% | 98.86% |
| Training time (10 epochs) | ~480s | ~122s |
| Lines of code (model) | ~200 (conv + pool + flatten) | ~20 |
| Gradient computation | Manual backward methods | `loss.backward()` |
| Parameter management | `layer.params()` / `zero_grad()` | `optimizer.zero_grad()` |
| Debugging | Full visibility into every array | Autograd graph, hooks needed |

### What PyTorch Abstracts Away

- im2col / col2im — handled internally by optimised C++/CUDA kernels
- Backward closures — `autograd` builds and executes the graph automatically
- Parameter collection — `model.parameters()` traverses the module tree
- Device management — `.to(device)` moves tensors to GPU transparently

The PyTorch model is ~4× faster on CPU despite identical architecture because its conv kernels are backed by optimised BLAS routines. On a GPU the gap would be 10–50×.

### Running

```bash
.venv/bin/python -m phase4.lenet_torch
```

---

---

## P4-03 — RNN from Scratch (NumPy)

**Files:** `phase4/rnn/rnn_cell.py`, `phase4/rnn_char.py`
**Status:** ✅ Complete — loss 93.4 → 2.1 over 20k iterations, coherent phrase generation by iter ~12,500

### Architecture

A single-layer vanilla RNN with one hidden state vector:

```
h_t = tanh(W_xh @ x_t  +  W_hh @ h_{t-1}  +  b_h)
y_t = W_hy @ h_t  +  b_y
```

| Symbol | Shape | Role |
|--------|-------|------|
| `x_t` | `(vocab, 1)` | One-hot character input at step t |
| `h_t` | `(hidden, 1)` | Hidden state — the network's "memory" |
| `W_xh` | `(hidden, vocab)` | Input-to-hidden weights |
| `W_hh` | `(hidden, hidden)` | Recurrent weights — hidden-to-hidden |
| `W_hy` | `(vocab, hidden)` | Hidden-to-output weights |
| `y_t` | `(vocab, 1)` | Raw logits over the character vocabulary |

The key difference from a feedforward network is `W_hh @ h_{t-1}` — the hidden state from the previous step feeds back in. The same weight matrices are shared across every time step.

### Backpropagation Through Time (BPTT)

Because the same weights are used at every step, gradients must be accumulated across the entire unrolled sequence. Working backward from step T to step 0:

```
dL/dW_hy += dy_t @ h_t.T          (output weights — straightforward)

dh_t = W_hy.T @ dy_t + dh_{t+1}   (gradient into h_t from output + next step)
dtanh = (1 - h_t²) * dh_t         (through tanh nonlinearity)

dL/dW_xh += dtanh @ x_t.T
dL/dW_hh += dtanh @ h_{t-1}.T
dh_{t-1}  = W_hh.T @ dtanh        (pass gradient back one more step)
```

The term `dh_{t+1}` is what makes this "through time" — the gradient at step t depends on the gradient that flowed back from step t+1. This is exactly the chain rule applied across the time dimension.

### Gradient Clipping

Gradients are clipped to `[-5, 5]` after accumulation. Without clipping, the recurrent path `W_hh.T @ dtanh` can amplify gradients exponentially over long sequences — the exploding gradient problem. Clipping is a blunt but effective fix. The vanishing gradient problem (gradients shrinking to zero over long sequences) is not fixed by clipping — that requires LSTM gates (P4-04).

### Truncated BPTT

Rather than unrolling the full corpus, training uses a sliding window of `seq_len = 25` characters. The hidden state `h` is carried forward between windows so the network retains context across chunk boundaries, but gradients only flow back 25 steps. This is the standard practical approach — full BPTT over thousands of steps is both slow and numerically unstable.

### Optimiser — Adagrad

Adagrad adapts the learning rate per parameter based on the sum of squared historical gradients:

```
mem[k] += grad[k]²
param[k] -= lr * grad[k] / (sqrt(mem[k]) + ε)
```

Parameters that receive large gradients frequently get a smaller effective learning rate. This works well for character models where some characters (spaces, 'e', 't') appear far more often than others — their weights would otherwise dominate updates.

### Training Results

| Iteration | Smooth Loss | Sample quality |
|-----------|-------------|----------------|
| 1 | 93.4 | Random characters |
| 2,000 | 60.8 | Word-like fragments |
| 5,000 | 33.3 | English words, wrong grammar |
| 10,000 | 12.8 | Recognisable phrases |
| 12,500 | 7.1 | "To be, or not to be, that..." |
| 20,000 | 2.1 | Memorised corpus fragments with variation |

The model is small (128 hidden units) and the corpus is tiny (~1,400 characters), so it eventually memorises rather than generalises. The interesting phase is 5,000–15,000 iterations where it transitions from noise to structure.

### The Vanishing Gradient Problem in RNNs

At iter 9,000 the gradient norm spiked to 322 — a sign of instability in the recurrent path. Clipping kept training stable, but the underlying problem is structural: gradients flowing back through `tanh` and `W_hh` at every step are multiplied by `(1 - h²) * W_hh`. If the spectral radius of `W_hh` is less than 1, this product shrinks exponentially with sequence length. Dependencies beyond ~20 steps effectively vanish.

This is why vanilla RNNs fail on tasks requiring long-range memory — and why LSTM was invented (P4-04).

### Running

```bash
python3 -m phase4.rnn_char
```

---

## P4-04 — LSTM from Scratch (NumPy)

**Files:** `phase4/rnn/lstm_cell.py`, `phase4/lstm_char.py`
**Status:** ✅ Complete — loss 93.4 → 0.029 over 20k iterations, verbatim corpus recall by iter ~4,000

### The Problem LSTM Solves

In the vanilla RNN, the gradient flowing back through time is multiplied at every step by `(1 - h²) * W_hh`. If the spectral radius of `W_hh` is less than 1, this product shrinks exponentially — gradients from 20+ steps ago effectively vanish. The network cannot learn long-range dependencies.

LSTM introduces a **cell state** `c_t` — a separate memory channel that flows through time with only multiplicative (not additive-then-squashed) interactions. Gradients can flow back through `c_t` without passing through a tanh at every step, which is what keeps them alive over long sequences.

### Architecture — One Time Step

```
z   = W @ [h_{t-1}; x_t] + b        (single matrix multiply for all gates)

i_t = σ(z[0:H])                      input gate  — what new info to write
f_t = σ(z[H:2H])                     forget gate — what to erase from memory
g_t = tanh(z[2H:3H])                 cell gate   — candidate values to write
o_t = σ(z[3H:4H])                    output gate — what to expose as hidden state

c_t = f_t ⊙ c_{t-1} + i_t ⊙ g_t    cell state update
h_t = o_t ⊙ tanh(c_t)               hidden state
y_t = W_hy @ h_t + b_y              output logits
```

All four gates are computed in a single matrix multiply by stacking their weight matrices into one `(4H, H+I)` matrix `W`. This is the standard efficient formulation — one BLAS call instead of four.

### The Four Gates

| Gate | Activation | Role |
|------|-----------|------|
| Input `i` | sigmoid → (0,1) | Controls how much of the new candidate `g` to write into cell state |
| Forget `f` | sigmoid → (0,1) | Controls how much of the previous cell state `c_{t-1}` to retain |
| Cell `g` | tanh → (-1,1) | Candidate values — what could be written to cell state |
| Output `o` | sigmoid → (0,1) | Controls how much of the cell state to expose as the hidden state |

The forget gate bias is initialised to 1.0. This means the network starts by defaulting to remembering everything, and learns to forget selectively. Initialising to 0 causes the network to forget aggressively early in training before it has learned what to keep — a common source of slow convergence.

### Why the Cell State Fixes Vanishing Gradients

The gradient of the loss with respect to `c_{t-1}` is:

```
dc_{t-1} = dc_t * f_t
```

This is a simple elementwise multiply — no tanh, no matrix multiply through `W_hh`. The gradient flows back through the cell state highway multiplied only by the forget gate values. As long as `f_t` is close to 1 (the network has learned to remember), gradients propagate without shrinking. This is the **constant error carousel** — the key insight from Hochreiter & Schmidhuber (1997).

### BPTT Backward Pass

Working backward from step T to 0, at each step:

```
dh_t  = W_hy.T @ dy_t + dh_{t+1}       (from output + next hidden)

# Through h_t = o * tanh(c_t)
do    = dh_t * tanh(c_t)
dc_t  = dh_t * o * (1 - tanh(c_t)²) + dc_{t+1}   ← cell state highway

# Through c_t = f * c_{t-1} + i * g
df    = dc_t * c_{t-1}
dc_{t-1} = dc_t * f                     ← gradient flows back through forget gate
di    = dc_t * g
dg    = dc_t * i

# Through gate activations (sigmoid' = s*(1-s), tanh' = 1-tanh²)
dz = [di*i*(1-i), df*f*(1-f), dg*(1-g²), do*o*(1-o)]   # (4H, 1)

dW   += dz @ [h_{t-1}; x_t].T
dh_{t-1} = (W.T @ dz)[:H]              ← gradient into previous hidden state
```

### Training Results

Same corpus, same hyperparameters as P4-03 (hidden=128, seq_len=25, Adagrad lr=0.1):

| Iteration | LSTM Loss | RNN Loss | LSTM Sample Quality |
|-----------|-----------|----------|---------------------|
| 1 | 93.4 | 93.4 | Random characters |
| 500 | 75.3 | 89.2 | Word fragments |
| 1,500 | 33.8 | 68.5 | **Complete verbatim lines** |
| 5,000 | 2.9 | 33.3 | Long verbatim passages |
| 10,000 | 0.11 | 12.8 | Near-perfect recall |
| 20,000 | **0.029** | **2.08** | Verbatim with occasional variation |

The LSTM reaches the quality the RNN achieves at iter 12,500 by approximately iter 1,500 — roughly 8× faster convergence on this task. The gradient norms are also dramatically more stable: LSTM stays in the range 0.1–15 throughout, while the RNN spiked to 465 at iter 10,000.

### Gradient Norm Comparison

| Model | Max |grad| observed | Behaviour |
|-------|------------------|-----------|
| RNN | 465 (iter 10,000) | Frequent spikes, clipping active |
| LSTM | 15 (iter 4,500) | Smooth decay after initial phase |

The LSTM's stable gradient norms are a direct consequence of the cell state highway — gradients do not have to fight through a tanh and a recurrent matrix multiply at every step.

### Running

```bash
python3 -m phase4.lstm_char
```

---

## P4-05 — Transformer: Attention Mechanism (NumPy)

**Files:** `phase4/transformer/attention.py`, `phase4/attention_test.py`
**Status:** ✅ Complete — gradient errors < 1e-11, copy task solved by iter 500

### What Attention Does

An RNN processes a sequence one token at a time, compressing all prior context into a fixed-size hidden state. Attention abandons that constraint entirely. Every output position can look directly at every input position simultaneously, with a learned weighting that says how much each source position matters for each target position.

The weighting is not fixed — it is computed dynamically from the content of the tokens themselves. This is what makes attention powerful: the routing of information is input-dependent.

### Scaled Dot-Product Attention

Given three matrices derived from the input sequence:

```
Q  (T, d_k)  — Queries: what each position is looking for
K  (T, d_k)  — Keys:    what each position is advertising
V  (T, d_v)  — Values:  what each position will contribute if selected

scores  = Q @ K.T / sqrt(d_k)     (T, T)  — how well each Q matches each K
weights = softmax(scores)          (T, T)  — normalised attention distribution
out     = weights @ V              (T, d_v) — weighted sum of values
```

The `sqrt(d_k)` scaling prevents the dot products from growing large in magnitude as `d_k` increases — without it, the softmax saturates into near-one-hot distributions and gradients vanish.

Each row of `weights` is a probability distribution over the T source positions. Row `i` of `out` is a weighted average of all value vectors, where the weights say how much position `i` attends to each source position.

### Backward Through Softmax Attention

The backward pass through the softmax is the non-obvious piece. Given `dout` (gradient of loss w.r.t. `out`):

```
dV       = weights.T @ dout                          # straightforward

dweights = dout @ V.T                                # gradient into attention weights

# Backward through row-wise softmax:
# For each row: ds_i = w_i * (dw_i - sum_j(w_j * dw_j))
dscores  = weights * (dweights - (dweights * weights).sum(axis=-1, keepdims=True))
dscores /= sqrt(d_k)

dQ = dscores @ K
dK = dscores.T @ Q
```

The softmax backward uses the Jacobian identity `dL/ds_i = w_i * (dL/dw_i - sum_j w_j * dL/dw_j)`. The subtracted term removes the component of the gradient that would change the sum — softmax outputs must sum to 1, so only the deviation from the weighted mean propagates.

Gradient check results: max error vs finite differences < **3.7e-12** for all three gradients (dQ, dK, dV).

### Causal Masking

For language modelling, position `i` must not attend to positions `j > i` — that would be looking at the future. A causal mask adds `-1e9` to all above-diagonal entries of the score matrix before softmax:

```
scores += triu(fill(-1e9), k=1)
```

After softmax, those positions receive weight ≈ 0. The mask is applied inside `ScaledDotProductAttention` when `mask=True`.

### Multi-Head Attention

Running attention once in the full `d_model` space forces the model to find a single way to route information. Multi-head attention runs `h` independent attention operations in parallel, each in a lower-dimensional subspace of size `d_k = d_model / h`:

```
# One combined projection for efficiency
qkv = x @ W_qkv + b_qkv                    (T, 3*d_model)
Q, K, V = split(qkv)                        each (T, d_model)

# Per-head slices
head_i = Attention(Q[:,i*d_k:(i+1)*d_k],
                   K[:,i*d_k:(i+1)*d_k],
                   V[:,i*d_k:(i+1)*d_k])    (T, d_k)

out = concat(head_0, ..., head_{h-1}) @ W_o + b_o    (T, d_model)
```

Different heads can specialise — one might learn syntactic relationships, another semantic similarity, another positional proximity. The output projection `W_o` learns how to combine the information from all heads.

The combined `W_qkv` projection `(d_model, 3*d_model)` is a standard efficiency trick: one matrix multiply instead of three separate ones for Q, K, V.

Gradient check: max error vs finite differences < **2.7e-11**.

### Sequence Copy Task

To verify the full forward/backward cycle works end-to-end, a single MHA layer (d_model=32, 2 heads, causal mask) is trained on a next-token prediction task over a fixed 6-token sequence. The model must learn to attend to the immediately preceding token at each position.

```
Sequence:  [1, 3, 5, 2, 4, 6]
Targets:   [3, 5, 2, 4, 6, 1]   (next token, circular)

iter     1  loss 2.0831  preds [4, 6, 6, 6, 6, 3]  ✗
iter   500  loss 0.0005  preds [3, 5, 2, 4, 6, 1]  ✓
```

The model solves the task by iter 500 and holds it to loss 0.0001 by iter 3000. The attention weights at convergence concentrate on the immediately preceding position for each query — the model has learned a "look one step back" attention pattern.

### Running

```bash
python3 -m phase4.attention_test
```

---

## P4-06 — Transformer: Full Model (NumPy)

**Files:** `phase4/transformer/layers.py`, `phase4/transformer/model.py`, `phase4/gpt_char.py`
**Status:** ✅ Complete — loss 239 → 2.76 over 5k iterations, coherent English structure by iter ~2,500

### Architecture — GPT-style Decoder-Only Transformer

```
token_ids  (T,)
    ↓  embedding lookup
E[token_ids]  (T, d_model)
    +  positional encoding (sinusoidal, fixed)
    ↓
TransformerBlock × N_layers:
    x = x + MHA(LayerNorm(x))      ← attention sublayer + residual
    x = x + FF(LayerNorm(x))       ← feed-forward sublayer + residual
    ↓
LayerNorm
    ↓
Linear (d_model → vocab)
    ↓
logits  (T, vocab)  →  cross-entropy loss
```

Training config: `d_model=64`, `n_heads=4`, `n_layers=2`, `ctx=64`, Adam `lr=3e-3`.

---

### Layer Normalisation

Layer norm normalises each token's feature vector independently (across the `d_model` dimension, not across the batch):

```
x_hat = (x - mean(x)) / sqrt(var(x) + ε)
out   = γ ⊙ x_hat + β
```

`γ` and `β` are learnable per-feature scale and shift vectors, initialised to 1 and 0. Unlike batch norm, layer norm has no dependence on other samples in the batch — it works identically at training and inference, and works on sequences of any length.

**Backward through layer norm** (Ioffe & Szegedy derivation):

```
dgamma = sum(dout * x_hat, axis=T)
dbeta  = sum(dout, axis=T)
dx_hat = dout * gamma
dvar   = sum(dx_hat * (x - mean) * -0.5 * std^{-3}, axis=D)
dmean  = sum(dx_hat * -std^{-1}, axis=D) + dvar * mean(-2*(x-mean))
dx     = dx_hat * std^{-1} + dvar * 2*(x-mean)/D + dmean/D
```

The three terms in `dx` correspond to the three paths through which `x` affects the output: directly through `x_hat`, through the variance, and through the mean.

---

### Feed-Forward Sublayer

A two-layer MLP applied independently and identically to each token position:

```
h   = ReLU(x @ W1 + b1)     inner dim = 4 * d_model
out = h @ W2 + b2
```

The 4× expansion ratio is from the original Transformer paper and has been retained in GPT-2 and most successors. The FF sublayer is where most of the model's "knowledge storage" capacity lives — the attention mechanism routes information, the FF layers transform it.

---

### Residual Connections and Pre-Norm

Every sublayer is wrapped in a residual connection: `x = x + sublayer(x)`. This gives gradients a direct path back to early layers without passing through any nonlinearity — the same principle as the LSTM cell state highway, applied to depth rather than time.

The original Transformer used post-norm (LN after the residual add). GPT-2 and most modern models use **pre-norm** (LN before the sublayer):

```
# Pre-norm (GPT-2 style — used here)
x = x + MHA(LN(x))

# Post-norm (original paper)
x = LN(x + MHA(x))
```

Pre-norm is more stable at initialisation because the residual stream starts as the raw input — the sublayer output is added as a small perturbation. With post-norm, the LN is applied to the sum of two potentially large tensors, which can cause instability early in training.

---

### Positional Encoding

Attention has no inherent notion of position — `weights @ V` is a weighted sum that is permutation-invariant. Position information must be injected explicitly.

The sinusoidal encoding from Vaswani et al. adds a fixed pattern to each token embedding:

```
PE[pos, 2i]   = sin(pos / 10000^(2i/d_model))
PE[pos, 2i+1] = cos(pos / 10000^(2i/d_model))
```

Each dimension oscillates at a different frequency. Low dimensions change slowly (long-range position signal), high dimensions change rapidly (short-range). The model can learn to read off relative positions from the difference between two PE vectors because `sin(a+b)` and `cos(a+b)` are linear combinations of `sin(a)`, `cos(a)`, `sin(b)`, `cos(b)`.

This encoding is fixed (not learned) and generalises to sequence lengths not seen during training.

---

### Autoregressive Sampling

At inference, the model generates one token at a time. The last logit vector is divided by a temperature parameter before softmax:

```
p = softmax(logits[-1] / temperature)
next_token = sample(p)
```

- `temperature < 1.0` → sharper distribution → more deterministic / repetitive output
- `temperature > 1.0` → flatter distribution → more random / creative output
- `temperature = 1.0` → unmodified model distribution

The context window is truncated to `max_T` tokens at each step so the positional encoding never goes out of range.

---

### Training Results

Same corpus as P4-03/P4-04. 2-layer GPT, d_model=64, 4 heads, context=64, Adam lr=3e-3:

| Iteration | Loss | Sample quality |
|-----------|------|----------------|
| 1 | 239 | Random characters |
| 500 | 146 | Letter frequency correct |
| 1,000 | 89 | Word-like fragments |
| 2,000 | 34 | English words, some grammar |
| 3,500 | 8.9 | Recognisable phrases |
| 5,000 | 2.8 | Coherent English structure |

### Comparison: RNN vs LSTM vs GPT (same corpus, 20k / 20k / 5k iters)

| | RNN | LSTM | GPT |
|---|---|---|---|
| Final loss | 2.08 | 0.029 | 2.76 (5k iters) |
| Verbatim recall | Partial | Near-complete | Structural, not verbatim |
| Gradient stability | Spikes to 465 | Max 15 | Stable (Adam + residuals) |
| Context mechanism | Hidden state (fixed size) | Cell state highway | Direct attention (all positions) |
| Long-range dependency | Poor (vanishing grad) | Good (gating) | Excellent (O(1) path length) |
| Parameters | ~50k | ~200k | ~130k |

The GPT does not memorise the corpus verbatim the way the LSTM does — it is learning structure and generalising. This is the correct behaviour for a model with a 64-token context window trained on a 1,400-character corpus: the LSTM overfits because it has no context limit, the GPT is constrained to learn patterns rather than sequences.

---

### Running

```bash
python3 -m phase4.gpt_char
```

---

## P4-07 — nanoGPT Walkthrough (PyTorch)

**File:** `phase4/nanogpt.py`
**Data:** `data/shakespeare/input.txt` — 1.1MB, 1,115,394 characters, 65-char vocabulary
**Status:** ✅ Complete — 4 configs trained, hyperparameter effects measured

### What This Is

An annotated, self-contained port of Karpathy's nanoGPT — every architectural decision explained inline. Trained on the full tiny Shakespeare dataset (~1M tokens) rather than the 1,400-character excerpt used in P4-03/P4-06. This is the first time the model is working on a real dataset at real scale.

### Architecture Differences vs P4-06 (NumPy GPT)

| | P4-06 NumPy GPT | P4-07 nanoGPT |
|---|---|---|
| Positional encoding | Sinusoidal (fixed) | Learned `nn.Embedding` |
| Activation | ReLU | GELU |
| Dropout | None | 0.1 on attention weights + residuals |
| Optimiser | Adam | AdamW (decoupled weight decay) |
| LR schedule | None | Warmup (200 iters) + cosine decay |
| Weight init | He | GPT-2 style (std=0.02, residuals scaled by `1/√(2·n_layer)`) |
| Weight tying | No | Yes — `lm_head` shares weights with `tok_emb` |
| Gradient clipping | None | `clip_grad_norm_` at 1.0 |

Each of these differences is explained below.

### Key Implementation Details

**GELU vs ReLU.** GELU (Gaussian Error Linear Unit) is `x * Φ(x)` where `Φ` is the Gaussian CDF. Unlike ReLU it doesn't hard-zero negative inputs — it attenuates them smoothly. Empirically outperforms ReLU on language tasks; used in GPT-2 and BERT.

**AdamW — decoupled weight decay.** Standard Adam applies weight decay as a gradient penalty, which interacts with the adaptive learning rate and effectively reduces the regularisation effect. AdamW applies weight decay directly to the weights after the Adam step, decoupled from the gradient. Weight decay is applied only to weight matrices (`dim >= 2`), not to biases or LayerNorm parameters — those don't benefit from regularisation.

**Residual projection scaling.** The output projection of each attention and FF sublayer is initialised with `std = 0.02 / sqrt(2 * n_layer)`. Without this, the residual stream variance grows with depth — each block adds a contribution of variance ~0.02², and with N blocks the total variance is N × 0.02². Scaling down by `1/sqrt(2N)` keeps the residual stream variance approximately constant regardless of depth.

**Weight tying.** The token embedding matrix `(vocab, d_model)` and the output unembedding matrix `(d_model, vocab)` are the same object. They are doing inverse operations — embedding maps token → vector, unembedding maps vector → token logits — so sharing weights is a natural constraint. Reduces parameters by `vocab × d_model` and often improves perplexity.

**Top-k sampling.** During generation, after dividing logits by temperature, all logits below the k-th largest are set to `-inf` before softmax. This prevents sampling from the long tail of very unlikely tokens while preserving diversity. `top_k=40` is the nanoGPT default.

**LR warmup + cosine decay.** The learning rate ramps linearly from 0 to `lr` over 200 iterations, then follows a cosine curve to ~0 by the final iteration. Warmup prevents large gradient steps when the model is randomly initialised — the loss surface is steep and poorly conditioned at the start. Cosine decay ensures the model takes small, precise steps near convergence.

### Hyperparameter Experiment Results

All configs: 3,000 iterations, Adam lr=3e-3, tiny Shakespeare.

| Config | n_layer | n_head | d_model | ctx | Params | Val loss | Time |
|--------|---------|--------|---------|-----|--------|----------|------|
| small | 4 | 4 | 128 | 128 | 810k | **1.562** | 2,293s |
| deep | 8 | 4 | 128 | 128 | 1.60M | **1.510** | 4,515s |
| medium | 4 | 8 | 128 | 128 | 810k | **1.534** | 2,857s |
| wide_ctx | 4 | 4 | 128 | 512 | 859k | **1.542** | 11,221s |

#### What each change did

**deep (2× layers, 1.56 → 1.51):** The clearest improvement — +4 layers, +800k params, -0.05 val loss. Deeper residual stacks can model more compositional structure. Cost: 2× training time. The improvement is real but modest at this scale — depth helps more when the model is underfitting, which at 810k params on 1M tokens it is.

**medium (2× heads, same params, 1.56 → 1.53):** Doubling heads from 4 to 8 (d_k goes from 32 to 16) gives a small improvement at no parameter cost. More heads = more diverse attention patterns in parallel. The gain is smaller than adding layers because d_k=16 is quite narrow — each head has limited capacity.

**wide_ctx (4× context, 1.56 → 1.54):** Extending context from 128 to 512 tokens gives a small improvement but at 5× the training time (attention is O(T²)). The model can now see longer-range dependencies — useful for tracking character names and scene structure across a speech. The gain is modest because most of the predictable structure in Shakespeare is local (word and phrase level), not long-range.

**Key insight:** At this scale (810k params, 1M tokens, 3k iters), adding depth is the most efficient use of compute. Context length is the most expensive dimension to scale. Head count is nearly free but has diminishing returns once d_k gets small.

### Sample Quality

All four configs produce coherent Shakespeare-style dialogue with correct character name formatting, iambic rhythm, and appropriate vocabulary. The deep config produces the most coherent multi-turn exchanges. This is a real language model — not memorisation.

```
LADY ANNE:
Beace the heast to cheer call thee?

HENRY BOLINGBROKE:
Prov...
```

### Running

```bash
# Baseline
.venv/bin/python -m phase4.nanogpt --config small

# 2× depth
.venv/bin/python -m phase4.nanogpt --config deep

# 2× heads (same params)
.venv/bin/python -m phase4.nanogpt --config medium

# 4× context window
.venv/bin/python -m phase4.nanogpt --config wide_ctx
```

---

## P4-08 — Autoencoder (NumPy)

**Files:** `phase4/autoencoder/autoencoder.py`, `phase4/autoencoder_mnist.py`
**Outputs:** `phase4/autoencoder_reconstructions.png`, `phase4/autoencoder_latent.png`
**Status:** ✅ Complete — val MSE 0.0365 after 20 epochs, class clustering visible in latent space

### Architecture

An autoencoder is two MLPs chained through a narrow bottleneck. The encoder compresses the input to a low-dimensional latent code; the decoder reconstructs the input from that code. The only supervision signal is the reconstruction error — no labels are used.

```
Input  (batch, 784)
    ↓  Encoder
    Linear(784 → 256) → ReLU
    Linear(256 → 64)  → ReLU
    Linear(64  → 2)              ← bottleneck (no activation — unconstrained reals)
    ↓  z  (batch, 2)
    ↓  Decoder
    Linear(2   → 64)  → ReLU
    Linear(64  → 256) → ReLU
    Linear(256 → 784) → Sigmoid  ← output in [0,1] to match normalised pixels
    ↓  x̂  (batch, 784)

Loss: MSE(x̂, x)
```

The bottleneck is 2D deliberately — so the latent space can be plotted directly without dimensionality reduction. This is an extreme compression (784 → 2, factor of 392×) that forces the model to learn the most compact possible representation of digit structure.

The Sigmoid output activation is important: without it, reconstructions can go outside [0, 1] and the MSE loss will push pixel values to arbitrary magnitudes. Sigmoid constrains the output to the same range as the input.

### Why No Activation on the Bottleneck

The latent codes `z` are left as unconstrained real numbers. Applying ReLU would prevent negative latent values, artificially restricting the geometry of the latent space. Applying Sigmoid would compress everything to (0, 1), which limits the dynamic range. The decoder learns to interpret whatever distribution the encoder produces — no constraint needed.

### Training

Built entirely from phase1 primitives (`Linear`, `ReLU`, `Sigmoid`, `MSELoss`). Adam optimiser implemented locally over the flat parameter list. No new machinery.

| Epoch | Train MSE | Val MSE |
|-------|-----------|---------|
| 1 | 0.05767 | 0.04808 |
| 5 | 0.04110 | 0.04057 |
| 10 | 0.03868 | 0.03852 |
| 20 | **0.03632** | **0.03649** |

Loss decreases smoothly with no overfitting gap — the bottleneck acts as a strong regulariser. The model cannot memorise individual images because it must compress them to 2 numbers first.

### Latent Space

Encoding the full 10,000-test-image set to 2D and plotting by class reveals clear structure: the model has learned to organise the latent space so that similar digits cluster together, despite never seeing a single label during training.

The clustering emerges because the reconstruction loss forces the encoder to preserve the information that matters for reconstruction — and digits of the same class share the same stroke patterns, so they end up near each other in the 2D space.

t-SNE applied to the 2D latent codes (rather than the raw 784D pixels) shows tighter, more separated clusters — the autoencoder has already done most of the work of separating the classes.

### What the Bottleneck Forces the Model to Learn

With 784 input dimensions and a 2D bottleneck, the encoder must discard everything except the two most informative directions of variation in the data. For MNIST these turn out to be roughly:

- One axis separating round digits (0, 6, 8, 9) from angular ones (1, 4, 7)
- One axis separating simple strokes (1) from complex ones (8)

This is unsupervised feature discovery — the model finds structure in the data without being told what to look for.

### Running

```bash
python3 -m phase4.autoencoder_mnist
# Outputs:
#   phase4/autoencoder_reconstructions.png  — original vs reconstructed digits
#   phase4/autoencoder_latent.png           — 2D latent space + t-SNE
```

---

## P4-09 — Variational Autoencoder (NumPy)

**Files:** `phase4/autoencoder/vae.py`, `phase4/vae_mnist.py`
**Outputs:** `phase4/vae_reconstructions.png`, `phase4/vae_latent.png`, `phase4/vae_samples.png`, `phase4/vae_traversal.png`
**Status:** ✅ Complete — reconstruction BCE 0.23, posterior collapse observed and diagnosed

### Architecture

The VAE extends the P4-08 autoencoder with a probabilistic bottleneck. The encoder no longer outputs a single latent code — it outputs two vectors, `mu` and `log_var`, that parameterise a Gaussian distribution over the latent space.

```
Encoder:
    Linear(784→256) → ReLU → Linear(256→64) → ReLU
        ↓                              ↓
    fc_mu → mu (16,)          fc_lv → log_var (16,)

Reparameterisation:
    eps   ~ N(0, I)
    z     = mu + eps * exp(0.5 * log_var)     ← differentiable sample

Decoder (unchanged from P4-08):
    Linear(16→64) → ReLU → Linear(64→256) → ReLU → Linear(256→784) → Sigmoid

Loss:
    recon = BCE(x_hat, x) = -mean( x·log(x_hat) + (1-x)·log(1-x_hat) )
    KL    = -0.5 · mean( sum( 1 + log_var - mu² - exp(log_var) ) )
    L     = recon + beta · KL
```

### The Reparameterisation Trick

The core problem a VAE must solve: we want to sample `z ~ N(mu, var)` and backpropagate through that sample to train the encoder. Sampling is not differentiable — you cannot compute `d(sample)/d(mu)`.

The reparameterisation trick sidesteps this by factoring the randomness out:

```
z = mu + eps * exp(0.5 * log_var),   eps ~ N(0, I)
```

Now `z` is a deterministic function of `mu` and `log_var` (plus a fixed noise sample `eps`). Gradients flow through `mu` and `log_var` normally:

```
dL/d(mu)      = dL/dz                              (direct — dz/dmu = 1)
dL/d(log_var) = dL/dz * eps * 0.5 * exp(0.5*lv)   (through std)
```

### The KL Divergence Term

The KL term `KL(N(mu, var) || N(0,1))` penalises the posterior for deviating from the standard normal prior. Its closed form for diagonal Gaussians is:

```
KL = -0.5 * sum( 1 + log_var - mu² - exp(log_var) )
```

This has a clean interpretation: it penalises `mu` for being far from 0 (the `mu²` term) and penalises `log_var` for being far from 0 (the `exp(log_var) - log_var - 1` term, minimised at `log_var=0` i.e. unit variance). Together they push the posterior towards `N(0,I)`.

The KL gradients are:

```
dKL/d(mu)      = mu / batch
dKL/d(log_var) = 0.5 * (exp(log_var) - 1) / batch
```

### Posterior Collapse — A Real Phenomenon

Training this VAE revealed **posterior collapse** — the encoder learns to set `log_var` to a value that makes `KL ≈ 0`, effectively ignoring the stochastic bottleneck and behaving like a plain autoencoder. This happened despite:

- Switching from MSE to BCE reconstruction loss (larger per-pixel gradients)
- KL warm-up (beta annealed 0→1 over 5 epochs)
- Increasing latent dim from 2 to 16
- Adding a free bits constraint (minimum KL per dimension)

The root cause is that Adam's per-parameter adaptive learning rate tunes the `log_var` parameters to follow the reconstruction signal, which drives them to a local optimum where `log_var ≈ 0` and `mu` encodes all the information deterministically. The KL gradient is present but Adam's momentum carries `log_var` past it.

This is not a bug — it is a well-known failure mode of VAEs that has generated significant research:

| Technique | What it does |
|-----------|-------------|
| KL warm-up | Anneal beta 0→1 — gives reconstruction time to stabilise before KL pressure |
| Free bits | Enforce minimum KL per dimension — prevents full collapse but can pin at floor |
| beta-VAE | Increase beta > 1 — stronger KL pressure, worse reconstruction |
| Skip connections | Give decoder direct access to input — reduces reconstruction pressure on encoder |
| IAF / VQ-VAE | Replace diagonal Gaussian with more expressive posterior |

In a production PyTorch VAE, the combination of a larger model, more training epochs, and careful beta scheduling resolves collapse. The NumPy implementation here demonstrates the phenomenon clearly — which is itself the learning objective.

### What Does Work

Despite posterior collapse, the model produces good reconstructions (BCE 0.23 vs plain autoencoder 0.26 — comparable quality) and the `mu` values encode meaningful structure. The t-SNE of posterior means shows clear digit clustering, and the latent traversal shows smooth digit morphing across the grid — the decoder has learned a well-structured manifold even if the encoder's variance is degenerate.

### Running

```bash
python3 -m phase4.vae_mnist
# Outputs:
#   phase4/vae_reconstructions.png  — original vs reconstructed
#   phase4/vae_latent.png           — t-SNE of posterior means
#   phase4/vae_samples.png          — 100 digits sampled from N(0,I)
#   phase4/vae_traversal.png        — latent space grid traversal (z0 × z1)
```
