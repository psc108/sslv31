import json
import os
import time


class Tracker:
    """Lightweight experiment tracker.

    Logs scalar metrics per step/epoch. Saves to JSON.
    No external dependencies beyond the standard library.

    Usage:
        tracker = Tracker('my_experiment')
        for epoch in range(epochs):
            tracker.log(epoch=epoch, loss=0.5, accuracy=0.9)
        tracker.save('results/')
    """

    def __init__(self, name):
        self.name    = name
        self.records = []
        self.start   = time.time()

    def log(self, **kwargs):
        record = {'t': round(time.time() - self.start, 3)}
        record.update(kwargs)
        self.records.append(record)

    def save(self, directory='.'):
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f'{self.name}.json')
        with open(path, 'w') as f:
            json.dump({'name': self.name, 'records': self.records}, f, indent=2)
        return path

    def get(self, key):
        """Return list of values for a logged key."""
        return [r[key] for r in self.records if key in r]

    def summary(self):
        if not self.records:
            return
        keys = [k for k in self.records[-1] if k != 't']
        print(f'\n--- {self.name} ---')
        for key in keys:
            vals = self.get(key)
            if vals:
                print(f'  {key}: first={vals[0]:.4f}  last={vals[-1]:.4f}  '
                      f'min={min(vals):.4f}  max={max(vals):.4f}')


def plot_history(trackers, metric='loss', save_path=None):
    """Plot a metric from one or more Tracker instances."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print('matplotlib not installed — skipping plot')
        return

    fig, ax = plt.subplots(figsize=(9, 5))
    for tracker in trackers:
        vals = tracker.get(metric)
        if vals:
            ax.plot(vals, label=tracker.name)

    ax.set_xlabel('Epoch')
    ax.set_ylabel(metric)
    ax.set_title(metric)
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f'Saved to {save_path}')
    else:
        plt.show()
