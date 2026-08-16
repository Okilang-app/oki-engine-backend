"""Envelope encryption with Fernet and key rotation support."""

from cryptography.fernet import Fernet, InvalidToken

from oki.api.errors import ProblemException


class EnvelopeCipher:
    """Encrypt and decrypt bearer tokens using Fernet with key rotation."""

    def __init__(self, primary_key: str, previous_keys: tuple[str, ...] = ()) -> None:
        """
        :param primary_key: URL-safe base64-encoded 32-byte key used for *encryption*.
        :param previous_keys: Additional keys tried during *decryption* for rotation.
        """
        self._primary: Fernet = Fernet(primary_key.encode())
        self._fernets: list[Fernet] = [self._primary]
        for key in previous_keys:
            self._fernets.append(Fernet(key.encode()))

    @classmethod
    def generate_key(cls) -> str:
        """Return a new URL-safe base64-encoded Fernet key."""
        return Fernet.generate_key().decode()

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt plaintext with the primary key."""
        return self._primary.encrypt(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt ciphertext, trying all known keys in order."""
        for fernet in self._fernets:
            try:
                return fernet.decrypt(ciphertext)
            except InvalidToken:
                continue
        raise ProblemException(
            status_code=400,
            code="token_decryption_failed",
            title="Token decryption failed",
            detail="Unable to decrypt the token with any known key.",
        )
