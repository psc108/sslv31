"""
P4-03 — Vanilla RNN, character-level text generation.

Trains a single-layer RNN on a small text corpus using truncated BPTT.
Every 500 iterations prints loss and samples 200 characters from the model.

Usage:
    python3 -m phase4.rnn_char
"""

import numpy as np
from phase4.rnn.rnn_cell import RNNCell

# ---------------------------------------------------------------------------
# Corpus — small excerpt used as training text
# ---------------------------------------------------------------------------
CORPUS = """
To be, or not to be, that is the question:
Whether 'tis nobler in the mind to suffer
The slings and arrows of outrageous fortune,
Or to take arms against a sea of troubles
And by opposing end them. To die, to sleep,
No more; and by a sleep to say we end
The heartache and the thousand natural shocks
That flesh is heir to: 'tis a consummation
Devoutly to be wish'd. To die, to sleep;
To sleep, perchance to dream. Ay, there's the rub,
For in that sleep of death what dreams may come,
When we have shuffled off this mortal coil,
Must give us pause. There's the respect
That makes calamity of so long life.
For who would bear the whips and scorns of time,
The oppressor's wrong, the proud man's contumely,
The pangs of dispriz'd love, the law's delay,
The insolence of office, and the spurns
That patient merit of the unworthy takes,
When he himself might his quietus make
With a bare bodkin? Who would fardels bear,
To grunt and sweat under a weary life,
But that the dread of something after death,
The undiscover'd country, from whose bourn
No traveller returns, puzzles the will,
And makes us rather bear those ills we have
Than fly to others that we know not of?
Thus conscience does make cowards of us all,
And thus the native hue of resolution
Is sicklied o'er with the pale cast of thought,
And enterprises of great pitch and moment
With this regard their currents turn awry
And lose the name of action.
""".strip()

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------
chars  = sorted(set(CORPUS))
vocab  = len(chars)
ch2ix  = {c: i for i, c in enumerate(chars)}
ix2ch  = {i: c for c, i in ch2ix.items()}

def one_hot(ix: int) -> np.ndarray:
    v = np.zeros((vocab, 1))
    v[ix] = 1.0
    return v

# ---------------------------------------------------------------------------
# Softmax + cross-entropy helpers
# ---------------------------------------------------------------------------
def softmax(logits: np.ndarray) -> np.ndarray:
    e = np.exp(logits - logits.max())
    return e / e.sum()

def cross_entropy_seq(ys: list, targets: list[int]):
    """Returns total loss and list of dL/dy_t gradients."""
    loss, dy_list = 0.0, []
    for y, t in zip(ys, targets):
        p = softmax(y)
        loss -= np.log(p[t, 0] + 1e-8)
        dy = p.copy()
        dy[t] -= 1.0
        dy_list.append(dy)
    return loss, dy_list

# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------
def sample(cell: RNNCell, seed_ix: int, length: int = 200) -> str:
    h = np.zeros((cell.hidden_size, 1))
    ix = seed_ix
    out = [ix2ch[ix]]
    for _ in range(length - 1):
        x = one_hot(ix)
        ys, hs = cell.forward([x], h)
        h = hs[0]
        p = softmax(ys[0]).ravel()
        ix = np.random.choice(vocab, p=p)
        out.append(ix2ch[ix])
    return ''.join(out)

# ---------------------------------------------------------------------------
# Training — Adagrad, truncated BPTT with seq_len = 25
# ---------------------------------------------------------------------------
def train():
    hidden_size = 128
    seq_len     = 25
    lr          = 0.1
    n_iters     = 20_000

    cell = RNNCell(vocab, hidden_size, vocab)

    # Adagrad memory
    mem = {k: np.zeros_like(v) for k, v in cell.params().items()}

    data = [ch2ix[c] for c in CORPUS]
    n    = len(data)
    h    = np.zeros((hidden_size, 1))
    pos  = 0
    smooth_loss = -np.log(1.0 / vocab) * seq_len  # initial expected loss

    for it in range(1, n_iters + 1):
        # Reset position and hidden state at end of corpus
        if pos + seq_len + 1 >= n:
            pos, h = 0, np.zeros((hidden_size, 1))

        inputs  = [one_hot(data[pos + t])     for t in range(seq_len)]
        targets = [data[pos + t + 1]          for t in range(seq_len)]

        ys, hs = cell.forward(inputs, h)
        loss, dy_list = cross_entropy_seq(ys, targets)
        grads = cell.backward(inputs, hs, dy_list)

        # Adagrad update
        params = cell.params()
        for k in params:
            mem[k] += grads[k] ** 2
            params[k] -= lr * grads[k] / (np.sqrt(mem[k]) + 1e-8)

        h = hs[seq_len - 1].copy()  # carry hidden state forward
        pos += seq_len
        smooth_loss = 0.999 * smooth_loss + 0.001 * loss

        if it % 500 == 0 or it == 1:
            grad_norm = sum(np.linalg.norm(g) for g in grads.values())
            print(f"iter {it:>6}  loss {smooth_loss:.4f}  |grad| {grad_norm:.4f}")
            print(sample(cell, seed_ix=data[pos], length=200))
            print()

    return cell


if __name__ == '__main__':
    np.random.seed(42)
    train()
