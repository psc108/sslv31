# Phase 2 — The Mathematics
*Worked Reference Document · Run in parallel with Phase 1*

---

## Overview

Phase 2 is not a coding phase. It is the mathematical foundation that makes everything in Phases 1–4 legible. The goal is not to pass an exam — it is to look at an equation and feel what it is doing. Each section below covers one topic with definitions, worked examples, and a direct connection to where it appears in neural networks.

**Topics covered:**

| ID | Topic | Area |
|----|-------|------|
| P2-01 | Vectors & Matrices | Linear Algebra |
| P2-02 | Eigenvalues & Eigenvectors | Linear Algebra |
| P2-03 | Partial Derivatives | Calculus |
| P2-04 | The Chain Rule | Calculus |
| P2-05 | Probability Distributions | Probability |
| P2-06 | Cross-Entropy & KL Divergence | Probability |
| P2-07 | Matrix Calculus | Matrix Calculus |

**Recommended alongside this document:**
- 3Blue1Brown — Essence of Linear Algebra (YouTube, ~3 hours)
- 3Blue1Brown — Essence of Calculus (YouTube, ~3 hours)
- Parr & Howard — The Matrix Calculus You Need for Deep Learning (free PDF)

---

## P2-01 — Linear Algebra: Vectors & Matrices

### Vectors

A vector is an ordered list of numbers. In neural networks, vectors represent inputs, outputs, biases, and activations.

```
x = [2.0, -1.0, 3.0]    # a 3-dimensional column vector
```

Written formally as **x** ∈ ℝⁿ — a point in n-dimensional space.

#### Dot Product

The dot product of two vectors **a** and **b** of the same length:

```
a · b = a₁b₁ + a₂b₂ + ... + aₙbₙ
```

Worked example:

```
a = [1, 2, 3]
b = [4, 5, 6]

a · b = (1×4) + (2×5) + (3×6)
      = 4 + 10 + 18
      = 32
```

Geometric meaning: `a · b = |a| |b| cos(θ)` where θ is the angle between them.
- If `a · b = 0`, the vectors are perpendicular (orthogonal)
- If `a · b > 0`, they point in roughly the same direction
- If `a · b < 0`, they point in roughly opposite directions

**Neural network connection:** A single neuron computes `w · x + b` — a dot product of weights and inputs, plus a bias. The entire forward pass of a layer is built from dot products.

#### Vector Norms

The norm (length) of a vector:

```
|x| = sqrt(x₁² + x₂² + ... + xₙ²)    # L2 norm (Euclidean length)
```

Worked example:

```
x = [3, 4]
|x| = sqrt(3² + 4²) = sqrt(9 + 16) = sqrt(25) = 5
```

**Neural network connection:** L2 norm appears in weight decay (regularisation) — penalising large weights means penalising large weight vector norms.

---

### Matrices

A matrix is a 2D array of numbers with shape (rows × columns). Written **A** ∈ ℝᵐˣⁿ.

```
A = [[1, 2, 3],
     [4, 5, 6]]    # shape (2, 3) — 2 rows, 3 columns
```

#### Matrix Multiplication

For **A** ∈ ℝᵐˣⁿ and **B** ∈ ℝⁿˣᵖ, the product **C** = **AB** ∈ ℝᵐˣᵖ.

Each element `C[i,j]` is the dot product of row i of **A** with column j of **B**:

```
C[i,j] = Σₖ A[i,k] × B[k,j]
```

Worked example:

```
A = [[1, 2],      B = [[5, 6],
     [3, 4]]           [7, 8]]

C[0,0] = (1×5) + (2×7) = 5 + 14  = 19
C[0,1] = (1×6) + (2×8) = 6 + 16  = 22
C[1,0] = (3×5) + (4×7) = 15 + 28 = 43
C[1,1] = (3×6) + (4×8) = 18 + 32 = 50

C = [[19, 22],
     [43, 50]]
```

Key rule: the inner dimensions must match. **(m×n) × (n×p) → (m×p)**. The n's cancel.

Matrix multiplication is **not commutative**: **AB** ≠ **BA** in general.

**Neural network connection:** A fully-connected layer with weight matrix **W** ∈ ℝᵒˣⁱ and input **x** ∈ ℝⁱ computes **Wx** — a matrix-vector multiplication. For a batch of inputs **X** ∈ ℝᴮˣⁱ, the entire batch is processed as **XWᵀ** in one matrix multiplication. This is why GPUs are so effective — they are optimised for exactly this operation.

#### Transpose

The transpose **Aᵀ** flips a matrix over its diagonal — rows become columns.

```
A = [[1, 2, 3],      Aᵀ = [[1, 4],
     [4, 5, 6]]             [2, 5],
                            [3, 6]]
```

Shape rule: if **A** is (m×n), then **Aᵀ** is (n×m).

Key identity: **(AB)ᵀ = BᵀAᵀ** — the order reverses.

**Neural network connection:** Transpose appears constantly in backpropagation. When computing the gradient with respect to inputs in a linear layer, the weight matrix must be transposed: `dL/dx = Wᵀ · dL/dy`.

---

### Summary Table

| Operation | Notation | Shape Rule | NN Appearance |
|-----------|----------|------------|---------------|
| Dot product | **a** · **b** | Both ℝⁿ → scalar | Single neuron computation |
| Matrix multiply | **AB** | (m×n)(n×p) → (m×p) | Forward pass through a layer |
| Transpose | **Aᵀ** | (m×n) → (n×m) | Backward pass gradient computation |
| L2 norm | \|**x**\| | ℝⁿ → scalar | Weight decay / regularisation |


---

## P2-02 — Linear Algebra: Eigenvalues & Eigenvectors

### The Core Idea

Most vectors change both direction and magnitude when multiplied by a matrix. An eigenvector is special — it only changes in magnitude, never direction.

Formally, **v** is an eigenvector of matrix **A** with eigenvalue λ if:

```
Av = λv
```

Multiplying **A** by **v** gives back **v** scaled by λ. The direction is preserved.

### Worked Example

```
A = [[2, 1],
     [1, 2]]
```

Try v = [1, 1]:

```
Av = [[2, 1],  ×  [1]  =  [3]  =  3 × [1]
      [1, 2]]     [1]      [3]         [1]
```

So **v** = [1, 1] is an eigenvector with eigenvalue λ = 3. The matrix stretches this vector by a factor of 3 without rotating it.

Try v = [1, -1]:

```
Av = [[2, 1],  ×  [ 1]  =  [ 1]  =  1 × [ 1]
      [1, 2]]     [-1]      [-1]         [-1]
```

So **v** = [1, -1] is an eigenvector with eigenvalue λ = 1. This vector is unchanged by the matrix.

### Finding Eigenvalues

Eigenvalues are found by solving the characteristic equation:

```
det(A - λI) = 0
```

For the 2×2 example above:

```
A - λI = [[2-λ,  1  ],
          [ 1,  2-λ ]]

det = (2-λ)(2-λ) - (1)(1)
    = (2-λ)² - 1
    = λ² - 4λ + 3
    = (λ-3)(λ-1)

λ = 3  or  λ = 1
```

This matches what we found by inspection above.

### Geometric Intuition

Think of a matrix as a transformation of space — it stretches, squishes, and rotates. Eigenvectors are the axes along which the transformation is purely a stretch (or squish). The eigenvalue tells you by how much.

- λ > 1: the eigenvector direction is stretched
- 0 < λ < 1: the eigenvector direction is squished
- λ < 0: the eigenvector direction is flipped and scaled
- λ = 0: the matrix collapses space along this direction (singular matrix)

### Neural Network Connections

**Weight initialisation:** If the eigenvalues of the weight matrix are much larger than 1, activations will explode as they pass through layers. If much smaller than 1, they will vanish. Good initialisation schemes (Xavier, He) are designed to keep eigenvalues near 1 at the start of training.

**PCA (Principal Component Analysis):** PCA finds the eigenvectors of the data covariance matrix. The eigenvector with the largest eigenvalue is the direction of greatest variance in the data. Used in Phase 4 for latent space visualisation.

**Gradient flow:** The condition number of a matrix (ratio of largest to smallest eigenvalue) determines how hard it is to optimise. A high condition number means the loss landscape is elongated — gradient descent oscillates and converges slowly. This is part of why batch normalisation helps.

### Summary

| Term | Meaning |
|------|---------|
| Eigenvector | A vector whose direction is unchanged by the matrix |
| Eigenvalue | The scalar factor by which the eigenvector is scaled |
| Characteristic equation | `det(A - λI) = 0` — used to find eigenvalues |
| Condition number | Ratio of max to min eigenvalue — measures how well-behaved a matrix is |


---

## P2-03 — Calculus: Partial Derivatives

### Ordinary Derivatives (Recap)

The derivative of f(x) measures how much f changes when x changes by a tiny amount:

```
df/dx = lim(ε→0) [ f(x + ε) - f(x) ] / ε
```

Common rules you need to know cold:

| Function | Derivative |
|----------|-----------|
| f(x) = xⁿ | f'(x) = nxⁿ⁻¹ |
| f(x) = eˣ | f'(x) = eˣ |
| f(x) = ln(x) | f'(x) = 1/x |
| f(x) = sin(x) | f'(x) = cos(x) |
| f(x) = constant | f'(x) = 0 |

### Partial Derivatives

When a function takes multiple inputs, a partial derivative measures the effect of changing just one input while holding all others fixed. The notation ∂f/∂x means "the derivative of f with respect to x, treating all other variables as constants."

Worked example — f(x, y) = x²y + 3xy²:

```
∂f/∂x:  treat y as a constant
        = 2xy + 3y²

∂f/∂y:  treat x as a constant
        = x² + 6xy
```

Verify at the point (x=2, y=1):

```
∂f/∂x at (2,1) = 2(2)(1) + 3(1²) = 4 + 3 = 7
∂f/∂y at (2,1) = (2²) + 6(2)(1) = 4 + 12 = 16
```

### The Gradient

The gradient of a scalar function f(x₁, x₂, ..., xₙ) is the vector of all its partial derivatives:

```
∇f = [∂f/∂x₁, ∂f/∂x₂, ..., ∂f/∂xₙ]
```

The gradient points in the direction of steepest increase of f. Its negative points in the direction of steepest decrease — which is exactly the direction gradient descent moves.

Worked example — f(x, y) = x² + y²  (a bowl shape):

```
∇f = [∂f/∂x, ∂f/∂y] = [2x, 2y]

At (3, 4):  ∇f = [6, 8]
```

The gradient [6, 8] points away from the minimum at (0, 0). Gradient descent subtracts a fraction of this: move to (3 - α·6, 4 - α·8) for learning rate α.

### Neural Network Connection

The loss L is a scalar function of all the weights and biases in the network. Training requires computing ∂L/∂w for every weight w. That is the gradient of the loss — a vector with one entry per parameter. Backpropagation is the algorithm that computes all these partial derivatives efficiently in one backward pass.

---

## P2-04 — Calculus: The Chain Rule

### Single Variable Chain Rule

For composed functions f(g(x)), the derivative is:

```
d/dx f(g(x)) = f'(g(x)) · g'(x)
```

In words: the derivative of the outer function (evaluated at the inner function) times the derivative of the inner function.

Worked example — h(x) = (3x + 1)⁴:

```
Let g(x) = 3x + 1,  f(u) = u⁴

g'(x) = 3
f'(u) = 4u³

dh/dx = f'(g(x)) · g'(x)
      = 4(3x+1)³ · 3
      = 12(3x+1)³
```

### Multivariate Chain Rule

When a function depends on intermediate variables that each depend on the inputs, the chain rule sums over all paths:

```
If L = f(u, v),  u = g(x),  v = h(x):

dL/dx = (∂L/∂u)(du/dx) + (∂L/∂v)(dv/dx)
```

Each path from L back to x contributes a term. The contributions are summed.

### The Chain Rule IS Backpropagation

Consider a simple 2-layer network:

```
x → [Layer 1] → h → [Layer 2] → y → [Loss] → L
```

To find ∂L/∂x, apply the chain rule along the path:

```
∂L/∂x = (∂L/∂y) · (∂y/∂h) · (∂h/∂x)
```

Each term is a local derivative — how much does the output of each operation change when its input changes? Backpropagation computes these local derivatives at each node and multiplies them together as it walks backward through the graph.

This is exactly what the `_backward` closures in `phase1/autograd/engine.py` implement. Each closure computes one local derivative and multiplies it by `out.grad` (the upstream gradient). The chain rule is the multiplication.

### Worked Example Through a Network

Forward pass:

```
x = 2.0
w = -3.0
b = 1.0

u = w * x     = -6.0
y = u + b     = -5.0
L = y²        = 25.0
```

Backward pass — apply chain rule from L back to each variable:

```
dL/dy = 2y = 2(-5) = -10

dL/du = dL/dy · dy/du = -10 · 1 = -10

dL/dw = dL/du · du/dw = -10 · x = -10 · 2  = -20
dL/dx = dL/du · du/dx = -10 · w = -10 · (-3) = 30
dL/db = dL/dy · dy/db = -10 · 1 = -10
```

Verify dL/dw with finite differences:

```
L(w + ε) = ((w+ε)x + b)² = ((-3+0.001)(2) + 1)² = (-5 + 0.002)² = 24.980004
L(w - ε) = ((-3-0.001)(2) + 1)² = (-5 - 0.002)² = 25.020004

dL/dw ≈ (24.980004 - 25.020004) / (2 × 0.001) = -0.04 / 0.002 = -20.0  ✓
```

### Why Gradients Accumulate with +=

If a variable appears in multiple places in the computation graph, the chain rule sums the gradient contributions from each path. In code this means `self.grad += ...` not `self.grad = ...`. Using `=` would discard all but the last path's contribution — a silent, hard-to-debug error.

### Summary

| Concept | Formula | NN Role |
|---------|---------|---------|
| Single-variable chain rule | d/dx f(g(x)) = f'(g(x))·g'(x) | Gradient through one operation |
| Multivariate chain rule | dL/dx = Σ (∂L/∂uᵢ)(∂uᵢ/∂x) | Gradient through branching graph |
| Backpropagation | Chain rule applied recursively | Computing all ∂L/∂w efficiently |


---

## P2-05 — Probability: Distributions

### Why Probability Matters in Neural Networks

Neural networks are not deterministic rule systems — they model uncertainty. The output of a classifier is a probability distribution over classes. Weight initialisation draws from a probability distribution. Understanding distributions is prerequisite to understanding why networks are designed the way they are.

### The Normal (Gaussian) Distribution

The most important distribution in neural networks. Defined by mean μ and standard deviation σ:

```
p(x) = (1 / σ√(2π)) · exp(-(x - μ)² / 2σ²)
```

Key properties:
- Symmetric, bell-shaped curve centred at μ
- 68% of values fall within 1σ of the mean
- 95% within 2σ, 99.7% within 3σ

**Neural network connection — weight initialisation:** Weights are initialised by drawing from a Gaussian with mean 0 and a carefully chosen σ. If σ is too large, activations explode. If too small, they vanish. Xavier initialisation sets σ = sqrt(1/n_in). He initialisation sets σ = sqrt(2/n_in) for ReLU networks. Both are derived by analysing how variance propagates through layers.

### The Bernoulli Distribution

Models a binary outcome — 0 or 1 — with probability p of being 1:

```
P(X = 1) = p
P(X = 0) = 1 - p
```

Mean = p, Variance = p(1-p).

**Neural network connection:** Binary classification. A sigmoid output neuron produces p — the probability that the input belongs to class 1. The Bernoulli distribution is the probabilistic model underlying binary cross-entropy loss.

### The Categorical Distribution

Generalises Bernoulli to K mutually exclusive outcomes:

```
P(X = k) = pₖ    where Σpₖ = 1
```

**Neural network connection:** Multi-class classification. A softmax output layer produces a categorical distribution over K classes. The probabilities sum to 1 by construction.

### Mean, Variance, Expectation

For a random variable X:

```
Mean (expectation):  E[X] = Σ x · P(X=x)          (discrete)
                           = ∫ x · p(x) dx          (continuous)

Variance:  Var(X) = E[(X - E[X])²] = E[X²] - E[X]²

Standard deviation:  σ = sqrt(Var(X))
```

Worked example — fair six-sided die:

```
E[X] = (1+2+3+4+5+6)/6 = 3.5

E[X²] = (1+4+9+16+25+36)/6 = 91/6 ≈ 15.17

Var(X) = 15.17 - 3.5² = 15.17 - 12.25 = 2.92

σ = sqrt(2.92) ≈ 1.71
```

---

## P2-06 — Probability: Cross-Entropy & KL Divergence

### Information Entropy

Shannon entropy measures the average surprise (information content) of a probability distribution:

```
H(p) = -Σ p(x) · log p(x)
```

Intuition: a distribution where one outcome is certain (p=1) has zero entropy — no surprise. A uniform distribution has maximum entropy — maximum uncertainty.

Worked example — two distributions over 4 classes:

```
p = [1.0, 0.0, 0.0, 0.0]   # certain — always class 0
H(p) = -(1·log1 + 0 + 0 + 0) = 0

q = [0.25, 0.25, 0.25, 0.25]  # uniform — maximum uncertainty
H(q) = -(4 × 0.25·log0.25) = -(4 × 0.25 × (-1.386)) = 1.386
```

### Cross-Entropy Loss

Cross-entropy measures how well a predicted distribution q approximates a true distribution p:

```
H(p, q) = -Σ p(x) · log q(x)
```

In classification, p is the one-hot true label (1 for the correct class, 0 elsewhere). This simplifies the sum to a single term:

```
L = -log q(y_true)
```

Where q(y_true) is the predicted probability assigned to the correct class.

Worked example — 3-class problem, true class = 1:

```
True label:  p = [0, 1, 0]
Predictions: q = [0.1, 0.7, 0.2]

L = -(0·log0.1 + 1·log0.7 + 0·log0.2)
  = -log(0.7)
  = 0.357
```

If the model was less confident:

```
q = [0.3, 0.4, 0.3]
L = -log(0.4) = 0.916    # higher loss — worse prediction
```

If the model was perfectly confident:

```
q = [0, 1, 0]
L = -log(1.0) = 0.0      # zero loss — perfect prediction
```

### Why Cross-Entropy, Not MSE, for Classification

MSE loss for classification would be `(predicted_prob - true_label)²`. The problem: when the model is confidently wrong (predicts 0.01 for the true class), the MSE gradient is tiny — the model barely updates. Cross-entropy's `-log(q)` term grows very large as q → 0, producing large gradients that force the model to correct confident mistakes aggressively.

### Softmax + Cross-Entropy: The Natural Pairing

Softmax converts raw scores (logits) into a valid probability distribution:

```
softmax(zᵢ) = exp(zᵢ) / Σⱼ exp(zⱼ)
```

The combined gradient of softmax + cross-entropy with respect to the logits z is elegantly simple:

```
∂L/∂zᵢ = qᵢ - pᵢ
```

Where q is the predicted probability and p is the true label. This is the predicted probability minus the true label — intuitive and numerically stable. This is why softmax and cross-entropy are always used together.

### KL Divergence

KL divergence measures how much one distribution differs from another:

```
KL(p || q) = Σ p(x) · log(p(x) / q(x))
```

Properties:
- KL(p || q) ≥ 0 always
- KL(p || q) = 0 if and only if p = q
- Not symmetric: KL(p || q) ≠ KL(q || p) in general

Relationship to cross-entropy:

```
H(p, q) = H(p) + KL(p || q)
```

Minimising cross-entropy loss is equivalent to minimising KL divergence between the true and predicted distributions (since H(p) is fixed for a given dataset).

**Neural network connection:** KL divergence appears directly in the VAE loss (Phase 4). The encoder must produce a latent distribution close to a standard Gaussian — the KL term in the loss penalises deviation from it.

---

## P2-07 — Matrix Calculus

### Why This Is Needed

In Phase 1, the scalar autograd engine computes derivatives of scalars with respect to scalars. Real networks operate on vectors and matrices. Matrix calculus extends differentiation to these cases — it is the language in which backpropagation through a linear layer is written.

**Reference:** Parr & Howard — *The Matrix Calculus You Need for Deep Learning* (free PDF). Read this alongside this section.

### The Jacobian

When a function maps a vector to a vector — **f**: ℝⁿ → ℝᵐ — the derivative is a matrix called the Jacobian:

```
J[i,j] = ∂fᵢ/∂xⱼ
```

The Jacobian has shape (m × n) — one row per output, one column per input.

Worked example — f(x) = [x₁², x₁x₂]:

```
J = [[∂f₁/∂x₁,  ∂f₁/∂x₂],     =  [[2x₁,  0 ],
     [∂f₂/∂x₁,  ∂f₂/∂x₂]]         [ x₂,  x₁]]
```

At (x₁=2, x₂=3):

```
J = [[4, 0],
     [3, 2]]
```

### Scalar-by-Vector Derivative

When L is a scalar and **x** is a vector, ∂L/∂**x** is a vector of the same shape as **x**:

```
∂L/∂x = [∂L/∂x₁, ∂L/∂x₂, ..., ∂L/∂xₙ]
```

This is the gradient — the most common case in neural network training.

### Key Identities for Neural Networks

These are the derivatives you will use repeatedly in backpropagation:

#### Linear layer: y = Wx

Given loss L, and forward pass **y** = **Wx**:

```
∂L/∂W = (∂L/∂y) · xᵀ        # outer product — shape matches W
∂L/∂x = Wᵀ · (∂L/∂y)        # transpose of W times upstream gradient
```

Worked example — W ∈ ℝ²ˣ³, x ∈ ℝ³, y ∈ ℝ²:

```
If ∂L/∂y = [δ₁, δ₂]  (upstream gradient, shape 2)
   x      = [x₁, x₂, x₃]

∂L/∂W = [[δ₁x₁, δ₁x₂, δ₁x₃],    # shape (2×3) — matches W
          [δ₂x₁, δ₂x₂, δ₂x₃]]

∂L/∂x = Wᵀ · [δ₁, δ₂]            # shape (3) — matches x
```

#### Bias: y = x + b

```
∂L/∂b = ∂L/∂y    # gradient passes through unchanged
```

#### Batched linear layer: Y = XWᵀ

For a batch X ∈ ℝᴮˣⁱ, W ∈ ℝᵒˣⁱ, Y ∈ ℝᴮˣᵒ:

```
∂L/∂W = (∂L/∂Y)ᵀ · X           # shape (o×i) — matches W
∂L/∂X = (∂L/∂Y) · W            # shape (B×i) — matches X
∂L/∂b = sum(∂L/∂Y, axis=0)     # sum over batch dimension
```

The sum over the batch dimension for the bias gradient is easy to forget — it is required because b is broadcast across all B examples in the forward pass.

### Shape as a Sanity Check

A powerful debugging technique: the gradient of any variable must have the same shape as that variable. If ∂L/∂W does not have the same shape as W, the matrix calculus is wrong. Always check shapes before checking values.

```
W shape:      (o × i)
∂L/∂W shape: must be (o × i)

x shape:      (i,)
∂L/∂x shape: must be (i,)
```

---

## Task Status

| ID | Topic | Status |
|----|-------|--------|
| P2-01 | Linear Algebra — Vectors & Matrices | ✅ Complete |
| P2-02 | Linear Algebra — Eigenvalues | ✅ Complete |
| P2-03 | Calculus — Partial Derivatives | ✅ Complete |
| P2-04 | Calculus — Chain Rule | ✅ Complete |
| P2-05 | Probability — Distributions | ✅ Complete |
| P2-06 | Probability — Cross-Entropy & KL | ✅ Complete |
| P2-07 | Matrix Calculus | ✅ Complete |
