import numpy as np


class BatchNorm:
    """Batch Normalisation layer.

    Normalises each feature across the batch to zero mean and unit variance,
    then applies learnable scale (gamma) and shift (beta).

    Forward (training):
        μ  = mean(x, axis=0)
        σ² = var(x, axis=0)
        x̂  = (x - μ) / sqrt(σ² + ε)
        y  = gamma * x̂ + beta

    Forward (inference):
        Uses running mean and variance accumulated during training.
        x̂  = (x - running_mean) / sqrt(running_var + ε)
        y  = gamma * x̂ + beta

    Backward:
        Gradients for gamma, beta, and x — derived from the full
        batch norm Jacobian (see documentation).

    Why it helps:
        - Reduces internal covariate shift: each layer sees a stable
          input distribution regardless of upstream weight changes
        - Allows higher learning rates
        - Acts as mild regularisation (noise from batch statistics)
        - Gradient flow is improved — normalisation prevents saturation

    Args:
        num_features : number of features (must match layer output width)
        eps          : numerical stability constant
        momentum     : running stats update rate (0.1 = typical)
    """

    def __init__(self, num_features, eps=1e-5, momentum=0.1):
        self.eps      = eps
        self.momentum = momentum
        self.training = True

        # Learnable parameters
        self.gamma = np.ones(num_features)
        self.beta  = np.zeros(num_features)
        self.dgamma = np.zeros_like(self.gamma)
        self.dbeta  = np.zeros_like(self.beta)

        # Running statistics for inference
        self.running_mean = np.zeros(num_features)
        self.running_var  = np.ones(num_features)

    def __call__(self, x):
        return self.forward(x)

    def forward(self, x):
        if self.training:
            mu      = x.mean(axis=0)
            var     = x.var(axis=0)
            x_hat   = (x - mu) / np.sqrt(var + self.eps)

            # Cache for backward
            self._x     = x
            self._x_hat = x_hat
            self._mu    = mu
            self._var   = var
            self._std   = np.sqrt(var + self.eps)

            # Update running stats
            self.running_mean = (1 - self.momentum) * self.running_mean + self.momentum * mu
            self.running_var  = (1 - self.momentum) * self.running_var  + self.momentum * var
        else:
            x_hat = (x - self.running_mean) / np.sqrt(self.running_var + self.eps)

        return self.gamma * x_hat + self.beta

    def backward(self, grad):
        N = self._x.shape[0]

        self.dgamma += (grad * self._x_hat).sum(axis=0)
        self.dbeta  += grad.sum(axis=0)

        # Gradient with respect to x_hat
        dx_hat = grad * self.gamma

        # Full batch norm backward (Ioffe & Szegedy derivation)
        dx = (1.0 / (N * self._std)) * (
            N * dx_hat
            - dx_hat.sum(axis=0)
            - self._x_hat * (dx_hat * self._x_hat).sum(axis=0)
        )
        return dx

    def params(self):
        return [(self.gamma, self.dgamma), (self.beta, self.dbeta)]

    def zero_grad(self):
        self.dgamma[:] = 0.0
        self.dbeta[:]  = 0.0

    def __repr__(self):
        return f"BatchNorm(features={len(self.gamma)})"
