import json
from datetime import date, datetime, timedelta, timezone

import pytest

from cloudme_notify import NotFoundError, Recurrence, ServerError, ValidationError

from .conftest import json_response, token_body

OTP_SENT = {"success": True, "otp_id": "otp-1", "channel": "sms", "recipient": "998901234567", "status": "pending", "code_length": 6,
            "max_attempts": 3, "expires_at": "x", "expires_in": 300, "message_id": "m-1", "price": "120.00", "currency": "UZS", "code": "481201"}


def debt_body(**overrides):
    return {"id": "debt-1", "external_id": "INV-1", "name": "Aziz", "phone": "998901234567", "amount": "1000.00", "paid_amount": "0.00",
            "remaining_amount": "1000.00", "currency": "UZS", "due_date": "2026-10-15", "status": "active", "environment": "production",
            "next_reminder_at": None, "paid_at": None, "paid_channel": None, "paid_days_late": None, **overrides}


def schedule_body(**overrides):
    return {"id": "schedule-1", "status": "active", "environment": "production", "channel": "sms", "recipient": "998901234567",
            "message": "Eslatma", "schedule_type": "recurring", "starts_at": "2026-10-05T09:00:00+05:00", "recurrence_type": "weekly",
            "weekdays": [1, 4], "next_run_at": "2026-10-05T09:00:00+05:00", **overrides}


def test_otp_send_and_verify_outcomes(make_client):
    history = []
    client = make_client([
        json_response(200, token_body()),
        json_response(200, OTP_SENT),
        json_response(422, {"success": False, "verified": False, "status": "pending", "attempts_left": 2, "error": {"code": "OTP_INVALID", "message": "Wrong"}}),
        json_response(200, {"success": True, "verified": True, "status": "verified", "verified_at": "now"}),
    ], history)

    otp = client.otp.send(to="998901234567")
    wrong = client.otp.verify(otp.otp_id, "000000")
    right = client.otp.verify(otp.otp_id, otp.code)

    assert otp.code == "481201"
    assert not wrong.verified and wrong.can_retry() and wrong.attempts_left == 2
    assert right.verified
    assert json.loads(history[1].content) == {"to": "998901234567", "channel": "sms"}


def test_otp_send_is_never_retried(make_client):
    history = []
    client = make_client([json_response(200, token_body()), json_response(503, {})], history, max_retries=3)

    with pytest.raises(ServerError):
        client.otp.send(to="1")
    assert len(history) == 2


def test_debts_create_find_pay_and_cancel(make_client):
    history = []
    client = make_client([
        json_response(200, token_body()),
        json_response(201, {"success": True, "debt": debt_body()}),
        json_response(200, {"success": True, "debt": debt_body(), "payments": [{"id": "p-1", "amount": "100.00", "paid_at": "x", "attributed_channel": "sms", "days_late": 2}]}),
        json_response(201, {"success": True, "payment": {"id": "p-2", "amount": "900.00", "paid_at": "y", "attributed_channel": None, "days_late": -1},
                            "debt": debt_body(status="paid", remaining_amount="0.00")}),
        json_response(200, {"success": True, "debt": debt_body(status="cancelled")}),
    ], history)

    debt = client.debts.create(name="Aziz", phone="998901234567", amount=1000, due_date=date(2026, 10, 15), external_id="INV-1")
    found = client.debts.find(debt.id)
    result = client.debts.record_payment(debt.id, 900, paid_at=datetime(2026, 10, 14, 9, tzinfo=timezone(timedelta(hours=5))))
    cancelled = client.debts.cancel(debt.id)

    assert json.loads(history[1].content) == {"name": "Aziz", "phone": "998901234567", "amount": 1000, "due_date": "2026-10-15", "external_id": "INV-1"}
    assert found.payments[0].is_late()
    assert result.debt.is_paid() and result.payment.days_late == -1
    assert json.loads(history[3].content)["paid_at"] == "2026-10-14T09:00:00+05:00"
    assert cancelled.status == "cancelled"


def test_debt_create_is_retried_only_with_an_external_id(make_client):
    history = []
    client = make_client([json_response(200, token_body()), json_response(503, {}), json_response(201, {"success": True, "debt": debt_body()})], history)
    client.debts.create(name="A", phone="1", amount=1, due_date="2026-10-15", external_id="INV-1")
    assert len(history) == 3

    client = make_client([json_response(200, token_body()), json_response(503, {})])
    with pytest.raises(ServerError):
        client.debts.create(name="A", phone="1", amount=1, due_date="2026-10-15")


def test_scheduled_message_create_maps_recurrence_and_the_response(make_client):
    history = []
    client = make_client([json_response(200, token_body()), json_response(201, {"success": True, "scheduled_message": schedule_body()})], history)

    schedule = client.scheduled_messages.create(
        channel="sms",
        starts_at=datetime(2026, 10, 5, 9, 0, tzinfo=timezone(timedelta(hours=5))),
        recipient="998901234567",
        message="Eslatma",
        recurrence=Recurrence.weekly([1, 4]),
    )

    assert schedule.is_active() and schedule.is_recurring() and schedule.weekdays == [1, 4]
    assert history[1].method == "POST" and history[1].url.path == "/api/v1/scheduled-messages"
    assert json.loads(history[1].content) == {
        "channel": "sms", "recipient": "998901234567", "message": "Eslatma", "schedule_type": "recurring",
        "starts_at": "2026-10-05T09:00:00+05:00", "recurrence_type": "weekly", "weekdays": [1, 4],
    }


def test_scheduled_message_once_update_list_and_actions(make_client):
    history = []
    client = make_client([
        json_response(200, token_body()),
        json_response(201, {"success": True, "scheduled_message": schedule_body(schedule_type="once")}),
        json_response(200, {"success": True, "scheduled_message": schedule_body()}),
        json_response(200, {"success": True, "scheduled_messages": [schedule_body(), schedule_body(id="schedule-2")],
                            "meta": {"current_page": 1, "last_page": 2, "per_page": 2, "total": 3}}),
        json_response(200, {"success": True, "scheduled_message": schedule_body(status="paused", next_run_at=None)}),
        json_response(200, {"success": True, "scheduled_message": schedule_body()}),
        json_response(200, {"success": True, "scheduled_message": schedule_body(status="cancelled", next_run_at=None)}),
    ], history)

    client.scheduled_messages.create(channel="telegram", starts_at="2026-10-06T10:00:00+05:00", contact_group_id=12, message="Salom, {{name}}!")
    client.scheduled_messages.update("schedule-1", channel="sms", starts_at="2026-10-06T10:00:00+05:00", recipient="1", message="Yangi", recurrence=Recurrence.every(2, "hours"))
    page = client.scheduled_messages.list(status="active", per_page=2)
    assert client.scheduled_messages.pause("schedule-1").is_paused()
    assert client.scheduled_messages.resume("schedule-1").is_active()
    assert client.scheduled_messages.cancel("schedule-1").status == "cancelled"

    assert json.loads(history[1].content) == {"channel": "telegram", "contact_group_id": 12, "message": "Salom, {{name}}!", "schedule_type": "once", "starts_at": "2026-10-06T10:00:00+05:00"}
    assert history[2].method == "PUT"
    assert json.loads(history[2].content)["interval_unit"] == "hours"
    assert page.total == 3 and page.has_more_pages() and page.items[1].id == "schedule-2"
    assert str(history[3].url.query, "ascii") == "status=active&page=1&per_page=2"
    assert [request.url.path.rsplit("/", 1)[-1] for request in history[4:]] == ["pause", "resume", "cancel"]


def test_scheduled_message_errors_and_recurrence_validation(make_client):
    client = make_client([
        json_response(200, token_body()),
        json_response(422, {"success": False, "error": {"code": "SCHEDULE_START_PASSED", "message": "passed"}}),
        json_response(404, {"success": False, "error": {"code": "NOT_FOUND", "message": "missing"}}),
    ])

    with pytest.raises(ValidationError) as raised:
        client.scheduled_messages.resume("schedule-1")
    assert raised.value.error_code == "SCHEDULE_START_PASSED"
    with pytest.raises(NotFoundError):
        client.scheduled_messages.find("missing")

    for invalid in (lambda: Recurrence.every(0, "days"), lambda: Recurrence.every(1, "weeks"), lambda: Recurrence.weekly([]), lambda: Recurrence.monthly([])):
        with pytest.raises(ValueError):
            invalid()
