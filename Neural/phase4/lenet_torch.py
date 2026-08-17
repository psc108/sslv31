"""P4-02 — LeNet-5 in PyTorch

Direct reimplementation of P4-01 in PyTorch.
Same architecture, same dataset, same hyperparameters — compare:
  - Lines of code
  - Training speed
  - What PyTorch abstracts away

Run:
    python3 -m phase4.lenet_torch
"""

import time
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import numpy as np

from phase1.data import load


class LeNet5(nn.Module):
    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 6, kernel_size=5, padding=2), nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(6, 16, kernel_size=5), nn.ReLU(),
            nn.MaxPool2d(2),
        )
        self.classifier = nn.Sequential(
            nn.Linear(400, 120), nn.ReLU(),
            nn.Linear(120, 84),  nn.ReLU(),
            nn.Linear(84, 10),
        )

    def forward(self, x):
        return self.classifier(self.features(x).flatten(1))


def run(data_dir='data/mnist', epochs=10, batch_size=64):
    # Load MNIST via our existing loader, convert to torch tensors
    print('Loading MNIST...')
    X_train, y_train, X_test, y_test = load(data_dir=data_dir, flatten=False)

    X_train = torch.tensor(X_train[:, np.newaxis], dtype=torch.float32)
    y_train = torch.tensor(y_train, dtype=torch.long)
    X_test  = torch.tensor(X_test[:,  np.newaxis], dtype=torch.float32)
    y_test  = torch.tensor(y_test,  dtype=torch.long)

    train_loader = DataLoader(TensorDataset(X_train, y_train),
                              batch_size=batch_size, shuffle=True)
    test_loader  = DataLoader(TensorDataset(X_test,  y_test),
                              batch_size=256, shuffle=False)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f'Device: {device}')

    model     = LeNet5().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)

    print(f'\nArchitecture:\n{model}')
    total_params = sum(p.numel() for p in model.parameters())
    print(f'Total parameters: {total_params:,}')

    print(f'\nTraining for {epochs} epochs...\n')
    t0 = time.time()

    for epoch in range(1, epochs + 1):
        model.train()
        e_loss, e_correct, e_total = 0.0, 0, 0

        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()
            logits = model(xb)
            loss   = criterion(logits, yb)
            loss.backward()
            optimizer.step()

            e_loss    += loss.item()
            e_correct += (logits.argmax(1) == yb).sum().item()
            e_total   += len(yb)

        # Test accuracy
        model.eval()
        t_correct, t_total = 0, 0
        with torch.no_grad():
            for xb, yb in test_loader:
                xb, yb = xb.to(device), yb.to(device)
                t_correct += (model(xb).argmax(1) == yb).sum().item()
                t_total   += len(yb)

        print(f'Epoch {epoch:2d}/{epochs}  '
              f'loss: {e_loss/len(train_loader):.4f}  '
              f'train_acc: {e_correct/e_total:.4f}  '
              f'test_acc: {t_correct/t_total:.4f}')

    elapsed = time.time() - t0
    print(f'\nTotal training time: {elapsed:.1f}s')
    print(f'Final test accuracy: {t_correct/t_total:.4f} ({t_correct/t_total*100:.2f}%)')


if __name__ == '__main__':
    run()
