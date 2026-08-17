import numpy as np


def train(model, loss_fn, optimiser, X, y,
          epochs=100, batch_size=32, print_every=10):
    """Train a Sequential model with mini-batch gradient descent.

    Args:
        model      : Sequential instance
        loss_fn    : CrossEntropyLoss or MSELoss instance
        optimiser  : SGD (or any optimiser with a .step() method)
        X          : (N, features)  training inputs
        y          : (N,)           training labels (integer class indices)
        epochs     : number of full passes over the training data
        batch_size : number of examples per mini-batch
        print_every: print loss/accuracy every n epochs (0 = silent)

    Returns:
        history : dict with 'loss' and 'accuracy' lists (one entry per epoch)
    """
    N = X.shape[0]
    history = {'loss': [], 'accuracy': []}

    for epoch in range(1, epochs + 1):
        # Shuffle training data each epoch
        indices = np.random.permutation(N)
        X_shuf, y_shuf = X[indices], y[indices]

        epoch_loss = 0.0
        epoch_acc  = 0.0
        n_batches  = 0

        for start in range(0, N, batch_size):
            xb = X_shuf[start : start + batch_size]
            yb = y_shuf[start : start + batch_size]

            # 1. Forward pass
            logits = model(xb)

            # 2. Compute loss
            loss = loss_fn(logits, yb)

            # 3. Backward pass
            grad = loss_fn.backward()
            model.backward(grad)

            # 4. Optimiser step
            optimiser.step()

            # 5. Zero gradients for next batch
            model.zero_grad()

            epoch_loss += loss
            if hasattr(loss_fn, 'accuracy'):
                epoch_acc += loss_fn.accuracy(yb)
            n_batches += 1

        avg_loss = epoch_loss / n_batches
        avg_acc  = epoch_acc  / n_batches

        history['loss'].append(avg_loss)
        history['accuracy'].append(avg_acc)

        if print_every and epoch % print_every == 0:
            print(f'Epoch {epoch:4d}/{epochs}  loss: {avg_loss:.4f}  acc: {avg_acc:.4f}')

    return history


def evaluate(model, loss_fn, X, y, batch_size=256):
    """Evaluate model on a dataset. Returns (loss, accuracy)."""
    N = X.shape[0]
    total_loss = 0.0
    total_acc  = 0.0
    n_batches  = 0

    for start in range(0, N, batch_size):
        xb = X[start : start + batch_size]
        yb = y[start : start + batch_size]

        logits = model(xb)
        loss   = loss_fn(logits, yb)

        total_loss += loss
        if hasattr(loss_fn, 'accuracy'):
            total_acc += loss_fn.accuracy(yb)
        n_batches += 1

    return total_loss / n_batches, total_acc / n_batches
