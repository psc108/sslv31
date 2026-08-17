"""
Autoencoder — encoder/decoder bottleneck architecture.

Built entirely from phase1 primitives (Linear, ReLU, Sigmoid, MSELoss).
No new machinery needed — an autoencoder is just two MLPs chained together
with a narrow bottleneck in the middle.

Architecture:
    Encoder: 784 → 256 → 64 → latent_dim   (ReLU hidden, linear output)
    Decoder: latent_dim → 64 → 256 → 784   (ReLU hidden, Sigmoid output)

The Sigmoid output constrains reconstructions to [0, 1], matching the
normalised pixel range of the input.
"""

import numpy as np
from phase1.nn.linear     import Linear
from phase1.nn.activations import ReLU, Sigmoid
from phase1.nn.losses      import MSELoss


class Encoder:
    def __init__(self, input_dim: int, hidden_dim: int, latent_dim: int):
        self.fc1  = Linear(input_dim, hidden_dim)
        self.act1 = ReLU()
        self.fc2  = Linear(hidden_dim, hidden_dim // 4)
        self.act2 = ReLU()
        self.fc3  = Linear(hidden_dim // 4, latent_dim)
        # No activation on the bottleneck — latent codes are unconstrained reals

    def forward(self, x: np.ndarray) -> np.ndarray:
        x = self.act1(self.fc1(x))
        x = self.act2(self.fc2(x))
        return self.fc3(x)

    def backward(self, dz: np.ndarray) -> np.ndarray:
        dz = self.fc3.backward(dz)
        dz = self.act2.backward(dz)
        dz = self.fc2.backward(dz)
        dz = self.act1.backward(dz)
        return self.fc1.backward(dz)

    def params(self):
        return self.fc1.params() + self.fc2.params() + self.fc3.params()

    def zero_grad(self):
        for layer in (self.fc1, self.fc2, self.fc3):
            layer.zero_grad()


class Decoder:
    def __init__(self, latent_dim: int, hidden_dim: int, output_dim: int):
        self.fc1  = Linear(latent_dim, hidden_dim // 4)
        self.act1 = ReLU()
        self.fc2  = Linear(hidden_dim // 4, hidden_dim)
        self.act2 = ReLU()
        self.fc3  = Linear(hidden_dim, output_dim)
        self.act3 = Sigmoid()   # output in [0, 1] to match normalised pixels

    def forward(self, z: np.ndarray) -> np.ndarray:
        z = self.act1(self.fc1(z))
        z = self.act2(self.fc2(z))
        return self.act3(self.fc3(z))

    def backward(self, dx: np.ndarray) -> np.ndarray:
        dx = self.fc3.backward(self.act3.backward(dx))
        dx = self.act2.backward(dx)
        dx = self.fc2.backward(dx)
        dx = self.act1.backward(dx)
        return self.fc1.backward(dx)

    def params(self):
        return self.fc1.params() + self.fc2.params() + self.fc3.params()

    def zero_grad(self):
        for layer in (self.fc1, self.fc2, self.fc3):
            layer.zero_grad()


class Autoencoder:
    """
    Chains Encoder → Decoder. Forward pass returns the reconstruction.
    Backward pass flows gradients from MSE loss back through both halves.
    """

    def __init__(self, input_dim: int = 784,
                 hidden_dim: int = 256,
                 latent_dim: int = 2):
        self.encoder = Encoder(input_dim, hidden_dim, latent_dim)
        self.decoder = Decoder(latent_dim, hidden_dim, input_dim)
        self.loss_fn = MSELoss()

    def forward(self, x: np.ndarray):
        """Returns (reconstruction, latent_codes)."""
        z    = self.encoder.forward(x)
        x_hat = self.decoder.forward(z)
        return x_hat, z

    def loss(self, x_hat: np.ndarray, x: np.ndarray) -> float:
        return self.loss_fn(x_hat, x)

    def backward(self):
        """Backprop from MSE loss through decoder then encoder."""
        d = self.loss_fn.backward()          # dL/d(x_hat)
        dz = self.decoder.backward(d)        # dL/dz
        self.encoder.backward(dz)            # dL/d(encoder params)

    def params(self):
        return self.encoder.params() + self.decoder.params()

    def zero_grad(self):
        self.encoder.zero_grad()
        self.decoder.zero_grad()

    def encode(self, x: np.ndarray) -> np.ndarray:
        """Encode only — used for latent space inspection."""
        return self.encoder.forward(x)
