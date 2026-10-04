import hashlib
import hmac
import json

import pytest

from cloudme_notify import ConfigurationError, InvalidWebhookSignatureError, WebhookVerifier

SECRET = "whsec_test"
NOW = 1_790_000_000
BODY = json.dumps({"event": "message.failed", "message_id": "m-1", "channel": "sms", "recipient": "1", "status": "failed",
                   "environment": "production", "error_code": "PROVIDER_ERROR", "error_message": "x", "timestamp": "2026-10-04T12:00:00+05:00"}).encode()


def sign(body: bytes, timestamp: int, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()


def headers(timestamp: int = NOW, signature: str = None):
    return {"x-webhook-id": "evt-1", "X-Webhook-Event": "message.failed", "X-Webhook-Timestamp": str(timestamp), "X-Signature": signature or sign(BODY, timestamp)}


def test_a_correctly_signed_webhook_is_parsed():
    event = WebhookVerifier(SECRET).parse(BODY, headers(), now=NOW)

    assert event.id == "evt-1"
    assert event.event == "message.failed"
    assert event.error_code == "PROVIDER_ERROR"
    assert event.signed_at == NOW
    assert event.occurred_at().isoformat() == "2026-10-04T12:00:00+05:00"
    assert not event.is_test()


@pytest.mark.parametrize("case", ["wrong signature", "other secret", "stale timestamp", "tampered body"])
def test_forged_replayed_or_tampered_webhooks_are_rejected(case):
    verifier = WebhookVerifier(SECRET)
    body, request_headers, now = BODY, headers(), NOW
    if case == "wrong signature":
        request_headers = headers(signature="0" * 64)
    elif case == "other secret":
        request_headers = headers(signature=sign(BODY, NOW, "other"))
    elif case == "stale timestamp":
        now = NOW + 301
    else:
        body = BODY.replace(b"failed", b"delivered")

    with pytest.raises(InvalidWebhookSignatureError):
        verifier.parse(body, request_headers, now=now)


def test_a_blank_secret_is_a_configuration_error():
    with pytest.raises(ConfigurationError):
        WebhookVerifier(" ")
