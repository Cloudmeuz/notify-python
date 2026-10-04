"""Request signing and access-token lifecycle.

``/oauth/token`` requires an RSA-SHA256 (PKCS#1 v1.5) signature over
``"{client_id}\\n{timestamp}\\n{nonce}\\n{sha256(api_key)}"`` made with the API
client's private key. :class:`TokenManager` obtains, caches and refreshes the
resulting access token so callers never deal with OAuth themselves.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Protocol, Union

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .exceptions import AuthenticationError, ConfigurationError, NetworkError

if TYPE_CHECKING:
    from ._http import HttpClient

TokenPair = Dict[str, Any]
"""``{"access_token", "access_token_expires_at", "refresh_token", "refresh_token_expires_at"}`` (expiry as Unix seconds)."""


class SignatureSigner:
    """Signs the proof-of-possession the ``/oauth/token`` endpoint verifies."""

    def __init__(self, private_key: Union[str, bytes, os.PathLike]) -> None:
        """``private_key`` is PEM text/bytes, or a filesystem path to a PEM file."""
        pem = self._read_pem(private_key)

        try:
            key = serialization.load_pem_private_key(pem, password=None)
        except (ValueError, TypeError) as error:
            raise ConfigurationError(f"The Notify private key is not a valid PEM-encoded RSA private key: {error}") from error

        if not isinstance(key, rsa.RSAPrivateKey):
            raise ConfigurationError("The Notify private key must be an RSA key.")

        self._key = key

    @staticmethod
    def _read_pem(private_key: Union[str, bytes, os.PathLike]) -> bytes:
        if isinstance(private_key, bytes):
            return private_key

        text = os.fspath(private_key)
        if "-----BEGIN" in text:
            return text.encode()

        path = Path(text)
        if not path.is_file():
            raise ConfigurationError(f'Could not read the Notify private key from "{text}".')

        return path.read_bytes()

    @staticmethod
    def signing_string(client_id: str, timestamp: int, nonce: str, api_key: str) -> str:
        return "\n".join([client_id, str(timestamp), nonce, hashlib.sha256(api_key.encode()).hexdigest()])

    def sign(self, client_id: str, timestamp: int, nonce: str, api_key: str) -> str:
        """Returns the base64-encoded RSA-SHA256 signature."""
        signature = self._key.sign(
            self.signing_string(client_id, timestamp, nonce, api_key).encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode()

    @staticmethod
    def generate_nonce() -> str:
        return secrets.token_hex(16)


class TokenStorage(Protocol):
    """Keeps the token pair between calls - implement it over Redis, a DB row, etc."""

    def get(self) -> Optional[TokenPair]: ...

    def put(self, tokens: TokenPair) -> None: ...

    def clear(self) -> None: ...


class MemoryTokenStorage:
    """The default: lives as long as the NotifyClient object (one process)."""

    def __init__(self) -> None:
        self._tokens: Optional[TokenPair] = None

    def get(self) -> Optional[TokenPair]:
        return self._tokens

    def put(self, tokens: TokenPair) -> None:
        self._tokens = dict(tokens)

    def clear(self) -> None:
        self._tokens = None


class FileTokenStorage:
    """Persists the pair to one JSON file (mode 0600) so repeated scripts reuse it.

    Not safe for concurrent writers in several processes - use a shared cache
    behind your own :class:`TokenStorage` for that.
    """

    def __init__(self, path: Union[str, os.PathLike]) -> None:
        self._path = Path(path)

    def get(self) -> Optional[TokenPair]:
        try:
            decoded = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return None

        return decoded if isinstance(decoded, dict) else None

    def put(self, tokens: TokenPair) -> None:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._path.write_text(json.dumps(tokens))
        os.chmod(self._path, 0o600)

    def clear(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass


class TokenManager:
    """Obtains, caches and transparently refreshes the access token."""

    #: Refresh this many seconds early so a token never dies mid-request.
    EXPIRY_SKEW_SECONDS = 30
    MAX_AUTH_ATTEMPTS = 3
    #: The API does not return the refresh token's TTL; Notify documents 14 days.
    REFRESH_TOKEN_LIFETIME_SECONDS = 14 * 86400

    def __init__(self, http: "HttpClient", signer: SignatureSigner, storage: TokenStorage, client_id: str, api_key: str) -> None:
        self._http = http
        self._signer = signer
        self._storage = storage
        self._client_id = client_id
        self._api_key = api_key

    def get_access_token(self) -> str:
        tokens = self._storage.get()
        now = time.time()

        if tokens and tokens.get("access_token_expires_at", 0) > now + self.EXPIRY_SKEW_SECONDS:
            return str(tokens["access_token"])

        if tokens and tokens.get("refresh_token_expires_at", 0) > now + self.EXPIRY_SKEW_SECONDS:
            try:
                return self._refresh(str(tokens["refresh_token"]))
            except AuthenticationError:
                # Expired, revoked or reused refresh token - start over with a
                # signed /oauth/token call instead of failing the caller.
                pass

        return self._authenticate()

    def force_reauthenticate(self) -> str:
        """Drops the cached pair and signs a fresh /oauth/token request (after a live 401)."""
        self._storage.clear()
        return self._authenticate()

    def _authenticate(self) -> str:
        last_error: Optional[NetworkError] = None

        for attempt in range(1, self.MAX_AUTH_ATTEMPTS + 1):
            # A fresh nonce/timestamp every attempt: the server consumes each
            # nonce once, so replaying the same signed body would be refused.
            timestamp = int(time.time())
            nonce = SignatureSigner.generate_nonce()

            try:
                response = self._http.request("POST", "oauth/token", json={
                    "client_id": self._client_id,
                    "api_key": self._api_key,
                    "timestamp": timestamp,
                    "nonce": nonce,
                    "signature": self._signer.sign(self._client_id, timestamp, nonce, self._api_key),
                })
            except NetworkError as error:
                last_error = error
                if attempt < self.MAX_AUTH_ATTEMPTS:
                    time.sleep(0.3 * attempt)
                continue

            return self._store(response)

        assert last_error is not None
        raise last_error

    def _refresh(self, refresh_token: str) -> str:
        return self._store(self._http.request("POST", "oauth/refresh", json={"refresh_token": refresh_token}))

    def _store(self, response: Dict[str, Any]) -> str:
        now = int(time.time())
        self._storage.put({
            "access_token": response["access_token"],
            "access_token_expires_at": now + int(response["expires_in"]),
            "refresh_token": response["refresh_token"],
            "refresh_token_expires_at": now + self.REFRESH_TOKEN_LIFETIME_SECONDS,
        })

        return str(response["access_token"])
