import math


class Value:
    """Scalar value with automatic differentiation via reverse-mode autograd."""

    def __init__(self, data, _children=(), _op='', label=''):
        self.data = float(data)
        self.grad = 0.0
        self._backward = lambda: None
        self._prev = set(_children)
        self._op = _op
        self.label = label

    def __repr__(self):
        return f"Value(data={self.data:.4f}, grad={self.grad:.4f})"

    # --- Forward operations ---

    def __add__(self, other):
        other = other if isinstance(other, Value) else Value(other)
        out = Value(self.data + other.data, (self, other), '+')

        def _backward():
            # d(out)/d(self) = 1, d(out)/d(other) = 1
            self.grad += out.grad
            other.grad += out.grad

        out._backward = _backward
        return out

    def __mul__(self, other):
        other = other if isinstance(other, Value) else Value(other)
        out = Value(self.data * other.data, (self, other), '*')

        def _backward():
            # d(out)/d(self) = other, d(out)/d(other) = self
            self.grad += other.data * out.grad
            other.grad += self.data * out.grad

        out._backward = _backward
        return out

    def __pow__(self, exponent):
        assert isinstance(exponent, (int, float)), "exponent must be a scalar"
        out = Value(self.data ** exponent, (self,), f'**{exponent}')

        def _backward():
            # d(x^n)/dx = n * x^(n-1)
            self.grad += exponent * (self.data ** (exponent - 1)) * out.grad

        out._backward = _backward
        return out

    def exp(self):
        out = Value(math.exp(self.data), (self,), 'exp')

        def _backward():
            # d(e^x)/dx = e^x = out.data
            self.grad += out.data * out.grad

        out._backward = _backward
        return out

    def log(self):
        assert self.data > 0, "log undefined for non-positive values"
        out = Value(math.log(self.data), (self,), 'log')

        def _backward():
            # d(ln x)/dx = 1/x
            self.grad += (1.0 / self.data) * out.grad

        out._backward = _backward
        return out

    def relu(self):
        out = Value(max(0.0, self.data), (self,), 'relu')

        def _backward():
            # d(relu)/dx = 1 if x > 0 else 0
            self.grad += (1.0 if self.data > 0 else 0.0) * out.grad

        out._backward = _backward
        return out

    def tanh(self):
        t = math.tanh(self.data)
        out = Value(t, (self,), 'tanh')

        def _backward():
            # d(tanh)/dx = 1 - tanh(x)^2
            self.grad += (1.0 - t ** 2) * out.grad

        out._backward = _backward
        return out

    def sigmoid(self):
        s = 1.0 / (1.0 + math.exp(-self.data))
        out = Value(s, (self,), 'sigmoid')

        def _backward():
            # d(sigmoid)/dx = sigmoid * (1 - sigmoid)
            self.grad += s * (1.0 - s) * out.grad

        out._backward = _backward
        return out

    # --- Reverse operations (allow scalar op Value) ---

    def __radd__(self, other): return self + other
    def __rmul__(self, other): return self * other
    def __rsub__(self, other): return Value(other) + (-self)
    def __rtruediv__(self, other): return Value(other) * self ** -1

    def __neg__(self): return self * -1
    def __sub__(self, other): return self + (-other if isinstance(other, Value) else Value(-other))
    def __truediv__(self, other): return self * (other if isinstance(other, Value) else Value(other)) ** -1

    # --- Backward pass ---

    def backward(self):
        """Run reverse-mode autodiff from this node back through the graph."""
        topo = []
        visited = set()

        def build_topo(v):
            if v not in visited:
                visited.add(v)
                for child in v._prev:
                    build_topo(child)
                topo.append(v)

        build_topo(self)

        self.grad = 1.0
        for node in reversed(topo):
            node._backward()
