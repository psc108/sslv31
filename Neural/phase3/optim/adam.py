import numpy as np


class Adam:
    """Adam (Adaptive Moment Estimation) optimiser.

    Maintains per-parameter first moment (mean of gradients) and second
    moment (mean of squared gradients). Bias-corrected estimates are used
    to compute an adaptive learning rate for each parameter.

    Update rule:
        m = β1 * m + (1 - β1) * grad          # first moment (momentum)
        v = β2 * v + (1 - β2) * grad²         # second moment (RMS)
        m̂ = m / (1 - β1^t)                    # bias correction
        v̂ = v / (1 - β2^t)                    # bias correction
        param -= lr * m̂ / (sqrt(v̂) + ε)

    Why it works:
        - m̂ is a smoothed gradient direction (like momentum)
        - v̂ is a per-parameter scale — large gradients get smaller steps
        - Bias correction matters most in early steps when m and v are
          initialised at zero and would otherwise be underestimated

    Typical hyperparameters (from the original paper):
        lr=0.001, β1=0.9, β2=0.999, ε=1e-8

    Args:
        params : list of (parameter, gradient) pairs from model.params()
        lr     : learning rate (step size)
        beta1  : exponential decay for first moment
        beta2  : exponential decay for second moment
        eps    : numerical stability constant
    """

    def __init__(self, params, lr=0.001, beta1=0.9, beta2=0.999, eps=1e-8):
        self.params = params
        self.lr     = lr
        self.beta1  = beta1
        self.beta2  = beta2
        self.eps    = eps
        self.t      = 0   # step counter for bias correction

        self.m = [np.zeros_like(p) for p, _ in params]  # first moments
        self.v = [np.zeros_like(p) for p, _ in params]  # second moments

    def step(self):
        self.t += 1
        # Precompute bias correction denominators
        bc1 = 1.0 - self.beta1 ** self.t
        bc2 = 1.0 - self.beta2 ** self.t

        for i, (param, grad) in enumerate(self.params):
            self.m[i] = self.beta1 * self.m[i] + (1.0 - self.beta1) * grad
            self.v[i] = self.beta2 * self.v[i] + (1.0 - self.beta2) * grad ** 2

            m_hat = self.m[i] / bc1
            v_hat = self.v[i] / bc2

            param -= self.lr * m_hat / (np.sqrt(v_hat) + self.eps)
