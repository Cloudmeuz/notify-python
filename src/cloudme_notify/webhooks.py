"""Verifies and parses the webhooks Notify POSTs to your API client's webhook URL.

``X-Signature`` is the hex HMAC-SHA256 of ``"{X-Webhook-Timestamp}.{raw body}"`` with the
webhook's signing secret (dashboard -> API clients -> Webhook). A timestamp outside the
tolerance window is rejected so a captured request cannot be replayed.

Always pass the RAW body bytes - re-encoding parsed JSON changes them and breaks the signature.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Mapping, Optional, Union

from .exceptions import ConfigurationError, InvalidWebhookSignatureError

DEFAULT_TOLERANCE_SECONDS = 300


@dataclass(frozen=True)
class WebhookEvent:
    #: X-Webhook-Id - identical on every retry of the same event; dedupe on it.
    id: str
    #: message.sent, message.delivered, message.failed, message.rejected or webhook.test.
    event: str
    message_id: Optional[str]
    channel: Optional[str]
    recipient: Optional[str]
    status: Optional[str]
    environment: Optional[str]
    #: Only on message.failed / message.rejected.
    error_code: Optional[str]
    error_message: Optional[str]
    #: Unix time the delivery attempt was signed.
    signed_at: int
    payload: Dict[str, Any] = field(default_factory=dict)

    def is_test(self) -> bool:
        return self.event == "webhook.test"

    def occurred_at(self) -> Optional[datetime]:
        """The payload's ``timestamp`` - when Notify built this delivery (not for ordering events)."""
        value = self.payload.get("timestamp")
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    @classmethod
    def from_payload(cls, id: str, signed_at: int, payload: Mapping[str, Any]) -> "WebhookEvent":
        return cls(
            id=id,
            event=str(payload.get("event") or ""),
            message_id=payload.get("message_id"),
            channel=payload.get("channel"),
            recipient=payload.get("recipient"),
            status=payload.get("status"),
            environment=payload.get("environment"),
            error_code=payload.get("error_code"),
            error_message=payload.get("error_message"),
            signed_at=signed_at,
            payload=dict(payload),
        )


class WebhookVerifier:
    """
    .. code-block:: python

        verifier = WebhookVerifier(os.environ["NOTIFY_WEBHOOK_SECRET"])
        event = verifier.parse(request.body, request.headers)
        if event.event == "message.failed": ...
    """

    def __init__(self, secret: str, tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS) -> None:
        if not secret or not secret.strip():
            raise ConfigurationError("The webhook signing secret is required.")
        self._secret = secret.encode()
        self._tolerance = tolerance_seconds

    def is_valid(self, raw_body: Union[bytes, str], signature: str, timestamp: Union[str, int], now: Optional[int] = None) -> bool:
        timestamp = str(timestamp)
        if not timestamp.isdigit() or abs((now if now is not None else int(time.time())) - int(timestamp)) > self._tolerance:
            return False

        body = raw_body if isinstance(raw_body, bytes) else raw_body.encode()
        expected = hmac.new(self._secret, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, (signature or "").strip().lower())

    def parse(self, raw_body: Union[bytes, str], headers: Mapping[str, Any], now: Optional[int] = None) -> WebhookEvent:
        """``headers`` in any letter case (e.g. Django's ``request.headers``). Raises InvalidWebhookSignatureError."""
        lowered = {str(key).lower(): value for key, value in headers.items()}

        def header(name: str) -> str:
            value = lowered.get(name.lower(), "")
            if isinstance(value, (list, tuple)):
                value = value[0] if value else ""
            return str(value)

        timestamp = header("X-Webhook-Timestamp")
        if not self.is_valid(raw_body, header("X-Signature"), timestamp, now):
            raise InvalidWebhookSignatureError("Notify webhook signature or timestamp is invalid.")

        try:
            payload = json.loads(raw_body)
        except ValueError as error:
            raise InvalidWebhookSignatureError("Notify webhook body is not valid JSON.") from error

        return WebhookEvent.from_payload(header("X-Webhook-Id"), int(timestamp), payload if isinstance(payload, dict) else {})
