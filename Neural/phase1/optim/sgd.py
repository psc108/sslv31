class SGD:
    """Vanilla stochastic gradient descent.

    Update rule:  param -= lr * grad

    Args:
        params : list of (parameter, gradient) pairs from model.params()
        lr     : learning rate
    """

    def __init__(self, params, lr=0.01):
        self.params = params
        self.lr     = lr

    def step(self):
        for param, grad in self.params:
            param -= self.lr * grad
