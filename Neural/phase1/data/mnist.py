import gzip
import os
import struct
import urllib.request

import numpy as np

# MNIST IDX files hosted on Yann LeCun's site (original source)
_BASE_URL = 'https://storage.googleapis.com/cvdf-datasets/mnist/'
_FILES = {
    'train_images': 'train-images-idx3-ubyte.gz',
    'train_labels': 'train-labels-idx1-ubyte.gz',
    'test_images':  't10k-images-idx3-ubyte.gz',
    'test_labels':  't10k-labels-idx1-ubyte.gz',
}


def load(data_dir='data/mnist', normalise=True, flatten=True):
    """Download (if needed) and load MNIST as NumPy arrays.

    Args:
        data_dir  : directory to cache the raw files
        normalise : scale pixel values from [0, 255] to [0.0, 1.0]
        flatten   : return images as (N, 784) rather than (N, 28, 28)

    Returns:
        (X_train, y_train, X_test, y_test)
        X : float64 array of images
        y : int64 array of labels (0-9)
    """
    os.makedirs(data_dir, exist_ok=True)

    paths = {}
    for key, filename in _FILES.items():
        path = os.path.join(data_dir, filename)
        if not os.path.exists(path):
            url = _BASE_URL + filename
            print(f'Downloading {filename} ...', flush=True)
            urllib.request.urlretrieve(url, path)
        paths[key] = path

    X_train = _read_images(paths['train_images'])
    y_train = _read_labels(paths['train_labels'])
    X_test  = _read_images(paths['test_images'])
    y_test  = _read_labels(paths['test_labels'])

    if normalise:
        X_train = X_train / 255.0
        X_test  = X_test  / 255.0

    if flatten:
        X_train = X_train.reshape(len(X_train), -1)
        X_test  = X_test.reshape(len(X_test),  -1)

    return X_train, y_train, X_test, y_test


def _read_images(path):
    with gzip.open(path, 'rb') as f:
        magic, n, rows, cols = struct.unpack('>IIII', f.read(16))
        assert magic == 2051, f'Bad magic number in image file: {magic}'
        data = np.frombuffer(f.read(), dtype=np.uint8)
    return data.reshape(n, rows, cols).astype(np.float64)


def _read_labels(path):
    with gzip.open(path, 'rb') as f:
        magic, n = struct.unpack('>II', f.read(8))
        assert magic == 2049, f'Bad magic number in label file: {magic}'
        data = np.frombuffer(f.read(), dtype=np.uint8)
    return data.astype(np.int64)
