import math


class StepDecay:
    """Multiply LR by gamma every step_size epochs.

    Intuition: coarse steps early, fine steps later.
    """

    def __init__(self, optimiser, step_size, gamma=0.5):
        self.optimiser = optimiser
        self.step_size = step_size
        self.gamma     = gamma
        self.base_lr   = optimiser.lr

    def step(self, epoch):
        self.optimiser.lr = self.base_lr * (self.gamma ** (epoch // self.step_size))


class CosineDecay:
    """Anneal LR from base_lr to min_lr following a cosine curve.

    Intuition: fast progress early, gentle convergence at the end.
    Avoids the abrupt drops of step decay.
    """

    def __init__(self, optimiser, total_epochs, min_lr=0.0):
        self.optimiser     = optimiser
        self.total_epochs  = total_epochs
        self.min_lr        = min_lr
        self.base_lr       = optimiser.lr

    def step(self, epoch):
        progress = epoch / self.total_epochs
        cosine   = 0.5 * (1.0 + math.cos(math.pi * progress))
        self.optimiser.lr = self.min_lr + (self.base_lr - self.min_lr) * cosine


class WarmupCosineDecay:
    """Linear warmup for warmup_epochs, then cosine decay to min_lr.

    Intuition: start with tiny LR to stabilise early gradients,
    then ramp up before decaying. Common in Transformer training.
    """

    def __init__(self, optimiser, total_epochs, warmup_epochs, min_lr=0.0):
        self.optimiser      = optimiser
        self.total_epochs   = total_epochs
        self.warmup_epochs  = warmup_epochs
        self.min_lr         = min_lr
        self.base_lr        = optimiser.lr

    def step(self, epoch):
        if epoch < self.warmup_epochs:
            # Linear ramp from 0 to base_lr
            self.optimiser.lr = self.base_lr * (epoch + 1) / self.warmup_epochs
        else:
            # Cosine decay from base_lr to min_lr over remaining epochs
            progress = (epoch - self.warmup_epochs) / (self.total_epochs - self.warmup_epochs)
            cosine   = 0.5 * (1.0 + math.cos(math.pi * progress))
            self.optimiser.lr = self.min_lr + (self.base_lr - self.min_lr) * cosine
