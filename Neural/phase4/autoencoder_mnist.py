"""
P4-08 — Autoencoder on MNIST.

Trains a 2D-bottleneck autoencoder on MNIST, then:
  1. Plots a grid of original vs reconstructed digits
  2. Encodes the full test set and plots the 2D latent space,
     coloured by digit class — shows class clustering without
     any label supervision during training

Usage:
    python3 -m phase4.autoencoder_mnist
"""

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.manifold import TSNE

from phase1.data.mnist import load
from phase4.autoencoder.autoencoder import Autoencoder


# ---------------------------------------------------------------------------
# Adam optimiser (operates on flat param list)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
def train():
    np.random.seed(42)

    X_train, y_train, X_test, y_test = load(flatten=True, normalise=True)
    # Cast to float32 to halve memory — sufficient precision for this task
    X_train = X_train.astype(np.float32)
    X_test  = X_test.astype(np.float32)

    n_train  = len(X_train)
    latent   = 2        # 2D bottleneck so we can plot directly without t-SNE
    hidden   = 256
    batch    = 128
    epochs   = 20
    lr       = 1e-3

    model = Autoencoder(input_dim=784, hidden_dim=hidden, latent_dim=latent)
    opt   = Adam(model.params(), lr=lr)

    print(f"Training autoencoder  latent_dim={latent}  hidden={hidden}  "
          f"batch={batch}  epochs={epochs}")

    for epoch in range(1, epochs + 1):
        idx = np.random.permutation(n_train)
        epoch_loss = 0.0
        steps = 0
        for start in range(0, n_train, batch):
            xb = X_train[idx[start:start + batch]]
            model.zero_grad()
            x_hat, _ = model.forward(xb)
            loss = model.loss(x_hat, xb)
            model.backward()
            opt.step()
            epoch_loss += loss
            steps += 1

        # Validation reconstruction loss on 1000 test samples
        x_val = X_test[:1000]
        x_hat_val, _ = model.forward(x_val)
        val_loss = model.loss(x_hat_val, x_val)
        print(f"epoch {epoch:>2}  train_loss {epoch_loss/steps:.5f}  "
              f"val_loss {val_loss:.5f}")

    return model, X_train, y_train, X_test, y_test


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------
def plot_reconstructions(model, X_test, save_path='phase4/autoencoder_reconstructions.png'):
    """Side-by-side grid: original (top row) vs reconstruction (bottom row)."""
    n = 10
    samples = X_test[:n]
    recons, _ = model.forward(samples)

    fig, axes = plt.subplots(2, n, figsize=(14, 3))
    for i in range(n):
        axes[0, i].imshow(samples[i].reshape(28, 28), cmap='gray', vmin=0, vmax=1)
        axes[1, i].imshow(recons[i].reshape(28, 28),  cmap='gray', vmin=0, vmax=1)
        for row in range(2):
            axes[row, i].axis('off')
    axes[0, 0].set_ylabel('Original', fontsize=9)
    axes[1, 0].set_ylabel('Recon',    fontsize=9)
    plt.suptitle('Autoencoder Reconstructions (MNIST)', fontsize=11)
    plt.tight_layout()
    plt.savefig(save_path, dpi=120)
    plt.close()
    print(f"Saved: {save_path}")


def plot_latent_space(model, X_test, y_test,
                      save_path='phase4/autoencoder_latent.png'):
    """
    Encode the full test set and plot the 2D latent space coloured by class.

    With latent_dim=2 we can plot directly — no t-SNE needed.
    We also run t-SNE on the latent codes to show what it does to the
    already-structured space (it should look similar since it's already 2D).
    """
    # Encode in batches to avoid large memory spike
    batch = 512
    zs = []
    for start in range(0, len(X_test), batch):
        zs.append(model.encode(X_test[start:start + batch]))
    Z = np.concatenate(zs, axis=0)   # (10000, 2)

    colours = plt.cm.tab10(np.linspace(0, 1, 10))

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Left: raw 2D latent codes
    ax = axes[0]
    for digit in range(10):
        mask = y_test == digit
        ax.scatter(Z[mask, 0], Z[mask, 1], s=2, alpha=0.4,
                   color=colours[digit], label=str(digit))
    ax.set_title('2D Latent Space (direct)')
    ax.legend(markerscale=4, loc='upper right', fontsize=7)
    ax.set_xlabel('z₀'); ax.set_ylabel('z₁')

    # Right: t-SNE on the latent codes (subsample 3000 for speed)
    np.random.seed(0)
    idx = np.random.choice(len(Z), 3000, replace=False)
    Z_sub = Z[idx]; y_sub = y_test[idx]
    print("Running t-SNE on latent codes...")
    Z_tsne = TSNE(n_components=2, perplexity=30, random_state=0).fit_transform(Z_sub)

    ax = axes[1]
    for digit in range(10):
        mask = y_sub == digit
        ax.scatter(Z_tsne[mask, 0], Z_tsne[mask, 1], s=4, alpha=0.5,
                   color=colours[digit], label=str(digit))
    ax.set_title('t-SNE of Latent Codes (3k samples)')
    ax.legend(markerscale=3, loc='upper right', fontsize=7)
    ax.set_xlabel('t-SNE 1'); ax.set_ylabel('t-SNE 2')

    plt.suptitle('MNIST Autoencoder — Latent Space', fontsize=12)
    plt.tight_layout()
    plt.savefig(save_path, dpi=120)
    plt.close()
    print(f"Saved: {save_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    model, X_train, y_train, X_test, y_test = train()
    plot_reconstructions(model, X_test)
    plot_latent_space(model, X_test, y_test)
