"""P3-08 — Vanishing / Exploding Gradients Experiment

Deliberately constructs a 20-layer network with Sigmoid activations
and observes gradient collapse. Then repeats with ReLU to show the fix.

Run:
    python3 -m phase3.experiments.vanishing_gradients
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from phase1.nn import Linear, Sequential, CrossEntropyLoss
from phase1.nn.activations import Sigmoid, ReLU


def build_deep_network(depth, activation_class, init_scale=1.0):
    layers = []
    for i in range(depth):
        in_f  = 64 if i > 0 else 32
        out_f = 64 if i < depth - 1 else 10
        lin   = Linear(in_f, out_f)
        # Override Xavier with fixed scale to make the experiment clear
        lin.W = np.random.randn(*lin.W.shape) * init_scale / np.sqrt(in_f)
        layers.append(lin)
        if i < depth - 1:
            layers.append(activation_class())
    return Sequential(*layers)


def measure_grad_norms(model, x, y):
    """Run one forward+backward and return per-layer gradient norms."""
    loss_fn = CrossEntropyLoss()
    logits  = model(x)
    loss    = loss_fn(logits, y)
    grad    = loss_fn.backward()
    model.backward(grad)

    norms = []
    for layer in model.layers:
        if hasattr(layer, 'dW'):
            norms.append(np.linalg.norm(layer.dW))
    return norms


def run():
    np.random.seed(42)
    depth = 20
    x = np.random.randn(64, 32)
    y = np.random.randint(0, 10, 64)

    print(f'=== {depth}-layer network: gradient norms per Linear layer ===')
    print(f'{"Layer":<8} {"Sigmoid":>14} {"ReLU":>14}')
    print('-' * 38)

    sig_model  = build_deep_network(depth, Sigmoid)
    relu_model = build_deep_network(depth, ReLU)

    sig_norms  = measure_grad_norms(sig_model, x, y)
    relu_norms = measure_grad_norms(relu_model, x, y)

    for i, (s, r) in enumerate(zip(sig_norms, relu_norms)):
        print(f'Layer {i+1:<3} {s:>14.2e} {r:>14.2e}')

    print()
    print(f'Sigmoid — first layer norm: {sig_norms[0]:.2e}  '
          f'last layer norm: {sig_norms[-1]:.2e}')
    print(f'ReLU    — first layer norm: {relu_norms[0]:.2e}  '
          f'last layer norm: {relu_norms[-1]:.2e}')

    ratio_sig  = sig_norms[-1]  / (sig_norms[0]  + 1e-30)
    ratio_relu = relu_norms[-1] / (relu_norms[0] + 1e-30)
    print(f'\nSigmoid output/input gradient ratio: {ratio_sig:.2e}  '
          f'({"VANISHED" if ratio_sig < 1e-3 else "ok"})')
    print(f'ReLU    output/input gradient ratio: {ratio_relu:.2e}  '
          f'({"ok" if ratio_relu > 1e-3 else "vanished"})')


if __name__ == '__main__':
    run()
