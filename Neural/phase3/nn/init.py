import numpy as np


def xavier(layer):
    """Xavier/Glorot initialisation: scale = sqrt(1 / fan_in).

    Designed for Sigmoid/Tanh activations. Keeps variance of activations
    and gradients approximately equal across layers.
    """
    scale = np.sqrt(1.0 / layer.in_features)
    layer.W = np.random.randn(layer.out_features, layer.in_features) * scale
    layer.b = np.zeros(layer.out_features)


def he(layer):
    """He initialisation: scale = sqrt(2 / fan_in).

    Designed for ReLU activations. The factor of 2 compensates for ReLU
    zeroing half of its inputs on average, which would otherwise halve
    the variance at each layer.
    """
    scale = np.sqrt(2.0 / layer.in_features)
    layer.W = np.random.randn(layer.out_features, layer.in_features) * scale
    layer.b = np.zeros(layer.out_features)


def zeros(layer):
    """All-zeros initialisation — deliberately bad.

    Every neuron in a layer computes the same output and receives the same
    gradient. They never differentiate. This is the symmetry-breaking problem.
    """
    layer.W = np.zeros((layer.out_features, layer.in_features))
    layer.b = np.zeros(layer.out_features)


def large(layer, scale=10.0):
    """Large random initialisation — deliberately bad.

    Activations saturate immediately (for Sigmoid/Tanh) or explode (for ReLU).
    Gradients vanish or explode. Training fails or diverges.
    """
    layer.W = np.random.randn(layer.out_features, layer.in_features) * scale
    layer.b = np.zeros(layer.out_features)


def apply_init(model, strategy='xavier'):
    """Apply an initialisation strategy to all Linear layers in a Sequential model."""
    strategies = {'xavier': xavier, 'he': he, 'zeros': zeros, 'large': large}
    assert strategy in strategies, f"Unknown strategy '{strategy}'. Choose from {list(strategies)}"
    fn = strategies[strategy]
    for layer in model.layers:
        if hasattr(layer, 'W'):
            fn(layer)
