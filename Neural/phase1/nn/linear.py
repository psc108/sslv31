import numpy as np


class Linear:
    """Fully-connected layer: y = x @ W.T + b

    Shapes:
        x  : (batch, in_features)
        W  : (out_features, in_features)
        b  : (out_features,)
        y  : (batch, out_features)

    Gradients (derived from P2-07 matrix calculus identities):
        dL/dW = (dL/dy).T @ x          shape: (out_features, in_features)
        dL/db = dL/dy summed over batch shape: (out_features,)
        dL/dx = dL/dy @ W              shape: (batch, in_features)
    """

    def __init__(self, in_features, out_features):
        self.in_features  = in_features
        self.out_features = out_features

        # Xavier (Glorot) initialisation: keeps variance stable through layers.
        # scale = sqrt(1 / in_features)
        scale = np.sqrt(1.0 / in_features)
        self.W = np.random.randn(out_features, in_features) * scale
        self.b = np.zeros(out_features)

        self.dW = np.zeros_like(self.W)
        self.db = np.zeros_like(self.b)

    def __call__(self, x):
        return self.forward(x)

    def forward(self, x):
        """y = x @ W.T + b"""
        self._x = x
        return x @ self.W.T + self.b

    def backward(self, grad):
        """Backpropagate grad (dL/dy) through the layer.

        Returns dL/dx to pass to the previous layer.
        Accumulates dL/dW and dL/db into self.dW, self.db.
        """
        # dL/dW = (dL/dy).T @ x
        self.dW += grad.T @ self._x

        # dL/db = sum of dL/dy over the batch dimension
        self.db += grad.sum(axis=0)

        # dL/dx = dL/dy @ W  (passed back to the previous layer)
        return grad @ self.W

    def params(self):
        """Return list of (parameter, gradient) pairs for the optimiser."""
        return [(self.W, self.dW), (self.b, self.db)]

    def zero_grad(self):
        self.dW[:] = 0.0
        self.db[:] = 0.0

    def __repr__(self):
        return f"Linear(in={self.in_features}, out={self.out_features})"
