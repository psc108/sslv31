"""
Jasypt-compatible encryption engine.

Implements PBEWITHSHA256AND256BITAES-CBC-BC (BouncyCastle provider) to produce
ENC(...) values that can be decrypted by Java Jasypt StandardPBEStringEncryptor.

BouncyCastle PBE scheme:
  - KDF: PKCS#12 v1 (RFC 7292, Appendix B) with SHA-256
  - Cipher: AES-256-CBC
  - Output: salt || ciphertext (Base64 encoded)
  - Default iterations: 1000
"""

import hashlib
import os
import struct
from base64 import b64decode, b64encode

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7


# PKCS#12 KDF ID bytes (RFC 7292 Appendix B.3)
_KDF_ID_KEY = 1
_KDF_ID_IV = 2

DEFAULT_ITERATIONS = 1000
SALT_SIZE = 16
KEY_SIZE = 32  # AES-256
IV_SIZE = 16   # AES block size


def _pkcs12_kdf(password: str, salt: bytes, iterations: int,
                id_byte: int, dk_len: int) -> bytes:
    """
    PKCS#12 v1 key derivation function (RFC 7292 Appendix B).
    Uses SHA-256 as the hash function.

    This matches BouncyCastle's PKCS12ParametersGenerator with SHA-256.
    """
    hash_len = 64  # SHA-256 internal block size (v) for PKCS12 is 64
    u = 32  # SHA-256 output length

    # Step 1: Construct D (diversifier)
    D = bytes([id_byte]) * hash_len

    # Step 2: Construct I (salt + password in BMPString)
    # Password as BMPString (UTF-16BE with trailing 0x00 0x00)
    if password:
        password_bytes = password.encode('utf-16-be') + b'\x00\x00'
    else:
        password_bytes = b'\x00\x00'

    # Pad salt and password to multiples of hash_len (v)
    def _pad_to_block(data: bytes) -> bytes:
        if not data:
            return b''
        r = len(data) % hash_len
        if r == 0:
            return data
        return data + data[:hash_len - r]

    S = _pad_to_block(salt) if salt else b''
    P = _pad_to_block(password_bytes)
    I = S + P

    # Step 3: Iterate
    result = b''
    while len(result) < dk_len:
        # Hash: D || I
        A = hashlib.sha256(D + I).digest()
        for _ in range(iterations - 1):
            A = hashlib.sha256(A).digest()
        result += A

        if len(result) >= dk_len:
            break

        # Step 4: Update I
        # B = A repeated to fill hash_len bytes
        B = (A * (hash_len // u + 1))[:hash_len]

        # I_j = (I_j + B + 1) mod 2^(hash_len*8)
        new_I = bytearray()
        for j in range(0, len(I), hash_len):
            block = I[j:j + hash_len]
            # Add B + 1 to block (big-endian addition)
            carry = 1
            block_arr = bytearray(block)
            b_arr = bytearray(B)
            for k in range(hash_len - 1, -1, -1):
                temp = block_arr[k] + b_arr[k] + carry
                block_arr[k] = temp & 0xFF
                carry = temp >> 8
            new_I.extend(block_arr)
        I = bytes(new_I)

    return result[:dk_len]


def encrypt(plaintext: str, password: str, iterations: int = DEFAULT_ITERATIONS) -> str:
    """
    Encrypt plaintext using PBEWITHSHA256AND256BITAES-CBC-BC.

    Returns Base64-encoded string (salt + ciphertext) suitable for Jasypt ENC(...) wrapping.
    """
    salt = os.urandom(SALT_SIZE)

    # Derive key and IV using PKCS#12 KDF
    key = _pkcs12_kdf(password, salt, iterations, _KDF_ID_KEY, KEY_SIZE)
    iv = _pkcs12_kdf(password, salt, iterations, _KDF_ID_IV, IV_SIZE)

    # PKCS7 pad plaintext
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext.encode('utf-8')) + padder.finalize()

    # AES-256-CBC encrypt
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    # Output: salt || ciphertext → Base64
    return b64encode(salt + ciphertext).decode('ascii')


def decrypt(encoded: str, password: str, iterations: int = DEFAULT_ITERATIONS) -> str:
    """
    Decrypt a Jasypt-encrypted value.

    Input: Base64-encoded string (salt + ciphertext), as stored inside ENC(...).
    """
    raw = b64decode(encoded)
    salt = raw[:SALT_SIZE]
    ciphertext = raw[SALT_SIZE:]

    # Derive key and IV
    key = _pkcs12_kdf(password, salt, iterations, _KDF_ID_KEY, KEY_SIZE)
    iv = _pkcs12_kdf(password, salt, iterations, _KDF_ID_IV, IV_SIZE)

    # AES-256-CBC decrypt
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    # Remove PKCS7 padding
    unpadder = PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()

    return plaintext.decode('utf-8')


def wrap_enc(encrypted_value: str) -> str:
    """Wrap encrypted value in Jasypt ENC(...) format."""
    return f"ENC({encrypted_value})"


def unwrap_enc(wrapped: str) -> str:
    """Extract encrypted value from ENC(...) wrapper."""
    if wrapped.startswith("ENC(") and wrapped.endswith(")"):
        return wrapped[4:-1]
    return wrapped


def encrypt_wrapped(plaintext: str, password: str, iterations: int = DEFAULT_ITERATIONS) -> str:
    """Encrypt and return in ENC(...) format ready for properties files."""
    return wrap_enc(encrypt(plaintext, password, iterations))
