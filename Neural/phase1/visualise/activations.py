import numpy as np
import matplotlib.pyplot as plt
from phase1.nn import ReLU, Sigmoid, Tanh, Softmax


def plot_activations(save_path=None):
    x = np.linspace(-5, 5, 500)
    grad_in = np.ones_like(x)   # upstream gradient of 1 to get raw derivative

    activations = [ReLU(), Sigmoid(), Tanh()]
    names       = ['ReLU', 'Sigmoid', 'Tanh']
    colors      = ['#e74c3c', '#2ecc71', '#3498db']

    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    fig.suptitle('Activation Functions & Their Gradients', fontsize=14, fontweight='bold')

    for col, (act, name, color) in enumerate(zip(activations, names, colors)):
        y    = act(x)
        dy   = act.backward(grad_in)

        # Top row: function
        ax = axes[0, col]
        ax.plot(x, y, color=color, linewidth=2)
        ax.axhline(0, color='black', linewidth=0.5)
        ax.axvline(0, color='black', linewidth=0.5)
        ax.set_title(name, fontsize=12)
        ax.set_ylabel('f(x)')
        ax.set_ylim(-1.5, 1.5)
        ax.grid(True, alpha=0.3)

        # Bottom row: gradient
        ax = axes[1, col]
        ax.plot(x, dy, color=color, linewidth=2, linestyle='--')
        ax.axhline(0, color='black', linewidth=0.5)
        ax.axvline(0, color='black', linewidth=0.5)
        ax.set_ylabel("f'(x)")
        ax.set_ylim(-0.5, 1.5)
        ax.grid(True, alpha=0.3)
        ax.set_xlabel('x')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved to {save_path}")
    else:
        plt.show()


def plot_softmax(save_path=None):
    """Show softmax output and gradient for a 3-class example across a range of logit values."""
    z_range = np.linspace(-4, 4, 300)

    # Vary z[0] while holding z[1]=0, z[2]=1 fixed
    logits = np.stack([z_range, np.zeros_like(z_range), np.ones_like(z_range)], axis=1)

    act = Softmax()
    probs = act(logits)                          # (300, 3)
    grad_in = np.ones_like(probs) / probs.shape[1]
    grads = act.backward(grad_in)               # (300, 3)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))
    fig.suptitle('Softmax (3 classes, varying z[0])', fontsize=13, fontweight='bold')

    for i, (color, label) in enumerate(zip(['#e74c3c','#2ecc71','#3498db'],
                                            ['class 0','class 1','class 2'])):
        ax1.plot(z_range, probs[:, i], color=color, label=label, linewidth=2)
        ax2.plot(z_range, grads[:, i], color=color, label=label, linewidth=2, linestyle='--')

    for ax, ylabel, title in [
        (ax1, 'probability', 'Softmax output'),
        (ax2, 'gradient',    'Softmax gradient'),
    ]:
        ax.axhline(0, color='black', linewidth=0.5)
        ax.axvline(0, color='black', linewidth=0.5)
        ax.set_xlabel('z[0]')
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.legend()
        ax.grid(True, alpha=0.3)

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved to {save_path}")
    else:
        plt.show()


if __name__ == '__main__':
    plot_activations()
    plot_softmax()
