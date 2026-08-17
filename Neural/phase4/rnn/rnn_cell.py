"""
Vanilla RNN — manual forward pass and BPTT.

Architecture (one time step):
    h_t = tanh(W_xh @ x_t + W_hh @ h_{t-1} + b_h)
    y_t = W_hy @ h_t + b_y

BPTT unrolls the sequence backward through time, accumulating gradients
for the shared weight matrices at every step.
"""

import numpy as np


class RNNCell:
    def __init__(self, input_size: int, hidden_size: int, output_size: int):
        # He-style scale for input weights; small scale for recurrent weights
        scale_xh = np.sqrt(2.0 / input_size)
        scale_hh = np.sqrt(2.0 / hidden_size)
        scale_hy = np.sqrt(2.0 / hidden_size)

        self.W_xh = np.random.randn(hidden_size, input_size)  * scale_xh
        self.W_hh = np.random.randn(hidden_size, hidden_size) * scale_hh
        self.b_h  = np.zeros((hidden_size, 1))
        self.W_hy = np.random.randn(output_size, hidden_size) * scale_hy
        self.b_y  = np.zeros((output_size, 1))

        self.hidden_size = hidden_size
        self.output_size = output_size

    # ------------------------------------------------------------------
    # Forward — returns logits and hidden states for the full sequence
    # ------------------------------------------------------------------
    def forward(self, inputs: list[np.ndarray], h_prev: np.ndarray):
        """
        inputs : list of T one-hot column vectors, each (input_size, 1)
        h_prev : (hidden_size, 1) initial hidden state

        Returns
        -------
        ys  : list of T raw logit vectors (output_size, 1)
        hs  : dict {-1: h_prev, 0: h_0, ..., T-1: h_{T-1}}
        """
        hs, ys = {-1: h_prev}, []
        for t, x in enumerate(inputs):
            hs[t] = np.tanh(self.W_xh @ x + self.W_hh @ hs[t - 1] + self.b_h)
            ys.append(self.W_hy @ hs[t] + self.b_y)
        return ys, hs

    # ------------------------------------------------------------------
    # Backward — BPTT over the full unrolled sequence
    # ------------------------------------------------------------------
    def backward(self, inputs: list[np.ndarray], hs: dict,
                 dy_list: list[np.ndarray]):
        """
        dy_list : list of T upstream gradients dL/dy_t, each (output_size, 1)

        Returns accumulated parameter gradients and dh for the initial state.
        Gradients are clipped to [-5, 5] to prevent explosion.
        """
        T = len(inputs)
        dW_xh = np.zeros_like(self.W_xh)
        dW_hh = np.zeros_like(self.W_hh)
        db_h  = np.zeros_like(self.b_h)
        dW_hy = np.zeros_like(self.W_hy)
        db_y  = np.zeros_like(self.b_y)
        dh_next = np.zeros((self.hidden_size, 1))

        for t in reversed(range(T)):
            dy = dy_list[t]                          # (output_size, 1)
            dW_hy += dy @ hs[t].T
            db_y  += dy

            dh = self.W_hy.T @ dy + dh_next          # gradient into h_t
            dtanh = (1 - hs[t] ** 2) * dh            # through tanh

            dW_xh += dtanh @ inputs[t].T
            dW_hh += dtanh @ hs[t - 1].T
            db_h  += dtanh
            dh_next = self.W_hh.T @ dtanh

        grads = dict(W_xh=dW_xh, W_hh=dW_hh, b_h=db_h, W_hy=dW_hy, b_y=db_y)
        for g in grads.values():
            np.clip(g, -5, 5, out=g)
        return grads

    def params(self):
        return {
            'W_xh': self.W_xh, 'W_hh': self.W_hh, 'b_h': self.b_h,
            'W_hy': self.W_hy, 'b_y': self.b_y,
        }
