import numpy as np


class Dropout:
    """Dropout regularisation layer.

    During training, randomly zeroes each activation with probability p.
    Surviving activations are scaled up by 1/(1-p) — inverted dropout —
    so the expected value of each activation is unchanged. This means
    no scaling adjustment is needed at inference time.

    Why it works:
        Each forward pass uses a different random subset of neurons.
        The network cannot rely on any single neuron and must learn
        redundant representations. At inference, all neurons are active,
        which approximates averaging over the exponentially many
        sub-networks trained during dropout — an implicit ensemble.

    Args:
        p : probability of zeroing an activation (0.5 = typical hidden layer,
            0.1-0.2 = typical for input layer)
    """

    def __init__(self, p=0.5):
        assert 0.0 <= p < 1.0, "Dropout probability must be in [0, 1)"
        self.p        = p
        self.training = True
        self._mask    = None

    def __call__(self, x):
        return self.forward(x)

    def forward(self, x):
        if not self.training or self.p == 0.0:
            return x
        # Inverted dropout: scale surviving activations by 1/(1-p)
        self._mask = (np.random.rand(*x.shape) > self.p).astype(np.float64)
        return x * self._mask / (1.0 - self.p)

    def backward(self, grad):
        if not self.training or self.p == 0.0:
            return grad
        return grad * self._mask / (1.0 - self.p)

    def __repr__(self):
        return f"Dropout(p={self.p})"
