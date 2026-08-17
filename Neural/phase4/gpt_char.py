"""
P4-06 — GPT character-level language model from scratch.

Same corpus as P4-03/P4-04 for direct comparison.
Architecture: 2-layer Transformer, d_model=64, 4 heads, context=64.
Optimiser: Adam (lr=3e-3).

Usage:
    python3 -m phase4.gpt_char
"""

import numpy as np
from phase4.transformer.model import GPT

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

chars  = sorted(set(CORPUS))
vocab  = len(chars)
ch2ix  = {c: i for i, c in enumerate(chars)}
ix2ch  = {i: c for c, i in ch2ix.items()}
data   = [ch2ix[c] for c in CORPUS]


def softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


def cross_entropy(logits: np.ndarray, targets: list[int]):
    T = len(targets)
    probs = softmax(logits)
    loss  = -np.log(probs[np.arange(T), targets] + 1e-8).mean()
    dlogits = probs.copy()
    dlogits[np.arange(T), targets] -= 1.0
    dlogits /= T
    return loss, dlogits


def train():
    np.random.seed(42)

    # Hyperparameters
    d_model  = 64
    n_heads  = 4
    n_layers = 2
    ctx      = 64    # context window (tokens)
    lr       = 3e-3
    n_iters  = 5_000
    beta1, beta2, eps_adam = 0.9, 0.999, 1e-8

    model = GPT(vocab, d_model, n_heads, n_layers, max_T=ctx + 1)
    params = model.params()

    # Adam state
    m = {k: np.zeros_like(v) for k, v in params.items()}
    v = {k: np.zeros_like(v) for k, v in params.items()}

    n = len(data)
    smooth_loss = -np.log(1.0 / vocab) * ctx

    for it in range(1, n_iters + 1):
        # Random context window from corpus
        start   = np.random.randint(0, n - ctx - 1)
        inputs  = data[start : start + ctx]
        targets = data[start + 1 : start + ctx + 1]

        logits = model.forward(inputs)
        loss, dlogits = cross_entropy(logits, targets)
        grads = model.backward(dlogits)

        # Adam update
        for k in params:
            g = grads[k]
            np.clip(g, -1.0, 1.0, out=g)
            m[k] = beta1 * m[k] + (1 - beta1) * g
            v[k] = beta2 * v[k] + (1 - beta2) * g**2
            m_hat = m[k] / (1 - beta1**it)
            v_hat = v[k] / (1 - beta2**it)
            params[k] -= lr * m_hat / (np.sqrt(v_hat) + eps_adam)

        smooth_loss = 0.999 * smooth_loss + 0.001 * loss

        if it % 500 == 0 or it == 1:
            seed = data[np.random.randint(0, n - 1)]
            sampled = model.sample([seed], length=200, temperature=0.8)
            text = ix2ch[seed] + ''.join(ix2ch[i] for i in sampled)
            print(f"iter {it:>5}  loss {smooth_loss:.4f}")
            print(text)
            print()

    return model


if __name__ == '__main__':
    train()
