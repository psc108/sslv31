"""P3-09 — Learning Rate Schedule Comparison

Trains the same network on MNIST with three different LR schedules
and compares convergence. Logs results with the Tracker.

Run:
    python3 -m phase3.experiments.lr_schedules
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from phase1.data import load
from phase1.nn import Linear, ReLU, Sequential, CrossEntropyLoss
from phase3.optim import SGD, StepDecay, CosineDecay, WarmupCosineDecay
from phase3.experiments.tracker import Tracker, plot_history


def train_one(schedule_name, schedule_fn, X_train, y_train, X_test, y_test,
              epochs=20, batch_size=64, base_lr=0.1):
    np.random.seed(42)
    model    = Sequential(Linear(784, 256), ReLU(), Linear(256, 128), ReLU(), Linear(128, 10))
    loss_fn  = CrossEntropyLoss()
    opt      = SGD(model.params(), lr=base_lr)
    schedule = schedule_fn(opt)
    tracker  = Tracker(schedule_name)

    N = len(X_train)
    for epoch in range(epochs):
        schedule.step(epoch)

        idx    = np.random.permutation(N)
        X_s, y_s = X_train[idx], y_train[idx]
        e_loss, e_acc, nb = 0.0, 0.0, 0

        for start in range(0, N, batch_size):
            xb, yb = X_s[start:start+batch_size], y_s[start:start+batch_size]
            logits = model(xb)
            loss   = loss_fn(logits, yb)
            model.backward(loss_fn.backward())
            opt.step()
            model.zero_grad()
            e_loss += loss; e_acc += loss_fn.accuracy(yb); nb += 1

        # Test accuracy
        test_logits = model(X_test)
        loss_fn(test_logits, y_test)
        test_acc = loss_fn.accuracy(y_test)

        tracker.log(epoch=epoch, loss=e_loss/nb, train_acc=e_acc/nb,
                    test_acc=test_acc, lr=opt.lr)
        print(f'  [{schedule_name}] epoch {epoch+1:2d}  '
              f'loss={e_loss/nb:.4f}  test_acc={test_acc:.4f}  lr={opt.lr:.5f}')

    return tracker


def run():
    print('Loading MNIST...')
    X_train, y_train, X_test, y_test = load(data_dir='data/mnist')

    epochs   = 20
    base_lr  = 0.1
    schedules = {
        'StepDecay':        lambda opt: StepDecay(opt, step_size=5, gamma=0.5),
        'CosineDecay':      lambda opt: CosineDecay(opt, total_epochs=epochs),
        'WarmupCosine':     lambda opt: WarmupCosineDecay(opt, total_epochs=epochs, warmup_epochs=3),
    }

    trackers = []
    for name, fn in schedules.items():
        print(f'\n--- {name} ---')
        t = train_one(name, fn, X_train, y_train, X_test, y_test,
                      epochs=epochs, base_lr=base_lr)
        t.summary()
        trackers.append(t)

    os.makedirs('results', exist_ok=True)
    for t in trackers:
        t.save('results')

    plot_history(trackers, metric='test_acc', save_path='results/lr_schedule_comparison.png')


if __name__ == '__main__':
    run()
