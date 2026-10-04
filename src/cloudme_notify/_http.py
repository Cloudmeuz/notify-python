"""HTTP transport: turns every failure into a typed NotifyError and retries when safe."""

from __future__ import annotations

import random
import time
from typing import Any, Dict, Mapping, Optional

import httpx

from .exceptions import (
    ApiError,
    AuthenticationError,
    ForbiddenError,
    InsufficientBalanceError,
    NetworkError,
    NotFoundError,
    NotifyError,
    RateLimitError,
    ServerError,
    SpendingLimitExceededError,
    ValidationError,
)

RETRY_BASE_DELAY_SECONDS = 0.4


class HttpClient:
    def __init__(self, client: httpx.Client, max_retries: int = 3) -> None:
        self._client = client
        self._max_retries = max(1, max_retries)

    def request(
        self,
        method: str,
        path: str,
        json: Optional[Mapping[str, Any]] = None,
        params: Optional[Mapping[str, Any]] = None,
        bearer_token: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        retryable: bool = False,
    ) -> Dict[str, Any]:
        """Sends the request and returns the decoded JSON body.

        Only a ``retryable`` call is repeated - on a network failure, a 429 or
        a 5xx - with exponential backoff (or the server's ``Retry-After``).
        """
        headers = {"Accept": "application/json"}
        if bearer_token is not None:
            headers["Authorization"] = f"Bearer {bearer_token}"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key

        max_attempts = self._max_retries if retryable else 1
        attempt = 0

        while True:
            attempt += 1
            try:
                response = self._client.request(
                    method,
                    path.lstrip("/"),
                    json=dict(json) if json else None,
                    params=dict(params) if params else None,
                    headers=headers,
                )
            except httpx.TransportError as error:
                if attempt < max_attempts:
                    self._sleep_before_retry(attempt)
                    continue
                raise NetworkError(f"Could not reach the Notify API: {error}") from error

            if response.is_success:
                return self._decode(response) or {}

            if retryable and attempt < max_attempts and (response.status_code == 429 or response.status_code >= 500):
                self._sleep_before_retry(attempt, self._retry_after(response))
                continue

            raise self._map_error(response)

    @staticmethod
    def _decode(response: httpx.Response) -> Optional[Dict[str, Any]]:
        try:
            decoded = response.json()
        except ValueError:
            return None

        return decoded if isinstance(decoded, dict) else None

    def _map_error(self, response: httpx.Response) -> NotifyError:
        status = response.status_code
        body = self._decode(response)
        error = body.get("error") if body else None
        error = error if isinstance(error, dict) else {}
        code = error.get("code")
        message = error.get("message") or (body or {}).get("message") or f"Notify API returned HTTP {status}."

        if status == 401:
            return AuthenticationError(message, code, status, body)
        if status == 402:
            cls = SpendingLimitExceededError if code == "SPENDING_LIMIT_EXCEEDED" else InsufficientBalanceError
            return cls(message, code, status, body)
        if status == 403:
            return ForbiddenError(message, code, status, body)
        if status == 404:
            return NotFoundError(message, code, status, body)
        if status == 422:
            errors = (body or {}).get("errors")
            return ValidationError(message, errors if isinstance(errors, dict) else {}, code, status, body)
        if status == 429:
            return RateLimitError(message, self._retry_after(response), code, status, body)
        if status >= 500:
            return ServerError(message, code, status, body)

        return ApiError(message, code, status, body)

    @staticmethod
    def _retry_after(response: httpx.Response) -> Optional[int]:
        header = response.headers.get("Retry-After")
        try:
            return int(header) if header else None
        except ValueError:
            return None

    @staticmethod
    def _sleep_before_retry(attempt: int, retry_after: Optional[int] = None) -> None:
        if retry_after is not None:
            time.sleep(retry_after)
            return

        # ~0.4s, ~0.8s, ~1.6s... plus jitter
        time.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 0.1))
