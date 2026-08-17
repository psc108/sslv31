# Phase 3 — Training Dynamics in Depth
*Developer & Implementation Reference*

---

## Overview

Phase 3 goes deeper on why training behaves the way it does. Each technique is implemented from scratch, broken deliberately where instructed, and observed empirically. The goal is not just to use these tools but to understand what each one is doing to the loss landscape and gradient flow.

---

## P3-01 — SGD Optimiser

**File:** `phase3/optim/sgd_momentum.py`
**Status:** ✅ Complete

Vanilla SGD is already implemented in `phase1/optim/sgd.py`. The Phase 3 version extends it with momentum and serves as the base for all schedule experiments.

### Mini-batch Selection

Each epoch, the training data is shuffled and split into batches of size B. Each batch produces one gradient estimate and one parameter update. Key tradeoffs:

| Batch size | Gradient quality | Update frequency | Memory |
|------------|-----------------|-----------------|--------|
| 1 (online) | Very noisy | Very high | Minimal |
| 32–256 | Moderate noise | High | Low |
| Full dataset | Exact | Low | High |

Noise from small batches is not purely bad — it acts as regularisation and can help escape sharp local minima. Very large batches converge to sharper minima that generalise worse (the "sharp minima" problem).

---

## P3-02 — Momentum

**File:** `phase3/optim/sgd_momentum.py`
**Status:** ✅ Complete

### Update Rule

```
v = β * v + grad
param -= lr * v
```

The velocity `v` accumulates a weighted history of past gradients. β = 0.9 means the current gradient contributes 10% and the history contributes 90%.

### Why It Helps

In a ravine-shaped loss landscape (common in deep networks), vanilla SGD oscillates across the narrow dimension while making slow progress along the valley. Momentum damps the oscillations because gradients across the ravine cancel in the velocity average, while gradients along the valley accumulate.

### Usage

```python
from phase3.optim import SGD

opt = SGD(model.params(), lr=0.01, momentum=0.9)
```

---

## P3-03 — Adam Optimiser

**File:** `phase3/optim/adam.py`
**Status:** ✅ Complete

### Update Rule

```
m = β1 * m + (1 - β1) * grad          # first moment — smoothed gradient
v = β2 * v + (1 - β2) * grad²         # second moment — smoothed squared gradient
m̂ = m / (1 - β1^t)                    # bias correction
v̂ = v / (1 - β2^t)                    # bias correction
param -= lr * m̂ / (sqrt(v̂) + ε)
```

### Why Bias Correction Matters

At step t=1, m and v are initialised at zero. Without correction, m̂ = 0.1 * grad (heavily underestimated). Bias correction divides by `(1 - β^t)` which is small early on, scaling the estimates back up to their true values. By step ~100 the correction factor approaches 1 and has negligible effect.

### Adaptive Learning Rates

The `sqrt(v̂)` denominator gives each parameter its own effective learning rate. Parameters with consistently large gradients get smaller steps; parameters with small or infrequent gradients get larger steps. This is particularly useful for sparse features (e.g. embeddings) where most parameters receive zero gradient most of the time.

### When Adam Underperforms SGD

Adam can converge to sharper minima than SGD with momentum, which sometimes generalises worse on image classification tasks. For CNNs on CIFAR/ImageNet, SGD + momentum + cosine decay often beats Adam. For Transformers and NLP tasks, Adam is almost universally preferred.

### Usage

```python
from phase3.optim import Adam

opt = Adam(model.params(), lr=0.001)   # paper defaults: β1=0.9, β2=0.999
```

---

## P3-04 — Weight Initialisation

**File:** `phase3/nn/init.py`
**Status:** ✅ Complete

### Strategies

| Strategy | Formula | Use case | What goes wrong without it |
|----------|---------|----------|---------------------------|
| Xavier | `σ = sqrt(1 / fan_in)` | Sigmoid / Tanh | Activations shrink or explode across layers |
| He | `σ = sqrt(2 / fan_in)` | ReLU | Factor of 2 compensates for ReLU zeroing half its inputs |
| Zeros | `W = 0` | Never | Symmetry — all neurons identical, never differentiate |
| Large | `σ = 10.0` | Never | Saturation (Sigmoid/Tanh) or explosion (ReLU) |

### The Symmetry-Breaking Problem

If all weights are initialised to zero, every neuron in a layer computes the same output and receives the same gradient. They update identically and remain identical forever — the layer is effectively a single neuron regardless of its width. Random initialisation breaks this symmetry.

### Variance Propagation

Xavier is derived by requiring that the variance of activations is the same at every layer. For a linear layer with `fan_in` inputs:

```
Var(output) = fan_in * Var(W) * Var(input)
```

Setting `Var(W) = 1 / fan_in` keeps `Var(output) = Var(input)`. He adds a factor of 2 because ReLU zeroes half its inputs, halving the variance — the factor of 2 restores it.

### Usage

```python
from phase3.nn import apply_init

apply_init(model, strategy='he')      # applies to all Linear layers
apply_init(model, strategy='xavier')
apply_init(model, strategy='zeros')   # deliberately bad — for experiment
apply_init(model, strategy='large')   # deliberately bad — for experiment
```

---

## P3-05 — Batch Normalisation

**File:** `phase3/nn/batchnorm.py`
**Status:** ✅ Complete

### What It Does

Normalises each feature across the batch to zero mean and unit variance, then applies learnable scale (gamma) and shift (beta).

```
μ  = mean(x, axis=0)          # per-feature batch mean
σ² = var(x, axis=0)           # per-feature batch variance
x̂  = (x - μ) / sqrt(σ² + ε)  # normalise
y  = gamma * x̂ + beta          # scale and shift (learnable)
```

### Training vs Inference

During training, statistics are computed from the current batch. During inference, stored running statistics (accumulated during training via exponential moving average) are used — because at inference time there may be no batch, or the batch may be a single example.

```python
bn.training = True    # use batch statistics (default)
bn.training = False   # use running statistics
```

### Why It Helps Gradient Flow

Without batch norm, the distribution of inputs to each layer shifts as upstream weights change — internal covariate shift. Each layer must constantly adapt to a moving target. Batch norm fixes the input distribution, allowing higher learning rates and making deeper networks trainable.

### Usage

```python
from phase3.nn import BatchNorm

model = Sequential(
    Linear(784, 256), BatchNorm(256), ReLU(),
    Linear(256, 128), BatchNorm(128), ReLU(),
    Linear(128, 10),
)
```

BatchNorm goes between the linear layer and the activation — it normalises the pre-activation values before the nonlinearity is applied.

---

## P3-06 — Dropout

**File:** `phase3/nn/dropout.py`
**Status:** ✅ Complete

### What It Does

During training, randomly zeroes each activation with probability p. Surviving activations are scaled up by `1/(1-p)` — inverted dropout — so the expected value is unchanged and no adjustment is needed at inference.

### Inverted Dropout

```
mask   = random(shape) > p          # 1 with prob (1-p), 0 with prob p
output = x * mask / (1 - p)         # scale up survivors
```

At inference: `output = x` (no mask, no scaling needed).

### Why It Works

Each forward pass trains a different random sub-network. The full network cannot rely on any single neuron and must learn redundant representations. At inference, all neurons are active — this approximates averaging over the exponentially many sub-networks, an implicit ensemble.

### Training vs Inference

```python
drop = Dropout(p=0.5)
drop.training = True    # applies mask (default)
drop.training = False   # passthrough — no dropout at inference
```

### Typical Values

- Hidden layers: p = 0.5
- Input layer: p = 0.1–0.2
- After attention in Transformers: p = 0.1

---

## P3-07 — L2 Weight Decay

**File:** `phase3/nn/losses.py`
**Status:** ✅ Complete

### What It Does

Adds a penalty term to the loss proportional to the sum of squared weights:

```
L_total = L_ce + (λ/2) * Σ W²
```

The gradient of the L2 term is `λ * W`, which is added to `dW` before the optimiser step. This is equivalent to multiplying weights by `(1 - lr * λ)` at each step — hence "weight decay".

### Bayesian Interpretation

L2 regularisation is equivalent to placing a zero-mean Gaussian prior on the weights and performing MAP (maximum a posteriori) estimation. The prior says "weights should be small unless the data strongly demands otherwise." λ controls the strength of this prior.

### Usage

```python
from phase3.nn import CrossEntropyWithL2

loss_fn = CrossEntropyWithL2(l2_lambda=1e-4)
loss    = loss_fn(logits, y_true, model=model)   # model required for L2 term
grad    = loss_fn.backward()
```

---

## P3-08 — Vanishing / Exploding Gradients

**File:** `phase3/experiments/vanishing_gradients.py`
**Status:** ✅ Complete

### The Experiment

A 20-layer network is built with Sigmoid activations and the gradient norm at each layer is measured after one backward pass. The experiment is repeated with ReLU.

### Results

```
Layer           Sigmoid           ReLU
--------------------------------------
Layer 1         8.31e-13       7.82e-04
Layer 5         2.08e-10       8.78e-04
Layer 10        2.35e-07       9.59e-04
Layer 15        2.83e-04       5.35e-04
Layer 20        3.94e-01       4.05e-04
```

Sigmoid gradients at layer 1 are `8.31e-13` — effectively zero. The first layers receive no learning signal. ReLU gradients are consistent at `~1e-3` throughout all 20 layers.

### Why Sigmoid Vanishes

Sigmoid's derivative is `σ(x)(1 - σ(x))`, which has a maximum of 0.25 at x=0 and approaches 0 for large |x|. Multiplying 20 values of ≤ 0.25 together: `0.25^20 ≈ 9e-13`. The gradient is annihilated.

### Why ReLU Doesn't

ReLU's derivative is 1 for positive inputs and 0 for negative. For positive activations, the gradient passes through unchanged — no shrinkage. This is why ReLU (and its variants) replaced Sigmoid in deep networks.

### Run It

```bash
python3 -m phase3.experiments.vanishing_gradients
```

---

## P3-09 — Learning Rate Schedules

**File:** `phase3/optim/schedules.py`, `phase3/experiments/lr_schedules.py`
**Status:** ✅ Complete

### Schedules Implemented

| Schedule | Behaviour | Intuition |
|----------|-----------|-----------|
| `StepDecay` | Multiply LR by γ every N epochs | Simple, predictable drops |
| `CosineDecay` | Smooth cosine curve from base_lr to min_lr | Gentle convergence, no abrupt drops |
| `WarmupCosineDecay` | Linear ramp up, then cosine decay | Stabilises early training, then decays |

### Usage

```python
from phase3.optim import SGD, CosineDecay, WarmupCosineDecay

opt      = SGD(model.params(), lr=0.1)
schedule = WarmupCosineDecay(opt, total_epochs=30, warmup_epochs=3)

for epoch in range(30):
    schedule.step(epoch)   # updates opt.lr
    # ... train one epoch
```

### Run the Comparison

```bash
python3 -m phase3.experiments.lr_schedules
```

Trains the same MNIST network three times with different schedules and saves a comparison plot to `results/lr_schedule_comparison.png`.

---

## P3-10 — Experiment Tracking

**File:** `phase3/experiments/tracker.py`
**Status:** ✅ Complete

Lightweight local tracker — no external dependencies. Logs scalar metrics per epoch to an in-memory list, saves to JSON, and plots with matplotlib.

### Usage

```python
from phase3.experiments import Tracker, plot_history

tracker = Tracker('my_run')

for epoch in range(epochs):
    # ... train
    tracker.log(epoch=epoch, loss=avg_loss, accuracy=avg_acc)

tracker.save('results/')      # writes results/my_run.json
tracker.summary()             # prints first/last/min/max for each metric

# Compare multiple runs
plot_history([tracker1, tracker2], metric='loss', save_path='results/compare.png')
```

---

## Task Status

| ID | Task | Status |
|----|------|--------|
| P3-01 | SGD Optimiser | ✅ Complete |
| P3-02 | Momentum | ✅ Complete |
| P3-03 | Adam optimiser | ✅ Complete |
| P3-04 | Weight initialisation | ✅ Complete |
| P3-05 | Batch normalisation | ✅ Complete |
| P3-06 | Dropout | ✅ Complete |
| P3-07 | L2 weight decay | ✅ Complete |
| P3-08 | Vanishing/exploding gradients | ✅ Complete |
| P3-09 | Learning rate schedules | ✅ Complete |
| P3-10 | Experiment tracking | ✅ Complete |
