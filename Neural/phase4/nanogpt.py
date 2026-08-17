"""
P4-07 — nanoGPT: annotated character-level GPT in PyTorch.

A clean, fully-commented port of Karpathy's nanoGPT, trained on the
tiny Shakespeare dataset (~1MB). Every architectural decision is explained
inline. Run with different CONFIG presets to observe the effect of each
hyperparameter.

Usage:
    .venv/bin/python -m phase4.nanogpt                    # default (small)
    .venv/bin/python -m phase4.nanogpt --config medium
    .venv/bin/python -m phase4.nanogpt --config deep
    .venv/bin/python -m phase4.nanogpt --config wide_ctx
"""

import argparse
import math
import time
import torch
import torch.nn as nn
from torch.nn import functional as F

# ---------------------------------------------------------------------------
# Hyperparameter configs — swap these to observe the effect of each knob
# ---------------------------------------------------------------------------
CONFIGS = {
    # Baseline: small model, fast to train, establishes the reference loss
    'small': dict(
        n_layer=4, n_head=4, d_model=128,
        ctx=128, batch=32, lr=3e-3, n_iters=3000,
        desc="4 layers, 4 heads, d=128, ctx=128"
    ),
    # More layers: deeper residual stack — can model longer-range structure
    # but harder to optimise (more gradient path length)
    'deep': dict(
        n_layer=8, n_head=4, d_model=128,
        ctx=128, batch=32, lr=3e-3, n_iters=3000,
        desc="8 layers (2×depth), 4 heads, d=128, ctx=128"
    ),
    # More heads: finer-grained attention subspaces — each head d_k=32 vs 32
    # (same total params in attention, different inductive bias)
    'medium': dict(
        n_layer=4, n_head=8, d_model=128,
        ctx=128, batch=32, lr=3e-3, n_iters=3000,
        desc="4 layers, 8 heads (2×heads), d=128, ctx=128"
    ),
    # Wider context: model sees 4× more history per step — should capture
    # longer-range dependencies but each forward pass is more expensive
    'wide_ctx': dict(
        n_layer=4, n_head=4, d_model=128,
        ctx=512, batch=16, lr=3e-3, n_iters=3000,
        desc="4 layers, 4 heads, d=128, ctx=512 (4×context)"
    ),
}

# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------
DATA_PATH = 'data/shakespeare/input.txt'

def load_data():
    with open(DATA_PATH, 'r') as f:
        text = f.read()
    chars  = sorted(set(text))
    vocab  = len(chars)
    ch2ix  = {c: i for i, c in enumerate(chars)}
    data   = torch.tensor([ch2ix[c] for c in text], dtype=torch.long)
    # 90/10 train/val split
    n      = int(0.9 * len(data))
    return data[:n], data[n:], vocab, {i: c for c, i in ch2ix.items()}

def get_batch(data: torch.Tensor, ctx: int, batch: int, device: str):
    """Sample `batch` random context windows from data."""
    ix = torch.randint(len(data) - ctx, (batch,))
    x  = torch.stack([data[i    : i + ctx    ] for i in ix])
    y  = torch.stack([data[i + 1: i + ctx + 1] for i in ix])
    return x.to(device), y.to(device)

# ---------------------------------------------------------------------------
# Model components
# ---------------------------------------------------------------------------

class CausalSelfAttention(nn.Module):
    """
    Multi-head causal self-attention.

    PyTorch version of what we built manually in P4-05/P4-06.
    nn.Linear handles the QKV projection and output projection.
    The causal mask is registered as a buffer (not a parameter —
    it doesn't get gradients or appear in model.parameters()).

    Key difference from P4-06: dropout on attention weights.
    Dropout here acts as a stochastic structural regulariser —
    it randomly zeroes out attention edges, forcing the model
    not to rely on any single attention pattern.
    """

    def __init__(self, d_model: int, n_head: int, ctx: int, dropout: float):
        super().__init__()
        assert d_model % n_head == 0
        self.n_head  = n_head
        self.d_k     = d_model // n_head

        # Combined QKV projection — one Linear instead of three
        self.c_attn  = nn.Linear(d_model, 3 * d_model, bias=True)
        self.c_proj  = nn.Linear(d_model, d_model,     bias=True)
        self.attn_drop = nn.Dropout(dropout)
        self.resid_drop = nn.Dropout(dropout)

        # Causal mask: lower-triangular ones, upper-triangular -inf after softmax
        # Registered as buffer so it moves to the right device with .to(device)
        self.register_buffer(
            'mask',
            torch.tril(torch.ones(ctx, ctx)).view(1, 1, ctx, ctx)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, C = x.shape                                 # batch, time, d_model

        # Project and split into Q, K, V — then reshape into (B, n_head, T, d_k)
        # This is the batched multi-head formulation: all heads computed in parallel
        q, k, v = self.c_attn(x).split(C, dim=2)
        q = q.view(B, T, self.n_head, self.d_k).transpose(1, 2)  # (B, H, T, d_k)
        k = k.view(B, T, self.n_head, self.d_k).transpose(1, 2)
        v = v.view(B, T, self.n_head, self.d_k).transpose(1, 2)

        # Scaled dot-product attention
        # (B, H, T, d_k) @ (B, H, d_k, T) → (B, H, T, T)
        scale  = 1.0 / math.sqrt(self.d_k)
        scores = q @ k.transpose(-2, -1) * scale
        scores = scores.masked_fill(self.mask[:, :, :T, :T] == 0, float('-inf'))
        weights = F.softmax(scores, dim=-1)
        weights = self.attn_drop(weights)

        # (B, H, T, T) @ (B, H, T, d_k) → (B, H, T, d_k)
        out = weights @ v
        # Reassemble heads: (B, H, T, d_k) → (B, T, d_model)
        out = out.transpose(1, 2).contiguous().view(B, T, C)
        return self.resid_drop(self.c_proj(out))


class FeedForward(nn.Module):
    """
    Position-wise feed-forward network.

    Two linear layers with GELU activation (not ReLU as in P4-06).
    GELU is smoother than ReLU — it doesn't hard-zero negative inputs,
    it attenuates them. GPT-2 uses GELU; it empirically outperforms ReLU
    on language tasks.

    Inner dimension is 4 * d_model — the standard Transformer ratio.
    """

    def __init__(self, d_model: int, dropout: float):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(d_model, 4 * d_model),
            nn.GELU(),
            nn.Linear(4 * d_model, d_model),
            nn.Dropout(dropout),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class TransformerBlock(nn.Module):
    """
    One GPT-style decoder block: pre-norm, attention + FF, both with residuals.

        x = x + Attention(LayerNorm(x))
        x = x + FeedForward(LayerNorm(x))

    Pre-norm (LN before sublayer) is more stable than the original post-norm.
    The residual connections give gradients a direct path to early layers.
    """

    def __init__(self, d_model: int, n_head: int, ctx: int, dropout: float):
        super().__init__()
        self.ln1  = nn.LayerNorm(d_model)
        self.attn = CausalSelfAttention(d_model, n_head, ctx, dropout)
        self.ln2  = nn.LayerNorm(d_model)
        self.ff   = FeedForward(d_model, dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.attn(self.ln1(x))
        x = x + self.ff(self.ln2(x))
        return x


class GPT(nn.Module):
    """
    Decoder-only Transformer language model (GPT architecture).

    token embedding  (vocab, d_model)
    + position embedding (ctx, d_model)   ← learned, unlike our sinusoidal P4-06
    → N × TransformerBlock
    → LayerNorm
    → Linear (d_model → vocab)

    Note: learned positional embeddings (nn.Embedding) rather than sinusoidal.
    Both work; learned embeddings are slightly more flexible but don't
    generalise to lengths beyond ctx. nanoGPT uses learned — we follow that.

    Weight tying: the output projection shares weights with the token embedding.
    This is a standard trick (Press & Wolf 2017) — the embedding and unembedding
    matrices are doing inverse operations, so sharing weights reduces parameters
    and often improves performance.
    """

    def __init__(self, vocab: int, d_model: int, n_head: int,
                 n_layer: int, ctx: int, dropout: float = 0.1):
        super().__init__()
        self.ctx = ctx

        self.transformer = nn.ModuleDict(dict(
            tok_emb = nn.Embedding(vocab, d_model),
            pos_emb = nn.Embedding(ctx, d_model),
            drop    = nn.Dropout(dropout),
            blocks  = nn.ModuleList([
                TransformerBlock(d_model, n_head, ctx, dropout)
                for _ in range(n_layer)
            ]),
            ln_f    = nn.LayerNorm(d_model),
        ))
        self.lm_head = nn.Linear(d_model, vocab, bias=False)

        # Weight tying: lm_head and tok_emb share the same weight matrix
        self.transformer.tok_emb.weight = self.lm_head.weight

        # Initialise weights: std=0.02 for embeddings/linears (GPT-2 style),
        # residual projections scaled down by 1/sqrt(2*n_layer) so the
        # residual stream variance stays ~1 regardless of depth
        self.apply(self._init_weights)
        for name, p in self.named_parameters():
            if name.endswith('c_proj.weight'):
                nn.init.normal_(p, mean=0.0, std=0.02 / math.sqrt(2 * n_layer))

    def _init_weights(self, module):
        if isinstance(module, nn.Linear):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if module.bias is not None:
                nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(self, idx: torch.Tensor,
                targets: torch.Tensor = None):
        B, T = idx.shape
        assert T <= self.ctx

        pos = torch.arange(T, device=idx.device)
        x   = self.transformer.drop(
                  self.transformer.tok_emb(idx) +
                  self.transformer.pos_emb(pos)
              )
        for block in self.transformer.blocks:
            x = block(x)
        x = self.transformer.ln_f(x)
        logits = self.lm_head(x)                          # (B, T, vocab)

        loss = None
        if targets is not None:
            # Flatten to (B*T, vocab) for cross-entropy
            loss = F.cross_entropy(
                logits.view(-1, logits.size(-1)),
                targets.view(-1)
            )
        return logits, loss

    @torch.no_grad()
    def generate(self, idx: torch.Tensor, length: int,
                 temperature: float = 0.8, top_k: int = None) -> torch.Tensor:
        """
        Autoregressive generation with optional top-k sampling.

        top_k: restrict sampling to the k most probable tokens.
        This prevents the model from sampling very unlikely tokens
        while still allowing diversity (unlike greedy argmax).
        """
        for _ in range(length):
            idx_ctx = idx[:, -self.ctx:]                  # truncate to ctx
            logits, _ = self(idx_ctx)
            logits = logits[:, -1, :] / temperature       # last position only

            if top_k is not None:
                # Zero out all logits below the top-k threshold
                v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                logits[logits < v[:, [-1]]] = float('-inf')

            probs = F.softmax(logits, dim=-1)
            next_tok = torch.multinomial(probs, num_samples=1)
            idx = torch.cat([idx, next_tok], dim=1)
        return idx

    def num_params(self) -> int:
        # Subtract tied embedding weights (counted twice otherwise)
        return sum(p.numel() for p in self.parameters()) \
               - self.transformer.tok_emb.weight.numel()

# ---------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------

@torch.no_grad()
def estimate_loss(model, train_data, val_data, ctx, batch, device, eval_iters=50):
    """Estimate loss on train and val by averaging over eval_iters batches."""
    model.eval()
    out = {}
    for split, data in [('train', train_data), ('val', val_data)]:
        losses = []
        for _ in range(eval_iters):
            x, y = get_batch(data, ctx, batch, device)
            _, loss = model(x, y)
            losses.append(loss.item())
        out[split] = sum(losses) / len(losses)
    model.train()
    return out


def run(config_name: str):
    cfg    = CONFIGS[config_name]
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"\n{'='*60}")
    print(f"Config: {config_name} — {cfg['desc']}")
    print(f"Device: {device}")

    train_data, val_data, vocab, ix2ch = load_data()
    print(f"Vocab: {vocab} chars  |  "
          f"Train: {len(train_data):,} tokens  |  "
          f"Val: {len(val_data):,} tokens")

    model = GPT(
        vocab   = vocab,
        d_model = cfg['d_model'],
        n_head  = cfg['n_head'],
        n_layer = cfg['n_layer'],
        ctx     = cfg['ctx'],
    ).to(device)
    print(f"Parameters: {model.num_params():,}")

    # AdamW — Adam with decoupled weight decay.
    # Weight decay is applied to weight matrices but NOT to biases or
    # LayerNorm parameters (they don't benefit from regularisation).
    decay_params  = [p for n, p in model.named_parameters()
                     if p.dim() >= 2]
    nodecay_params = [p for n, p in model.named_parameters()
                      if p.dim() < 2]
    optimiser = torch.optim.AdamW([
        {'params': decay_params,   'weight_decay': 0.1},
        {'params': nodecay_params, 'weight_decay': 0.0},
    ], lr=cfg['lr'])

    # Cosine LR schedule with linear warmup (200 iters)
    # Warmup prevents large early updates when the model is random.
    # Cosine decay smoothly reduces LR to near-zero by the end.
    warmup = 200
    def lr_lambda(it):
        if it < warmup:
            return it / warmup
        progress = (it - warmup) / max(1, cfg['n_iters'] - warmup)
        return 0.5 * (1.0 + math.cos(math.pi * progress))
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimiser, lr_lambda)

    t0 = time.time()
    for it in range(1, cfg['n_iters'] + 1):
        x, y = get_batch(train_data, cfg['ctx'], cfg['batch'], device)
        _, loss = model(x, y)
        optimiser.zero_grad()
        loss.backward()
        # Gradient clipping: prevents occasional large gradient steps
        # that destabilise training. 1.0 is the standard nanoGPT value.
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimiser.step()
        scheduler.step()

        if it % 500 == 0 or it == 1:
            metrics = estimate_loss(model, train_data, val_data,
                                    cfg['ctx'], cfg['batch'], device)
            elapsed = time.time() - t0
            lr_now  = optimiser.param_groups[0]['lr']
            print(f"iter {it:>5}  "
                  f"train {metrics['train']:.4f}  "
                  f"val {metrics['val']:.4f}  "
                  f"lr {lr_now:.2e}  "
                  f"time {elapsed:.0f}s")

    # Sample from the trained model
    print("\n--- Sample (temperature=0.8, top_k=40) ---")
    seed = torch.zeros((1, 1), dtype=torch.long, device=device)
    out  = model.generate(seed, length=300, temperature=0.8, top_k=40)
    print(''.join(ix2ch[i] for i in out[0].tolist()))
    print(f"\nTotal time: {time.time() - t0:.0f}s")
    return metrics['val']


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='small',
                        choices=list(CONFIGS.keys()))
    args = parser.parse_args()
    run(args.config)
