import pytest
from cryptography.fernet import Fernet

from oki.crypto.envelope import EnvelopeCipher
from oki.api.errors import ProblemException


def test_encrypt_decrypt_roundtrip() -> None:
    key = Fernet.generate_key().decode()
    cipher = EnvelopeCipher(key)
    plaintext = b"sensitive token data"
    ciphertext = cipher.encrypt(plaintext)
    assert ciphertext != plaintext
    decrypted = cipher.decrypt(ciphertext)
    assert decrypted == plaintext


def test_key_rotation_decrypts_with_old_key() -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    old_cipher = EnvelopeCipher(old_key)
    ciphertext = old_cipher.encrypt(b"secret")
    new_cipher = EnvelopeCipher(new_key, previous_keys=(old_key,))
    decrypted = new_cipher.decrypt(ciphertext)
    assert decrypted == b"secret"


def test_reencrypt_with_new_key() -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    old_cipher = EnvelopeCipher(old_key)
    ciphertext = old_cipher.encrypt(b"rotate me")
    new_cipher = EnvelopeCipher(new_key, previous_keys=(old_key,))
    decrypted = new_cipher.decrypt(ciphertext)
    reencrypted = new_cipher.encrypt(decrypted)
    assert reencrypted != ciphertext
    assert new_cipher.decrypt(reencrypted) == b"rotate me"


def test_decrypt_with_unknown_key_raises() -> None:
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()
    cipher_a = EnvelopeCipher(key_a)
    ciphertext = cipher_a.encrypt(b"secret")
    cipher_b = EnvelopeCipher(key_b)
    with pytest.raises(ProblemException) as exc_info:
        cipher_b.decrypt(ciphertext)
    assert exc_info.value.code == "token_decryption_failed"


def test_generate_key_returns_urlsafe_base64() -> None:
    key = EnvelopeCipher.generate_key()
    assert isinstance(key, str)
    assert len(key.encode()) == 44
    Fernet(key.encode())
