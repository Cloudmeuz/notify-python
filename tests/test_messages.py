import json

import httpx
import pytest

from cloudme_notify import (
    ForbiddenError,
    InsufficientBalanceError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ServerError,
    SpendingLimitExceededError,
    ValidationError,
)

from .conftest import json_response, token_body

SEND_OK = {"success": True, "message_id": "m-1", "channel_account_id": 7, "environment": "sandbox", "status": "queued", "price": "120.00", "currency": "UZS", "balance": "999880.00"}


def test_send_posts_to_the_channel_endpoint_with_an_idempotency_key(make_client):
    history = []
    client = make_client([json_response(200, token_body()), json_response(200, SEND_OK)], history)

    response = client.telegram.send(to="998901234567", message="<b>Tayyor</b>", photo_url="https://example.com/a.jpg", channel_account_id=7)

    assert response.message_id == "m-1"
    assert response.environment == "sandbox"
    assert response.channel_account_id == 7
    assert not response.is_held_for_moderation()
    request = history[1]
    assert request.url.path == "/api/v1/messages/telegram"
    assert json.loads(request.content) == {"to": "998901234567", "message": "<b>Tayyor</b>", "photo_url": "https://example.com/a.jpg", "channel_account_id": 7}
    assert len(request.headers["Idempotency-Key"]) == 32


def test_a_template_send_carries_its_variables_and_a_given_idempotency_key(make_client):
    history = []
    make_client([json_response(200, token_body()), json_response(200, SEND_OK)], history).sms.send(
        to="998901234567", template_id=42, variables={"name": "Aziz"}, sms_type="service", idempotency_key="order-1001",
    )

    assert json.loads(history[1].content) == {"to": "998901234567", "template_id": 42, "variables": {"name": "Aziz"}, "sms_type": "service"}
    assert history[1].headers["Idempotency-Key"] == "order-1001"


def test_an_unknown_runtime_channel_uses_the_universal_endpoint(make_client):
    history = []
    client = make_client([json_response(200, token_body()), json_response(200, SEND_OK), json_response(200, SEND_OK)], history)

    client.channel("sms").send(to="1", message="x")
    client.channel("rcs").send(to="1", message="x")

    assert history[1].url.path == "/api/v1/messages/sms"
    assert history[2].url.path == "/api/v1/messages"
    assert json.loads(history[2].content) == {"channel": "rcs", "recipient": "1", "message": "x"}


def test_a_send_is_retried_on_server_errors_with_the_same_idempotency_key(make_client):
    history = []
    client = make_client([json_response(200, token_body()), json_response(503, {"message": "down"}), httpx.ConnectError("reset"), json_response(200, SEND_OK)], history, max_retries=3)

    client.sms.send(to="1", message="x")

    keys = {request.headers["Idempotency-Key"] for request in history[1:]}
    assert len(history) == 4 and len(keys) == 1


@pytest.mark.parametrize(
    ("status", "body", "error_class"),
    [
        (402, {"success": False, "error": {"code": "INSUFFICIENT_BALANCE", "message": "no money"}}, InsufficientBalanceError),
        (402, {"success": False, "error": {"code": "SPENDING_LIMIT_EXCEEDED", "message": "cap"}}, SpendingLimitExceededError),
        (403, {"success": False, "error": {"code": "SCOPE_FORBIDDEN", "message": "scope", "required_scope": "sms:send"}}, ForbiddenError),
        (404, {"success": False, "error": {"code": "NOT_FOUND", "message": "missing"}}, NotFoundError),
        (422, {"message": "The to field is required.", "errors": {"to": ["The to field is required."]}}, ValidationError),
    ],
)
def test_error_responses_map_to_typed_exceptions(make_client, status, body, error_class):
    client = make_client([json_response(200, token_body()), json_response(status, body)])

    with pytest.raises(error_class) as raised:
        client.sms.send(to="1", message="x")

    assert raised.value.status_code == status
    if status == 403:
        assert raised.value.required_scope == "sms:send"
    if status == 422:
        assert raised.value.errors == {"to": ["The to field is required."]}


def test_localized_hint_and_docs_url_are_exposed(make_client):
    client = make_client([json_response(200, token_body()), json_response(422, {"success": False, "error": {
        "code": "MISSING_TEMPLATE_VARIABLE", "message": "Missing", "hint": "Send every variable.",
        "docs_url": "https://notify.cloudme.uz/api-docs#error-MISSING_TEMPLATE_VARIABLE", "missing_variables": ["name"],
    }})])

    with pytest.raises(ValidationError) as raised:
        client.sms.send(to="1", template_id=1)

    assert raised.value.error_code == "MISSING_TEMPLATE_VARIABLE"
    assert raised.value.hint == "Send every variable."
    assert raised.value.docs_url.endswith("#error-MISSING_TEMPLATE_VARIABLE")
    assert raised.value.missing_variables == ["name"]


def test_rate_limits_expose_retry_after_and_exhausted_retries_raise(make_client):
    client = make_client([json_response(200, token_body()), json_response(429, {"message": "Too Many Attempts."}, {"Retry-After": "7"})], max_retries=1)
    with pytest.raises(RateLimitError) as raised:
        client.balance()
    assert raised.value.retry_after_seconds == 7

    client = make_client([json_response(200, token_body()), json_response(500, {}), json_response(500, {})])
    with pytest.raises(ServerError):
        client.balance()

    client = make_client([json_response(200, token_body()), httpx.ConnectError("x"), httpx.ConnectError("x")])
    with pytest.raises(NetworkError):
        client.balance()


def test_status_balance_templates_reports_and_binding(make_client):
    history = []
    client = make_client([
        json_response(200, token_body()),
        json_response(200, {"success": True, "message_id": "m-1", "channel": "sms", "recipient": "1", "status": "delivered", "sms_type": None,
                            "price": "120.00", "currency": "UZS", "error_code": None, "created_at": "a", "sent_at": "b", "delivered_at": "c"}),
        json_response(200, {"balance": "1000.00", "reserved_balance": "0.00", "currency": "UZS"}),
        json_response(200, {"success": True, "templates": [{"id": 42, "name": "Order", "channel": "sms", "type": "company", "subject": None,
                                                           "content": "Hi {{name}}", "variables": ["name"]}]}),
        json_response(200, {"success": True, "data": [{"date": "2026-10-01", "channel": "sms", "count": 3, "amount": "360.00"}]}),
        json_response(200, {"success": True, "phone": "998901234567", "bound": False, "link": "https://t.me/bot?start=x", "expires_at": "z", "bot_username": "bot"}),
    ], history)

    assert client.message("m-1").status == "delivered"
    assert client.balance().balance == "1000.00"
    assert client.templates.list(channel="sms")[0].variables == ["name"]
    from datetime import date
    assert client.reports.daily(date(2026, 10, 1), date(2026, 10, 3))[0]["count"] == 3
    assert client.telegram.binding_link("998901234567").link == "https://t.me/bot?start=x"

    assert history[3].url.params["channel"] == "sms"
    assert dict(history[4].url.params) == {"from": "2026-10-01", "to": "2026-10-03"}


def test_push_device_registration(make_client):
    history = []
    make_client([json_response(200, token_body()), json_response(200, {"success": True})], history).push.register_device("998901234567", "fcm-token", channel_account_id=12)

    assert history[1].url.path == "/api/v1/push/devices"
    assert json.loads(history[1].content) == {"phone": "998901234567", "fcm_token": "fcm-token", "channel_account_id": 12}
