import numpy as np


class Tensor:
    """N-dimensional array with reverse-mode automatic differentiation."""

    def __init__(self, data, _children=(), _op='', label=''):
        self.data = np.array(data, dtype=np.float64)
        self.grad = np.zeros_like(self.data)
        self._backward = lambda: None
        self._prev = set(_children)
        self._op = _op
        self.label = label

    def __repr__(self):
        return f"Tensor(shape={self.data.shape}, op='{self._op}')"

    def _wrap(self, other):
        return other if isinstance(other, Tensor) else Tensor(other)

    # --- Forward operations ---

    def __add__(self, other):
        other = self._wrap(other)
        out = Tensor(self.data + other.data, (self, other), '+')

        def _backward():
            # Addition distributes gradient to both inputs.
            # sum_to handles broadcasting: if shapes differ, sum over broadcast dims.
            self.grad  += _sum_to(out.grad, self.data.shape)
            other.grad += _sum_to(out.grad, other.data.shape)

        out._backward = _backward
        return out

    def __mul__(self, other):
        other = self._wrap(other)
        out = Tensor(self.data * other.data, (self, other), '*')

        def _backward():
            # Elementwise multiply: d(out)/d(self) = other, and vice versa.
            self.grad  += _sum_to(other.data * out.grad, self.data.shape)
            other.grad += _sum_to(self.data  * out.grad, other.data.shape)

        out._backward = _backward
        return out

    def __pow__(self, exponent):
        assert isinstance(exponent, (int, float))
        out = Tensor(self.data ** exponent, (self,), f'**{exponent}')

        def _backward():
            # d(x^n)/dx = n * x^(n-1)
            self.grad += exponent * (self.data ** (exponent - 1)) * out.grad

        out._backward = _backward
        return out

    def matmul(self, other):
        """Matrix multiplication: out = self @ other.
        
        Gradients (from P2-07 matrix calculus identities):
            dL/d(self)  = dL/d(out) @ otherᵀ
            dL/d(other) = selfᵀ @ dL/d(out)
        """
        other = self._wrap(other)
        out = Tensor(self.data @ other.data, (self, other), 'matmul')

        def _backward():
            self.grad  += out.grad @ other.data.T
            other.grad += self.data.T @ out.grad

        out._backward = _backward
        return out

    def sum(self, axis=None, keepdims=False):
        out = Tensor(self.data.sum(axis=axis, keepdims=keepdims), (self,), 'sum')

        def _backward():
            # Gradient broadcasts back to the original shape.
            grad = out.grad
            if axis is not None and not keepdims:
                grad = np.expand_dims(grad, axis=axis)
            self.grad += np.broadcast_to(grad, self.data.shape)

        out._backward = _backward
        return out

    def exp(self):
        e = np.exp(self.data)
        out = Tensor(e, (self,), 'exp')

        def _backward():
            # d(e^x)/dx = e^x
            self.grad += e * out.grad

        out._backward = _backward
        return out

    def log(self):
        out = Tensor(np.log(self.data), (self,), 'log')

        def _backward():
            # d(ln x)/dx = 1/x
            self.grad += (1.0 / self.data) * out.grad

        out._backward = _backward
        return out

    def relu(self):
        out = Tensor(np.maximum(0, self.data), (self,), 'relu')

        def _backward():
            # d(relu)/dx = 1 where x > 0, else 0
            self.grad += (self.data > 0).astype(np.float64) * out.grad

        out._backward = _backward
        return out

    def tanh(self):
        t = np.tanh(self.data)
        out = Tensor(t, (self,), 'tanh')

        def _backward():
            self.grad += (1.0 - t ** 2) * out.grad

        out._backward = _backward
        return out

    def sigmoid(self):
        s = 1.0 / (1.0 + np.exp(-self.data))
        out = Tensor(s, (self,), 'sigmoid')

        def _backward():
            self.grad += s * (1.0 - s) * out.grad

        out._backward = _backward
        return out

    @property
    def T(self):
        out = Tensor(self.data.T, (self,), 'T')

        def _backward():
            self.grad += out.grad.T

        out._backward = _backward
        return out

    @property
    def shape(self):
        return self.data.shape

    # --- Reverse operations ---

    def __radd__(self, other): return self + other
    def __rmul__(self, other): return self * other
    def __neg__(self): return self * -1
    def __sub__(self, other): return self + (other * -1 if isinstance(other, Tensor) else Tensor(-np.array(other)))
    def __rsub__(self, other): return self._wrap(other) + (-self)
    def __truediv__(self, other): return self * self._wrap(other) ** -1
    def __matmul__(self, other): return self.matmul(other)

    # --- Backward pass ---

    def backward(self):
        """Reverse-mode autodiff from this node through the full graph."""
        topo = []
        visited = set()

        def build_topo(v):
            if v not in visited:
                visited.add(v)
                for child in v._prev:
                    build_topo(child)
                topo.append(v)

        build_topo(self)

        self.grad = np.ones_like(self.data)
        for node in reversed(topo):
            node._backward()

    def zero_grad(self):
        self.grad = np.zeros_like(self.data)


# --- Helpers ---

def _sum_to(grad, target_shape):
    """Sum gradient array down to target_shape, handling broadcasting."""
    if grad.shape == target_shape:
        return grad
    # Sum over any leading dimensions added by broadcasting
    ndim_added = grad.ndim - len(target_shape)
    for _ in range(ndim_added):
        grad = grad.sum(axis=0)
    # Sum over dimensions that were size-1 in the original (broadcast dims)
    for i, (gs, ts) in enumerate(zip(grad.shape, target_shape)):
        if ts == 1 and gs != 1:
            grad = grad.sum(axis=i, keepdims=True)
    return grad
