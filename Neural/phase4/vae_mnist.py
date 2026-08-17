"""
P4-09 — Variational Autoencoder on MNIST.

Trains a VAE (latent_dim=16, BCE loss, KL warm-up), then:
  1. Plots original vs reconstructed digits
  2. t-SNE of posterior means coloured by digit class
  3. Samples z ~ N(0,I) and decodes to generate new digits
  4. Traverses a 20x20 grid over the first two latent dimensions

Usage:
    python3 -m phase4.vae_mnist
"""

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.manifold import TSNE

from phase1.data.mnist import load
from phase4.autoencoder.vae import VAE


class Adam:
    def __init__(self, params, lr=1e-3, beta1=0.9, beta2=0.999, eps=1e-8):
        self.params = params
        self.lr = lr; self.beta1 = beta1; self.beta2 = beta2; self.eps = eps
        self.m = [np.zeros_like(p) for p, _ in params]
        self.v = [np.zeros_like(p) for p, _ in params]
        self.t = 0

    def step(self):
        self.t += 1
        for i, (p, g) in enumerate(self.params):
            self.m[i] = self.beta1 * self.m[i] + (1 - self.beta1) * g
            self.v[i] = self.beta2 * self.v[i] + (1 - self.beta2) * g**2
            m_hat = self.m[i] / (1 - self.beta1**self.t)
            v_hat = self.v[i] / (1 - self.beta2**self.t)
            p -= self.lr * m_hat / (np.sqrt(v_hat) + self.eps)


def train():
    np.random.seed(42)
    X_train, y_train, X_test, y_test = load(flatten=True, normalise=True)
    X_train = X_train.astype(np.float32)
    X_test  = X_test.astype(np.float32)

    n_train       = len(X_train)
    latent        = 16    # large enough that KL can compete with reconstruction
    hidden        = 256
    batch         = 128
    epochs        = 20
    lr            = 1e-3
    beta          = 1.0
    warmup_epochs = 5     # anneal beta 0 -> 1 over first 5 epochs

    model = VAE(input_dim=784, hidden_dim=hidden, latent_dim=latent,
                beta=0.0, free_bits=0.1)
    opt   = Adam(model.params(), lr=lr)

    print(f"Training VAE  latent={latent}  hidden={hidden}  "
          f"batch={batch}  epochs={epochs}  BCE  KL-warmup={warmup_epochs}")

    for epoch in range(1, epochs + 1):
        model.beta = beta * min(1.0, epoch / warmup_epochs)
        idx = np.random.permutation(n_train)
        t_loss = r_loss = k_loss = 0.0
        steps = 0

        for start in range(0, n_train, batch):
            xb = X_train[idx[start:start + batch]]
            model.zero_grad()
            total, recon, kl = model.step(xb)
            opt.step()
            t_loss += total; r_loss += recon; k_loss += kl
            steps += 1

        x_val = X_test[:1000]
        xh, mu_v, lv_v, _ = model.forward(x_val)
        vt, vr, vk = model.loss(x_val, xh, mu_v, lv_v, model.free_bits)
        print(f"epoch {epoch:>2}  beta={model.beta:.2f}  "
              f"train {t_loss/steps:.4f} "
              f"(recon {r_loss/steps:.4f}  kl {k_loss/steps:.4f})  "
              f"val {vt:.4f} (recon {vr:.4f}  kl {vk:.4f})")

    return model, X_train, y_train, X_test, y_test


def plot_reconstructions(model, X_test, path='phase4/vae_reconstructions.png'):
    n = 10
    x = X_test[:n]
    x_hat, _, _, _ = model.forward(x)
    fig, axes = plt.subplots(2, n, figsize=(14, 3))
    for i in range(n):
        axes[0, i].imshow(x[i].reshape(28, 28),     cmap='gray', vmin=0, vmax=1)
        axes[1, i].imshow(x_hat[i].reshape(28, 28), cmap='gray', vmin=0, vmax=1)
        for row in range(2): axes[row, i].axis('off')
    axes[0, 0].set_ylabel('Original', fontsize=9)
    axes[1, 0].set_ylabel('Recon',    fontsize=9)
    plt.suptitle('VAE Reconstructions (MNIST)', fontsize=11)
    plt.tight_layout(); plt.savefig(path, dpi=120); plt.close()
    print(f"Saved: {path}")


def plot_latent_space(model, X_test, y_test, path='phase4/vae_latent.png'):
    """t-SNE of posterior means coloured by digit class."""
    batch = 512
    mus = []
    for start in range(0, len(X_test), batch):
        mu, _ = model.encode(X_test[start:start + batch])
        mus.append(mu)
    Z = np.concatenate(mus, axis=0)   # (10000, latent_dim)

    np.random.seed(0)
    idx   = np.random.choice(len(Z), 3000, replace=False)
    Z_sub = Z[idx]; y_sub = y_test[idx]
    print("Running t-SNE on posterior means...")
    Z2 = TSNE(n_components=2, perplexity=30, random_state=0).fit_transform(Z_sub)

    colours = plt.cm.tab10(np.linspace(0, 1, 10))
    fig, ax = plt.subplots(figsize=(8, 7))
    for digit in range(10):
        mask = y_sub == digit
        ax.scatter(Z2[mask, 0], Z2[mask, 1], s=4, alpha=0.5,
                   color=colours[digit], label=str(digit))
    ax.set_title('VAE Latent Space — t-SNE of Posterior Means (μ)')
    ax.legend(markerscale=3, fontsize=8)
    ax.set_xlabel('t-SNE 1'); ax.set_ylabel('t-SNE 2')
    plt.tight_layout(); plt.savefig(path, dpi=120); plt.close()
    print(f"Saved: {path}")


def plot_samples(model, path='phase4/vae_samples.png'):
    """Sample z ~ N(0,I) and decode."""
    np.random.seed(0)
    samples = model.sample(100)
    fig, axes = plt.subplots(10, 10, figsize=(10, 10))
    for i, ax in enumerate(axes.flat):
        ax.imshow(samples[i].reshape(28, 28), cmap='gray', vmin=0, vmax=1)
        ax.axis('off')
    plt.suptitle('VAE Generated Digits (z ~ N(0,I))', fontsize=12)
    plt.tight_layout(); plt.savefig(path, dpi=120); plt.close()
    print(f"Saved: {path}")


def plot_latent_traversal(model, path='phase4/vae_traversal.png'):
    """
    Vary dimensions 0 and 1 of z across a grid, hold the rest at 0.
    Shows what the decoder maps each (z0, z1) region to.
    """
    latent_dim = model.encoder.fc_mu.out_features
    n    = 20
    rng  = 3.0
    grid = np.linspace(-rng, rng, n)

    canvas = np.zeros((28 * n, 28 * n))
    for i, z1 in enumerate(grid[::-1]):
        for j, z0 in enumerate(grid):
            z       = np.zeros((1, latent_dim), dtype=np.float32)
            z[0, 0] = z0
            z[0, 1] = z1
            digit   = model.decoder.forward(z)[0].reshape(28, 28)
            canvas[i*28:(i+1)*28, j*28:(j+1)*28] = digit

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.imshow(canvas, cmap='gray', vmin=0, vmax=1)
    ax.set_title('VAE Latent Traversal (z₀ × z₁, others=0, ±3σ)', fontsize=11)
    ax.set_xlabel('z₀  →'); ax.set_ylabel('← z₁')
    ax.set_xticks([]); ax.set_yticks([])
    plt.tight_layout(); plt.savefig(path, dpi=120); plt.close()
    print(f"Saved: {path}")


if __name__ == '__main__':
    model, X_train, y_train, X_test, y_test = train()
    plot_reconstructions(model, X_test)
    plot_latent_space(model, X_test, y_test)
    plot_samples(model)
    plot_latent_traversal(model)
