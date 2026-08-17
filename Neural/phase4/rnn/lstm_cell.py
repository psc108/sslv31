"""
LSTM Cell — manual forward pass and BPTT.

One time step:
    z   = W @ [h_{t-1}; x_t] + b        (combined linear projection, 4*hidden)
    i   = sigmoid(z[0:H])                (input gate)
    f   = sigmoid(z[H:2H])               (forget gate)
    g   = tanh(z[2H:3H])                 (cell gate / candidate)
    o   = sigmoid(z[3H:4H])              (output gate)
    c_t = f * c_{t-1} + i * g            (cell state update)
    h_t = o * tanh(c_t)                  (hidden state)
    y_t = W_hy @ h_t + b_y              (output logits)

All four gates are computed in a single matrix multiply by stacking the
weight matrices — this is the standard efficient formulation.
"""

import numpy as np


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return np.where(x >= 0, 1 / (1 + np.exp(-x)), np.exp(x) / (1 + np.exp(x)))


class LSTMCell:
    def __init__(self, input_size: int, hidden_size: int, output_size: int):
        H, I = hidden_size, input_size
        # Combined weight matrix for all four gates: (4H, H+I)
        scale = np.sqrt(2.0 / (H + I))
        self.W  = np.random.randn(4 * H, H + I) * scale
        self.b  = np.zeros((4 * H, 1))
        # Forget gate bias initialised to 1 — helps gradient flow early in training
        self.b[H:2*H] = 1.0

        scale_hy = np.sqrt(2.0 / H)
        self.W_hy = np.random.randn(output_size, H) * scale_hy
        self.b_y  = np.zeros((output_size, 1))

        self.hidden_size = H
        self.output_size = output_size

    # ------------------------------------------------------------------
    # Forward
    # ------------------------------------------------------------------
    def forward(self, inputs: list[np.ndarray],
                h_prev: np.ndarray, c_prev: np.ndarray):
        """
        inputs : list of T one-hot column vectors (input_size, 1)
        h_prev : (H, 1)
        c_prev : (H, 1)

        Returns
        -------
        ys    : list of T logit vectors (output_size, 1)
        cache : dict of all intermediate values needed for backward
        """
        H = self.hidden_size
        T = len(inputs)
        hs = {-1: h_prev}
        cs = {-1: c_prev}
        gates = {}   # stores (i, f, g, o, z) per step
        ys = []

        for t, x in enumerate(inputs):
            hx = np.vstack([hs[t - 1], x])          # (H+I, 1)
            z  = self.W @ hx + self.b                # (4H, 1)
            i  = _sigmoid(z[0:H])
            f  = _sigmoid(z[H:2*H])
            g  = np.tanh(z[2*H:3*H])
            o  = _sigmoid(z[3*H:4*H])
            cs[t] = f * cs[t - 1] + i * g
            hs[t] = o * np.tanh(cs[t])
            gates[t] = (i, f, g, o, hx, cs[t - 1])
            ys.append(self.W_hy @ hs[t] + self.b_y)

        return ys, hs, cs, gates

    # ------------------------------------------------------------------
    # Backward — BPTT
    # ------------------------------------------------------------------
    def backward(self, dy_list: list[np.ndarray],
                 hs: dict, cs: dict, gates: dict):
        """
        dy_list : list of T upstream gradients dL/dy_t (output_size, 1)

        Returns parameter gradients. Gradients clipped to [-5, 5].
        """
        H = self.hidden_size
        T = len(dy_list)
        dW    = np.zeros_like(self.W)
        db    = np.zeros_like(self.b)
        dW_hy = np.zeros_like(self.W_hy)
        db_y  = np.zeros_like(self.b_y)
        dh_next = np.zeros((H, 1))
        dc_next = np.zeros((H, 1))

        for t in reversed(range(T)):
            i, f, g, o, hx, c_prev = gates[t]
            c_t = cs[t]

            dy = dy_list[t]
            dW_hy += dy @ hs[t].T
            db_y  += dy

            dh = self.W_hy.T @ dy + dh_next          # (H, 1)

            # Backward through h_t = o * tanh(c_t)
            tanh_c = np.tanh(c_t)
            do = dh * tanh_c
            dc = dh * o * (1 - tanh_c ** 2) + dc_next

            # Backward through c_t = f * c_prev + i * g
            df = dc * c_prev
            dc_next = dc * f
            di = dc * g
            dg = dc * i

            # Backward through gate activations
            dz = np.vstack([
                di * i * (1 - i),          # sigmoid'(i)
                df * f * (1 - f),          # sigmoid'(f)
                dg * (1 - g ** 2),         # tanh'(g)
                do * o * (1 - o),          # sigmoid'(o)
            ])                             # (4H, 1)

            dW   += dz @ hx.T
            db   += dz
            dhx   = self.W.T @ dz          # (H+I, 1)
            dh_next = dhx[:H]              # gradient into h_{t-1}

        grads = dict(W=dW, b=db, W_hy=dW_hy, b_y=db_y)
        for g in grads.values():
            np.clip(g, -5, 5, out=g)
        return grads

    def params(self):
        return {'W': self.W, 'b': self.b, 'W_hy': self.W_hy, 'b_y': self.b_y}
