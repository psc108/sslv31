import numpy as np

from phase1.nn.losses import CrossEntropyLoss as _BaseCE


class CrossEntropyWithL2(_BaseCE):
    """Cross-entropy loss with L2 weight decay regularisation.

    L_total = L_ce + (lambda/2) * sum(W²)

    The L2 term penalises large weights, pushing them toward zero.
    Its gradient adds lambda * W to the weight gradient at each step,
    which is equivalent to multiplying weights by (1 - lr * lambda)
    before the gradient update — hence the name 'weight decay'.

    Bayesian interpretation: L2 regularisation is equivalent to placing
    a zero-mean Gaussian prior on the weights. MAP estimation under this
    prior gives the L2-regularised objective.

    Args:
        l2_lambda : regularisation strength (0 = no regularisation)
    """

    def __init__(self, l2_lambda=0.0):
        self.l2_lambda = l2_lambda
        self._l2_grad_pairs = []

    def __call__(self, logits, y_true, model=None):
        return self.forward(logits, y_true, model)

    def forward(self, logits, y_true, model=None):
        ce_loss = super().forward(logits, y_true)

        self._l2_grad_pairs = []
        l2_loss = 0.0

        if self.l2_lambda > 0.0 and model is not None:
            for layer in model.layers:
                if hasattr(layer, 'W'):
                    l2_loss += 0.5 * self.l2_lambda * np.sum(layer.W ** 2)
                    # Store reference so backward can add L2 gradient to dW
                    self._l2_grad_pairs.append((layer.W, layer.dW))

        return ce_loss + l2_loss

    def backward(self):
        grad = super().backward()
        # Add L2 gradient (lambda * W) directly to each weight's gradient
        for W, dW in self._l2_grad_pairs:
            dW += self.l2_lambda * W
        return grad
