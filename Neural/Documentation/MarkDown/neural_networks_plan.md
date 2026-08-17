# Neural Networks — Personal Learning Plan
### From First Principles to a Real Project
*v1.0 · Paul*

---

## Overview & Philosophy

This document is a personal reference and working plan for learning neural networks in depth. The approach prioritises building everything from scratch before touching any framework — developing genuine mathematical intuition rather than framework familiarity. Each phase builds directly on the last.

> **Core Principle:** Build it in raw Python/NumPy first. Understand it mathematically. Then see how frameworks abstract it. Then push into something novel. Resist the temptation to start with PyTorch — you will not understand what it is doing.

---

## PHASE 1 — FOUNDATIONS: RAW NUMPY, NO FRAMEWORKS

**Goal:** Build a working neural network library in pure Python and NumPy. Not a toy — a real, small framework with forward/backward passes, loss functions, and a training loop. Train it on MNIST and reach 97%+ accuracy.

### Task Breakdown

| ID | Task | Description | Status |
|----|------|-------------|--------|
| P1-01 | Scalar autograd engine | Implement backpropagation on individual scalar values. Follow Karpathy micrograd as a guide but type every line yourself. ~150 lines of Python. The single most important exercise in this entire plan. | ○ Pending |
| P1-02 | Extend to tensors | Make the autograd engine work on NumPy arrays rather than scalars. Feel the chain rule applied to matrix operations. This is where backprop becomes intuitive. | ○ Pending |
| P1-03 | Activation functions | Implement ReLU, Sigmoid, Tanh, Softmax — all by hand, with forward and backward methods. Visualise each function and its gradient. | ○ Pending |
| P1-04 | Linear layer | Implement a fully-connected (dense) layer: y = Wx + b. Derive the gradient with respect to W, x, and b from first principles. | ○ Pending |
| P1-05 | Loss functions | Implement MSE and cross-entropy loss with analytic gradients. Understand why cross-entropy is used for classification, not MSE. | ○ Pending |
| P1-06 | Training loop | Build a complete training loop: forward pass → compute loss → backward pass → gradient descent step. No framework. Pure Python. | ○ Pending |
| P1-07 | MNIST benchmark | Train your from-scratch network on the MNIST handwritten digit dataset. Target: 97%+ test accuracy with a 2-3 layer network. This is your Phase 1 acceptance test. | ○ Pending |

### Key Concepts to Understand by End of Phase 1

| Concept | What You Should Be Able to Do |
|---------|-------------------------------|
| Backpropagation | Derive gradients by hand for a 2-layer network on paper without looking anything up |
| Chain rule | Explain why gradients multiply as they flow backward through layers |
| Gradient descent | Explain what the learning rate does geometrically; what happens if it is too large or too small |
| Loss landscape | Explain what a local minimum is and why it matters less than people think for deep nets |
| Forward/backward pass | Trace a single training example through your own code, value by value |

---

## PHASE 2 — THE MATHEMATICS *(run in parallel with Phase 1)*

**Goal:** Build the mathematical foundation that makes everything else legible. You do not need a degree — you need three specific areas understood well enough to look at an equation and feel what it is doing.

> **Recommended Resource:** 3Blue1Brown "Essence of Linear Algebra" (YouTube, ~3 hours total) and "Essence of Calculus" are the best visual introductions to these topics that exist. Watch them before or alongside Phase 1 work. They are not optional.

### Mathematics Checklist

| ID | Topic | Description | Status |
|----|-------|-------------|--------|
| P2-01 | Linear Algebra — Vectors & Matrices | Matrix multiplication, dot products, vector norms, transpose. Understand why neural network layers are matrix multiplications. | ○ Pending |
| P2-02 | Linear Algebra — Eigenvalues | Eigenvectors and eigenvalues, intuition for what they represent. Useful for understanding PCA and weight initialisation. | ○ Pending |
| P2-03 | Calculus — Partial Derivatives | Partial derivatives, gradient of a scalar function. Be able to compute df/dx for any expression you will encounter in a network. | ○ Pending |
| P2-04 | Calculus — Chain Rule | Multivariate chain rule applied to composed functions. This IS backpropagation — understand it symbolically not just mechanically. | ○ Pending |
| P2-05 | Probability — Distributions | Normal, Bernoulli, categorical distributions. Mean, variance, expectation. Why initialisation uses Gaussian distributions. | ○ Pending |
| P2-06 | Probability — Cross-Entropy & KL | Information entropy, cross-entropy loss derivation, KL divergence. Understand why softmax + cross-entropy is the natural choice for classification. | ○ Pending |
| P2-07 | Matrix Calculus | Read "The Matrix Calculus You Need for Deep Learning" (Parr & Howard). Jacobians, vector-by-vector and scalar-by-matrix derivatives. | ○ Pending |

---

## PHASE 3 — TRAINING DYNAMICS IN DEPTH

**Goal:** Once your from-scratch network is working, go deeper on why training behaves the way it does. This phase is largely empirical: implement each technique, break things deliberately, observe the result, fix it.

### Task Breakdown

| ID | Task | Description | Status |
|----|------|-------------|--------|
| P3-01 | SGD Optimiser | Vanilla stochastic gradient descent. Understand mini-batch selection, why batching is necessary, and the variance/bias tradeoff of batch size. | ○ Pending |
| P3-02 | Momentum | Implement gradient momentum from scratch. Observe how it smooths oscillation in loss curves and why it helps escape shallow local minima. | ○ Pending |
| P3-03 | Adam optimiser | Implement Adam (adaptive moment estimation) from scratch. Understand why it outperforms vanilla SGD on most tasks, and when it does not. | ○ Pending |
| P3-04 | Weight initialisation | Xavier/Glorot vs He initialisation. Deliberately initialise badly — all zeros, too large — and watch gradients vanish or explode. Then fix it. | ○ Pending |
| P3-05 | Batch normalisation | Implement batch norm with learnable gamma and beta. Understand what it normalises, why it helps gradient flow, and why it behaves differently at inference. | ○ Pending |
| P3-06 | Dropout | Implement dropout as a regularisation layer. Understand why it acts as an ensemble method and how the scaling must change at inference time. | ○ Pending |
| P3-07 | L2 weight decay | Add L2 regularisation to the loss. Understand why it penalises large weights and how it relates to a Gaussian prior in a Bayesian interpretation. | ○ Pending |
| P3-08 | Vanishing/exploding gradients | Deliberately construct a network with 20+ layers and sigmoid activations. Observe gradient collapse. Understand why ReLU and residual connections were invented. | ○ Pending |
| P3-09 | Learning rate schedules | Implement warmup, cosine decay, and step decay. Observe the effect on training stability and final accuracy. Understand the intuition for each. | ○ Pending |
| P3-10 | Experiment tracking | Set up Weights & Biases (wandb) or similar. Log loss curves, weight histograms, gradient norms per layer. Get comfortable diagnosing training from charts. | ○ Pending |

---

## PHASE 4 — ARCHITECTURE ZOO *(pick what interests you)*

**Goal:** Implement each major architecture class once from scratch in NumPy, then once cleanly in PyTorch. You do not need to cover every architecture — follow your interest. The Transformer is the highest-value target.

> **Recommended: nanoGPT** — Andrej Karpathy's nanoGPT is a complete, working GPT-2-style language model in approximately 300 lines of clean PyTorch. It is the single best self-contained demonstration of the Transformer architecture. Read, run, and modify it as the culmination of Phase 4 Transformer work.

### Architectures Overview

| Architecture | What to Build | Suggested Dataset | Priority |
|---|---|---|---|
| CNN — Convolutional Neural Network | Conv layer (im2col method), max pooling, receptive field visualisation. Implement LeNet-5 from scratch. | CIFAR-10 image classification | High |
| RNN — Recurrent Neural Network | Vanilla RNN cell with BPTT (backprop through time). Observe vanishing gradient problem in sequences > 20 steps. | Character-level text generation | High |
| LSTM | LSTM gates (input, forget, output, cell) from scratch. Understand why gating fixes the vanishing gradient problem that kills vanilla RNNs. | Character prediction / time series | High |
| Transformer | Scaled dot-product attention, multi-head attention, positional encoding, feed-forward sublayer. Follow nanoGPT as a guide. | Character-level language model | **Essential** |
| Autoencoder | Encoder/decoder bottleneck architecture. Train to reconstruct inputs, then inspect the latent space. | MNIST or CIFAR | Medium |
| VAE — Variational Autoencoder | Add the KL divergence term, reparameterisation trick, sample from latent space. First generative model. | MNIST digit generation | Medium |

### Architecture Task Tracker

| ID | Task | Description | Status |
|----|------|-------------|--------|
| P4-01 | CNN — from scratch (NumPy) | Implement conv layer using im2col reshaping. Add max pooling. Train on CIFAR-10. Compare to Phase 1 fully-connected baseline. | ○ Pending |
| P4-02 | CNN — PyTorch implementation | Re-implement in PyTorch. Compare lines of code, training speed, and debugging experience. | ○ Pending |
| P4-03 | RNN — from scratch | Vanilla RNN cell with manual BPTT. Train on character-level text. Observe exploding/vanishing gradients in long sequences. | ○ Pending |
| P4-04 | LSTM — from scratch | Implement all four LSTM gates manually. Train on same task as RNN. Observe the improvement in longer sequence handling. | ○ Pending |
| P4-05 | Transformer — attention mechanism | Implement scaled dot-product attention from scratch: QKV projections, softmax over scores, weighted sum of values. | ○ Pending |
| P4-06 | Transformer — full model | Add multi-head attention, positional encoding, layer norm, feed-forward sublayer. Train a character-level language model. | ○ Pending |
| P4-07 | nanoGPT walkthrough | Read every line of Karpathy nanoGPT. Run it. Modify it: change n_head, n_layer, context length. Understand the effect of each hyperparameter. | ○ Pending |
| P4-08 | Autoencoder | Build encoder/decoder, train on MNIST. Visualise the 2D latent space by projecting with t-SNE. Observe class clustering. | ○ Pending |
| P4-09 | VAE | Extend autoencoder with KL divergence loss and reparameterisation trick. Sample from latent space to generate new digits. | ○ Pending |

---

## PHASE 5 — A REAL PROJECT THAT MEANS SOMETHING

**Goal:** Apply everything to a real problem with real data. The project should be yours — something where you have a personal stake in the result. Pick one and commit to it; breadth is not the objective at this point.

> **Recommendation:** Start with anomaly detection on Rose logs. You have the infrastructure, the data pipeline, and a genuine operational interest in the result. It uses an autoencoder (covered in Phase 4) on real time series data and delivers something immediately useful. It is the lowest-friction high-value option.

### Project Options

| Option | Description | What You Will Learn | Effort |
|--------|-------------|---------------------|--------|
| **Anomaly Detection on Rose Logs** | Train an autoencoder or LSTM on OpenSearch log streams from the Rose platform. Flag unusual patterns in infrastructure events. | Time series modelling, unsupervised anomaly detection, working with production log data, threshold selection. | Medium |
| **Vehicle Diagnostics — Freelander / Bipper** | Capture OBD-II sensor time series. Train an LSTM or TCN to identify fault precursors or classify fault conditions from sensor combinations. | Multivariate time series, classification vs. regression on sensor data, dealing with noisy real-world inputs. | Medium-High |
| **Tiny Language Model from Scratch** | Follow the nanoGPT path to a working, tiny language model trained on a corpus that interests you (technical manuals, RFC documents, engineering texts). | Complete Transformer implementation, tokenisation, dataset preparation, sampling strategies, temperature/top-k. | High |
| **Terrain / Land Classification** | Use satellite or OS map imagery of your Wales land and surrounding area. Train a CNN to classify terrain type, land cover, or identify features. | CNN for image tasks, working with geospatial data, dealing with limited labelled data, transfer learning. | High |

---

## REFERENCE — RESOURCES & VIEWING / READING LIST

### Video — Essential Watching *(in order)*

| ID | Resource | Description | Status |
|----|----------|-------------|--------|
| V-01 | **3Blue1Brown — Essence of Linear Algebra** | YouTube playlist (~3 hours). Visual, geometric intuition for vectors, matrices, eigenvectors. Watch before or during Phase 1. Do not skip. | ○ Pending |
| V-02 | **3Blue1Brown — Essence of Calculus** | YouTube playlist (~3 hours). Derivatives, chain rule, integrals — built from geometric first principles. Pairs with Phase 2 maths work. | ○ Pending |
| V-03 | **3Blue1Brown — Neural Networks series** | YouTube playlist (~4 hours). Gradient descent, backprop, and training visualised clearly. Watch before or during Phase 1. | ○ Pending |
| V-04 | **Karpathy — micrograd (YouTube)** | Single 2.5-hour video. Builds a scalar autograd engine from scratch. This is the Phase 1 foundation video. Type every line yourself. | ○ Pending |
| V-05 | **Karpathy — makemore series (YouTube)** | Multi-part series building character-level language models of increasing sophistication: Bigram → MLP → RNN → WaveNet → Transformer. Bridges Phases 1–4. | ○ Pending |
| V-06 | **Karpathy — nanoGPT (YouTube)** | Builds a complete GPT implementation from scratch in ~1 hour. Phase 4 Transformer capstone. Watch after implementing attention yourself. | ○ Pending |
| V-07 | **fast.ai Practical Deep Learning (Part 1)** | Free online course. Top-down approach (opposite of Karpathy). Useful contrast and perspective once you have the foundations. Watch after Phase 2. | ○ Pending |
| V-08 | **Karpathy — Intro to LLMs (YouTube)** | 1-hour talk on how large language models work at a high level. Good orientation for where Phase 4 Transformer work leads. | ○ Pending |

### Reading — Papers & Texts

| Resource | Type | When to Read | Notes |
|----------|------|-------------|-------|
| The Matrix Calculus You Need for Deep Learning (Parr & Howard) | Free PDF | Phase 2 | Dense but the definitive reference for the maths of backprop. Read alongside Phase 2 maths work. |
| Deep Learning — Goodfellow, Bengio & Courville | Free online textbook | Ongoing reference | The authoritative textbook. Use as a reference, not cover-to-cover. |
| Attention Is All You Need (Vaswani et al. 2017) | Original paper | Before Phase 4 Transformer | The paper that introduced the Transformer. Read once you understand attention conceptually. |
| Adam: A Method for Stochastic Optimization (Kingma & Ba 2014) | Original paper | Phase 3 | Short and readable. Understand the motivation before implementing Adam. |
| Dropout: A Simple Way to Prevent Overfitting (Srivastava et al.) | Original paper | Phase 3 | Short paper. The original description is clearer than most textbook treatments. |
| Auto-Encoding Variational Bayes (Kingma & Welling 2013) | Original paper | Before Phase 4 VAE | The VAE paper. Dense mathematically — read after you understand autoencoders. |
| Batch Normalization (Ioffe & Szegedy 2015) | Original paper | Phase 3 | Short. The problem it solves is as important as the solution. |

### Code Repositories

| Repository | URL | Purpose |
|-----------|-----|---------|
| micrograd | github.com/karpathy/micrograd | Karpathy's scalar autograd engine. Phase 1 reference — read after building your own. |
| nanoGPT | github.com/karpathy/nanoGPT | Minimal GPT in PyTorch. Phase 4 Transformer reference implementation. |
| makemore | github.com/karpathy/makemore | Character-level language model series. Tracks the makemore YouTube series. |
| nn-zero-to-hero | github.com/karpathy/nn-zero-to-hero | Companion notebooks for the full Karpathy YouTube series. Exercises included. |

### Tools & Environment

| Tool | Purpose | Install |
|------|---------|---------|
| Python 3.11+ | Primary language for all phases | System package or pyenv |
| NumPy | Phase 1–2 from-scratch implementations | `pip install numpy` |
| PyTorch | Phase 3+ framework implementations (prefer over TensorFlow) | pytorch.org/get-started |
| Jupyter Lab | Experimentation, visualisation, loss curve plots | `pip install jupyterlab` |
| Matplotlib | Loss curves, weight distributions, activation visualisation | `pip install matplotlib` |
| Weights & Biases | Experiment tracking for Phase 3 hyperparameter runs | `pip install wandb` |
| scikit-learn | Dataset utilities, metrics, t-SNE for latent space visualisation | `pip install scikit-learn` |
| torchvision | MNIST, CIFAR-10 dataset loaders (Phase 1 / 4) | `pip install torchvision` |

---

## QUICK REFERENCE — WHERE TO START

> **Day 1 Action:** Open a terminal, create a fresh Python virtualenv, and watch the Karpathy micrograd video (2.5 hours) with a code editor open alongside it. Type every line yourself. Do not copy-paste. That single session will give you more genuine understanding than six months of online courses.

### Minimum Viable Start (first week)

| ID | Task | Description | Status |
|----|------|-------------|--------|
| S-01 | Set up Python environment | Python 3.11+, virtualenv, NumPy, Jupyter. Nothing else yet. | ○ Pending |
| S-02 | Watch 3B1B Linear Algebra | Essence of Linear Algebra playlist, all episodes. Code nothing — just watch and absorb. | ○ Pending |
| S-03 | Watch micrograd video | Karpathy micrograd video, 2.5 hours, code editor open. Type every line. | ○ Pending |
| S-04 | Extend micrograd yourself | Add something Karpathy did not: a new activation function, a different loss, an additional operation. Break it. Fix it. | ○ Pending |
| S-05 | Watch 3B1B Neural Networks | Essence of Neural Networks playlist. After micrograd it will land completely differently. | ○ Pending |
