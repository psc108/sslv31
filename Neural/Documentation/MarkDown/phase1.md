# Phase 1 — Foundations: Raw NumPy, No Frameworks
*Developer & Implementation Reference*

---

## Overview

Phase 1 builds a working neural network library in pure Python and NumPy — no frameworks. The goal is a real, small autograd system with forward/backward passes, loss functions, and a training loop, culminating in 97%+ accuracy on MNIST.

---

## P1-01 — Scalar Autograd Engine

**File:** `phase1/autograd/engine.py`
**Status:** ✅ Complete

### What It Does

Implements reverse-mode automatic differentiation on individual scalar values. Every arithmetic operation builds a node in a computation graph. Calling `.backward()` on any node propagates gradients back through the entire graph to all leaf inputs.

### The Value Class

```python
from phase1.autograd import Value

a = Value(2.0)
b = Value(-3.0)
c = Value(10.0)

L = (a * b + c).relu()
L.backward()

print(a.grad)   # -3.0
print(b.grad)   #  2.0
print(c.grad)   #  1.0
```

Each `Value` holds:

| Attribute | Type | Purpose |
|-----------|------|---------|
| `data` | `float` | The scalar value |
| `grad` | `float` | Accumulated gradient ∂L/∂self |
| `_prev` | `set` | Child nodes this value was computed from |
| `_op` | `str` | The operation that produced this node (debug/display) |
| `_backward` | `callable` | Closure that propagates gradient one step back |

### Supported Operations

| Operation | Method | Notes |
|-----------|--------|-------|
| Addition | `__add__` | Also `__radd__` for `scalar + Value` |
| Multiplication | `__mul__` | Also `__rmul__` |
| Power | `__pow__` | Scalar exponent only |
| Negation | `__neg__` | Implemented as `self * -1` |
| Subtraction | `__sub__` | Implemented as `self + (-other)` |
| Division | `__truediv__` | Implemented as `self * other**-1` |
| Exponential | `.exp()` | `e^x` |
| Natural log | `.log()` | `ln(x)`, asserts `x > 0` |
| ReLU | `.relu()` | `max(0, x)` |
| Tanh | `.tanh()` | Hyperbolic tangent |
| Sigmoid | `.sigmoid()` | `1 / (1 + e^-x)` |

Subtraction and division are not implemented with their own backward functions — they are derived from addition, multiplication, negation, and power. This keeps the implementation minimal and demonstrates that you only need a small set of primitives.

### The Mathematics

#### Chain Rule

For a composed function `L = f(g(x))`, the chain rule states:

```
dL/dx = dL/df · df/dg · dg/dx
```

In the computation graph, each node stores its local derivative. The backward pass multiplies these local derivatives together as it walks from the output back to the inputs — that multiplication *is* the chain rule.

#### Local Gradients for Each Operation

| Operation | Forward | Backward (local gradient × upstream grad) |
|-----------|---------|------------------------------------------|
| `z = x + y` | `z = x + y` | `dx += 1 · dz`, `dy += 1 · dz` |
| `z = x * y` | `z = xy` | `dx += y · dz`, `dy += x · dz` |
| `z = x^n` | `z = x^n` | `dx += n · x^(n-1) · dz` |
| `z = e^x` | `z = e^x` | `dx += e^x · dz` (= `z · dz`) |
| `z = ln(x)` | `z = ln(x)` | `dx += (1/x) · dz` |
| `z = relu(x)` | `z = max(0,x)` | `dx += (1 if x>0 else 0) · dz` |
| `z = tanh(x)` | `z = tanh(x)` | `dx += (1 - tanh²(x)) · dz` |
| `z = sigmoid(x)` | `z = σ(x)` | `dx += σ(x)(1 - σ(x)) · dz` |

Note that gradients use `+=` not `=`. This is essential — if a node is used more than once in the graph (e.g. `z = x * x`), its gradient contributions from each use must be summed.

#### Topological Sort

The backward pass must visit nodes in reverse topological order — a node's gradient must be fully accumulated before its `_backward` is called. The sort is built by a depth-first traversal that appends each node *after* all its children:

```
build_topo(L):
    visit all children recursively first
    then append self
```

Reversing this list gives the correct backward order: output node first, leaf inputs last.

### Verification

Gradients are verified against numerical finite differences:

```
∂f/∂x ≈ (f(x + ε) - f(x - ε)) / 2ε    where ε = 1e-4
```

All operations pass this check to floating-point precision.

---

---

## P1-02 — Tensor Autograd Engine

**File:** `phase1/autograd/tensor.py`
**Status:** ✅ Complete

### What It Does

Extends the scalar autograd engine to operate on NumPy arrays of any shape. The same computation graph and topological-sort backward pass from P1-01 applies — the difference is that each node now holds an ndarray and each `_backward` closure computes matrix-aware gradients.

### Usage

```python
import numpy as np
from phase1.autograd import Tensor

A = Tensor([[1., 2., 3.],
            [4., 5., 6.]])   # shape (2, 3)
B = Tensor([[1., 2.],
            [3., 4.],
            [5., 6.]])        # shape (3, 2)

L = (A @ B).sum()
L.backward()

print(A.grad)   # dL/dA — shape (2, 3)
print(B.grad)   # dL/dB — shape (3, 2)
```

### Supported Operations

| Operation | Method | Notes |
|-----------|--------|-------|
| Elementwise add | `__add__` | Handles broadcasting |
| Elementwise multiply | `__mul__` | Handles broadcasting |
| Power | `__pow__` | Scalar exponent |
| Matrix multiply | `matmul` / `@` | Core linear layer op |
| Sum | `.sum(axis, keepdims)` | Reduces to scalar or lower rank |
| Exponential | `.exp()` | Elementwise |
| Natural log | `.log()` | Elementwise |
| ReLU | `.relu()` | Elementwise |
| Tanh | `.tanh()` | Elementwise |
| Sigmoid | `.sigmoid()` | Elementwise |
| Transpose | `.T` | Swaps last two dims |

### The Key Difference from Scalar: Broadcasting

When two tensors of different shapes are added (e.g. a weight matrix `(B, out)` plus a bias `(1, out)`), NumPy broadcasts the smaller tensor. The backward pass must reverse this — summing the gradient back down to the original shape. This is handled by `_sum_to`:

```python
def _sum_to(grad, target_shape):
    # Sum over leading dims added by broadcasting
    # Sum over dims that were size-1 in the original
```

Forgetting this is one of the most common bugs when implementing tensor autograd.

### Matrix Multiply Gradients (from P2-07)

For `out = A @ B`, the gradients are:

```
dL/dA = dL/d(out) @ Bᵀ
dL/dB = Aᵀ @ dL/d(out)
```

Shapes must be consistent — use shape as a sanity check before checking values.

---

## P1-03 — Activation Functions

**File:** `phase1/nn/activations.py`
**Visualisation:** `phase1/visualise/activations.py`
**Status:** ✅ Complete

### What It Does

Implements ReLU, Sigmoid, Tanh, and Softmax as stateful layer objects. Each caches its input during the forward pass so the backward pass can compute the local gradient without recomputing the forward.

### Usage

```python
import numpy as np
from phase1.nn import ReLU, Sigmoid, Tanh, Softmax

act = ReLU()
x   = np.array([[-2., 0., 3.]])
y   = act(x)              # forward:  [[0., 0., 3.]]
dy  = act.backward(np.ones_like(x))  # backward: [[0., 0., 1.]]
```

### Functions & Gradients

| Activation | Forward | Backward (local gradient) | Saturates? |
|------------|---------|--------------------------|------------|
| ReLU | `max(0, x)` | `1 if x > 0 else 0` | No (positive side) |
| Sigmoid | `1 / (1 + e⁻ˣ)` | `σ(x)(1 - σ(x))` | Yes — gradient → 0 for large \|x\| |
| Tanh | `tanh(x)` | `1 - tanh²(x)` | Yes — gradient → 0 for large \|x\| |
| Softmax | `eˣⁱ / Σeˣʲ` | `s * (grad - (grad·s).sum())` | N/A — output layer only |

### Implementation Notes

**Sigmoid numerical stability:** The naive `1 / (1 + exp(-x))` overflows for large negative x. The implementation uses `exp(x) / (1 + exp(x))` for x < 0, avoiding overflow in both branches.

**Softmax numerical stability:** Subtracting `max(x)` before exponentiating prevents overflow. Softmax is shift-invariant so this does not change the output.

**Softmax backward — the efficient form:** The full Jacobian of softmax is an (n×n) matrix. For backpropagation we only need the vector-Jacobian product, which contracts to:
```
dL/dx_i = s_i * (dL/ds_i - sum_j(dL/ds_j * s_j))
```
This avoids materialising the full Jacobian.

**ReLU at x=0:** The gradient is defined as 0 at the kink. Finite difference checks will disagree here (the numerical derivative is 0.5 at x=0) — this is expected and not a bug.

### Visualisation

Run to display plots of each function and its gradient:

```bash
python3 -m phase1.visualise.activations
```

---

---

## P1-04 — Linear Layer

**File:** `phase1/nn/linear.py`
**Status:** ✅ Complete

### What It Does

Implements a fully-connected (dense) layer: `y = x @ W.T + b`. Caches the input during the forward pass and computes all three gradients during the backward pass.

### Usage

```python
import numpy as np
from phase1.nn import Linear

layer = Linear(in_features=4, out_features=3)

x   = np.random.randn(5, 4)       # batch of 5 inputs
y   = layer(x)                     # forward: shape (5, 3)

grad_out = np.ones_like(y)         # upstream gradient from loss
grad_x   = layer.backward(grad_out)  # backward: returns dL/dx

# Gradients now in layer.dW and layer.db
# Pass (layer.W, layer.dW) and (layer.b, layer.db) to the optimiser
```

### Shapes

| Variable | Shape | Description |
|----------|-------|-------------|
| `x` | `(batch, in_features)` | Input |
| `W` | `(out_features, in_features)` | Weight matrix |
| `b` | `(out_features,)` | Bias vector |
| `y` | `(batch, out_features)` | Output |

### Gradient Derivations (from P2-07)

Given upstream gradient `dL/dy` of shape `(batch, out_features)`:

```
dL/dW = (dL/dy).T @ x       shape: (out_features, in_features)  — matches W
dL/db = sum(dL/dy, axis=0)  shape: (out_features,)              — matches b
dL/dx = dL/dy @ W           shape: (batch, in_features)         — matches x
```

`dL/db` sums over the batch because `b` is broadcast across all examples in the forward pass — each example contributes a gradient to `b`, and they must be summed.

### Weight Initialisation

Weights are initialised with Xavier (Glorot) initialisation:

```
W ~ N(0, sqrt(1 / in_features))
b = 0
```

This keeps the variance of activations approximately constant across layers at the start of training. Initialising all weights to zero would make every neuron in a layer identical — they would receive identical gradients and never differentiate. This is the symmetry-breaking problem.

### Optimiser Interface

`layer.params()` returns a list of `(parameter, gradient)` pairs:

```python
for param, grad in layer.params():
    param -= learning_rate * grad   # vanilla gradient descent step
```

`layer.zero_grad()` resets `dW` and `db` to zero before each forward pass.

---

---

## P1-05 — Loss Functions

**File:** `phase1/nn/losses.py`
**Status:** ✅ Complete

### What They Do

Loss functions measure how wrong the network's predictions are. They produce a scalar loss on the forward pass and return `dL/dy_pred` on the backward pass — the gradient that flows into the last layer.

### MSELoss

Mean Squared Error. Used for regression tasks.

```python
from phase1.nn import MSELoss

loss_fn = MSELoss()
loss    = loss_fn(y_pred, y_true)   # scalar
grad    = loss_fn.backward()        # dL/dy_pred, same shape as y_pred
```

```
Forward:  L = mean((y_pred - y_true)^2)
Backward: dL/dy_pred = (2 / N_total) * (y_pred - y_true)
```

`N_total` is the total number of elements (`batch * features`), matching what `np.mean` divides by.

### CrossEntropyLoss

Softmax + Cross-Entropy fused. Used for multi-class classification. Takes raw logits — do not apply softmax before passing to this loss.

```python
from phase1.nn import CrossEntropyLoss

loss_fn = CrossEntropyLoss()
loss    = loss_fn(logits, y_true)   # y_true: integer labels (batch,)
grad    = loss_fn.backward()        # dL/d(logits), shape (batch, num_classes)

acc = loss_fn.accuracy(y_true)      # fraction correct
```

```
Forward:  probs = softmax(logits)
          L     = -mean( log(probs[correct_class]) )

Backward: dL/d(logits) = (probs - one_hot(y_true)) / batch
```

### Why Cross-Entropy, Not MSE, for Classification

When a network is confidently wrong — predicting probability 0.01 for the true class — the MSE gradient is tiny: `2 * (0.01 - 1.0) / N ≈ small`. The network barely updates.

Cross-entropy's `-log(p)` term grows very large as `p → 0`, producing large gradients that force aggressive correction of confident mistakes. This is the right behaviour for classification.

### Why Fuse Softmax and Cross-Entropy

Computing softmax then cross-entropy separately involves `log(exp(x))` terms that cancel analytically but cause numerical instability in floating point. Fusing them gives the clean, stable backward gradient `(probs - y_true) / batch` — derived in P2-06.

---

---

## P1-06 — Training Loop

**Files:** `phase1/nn/model.py`, `phase1/optim/sgd.py`, `phase1/train.py`
**Status:** ✅ Complete

### Components

**Sequential** (`phase1/nn/model.py`) — ordered layer container. Drives the forward pass in order and the backward pass in reverse. Collects `(param, grad)` pairs from all layers that have them.

**SGD** (`phase1/optim/sgd.py`) — vanilla gradient descent: `param -= lr * grad`. Holds references to the model's parameter and gradient arrays. Requires `zero_grad` to zero in-place (not replace) so references stay valid.

**train / evaluate** (`phase1/train.py`) — the training loop and evaluation function.

### Usage

```python
from phase1.nn import Linear, ReLU, Sequential, CrossEntropyLoss
from phase1.optim import SGD
from phase1.train import train, evaluate

model     = Sequential(Linear(784, 128), ReLU(), Linear(128, 10))
loss_fn   = CrossEntropyLoss()
optimiser = SGD(model.params(), lr=0.01)

history = train(model, loss_fn, optimiser, X_train, y_train,
                epochs=20, batch_size=32, print_every=5)

test_loss, test_acc = evaluate(model, loss_fn, X_test, y_test)
```

### The Training Loop — Step by Step

```
for each epoch:
    shuffle training data
    for each mini-batch:
        1. logits = model(xb)          # forward pass
        2. loss   = loss_fn(logits, yb) # compute scalar loss
        3. grad   = loss_fn.backward()  # dL/d(logits)
           model.backward(grad)         # backprop through all layers
        4. optimiser.step()             # param -= lr * grad
        5. model.zero_grad()            # reset gradients (in-place)
```

### Bug Found and Fixed: zero_grad Must Be In-Place

The SGD optimiser captures references to gradient arrays at construction via `model.params()`. If `zero_grad` replaces `self.dW` with a new array (`self.dW = np.zeros_like(...)`), the optimiser's reference points to the old zeroed array — gradients accumulate but the optimiser never sees them.

The fix: zero in-place with `self.dW[:] = 0.0`. The array identity is preserved, the optimiser reference stays valid.

This is a real class of bug in any framework that separates parameter ownership from optimiser state.

---

---

## P1-07 — MNIST Benchmark

**Files:** `phase1/data/mnist.py`, `phase1/mnist.py`
**Status:** ✅ Complete — **98.33% test accuracy**

### Result

| Metric | Value |
|--------|-------|
| Test accuracy | **98.33%** |
| Target | 97.00% |
| Epochs | 30 |
| Parameters | 784×256 + 256×128 + 128×10 = ~235k |
| Framework | Pure NumPy |

### Architecture

```
Input (784) → Linear(256) → ReLU → Linear(128) → ReLU → Linear(10) → CrossEntropyLoss
```

### Training Configuration

| Setting | Value |
|---------|-------|
| Batch size | 64 |
| Initial LR | 0.1 |
| LR at epoch 15 | 0.05 |
| LR at epoch 22 | 0.01 |
| Weight init | Xavier |

The step-decay schedule is important — a high initial LR (0.1) drives fast early convergence, then decays prevent oscillation around the minimum in later epochs.

### Running the Benchmark

```bash
python3 -m phase1.mnist
```

MNIST files are downloaded automatically on first run and cached in `data/mnist/`.

### Data Loader

`phase1/data/mnist.py` downloads the four raw IDX files from Google's MNIST mirror, parses the binary format with `struct`, and returns normalised float64 NumPy arrays. No external dependencies beyond NumPy.

---

## Task Status

| ID | Task | Status |
|----|------|--------|
| P1-01 | Scalar autograd engine | ✅ Complete |
| P1-02 | Extend to tensors (NumPy) | ✅ Complete |
| P1-03 | Activation functions | ✅ Complete |
| P1-04 | Linear layer | ✅ Complete |
| P1-05 | Loss functions | ✅ Complete |
| P1-06 | Training loop | ✅ Complete |
| P1-07 | MNIST benchmark | ✅ Complete — 98.33% test accuracy |
