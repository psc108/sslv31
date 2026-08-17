import numpy as np


# ---------------------------------------------------------------------------
# im2col / col2im helpers
# ---------------------------------------------------------------------------

def im2col(x, kH, kW, stride=1, pad=0):
    """Rearrange image patches into columns for efficient convolution.

    Args:
        x      : (N, C, H, W)
        kH, kW : kernel height and width
        stride : convolution stride
        pad    : zero-padding on each side

    Returns:
        cols   : (N, C*kH*kW, out_H*out_W)
    """
    N, C, H, W = x.shape
    if pad > 0:
        x = np.pad(x, ((0,0),(0,0),(pad,pad),(pad,pad)), mode='constant')
    out_H = (H + 2*pad - kH) // stride + 1
    out_W = (W + 2*pad - kW) // stride + 1

    cols = np.zeros((N, C, kH, kW, out_H, out_W), dtype=x.dtype)
    for i in range(kH):
        i_max = i + stride * out_H
        for j in range(kW):
            j_max = j + stride * out_W
            cols[:, :, i, j, :, :] = x[:, :, i:i_max:stride, j:j_max:stride]

    # (N, C*kH*kW, out_H*out_W)
    return cols.reshape(N, C * kH * kW, out_H * out_W)


def col2im(cols, x_shape, kH, kW, stride=1, pad=0):
    """Inverse of im2col — accumulate column gradients back into image shape.

    Args:
        cols   : (N, C*kH*kW, out_H*out_W)
        x_shape: original (N, C, H, W) before padding
    """
    N, C, H, W = x_shape
    H_pad, W_pad = H + 2*pad, W + 2*pad
    out_H = (H + 2*pad - kH) // stride + 1
    out_W = (W + 2*pad - kW) // stride + 1

    cols_reshaped = cols.reshape(N, C, kH, kW, out_H, out_W)
    x_pad = np.zeros((N, C, H_pad, W_pad), dtype=cols.dtype)

    for i in range(kH):
        i_max = i + stride * out_H
        for j in range(kW):
            j_max = j + stride * out_W
            x_pad[:, :, i:i_max:stride, j:j_max:stride] += cols_reshaped[:, :, i, j, :, :]

    if pad > 0:
        return x_pad[:, :, pad:-pad, pad:-pad]
    return x_pad


# ---------------------------------------------------------------------------
# Conv2D
# ---------------------------------------------------------------------------

class Conv2D:
    """2D convolutional layer.

    Forward:  y = conv(x, W) + b
    Shapes:
        x : (N, C_in,  H,     W)
        W : (C_out, C_in, kH, kW)
        b : (C_out,)
        y : (N, C_out, out_H, out_W)

    Uses im2col to convert the convolution into a single matrix multiply,
    making the backward pass straightforward.

    Args:
        in_channels  : number of input channels
        out_channels : number of output filters
        kernel_size  : int or (kH, kW)
        stride       : convolution stride
        pad          : zero-padding on each side
    """

    def __init__(self, in_channels, out_channels, kernel_size, stride=1, pad=0):
        self.in_channels  = in_channels
        self.out_channels = out_channels
        self.kH = self.kW = kernel_size if isinstance(kernel_size, int) else kernel_size[0]
        self.stride = stride
        self.pad    = pad

        # He initialisation
        fan_in = in_channels * self.kH * self.kW
        scale  = np.sqrt(2.0 / fan_in)
        self.W  = np.random.randn(out_channels, in_channels, self.kH, self.kW) * scale
        self.b  = np.zeros(out_channels)
        self.dW = np.zeros_like(self.W)
        self.db = np.zeros_like(self.b)

    def __call__(self, x):
        return self.forward(x)

    def forward(self, x):
        N, C, H, W = x.shape
        out_H = (H + 2*self.pad - self.kH) // self.stride + 1
        out_W = (W + 2*self.pad - self.kW) // self.stride + 1

        # im2col: (N, C*kH*kW, out_H*out_W)
        self._cols   = im2col(x, self.kH, self.kW, self.stride, self.pad)
        self._x_shape = x.shape

        # W reshaped: (out_channels, C*kH*kW)
        W_flat = self.W.reshape(self.out_channels, -1)

        # (N, out_channels, out_H*out_W)
        out = W_flat @ self._cols + self.b[:, np.newaxis]
        return out.reshape(N, self.out_channels, out_H, out_W)

    def backward(self, grad):
        N, C_out, out_H, out_W = grad.shape

        # grad reshaped: (N, out_channels, out_H*out_W)
        grad_flat = grad.reshape(N, self.out_channels, -1)

        # dL/db: sum over N and spatial dims
        self.db += grad_flat.sum(axis=(0, 2))

        # dL/dW: (out_channels, C*kH*kW)
        W_flat = self.W.reshape(self.out_channels, -1)
        # sum over batch: (out_channels, C*kH*kW)
        dW_flat = sum(grad_flat[i] @ self._cols[i].T for i in range(N))
        self.dW += dW_flat.reshape(self.W.shape)

        # dL/dx via col2im
        # (N, C*kH*kW, out_H*out_W)
        dcols = np.stack([W_flat.T @ grad_flat[i] for i in range(N)])
        return col2im(dcols, self._x_shape, self.kH, self.kW, self.stride, self.pad)

    def params(self):
        return [(self.W, self.dW), (self.b, self.db)]

    def zero_grad(self):
        self.dW[:] = 0.0
        self.db[:] = 0.0

    def __repr__(self):
        return (f"Conv2D(in={self.in_channels}, out={self.out_channels}, "
                f"k={self.kH}, stride={self.stride}, pad={self.pad})")


# ---------------------------------------------------------------------------
# MaxPool2D
# ---------------------------------------------------------------------------

class MaxPool2D:
    """2D max pooling layer.

    Forward:  take the maximum value in each (kH, kW) window.
    Backward: route gradient only to the position that held the maximum.

    Args:
        kernel_size : pooling window size (int)
        stride      : stride (defaults to kernel_size — non-overlapping)
    """

    def __init__(self, kernel_size, stride=None):
        self.kH = self.kW = kernel_size
        self.stride = stride if stride is not None else kernel_size

    def __call__(self, x):
        return self.forward(x)

    def forward(self, x):
        N, C, H, W = x.shape
        out_H = (H - self.kH) // self.stride + 1
        out_W = (W - self.kW) // self.stride + 1

        out  = np.zeros((N, C, out_H, out_W))
        self._mask = np.zeros_like(x)

        for i in range(out_H):
            for j in range(out_W):
                h0, w0 = i * self.stride, j * self.stride
                patch = x[:, :, h0:h0+self.kH, w0:w0+self.kW]
                # Max over spatial window
                max_val = patch.max(axis=(2, 3), keepdims=True)
                out[:, :, i, j] = max_val[:, :, 0, 0]
                # Mask: 1 where the max was, 0 elsewhere
                self._mask[:, :, h0:h0+self.kH, w0:w0+self.kW] += (patch == max_val)

        return out

    def backward(self, grad):
        dx = np.zeros_like(self._mask)
        N, C, out_H, out_W = grad.shape

        for i in range(out_H):
            for j in range(out_W):
                h0, w0 = i * self.stride, j * self.stride
                # Distribute gradient to the max position
                dx[:, :, h0:h0+self.kH, w0:w0+self.kW] += (
                    self._mask[:, :, h0:h0+self.kH, w0:w0+self.kW]
                    * grad[:, :, i:i+1, j:j+1]
                )
        return dx

    def __repr__(self):
        return f"MaxPool2D(k={self.kH}, stride={self.stride})"
