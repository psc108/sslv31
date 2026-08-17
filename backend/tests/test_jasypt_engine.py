"""
Tests for Jasypt encryption engine.

Verifies that encrypt/decrypt round-trips correctly and that the output
format matches what Java Jasypt StandardPBEStringEncryptor expects.
"""

import pytest
from app.services.jasypt_engine import (
    decrypt,
    encrypt,
    encrypt_wrapped,
    unwrap_enc,
    wrap_enc,
)


class TestRoundTrip:
    """Verify encrypt → decrypt produces original plaintext."""

    def test_simple_password(self):
        plaintext = "changeit"
        password = "ecssecret"
        encrypted = encrypt(plaintext, password)
        assert decrypt(encrypted, password) == plaintext

    def test_empty_plaintext(self):
        plaintext = ""
        password = "ecssecret"
        encrypted = encrypt(plaintext, password)
        assert decrypt(encrypted, password) == plaintext

    def test_long_plaintext(self):
        plaintext = "a" * 1000
        password = "ecssecret"
        encrypted = encrypt(plaintext, password)
        assert decrypt(encrypted, password) == plaintext

    def test_special_characters(self):
        plaintext = "p@$$w0rd!#%^&*()_+-=[]{}|;':\",./<>?"
        password = "my-encryption-key-2024!"
        encrypted = encrypt(plaintext, password)
        assert decrypt(encrypted, password) == plaintext

    def test_unicode_plaintext(self):
        plaintext = "pässwörd"
        password = "ecssecret"
        encrypted = encrypt(plaintext, password)
        assert decrypt(encrypted, password) == plaintext

    def test_different_passwords_produce_different_output(self):
        plaintext = "changeit"
        enc1 = encrypt(plaintext, "key1")
        enc2 = encrypt(plaintext, "key2")
        assert enc1 != enc2

    def test_same_plaintext_different_salt(self):
        """Each encryption should produce different output (random salt)."""
        plaintext = "changeit"
        password = "ecssecret"
        enc1 = encrypt(plaintext, password)
        enc2 = encrypt(plaintext, password)
        assert enc1 != enc2  # Different salts
        assert decrypt(enc1, password) == plaintext
        assert decrypt(enc2, password) == plaintext

    def test_custom_iterations(self):
        plaintext = "changeit"
        password = "ecssecret"
        encrypted = encrypt(plaintext, password, iterations=500)
        assert decrypt(encrypted, password, iterations=500) == plaintext

    def test_wrong_password_fails(self):
        plaintext = "changeit"
        encrypted = encrypt(plaintext, "correct-key")
        with pytest.raises(Exception):
            decrypt(encrypted, "wrong-key")

    def test_wrong_iterations_fails(self):
        plaintext = "changeit"
        password = "ecssecret"
        encrypted = encrypt(plaintext, password, iterations=1000)
        with pytest.raises(Exception):
            decrypt(encrypted, password, iterations=500)


class TestEncWrapper:
    """Test ENC(...) wrapping/unwrapping."""

    def test_wrap(self):
        assert wrap_enc("abc123") == "ENC(abc123)"

    def test_unwrap(self):
        assert unwrap_enc("ENC(abc123)") == "abc123"

    def test_unwrap_no_wrapper(self):
        assert unwrap_enc("plain-value") == "plain-value"

    def test_encrypt_wrapped(self):
        result = encrypt_wrapped("changeit", "ecssecret")
        assert result.startswith("ENC(")
        assert result.endswith(")")
        inner = unwrap_enc(result)
        assert decrypt(inner, "ecssecret") == "changeit"


class TestOutputFormat:
    """Verify output format matches Jasypt expectations."""

    def test_output_is_base64(self):
        """Encrypted output should be valid Base64."""
        import base64
        encrypted = encrypt("changeit", "ecssecret")
        # Should not raise
        raw = base64.b64decode(encrypted)
        # Salt (16 bytes) + at least one AES block (16 bytes)
        assert len(raw) >= 32

    def test_output_contains_salt_plus_ciphertext(self):
        """First 16 bytes are salt, remainder is ciphertext."""
        import base64
        encrypted = encrypt("changeit", "ecssecret")
        raw = base64.b64decode(encrypted)
        assert len(raw) == 32  # 16 salt + 16 ciphertext (8 chars + padding = 1 block)

    def test_longer_plaintext_output_size(self):
        """17-char plaintext should produce 2 AES blocks of ciphertext."""
        import base64
        encrypted = encrypt("a" * 17, "ecssecret")
        raw = base64.b64decode(encrypted)
        # 16 salt + 32 ciphertext (17 chars + padding = 2 blocks)
        assert len(raw) == 48


class TestSSPDefaults:
    """Test with actual SSP default values."""

    def test_default_java_security_password(self):
        """Encrypt 'changeit' with 'ecssecret' — the SSP defaults."""
        encrypted = encrypt("changeit", "ecssecret")
        assert decrypt(encrypted, "ecssecret") == "changeit"

    def test_service_account_password(self):
        encrypted = encrypt("changeit", "ecssecret")
        wrapped = wrap_enc(encrypted)
        assert wrapped.startswith("ENC(")
        assert decrypt(unwrap_enc(wrapped), "ecssecret") == "changeit"

    def test_complex_db_password(self):
        """Simulate encrypting a real database password."""
        db_pass = "Str0ng!DB#Pass_2024"
        encrypted = encrypt_wrapped(db_pass, "ecssecret")
        inner = unwrap_enc(encrypted)
        assert decrypt(inner, "ecssecret") == db_pass
