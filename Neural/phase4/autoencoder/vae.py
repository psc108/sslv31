"""
Variational Autoencoder (VAE) — Kingma & Welling (2013).

Extends the P4-08 autoencoder with:
  1. Probabilistic encoder: outputs mu and log_var instead of a single z
  2. Reparameterisation trick: z = mu + eps * exp(0.5 * log_var), eps ~ N(0,1)
     Makes the sampling step differentiable so gradients flow back to the encoder
  3. KL divergence loss: KL(N(mu, var) || N(0,1)) regularises the latent space
     to be a standard normal — enables sampling at inference

Total loss:
    L = BCE(x_hat, x) + beta * KL
    KL = -0.5 * mean( sum( 1 + log_var - mu^2 - exp(log_var) ) )

Reconstruction uses binary cross-entropy (BCE), not MSE. BCE is the correct
loss for Bernoulli pixel outputs and produces much larger per-pixel gradients,
giving the KL term room to compete and preventing posterior collapse.

beta=1 is the standard VAE. KL warm-up (beta annealed 0->1 over the first
epochs) is applied in the training script to stabilise early training.

Reuses Decoder and the phase1 primitives unchanged.
"""

import numpy as np
from phase1.nn.linear      import Linear
from phase1.nn.activations  import ReLU
from phase4.autoencoder.autoencoder import Decoder


class VAEEncoder:
    """
    Same hidden layers as P4-08 Encoder, but the bottleneck splits into
    two parallel linear heads: one for mu, one for log_var.

    Using log_var instead of var keeps the parameterisation unconstrained
    (log_var can be any real; var must be positive). exp(log_var) is always
    positive, so the variance is always valid.
    """

    def __init__(self, input_dim: int, hidden_dim: int, latent_dim: int):
        self.fc1   = Linear(input_dim,       hidden_dim)
        self.act1  = ReLU()
        self.fc2   = Linear(hidden_dim,      hidden_dim // 4)
        self.act2  = ReLU()
        self.fc_mu = Linear(hidden_dim // 4, latent_dim)
        self.fc_lv = Linear(hidden_dim // 4, latent_dim)
        self._h2   = None

    def forward(self, x: np.ndarray):
        """Returns (mu, log_var) each (batch, latent_dim)."""
        h        = self.act1(self.fc1(x))
        self._h2 = self.act2(self.fc2(h))
        return self.fc_mu(self._h2), self.fc_lv(self._h2)

    def backward(self, dmu: np.ndarray, dlv: np.ndarray) -> np.ndarray:
        dh2 = self.fc_mu.backward(dmu) + self.fc_lv.backward(dlv)
        dh  = self.fc2.backward(self.act2.backward(dh2))
        return self.fc1.backward(self.act1.backward(dh))

    def params(self):
        return (self.fc1.params() + self.fc2.params() +
                self.fc_mu.params() + self.fc_lv.params())

    def zero_grad(self):
        for layer in (self.fc1, self.fc2, self.fc_mu, self.fc_lv):
            layer.zero_grad()


class VAE:
    """
    Full VAE: probabilistic encoder + reparameterisation + decoder.

    Forward:
        mu, log_var = encoder(x)
        eps         ~ N(0, I)
        z           = mu + eps * exp(0.5 * log_var)
        x_hat       = decoder(z)

    Loss:
        recon = BCE(x_hat, x) = -mean( x*log(x_hat) + (1-x)*log(1-x_hat) )
        KL    = -0.5 * mean( sum( 1 + log_var - mu^2 - exp(log_var) ) )
        L     = recon + beta * KL
    """

    def __init__(self, input_dim: int = 784, hidden_dim: int = 256,
                 latent_dim: int = 16, beta: float = 1.0, free_bits: float = 0.5):
        self.encoder   = VAEEncoder(input_dim, hidden_dim, latent_dim)
        self.decoder   = Decoder(latent_dim, hidden_dim, input_dim)
        self.beta      = beta
        self.free_bits = free_bits
        self._cache    = None

    def forward(self, x: np.ndarray):
        """Returns (x_hat, mu, log_var, z)."""
        mu, log_var = self.encoder.forward(x)
        eps  = np.random.randn(*mu.shape).astype(mu.dtype)
        z    = mu + eps * np.exp(0.5 * log_var)
        x_hat = self.decoder.forward(z)
        self._cache = (x, x_hat, mu, log_var, z, eps)
        return x_hat, mu, log_var, z

    def loss(self, x, x_hat, mu, log_var, free_bits: float = 0.5):
        """
        Returns (total, recon, kl).

        free_bits: minimum KL per latent dimension (Kingma et al. 2016).
        Each dimension is allowed at least `free_bits` nats of KL before
        the penalty kicks in. This prevents full posterior collapse while
        still allowing unused dimensions to go to zero.
        """
        c     = 1e-7
        recon = -np.mean(x * np.log(x_hat + c) + (1 - x) * np.log(1 - x_hat + c))
        # Per-dimension KL, then apply free bits floor
        kl_per_dim = -0.5 * np.mean(1 + log_var - mu**2 - np.exp(log_var), axis=0)  # (latent,)
        kl_per_dim = np.maximum(kl_per_dim, free_bits)
        kl = kl_per_dim.sum()
        return recon + self.beta * kl, recon, kl

    def backward(self, x, x_hat, mu, log_var, z, eps):
        """
        Backward through BCE reconstruction + KL + reparameterisation.

        BCE gradient:
            dBCE/d(x_hat) = -(x/x_hat - (1-x)/(1-x_hat)) / (batch*pixels)

        KL gradients (closed form):
            dKL/d(mu)      = mu / batch
            dKL/d(log_var) = 0.5 * (exp(log_var) - 1) / batch

        Reparameterisation:
            z = mu + eps * exp(0.5*log_var)
            dL/d(mu)      += dL/dz
            dL/d(log_var) += dL/dz * eps * 0.5 * exp(0.5*log_var)
        """
        batch = x.shape[0]
        c     = 1e-7

        # Reconstruction backward
        dx_hat = (-(x / (x_hat + c)) + (1 - x) / (1 - x_hat + c)) / x.size
        dz     = self.decoder.backward(dx_hat)

        # Reparameterisation backward
        std  = np.exp(0.5 * log_var)
        dmu  = dz.copy()
        dlv  = dz * eps * 0.5 * std

        # KL backward — only flows where KL > free_bits (straight-through elsewhere)
        kl_per_dim = -0.5 * np.mean(1 + log_var - mu**2 - np.exp(log_var), axis=0)
        active = (kl_per_dim > self.free_bits).astype(mu.dtype)  # (latent,)
        dmu += self.beta * active * mu / batch
        dlv += self.beta * active * 0.5 * (np.exp(log_var) - 1.0) / batch

        self.encoder.backward(dmu, dlv)

    def step(self, x: np.ndarray):
        x_hat, mu, log_var, z = self.forward(x)
        x_c, x_hat_c, mu_c, log_var_c, z_c, eps_c = self._cache
        total, recon, kl = self.loss(x, x_hat, mu, log_var, self.free_bits)
        self.backward(x, x_hat, mu, log_var, z, eps_c)
        return total, recon, kl

    def params(self):
        return self.encoder.params() + self.decoder.params()

    def zero_grad(self):
        self.encoder.zero_grad()
        self.decoder.zero_grad()

    def sample(self, n: int) -> np.ndarray:
        """Sample z ~ N(0,I) and decode."""
        z = np.random.randn(n, self.encoder.fc_mu.out_features).astype(np.float32)
        return self.decoder.forward(z)

    def encode(self, x: np.ndarray):
        return self.encoder.forward(x)
