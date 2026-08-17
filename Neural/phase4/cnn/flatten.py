import numpy as np


class Flatten:
    """Flatten all dimensions except batch into a single vector.

    Forward:  (N, C, H, W) -> (N, C*H*W)
    Backward: (N, C*H*W)   -> (N, C, H, W)
    """

    def __call__(self, x):
        return self.forward(x)

    def forward(self, x):
        self._shape = x.shape
        return x.reshape(x.shape[0], -1)

    def backward(self, grad):
        return grad.reshape(self._shape)

    def __repr__(self):
        return "Flatten()"
