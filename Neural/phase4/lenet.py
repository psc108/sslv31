"""P4-01 — LeNet-5 from Scratch (NumPy)

LeNet-5 architecture (LeCun et al. 1998), adapted for MNIST:
    Input  (1, 28, 28)
    Conv2D (6 filters, 5x5, pad=2) -> (6, 28, 28)
    ReLU
    MaxPool2D (2x2)                -> (6, 14, 14)
    Conv2D (16 filters, 5x5)       -> (16, 10, 10)
    ReLU
    MaxPool2D (2x2)                -> (16, 5, 5)
    Flatten                        -> (400,)
    Linear (120)
    ReLU
    Linear (84)
    ReLU
    Linear (10)
    CrossEntropyLoss

Run:
    python3 -m phase4.lenet
"""

import numpy as np

from phase1.data import load
from phase1.nn import Linear, CrossEntropyLoss
from phase1.nn.activations import ReLU
from phase1.nn.model import Sequential
from phase3.optim import Adam
from phase4.cnn import Conv2D, MaxPool2D, Flatten


def build_lenet():
    return Sequential(
        Conv2D(1, 6, kernel_size=5, pad=2), ReLU(),
        MaxPool2D(kernel_size=2),
        Conv2D(6, 16, kernel_size=5), ReLU(),
        MaxPool2D(kernel_size=2),
        Flatten(),
        Linear(400, 120), ReLU(),
        Linear(120, 84),  ReLU(),
        Linear(84, 10),
    )


def run(data_dir='data/mnist', epochs=10, batch_size=64):
    np.random.seed(42)

    print('Loading MNIST...')
    X_train, y_train, X_test, y_test = load(data_dir=data_dir, flatten=False)

    # Add channel dimension: (N, 28, 28) -> (N, 1, 28, 28)
    X_train = X_train[:, np.newaxis, :, :]
    X_test  = X_test[:,  np.newaxis, :, :]
    print(f'  Train: {X_train.shape}  Test: {X_test.shape}')

    model    = build_lenet()
    loss_fn  = CrossEntropyLoss()
    opt      = Adam(model.params(), lr=0.001)

    print(f'\nArchitecture:')
    for layer in model.layers:
        print(f'  {layer}')

    print(f'\nTraining for {epochs} epochs...\n')
    N = len(X_train)

    for epoch in range(1, epochs + 1):
        idx = np.random.permutation(N)
        X_s, y_s = X_train[idx], y_train[idx]
        e_loss, e_acc, nb = 0.0, 0.0, 0

        for start in range(0, N, batch_size):
            xb = X_s[start:start+batch_size]
            yb = y_s[start:start+batch_size]

            logits = model(xb)
            loss   = loss_fn(logits, yb)
            model.backward(loss_fn.backward())
            opt.step()
            model.zero_grad()

            e_loss += loss
            e_acc  += loss_fn.accuracy(yb)
            nb     += 1

        # Test accuracy — run in small batches to avoid memory issues
        t_acc, t_nb = 0.0, 0
        for start in range(0, len(X_test), 256):
            xb = X_test[start:start+256]
            yb = y_test[start:start+256]
            loss_fn(model(xb), yb)
            t_acc += loss_fn.accuracy(yb)
            t_nb  += 1

        print(f'Epoch {epoch:2d}/{epochs}  '
              f'loss: {e_loss/nb:.4f}  '
              f'train_acc: {e_acc/nb:.4f}  '
              f'test_acc: {t_acc/t_nb:.4f}')

    print('\nDone.')


if __name__ == '__main__':
    run()
