import numpy as np


class SGD:
    """Stochastic gradient descent with optional momentum.

    Vanilla SGD (momentum=0):
        param -= lr * grad

    With momentum (β > 0):
        v = β * v + grad          # accumulate velocity
        param -= lr * v

    Momentum smooths oscillation by accumulating a velocity vector in
    directions of persistent gradient. It helps escape shallow local minima
    and speeds convergence in ravine-shaped loss landscapes.

    Args:
        params   : list of (parameter, gradient) pairs from model.params()
        lr       : learning rate
        momentum : momentum coefficient β (0 = vanilla SGD, 0.9 = typical)
    """

    def __init__(self, params, lr=0.01, momentum=0.0):
        self.params   = params
        self.lr       = lr
        self.momentum = momentum
        # Velocity buffers — one per parameter, initialised to zero
        self.velocity = [np.zeros_like(p) for p, _ in params]

    def step(self):
        for i, (param, grad) in enumerate(self.params):
            if self.momentum > 0:
                self.velocity[i] = self.momentum * self.velocity[i] + grad
                param -= self.lr * self.velocity[i]
            else:
                param -= self.lr * grad
