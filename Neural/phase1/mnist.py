"""P1-07 — MNIST Benchmark

Target: 97%+ test accuracy with a 3-layer fully-connected network,
        pure NumPy, no frameworks.

Architecture:
    Input (784) -> Linear(256) -> ReLU -> Linear(128) -> ReLU -> Linear(10)
    Loss: CrossEntropyLoss (softmax fused)
    Optimiser: SGD with a simple step-decay learning rate schedule
"""

import numpy as np

from phase1.data import load
from phase1.nn import Linear, ReLU, Sequential, CrossEntropyLoss
from phase1.optim import SGD
from phase1.train import train, evaluate


def run(data_dir='data/mnist', epochs=30, batch_size=64, seed=42):
    np.random.seed(seed)

    # --- Data ---
    print('Loading MNIST...')
    X_train, y_train, X_test, y_test = load(data_dir=data_dir)
    print(f'  Train: {X_train.shape}  Test: {X_test.shape}')

    # --- Model ---
    model = Sequential(
        Linear(784, 256), ReLU(),
        Linear(256, 128), ReLU(),
        Linear(128, 10),
    )

    loss_fn   = CrossEntropyLoss()
    optimiser = SGD(model.params(), lr=0.1)

    print(f'\nArchitecture:')
    for layer in model.layers:
        print(f'  {layer}')

    # --- Training with step-decay LR schedule ---
    # Drop LR by 0.5 at epoch 15 and 22 — keeps convergence stable in later epochs
    print(f'\nTraining for {epochs} epochs...\n')

    all_history = {'loss': [], 'accuracy': []}

    schedule = {15: 0.05, 22: 0.01}

    for epoch in range(1, epochs + 1):
        if epoch in schedule:
            optimiser.lr = schedule[epoch]
            print(f'  [LR decay] lr -> {optimiser.lr}')

        indices  = np.random.permutation(len(X_train))
        X_shuf   = X_train[indices]
        y_shuf   = y_train[indices]

        epoch_loss = 0.0
        epoch_acc  = 0.0
        n_batches  = 0

        for start in range(0, len(X_train), batch_size):
            xb = X_shuf[start : start + batch_size]
            yb = y_shuf[start : start + batch_size]

            logits = model(xb)
            loss   = loss_fn(logits, yb)
            grad   = loss_fn.backward()
            model.backward(grad)
            optimiser.step()
            model.zero_grad()

            epoch_loss += loss
            epoch_acc  += loss_fn.accuracy(yb)
            n_batches  += 1

        avg_loss = epoch_loss / n_batches
        avg_acc  = epoch_acc  / n_batches
        all_history['loss'].append(avg_loss)
        all_history['accuracy'].append(avg_acc)

        print(f'Epoch {epoch:3d}/{epochs}  loss: {avg_loss:.4f}  train_acc: {avg_acc:.4f}')

    # --- Final evaluation ---
    print('\n--- Test Set Evaluation ---')
    test_loss, test_acc = evaluate(model, loss_fn, X_test, y_test, batch_size=256)
    print(f'Test loss:     {test_loss:.4f}')
    print(f'Test accuracy: {test_acc:.4f}  ({test_acc*100:.2f}%)')

    target = 0.97
    if test_acc >= target:
        print(f'\n✓ Target achieved: {test_acc*100:.2f}% >= {target*100:.0f}%')
    else:
        print(f'\n✗ Target not reached: {test_acc*100:.2f}% < {target*100:.0f}%')

    return test_acc, all_history


if __name__ == '__main__':
    run()
