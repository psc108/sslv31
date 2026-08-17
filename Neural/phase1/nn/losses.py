import numpy as np


class MSELoss:
    """Mean Squared Error loss: L = mean((y_pred - y_true)^2)

    Used for regression. Not suitable for classification — see CrossEntropyLoss.

    Forward:  L = (1/N) * sum((y_pred - y_true)^2)
    Backward: dL/dy_pred = (2/N) * (y_pred - y_true)
    """

    def __call__(self, y_pred, y_true):
        return self.forward(y_pred, y_true)

    def forward(self, y_pred, y_true):
        self._diff = y_pred - y_true
        self._n    = y_pred.size      # total elements, not just batch rows
        return np.mean(self._diff ** 2)

    def backward(self):
        return (2.0 / self._n) * self._diff


class CrossEntropyLoss:
    """Softmax + Cross-Entropy loss for multi-class classification.

    Takes raw logits (pre-softmax scores), not probabilities.
    Fusing softmax and cross-entropy gives a numerically stable backward
    pass with a clean gradient: (softmax(logits) - one_hot(y_true)) / batch.

    Forward:
        probs = softmax(logits)
        L     = -mean( sum_k( y_true_k * log(probs_k) ) )
              = -mean( log(probs[correct_class]) )   for one-hot targets

    Backward:
        dL/d(logits) = (probs - y_true) / batch

    Args:
        logits : (batch, num_classes)  raw scores
        y_true : (batch,)              integer class indices
                 OR (batch, num_classes) one-hot encoded
    """

    def __call__(self, logits, y_true):
        return self.forward(logits, y_true)

    def forward(self, logits, y_true):
        batch = logits.shape[0]

        # Numerically stable softmax
        shifted = logits - logits.max(axis=1, keepdims=True)
        e       = np.exp(shifted)
        self._probs = e / e.sum(axis=1, keepdims=True)

        # Convert integer labels to one-hot if needed
        if y_true.ndim == 1:
            one_hot = np.zeros_like(self._probs)
            one_hot[np.arange(batch), y_true.astype(int)] = 1.0
        else:
            one_hot = y_true

        self._one_hot = one_hot
        self._batch   = batch

        # Cross-entropy: -mean( sum( y_true * log(probs) ) )
        log_probs = np.log(np.clip(self._probs, 1e-12, 1.0))
        return -np.sum(one_hot * log_probs) / batch

    def backward(self):
        # Fused softmax + cross-entropy gradient: (probs - y_true) / batch
        return (self._probs - self._one_hot) / self._batch

    def predictions(self):
        """Return predicted class indices (argmax of softmax probabilities)."""
        return np.argmax(self._probs, axis=1)

    def accuracy(self, y_true):
        """Fraction of correct predictions. y_true must be integer labels."""
        if y_true.ndim > 1:
            y_true = np.argmax(y_true, axis=1)
        return np.mean(self.predictions() == y_true.astype(int))
