class Sequential:
    """Ordered container of layers.

    Drives the forward pass by calling each layer in order,
    and the backward pass by calling each layer in reverse.

    Usage:
        model = Sequential(
            Linear(784, 128), ReLU(),
            Linear(128, 64),  ReLU(),
            Linear(64, 10),
        )
        logits   = model(x)
        grad_in  = loss_fn.backward()
        model.backward(grad_in)
        optimiser.step()
        model.zero_grad()
    """

    def __init__(self, *layers):
        self.layers = list(layers)

    def __call__(self, x):
        return self.forward(x)

    def forward(self, x):
        for layer in self.layers:
            x = layer(x)
        return x

    def backward(self, grad):
        for layer in reversed(self.layers):
            grad = layer.backward(grad)
        return grad

    def params(self):
        """Collect (parameter, gradient) pairs from all layers that have them."""
        p = []
        for layer in self.layers:
            if hasattr(layer, 'params'):
                p.extend(layer.params())
        return p

    def zero_grad(self):
        for layer in self.layers:
            if hasattr(layer, 'zero_grad'):
                layer.zero_grad()
