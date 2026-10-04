"""``notify.scheduled_messages`` - send later, once or on a recurring timetable.

Requires the ``schedules:manage`` scope plus the channel's send scope (e.g. ``sms:send``).
These are the same schedules as the dashboard's Scheduled messages page.

.. code-block:: python

    from datetime import datetime
    from zoneinfo import ZoneInfo
    from cloudme_notify import Recurrence

    schedule = notify.scheduled_messages.create(
        channel="sms",
        starts_at=datetime(2026, 10, 6, 10, 0, tzinfo=ZoneInfo("Asia/Tashkent")),
        recipient="998901234567",
        message="Eslatma: bugun soat 15:00 da uchrashuv",
    )

    notify.scheduled_messages.create(
        channel="telegram",
        starts_at="2026-10-05T09:00:00+05:00",
        contact_group_id=12,
        message="Salom, {{name}}!",
        recurrence=Recurrence.weekly([1, 4]),
    )
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence, Union

from .responses import ScheduledMessageListResponse, ScheduledMessageResponse

if TYPE_CHECKING:
    from .client import NotifyClient


class Recurrence:
    """How a schedule repeats. Weekly and monthly sends use the time of day of ``starts_at``."""

    def __init__(self, type: str, interval_value: Optional[int] = None, interval_unit: Optional[str] = None, days: Optional[List[int]] = None) -> None:
        self.type = type
        self.interval_value = interval_value
        self.interval_unit = interval_unit
        self.days = days

    @classmethod
    def every(cls, value: int, unit: str) -> "Recurrence":
        """Every ``value`` "hours" or "days", counted from ``starts_at``."""
        if value < 1 or unit not in ("hours", "days"):
            raise ValueError('Recurrence.every() takes a positive value and "hours" or "days".')
        return cls("interval", interval_value=value, interval_unit=unit)

    @classmethod
    def weekly(cls, weekdays: Sequence[int]) -> "Recurrence":
        """ISO weekdays: 1 = Monday ... 7 = Sunday."""
        if not weekdays:
            raise ValueError("Recurrence.weekly() needs at least one weekday.")
        return cls("weekly", days=list(weekdays))

    @classmethod
    def monthly(cls, month_days: Sequence[int]) -> "Recurrence":
        """Days of the month 1-31; a day a month doesn't have is skipped that month."""
        if not month_days:
            raise ValueError("Recurrence.monthly() needs at least one day of the month.")
        return cls("monthly", days=list(month_days))

    def to_dict(self) -> Dict[str, Any]:
        if self.type == "interval":
            return {"recurrence_type": "interval", "interval_value": self.interval_value, "interval_unit": self.interval_unit}
        if self.type == "weekly":
            return {"recurrence_type": "weekly", "weekdays": self.days}
        return {"recurrence_type": "monthly", "month_days": self.days}

    def __repr__(self) -> str:
        return f"Recurrence({self.to_dict()!r})"


class ScheduledMessagesClient:
    def __init__(self, client: "NotifyClient") -> None:
        self._client = client

    def create(
        self,
        channel: str,
        starts_at: Union[datetime, str],
        recipient: Optional[str] = None,
        contact_group_id: Optional[int] = None,
        message: Optional[str] = None,
        template_id: Optional[int] = None,
        variables: Optional[Mapping[str, Any]] = None,
        recurrence: Optional[Recurrence] = None,
        subject: Optional[str] = None,
        sms_type: Optional[str] = None,
        photo_url: Optional[str] = None,
        channel_account_id: Optional[int] = None,
    ) -> ScheduledMessageResponse:
        """Pass ``recipient`` (one person) or ``contact_group_id`` (a dashboard contact group,
        production only; ``{{name}}`` becomes each contact's name). Without ``recurrence`` it is
        sent once. A naive datetime or a string without offset is read as Asia/Tashkent time.

        Not retried automatically - a lost response could otherwise create it twice.
        Raises ValidationError ``TEMPLATE_NOT_FOUND``, ``CONTACT_GROUP_NOT_FOUND``,
        ``SANDBOX_GROUP_UNSUPPORTED``; ForbiddenError when a scope is missing.
        """
        body = _body(channel, starts_at, recipient, contact_group_id, message, template_id, variables, recurrence, subject, sms_type, photo_url, channel_account_id)
        return ScheduledMessageResponse.from_dict(self._client._request("POST", "scheduled-messages", json=body)["scheduled_message"])

    def update(
        self,
        scheduled_message_id: str,
        channel: str,
        starts_at: Union[datetime, str],
        recipient: Optional[str] = None,
        contact_group_id: Optional[int] = None,
        message: Optional[str] = None,
        template_id: Optional[int] = None,
        variables: Optional[Mapping[str, Any]] = None,
        recurrence: Optional[Recurrence] = None,
        subject: Optional[str] = None,
        sms_type: Optional[str] = None,
        photo_url: Optional[str] = None,
        channel_account_id: Optional[int] = None,
    ) -> ScheduledMessageResponse:
        """Replaces the whole schedule - pass everything, as for create(). Clears ``last_error``.
        Safe to retry. Raises ValidationError ``SCHEDULE_STATE_INVALID`` for a completed or
        cancelled schedule."""
        body = _body(channel, starts_at, recipient, contact_group_id, message, template_id, variables, recurrence, subject, sms_type, photo_url, channel_account_id)
        response = self._client._request("PUT", f"scheduled-messages/{scheduled_message_id}", json=body, retryable=True)
        return ScheduledMessageResponse.from_dict(response["scheduled_message"])

    def find(self, scheduled_message_id: str) -> ScheduledMessageResponse:
        response = self._client._request("GET", f"scheduled-messages/{scheduled_message_id}", retryable=True)
        return ScheduledMessageResponse.from_dict(response["scheduled_message"])

    def list(self, status: Optional[str] = None, channel: Optional[str] = None, page: int = 1, per_page: int = 20) -> ScheduledMessageListResponse:
        """One page, newest first. ``status``: active, paused, completed or cancelled. ``per_page``: 1-100."""
        params = {key: value for key, value in {"status": status, "channel": channel, "page": page, "per_page": per_page}.items() if value is not None}
        return ScheduledMessageListResponse.from_dict(self._client._request("GET", "scheduled-messages", params=params, retryable=True))

    def pause(self, scheduled_message_id: str) -> ScheduledMessageResponse:
        """Only an active schedule can be paused (else ValidationError ``SCHEDULE_STATE_INVALID``)."""
        return self._action(scheduled_message_id, "pause")

    def resume(self, scheduled_message_id: str) -> ScheduledMessageResponse:
        """Continues at the next occurrence from now; sends missed while paused are skipped.
        Raises ValidationError ``SCHEDULE_START_PASSED`` for a one-time schedule whose time passed."""
        return self._action(scheduled_message_id, "resume")

    def cancel(self, scheduled_message_id: str) -> ScheduledMessageResponse:
        """Nothing more is sent; a cancelled schedule cannot be changed or resumed."""
        return self._action(scheduled_message_id, "cancel")

    def _action(self, scheduled_message_id: str, action: str) -> ScheduledMessageResponse:
        response = self._client._request("POST", f"scheduled-messages/{scheduled_message_id}/{action}")
        return ScheduledMessageResponse.from_dict(response["scheduled_message"])


def _body(
    channel: str,
    starts_at: Union[datetime, str],
    recipient: Optional[str],
    contact_group_id: Optional[int],
    message: Optional[str],
    template_id: Optional[int],
    variables: Optional[Mapping[str, Any]],
    recurrence: Optional[Recurrence],
    subject: Optional[str],
    sms_type: Optional[str],
    photo_url: Optional[str],
    channel_account_id: Optional[int],
) -> Dict[str, Any]:
    body = {
        "channel": channel,
        "recipient": recipient,
        "contact_group_id": contact_group_id,
        "message": message,
        "template_id": template_id,
        "variables": dict(variables) if variables else None,
        "subject": subject,
        "sms_type": sms_type,
        "photo_url": photo_url,
        "channel_account_id": channel_account_id,
        "schedule_type": "once" if recurrence is None else "recurring",
        "starts_at": starts_at.isoformat() if isinstance(starts_at, datetime) else starts_at,
        **(recurrence.to_dict() if recurrence else {}),
    }
    return {key: value for key, value in body.items() if value is not None}
