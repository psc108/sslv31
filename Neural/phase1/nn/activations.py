import numpy as np


class Activation:
    """Base class for activation functions. Caches input for backward pass."""

    def __call__(self, x):
        self._x = x
        return self.forward(x)

    def forward(self, x):
        raise NotImplementedError

    def backward(self, grad):
        raise NotImplementedError

    def __repr__(self):
        return f'{self.__class__.__name__}()'


class ReLU(Activation):
    """Rectified Linear Unit: f(x) = max(0, x).

    Forward:  f(x) = x if x > 0 else 0
    Backward: f'(x) = 1 if x > 0 else 0
    """

    def forward(self, x):
        return np.maximum(0, x)

    def backward(self, grad):
        return (self._x > 0).astype(np.float64) * grad


class Sigmoid(Activation):
    """Sigmoid: f(x) = 1 / (1 + e^-x).

    Forward:  f(x) = 1 / (1 + e^-x)
    Backward: f'(x) = f(x) * (1 - f(x))
    """

    def forward(self, x):
        # Numerically stable: avoid overflow for large negative x
        self._s = np.where(x >= 0,
                           1.0 / (1.0 + np.exp(-x)),
                           np.exp(x) / (1.0 + np.exp(x)))
        return self._s

    def backward(self, grad):
        return self._s * (1.0 - self._s) * grad


class Tanh(Activation):
    """Hyperbolic tangent: f(x) = tanh(x).

    Forward:  f(x) = tanh(x)
    Backward: f'(x) = 1 - tanh(x)^2
    """

    def forward(self, x):
        self._t = np.tanh(x)
        return self._t

    def backward(self, grad):
        return (1.0 - self._t ** 2) * grad


class Softmax(Activation):
    """Softmax over the last axis: f(x)_i = e^x_i / sum(e^x_j).

    Used as the output activation for multi-class classification.
    In practice the backward pass is fused with cross-entropy loss
    (gradient simplifies to: predicted - true). The full Jacobian
    is implemented here for completeness.

    Forward:  f(x)_i = e^(x_i - max(x)) / sum_j e^(x_j - max(x))
    Backward: dL/dx_i = sum_j (dL/df_j * df_j/dx_i)
              df_j/dx_i = f_j(delta_ij - f_i)   (Jacobian of softmax)
    """

    def forward(self, x):
        # Subtract max for numerical stability (softmax is shift-invariant)
        shifted = x - x.max(axis=-1, keepdims=True)
        e = np.exp(shifted)
        self._s = e / e.sum(axis=-1, keepdims=True)
        return self._s

    def backward(self, grad):
        # For each sample: dL/dx = s * (grad - (grad * s).sum())
        # This is the efficient form of the full Jacobian contraction.
        return self._s * (grad - (grad * self._s).sum(axis=-1, keepdims=True))
