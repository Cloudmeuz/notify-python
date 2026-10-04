"""Test helpers: an httpx.MockTransport stands in for the Notify API, so no request leaves the process."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Union

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from cloudme_notify import NotifyClient

Reply = Union[httpx.Response, Exception]


@pytest.fixture(scope="session")
def key_pair() -> Dict[str, Any]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    return {"private_pem": pem, "public_key": key.public_key()}


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cloudme_notify._http.time.sleep", lambda seconds: None)
    monkeypatch.setattr("cloudme_notify.auth.time.sleep", lambda seconds: None)


def json_response(status: int, body: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> httpx.Response:
    return httpx.Response(status, json=body if body is not None else {}, headers=headers)


def token_body(access_token: str = "access-token-1", expires_in: int = 900, refresh_token: str = "refresh-token-1") -> Dict[str, Any]:
    return {"token_type": "Bearer", "access_token": access_token, "expires_in": expires_in, "refresh_token": refresh_token}


@pytest.fixture
def make_client(key_pair: Dict[str, Any]) -> Callable[..., NotifyClient]:
    """``make_client([replies...], history)`` - replies are served in order, one per HTTP call."""

    def factory(replies: List[Reply], history: Optional[List[httpx.Request]] = None, **options: Any) -> NotifyClient:
        queue = list(replies)
        recorded = history if history is not None else []

        def handler(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            if not queue:
                raise AssertionError(f"Unexpected request: {request.method} {request.url}")
            reply = queue.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        return NotifyClient(
            client_id="test-client-id",
            api_key="test-api-key",
            private_key=key_pair["private_pem"],
            base_url="https://notify.test/api/v1",
            transport=httpx.MockTransport(handler),
            max_retries=options.pop("max_retries", 2),
            **options,
        )

    return factory
