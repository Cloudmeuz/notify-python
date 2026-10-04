"""Typed results returned by the client - frozen dataclasses built from the JSON body."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional


def _int(value: Any) -> Optional[int]:
    return int(value) if value is not None else None


def _str(value: Any) -> Optional[str]:
    return str(value) if value is not None else None


@dataclass(frozen=True)
class SendMessageResponse:
    message_id: str
    status: str
    price: str
    currency: str
    balance: Optional[str]
    #: "production" or "sandbox" - confirms which one handled the send.
    environment: str = "production"
    channel_account_id: Optional[int] = None

    def is_held_for_moderation(self) -> bool:
        """Free text matching none of your templates waits for a moderator - send a template to skip it."""
        return self.status == "moderation"

    def is_rejected(self) -> bool:
        """A moderator refused it; it was not sent and was refunded."""
        return self.status == "rejected"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SendMessageResponse":
        return cls(
            message_id=str(data["message_id"]),
            status=str(data["status"]),
            price=str(data["price"]),
            currency=str(data["currency"]),
            balance=_str(data.get("balance")),
            environment=str(data.get("environment") or "production"),
            channel_account_id=_int(data.get("channel_account_id")),
        )


@dataclass(frozen=True)
class MessageStatusResponse:
    message_id: str
    channel: str
    recipient: str
    status: str
    sms_type: Optional[str]
    price: str
    currency: str
    error_code: Optional[str]
    created_at: Optional[str]
    sent_at: Optional[str]
    delivered_at: Optional[str]
    environment: str = "production"
    channel_account_id: Optional[int] = None

    def is_held_for_moderation(self) -> bool:
        return self.status == "moderation"

    def is_rejected(self) -> bool:
        return self.status == "rejected"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MessageStatusResponse":
        return cls(
            message_id=str(data["message_id"]),
            channel=str(data["channel"]),
            recipient=str(data["recipient"]),
            status=str(data["status"]),
            sms_type=data.get("sms_type"),
            price=str(data["price"]),
            currency=str(data["currency"]),
            error_code=data.get("error_code"),
            created_at=data.get("created_at"),
            sent_at=data.get("sent_at"),
            delivered_at=data.get("delivered_at"),
            environment=str(data.get("environment") or "production"),
            channel_account_id=_int(data.get("channel_account_id")),
        )


@dataclass(frozen=True)
class BalanceResponse:
    balance: str
    reserved_balance: str
    currency: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BalanceResponse":
        return cls(balance=str(data["balance"]), reserved_balance=str(data["reserved_balance"]), currency=str(data["currency"]))


@dataclass(frozen=True)
class TemplateResponse:
    """Send it with ``template_id=template.id`` and a value for every name in ``variables``."""

    id: int
    name: str
    channel: str
    #: "system" (shared by every company) or "company" (your own approved template).
    type: str
    subject: Optional[str]
    content: str
    variables: List[str]
    whatsapp_template_name: Optional[str]
    whatsapp_template_language: Optional[str]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TemplateResponse":
        return cls(
            id=int(data["id"]),
            name=str(data["name"]),
            channel=str(data["channel"]),
            type=str(data["type"]),
            subject=data.get("subject"),
            content=str(data["content"]),
            variables=[str(name) for name in data.get("variables") or []],
            whatsapp_template_name=data.get("whatsapp_template_name"),
            whatsapp_template_language=data.get("whatsapp_template_language"),
        )


@dataclass(frozen=True)
class TelegramBindingResponse:
    """Send ``link`` to the customer; ``bound`` is True (and ``link`` None) once they pressed Start."""

    phone: str
    bound: bool
    link: Optional[str]
    #: ISO 8601; the link stays valid until then (7 days).
    expires_at: Optional[str]
    bot_username: str
    channel_account_id: Optional[int]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TelegramBindingResponse":
        return cls(
            phone=str(data["phone"]),
            bound=bool(data["bound"]),
            link=data.get("link"),
            expires_at=data.get("expires_at"),
            bot_username=str(data["bot_username"]),
            channel_account_id=_int(data.get("channel_account_id")),
        )


@dataclass(frozen=True)
class OtpSendResponse:
    #: Keep this - verify() needs it.
    otp_id: str
    channel: str
    recipient: str
    status: str
    code_length: int
    max_attempts: int
    expires_at: Optional[str]
    expires_in: int
    message_id: str
    price: str
    currency: str
    balance: Optional[str]
    environment: str = "production"
    #: The generated code - only ever set in the sandbox, for testing verify().
    code: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OtpSendResponse":
        return cls(
            otp_id=str(data["otp_id"]),
            channel=str(data["channel"]),
            recipient=str(data["recipient"]),
            status=str(data["status"]),
            code_length=int(data["code_length"]),
            max_attempts=int(data["max_attempts"]),
            expires_at=data.get("expires_at"),
            expires_in=int(data.get("expires_in") or 0),
            message_id=str(data["message_id"]),
            price=str(data["price"]),
            currency=str(data["currency"]),
            balance=_str(data.get("balance")),
            environment=str(data.get("environment") or "production"),
            code=_str(data.get("code")),
        )


@dataclass(frozen=True)
class OtpVerifyResponse:
    INVALID = "OTP_INVALID"
    EXPIRED = "OTP_EXPIRED"
    ATTEMPTS_EXCEEDED = "OTP_ATTEMPTS_EXCEEDED"
    ALREADY_VERIFIED = "OTP_ALREADY_VERIFIED"

    verified: bool
    #: pending, verified, expired or failed (attempts exhausted).
    status: str
    #: None when verified; otherwise one of the constants above.
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    #: How many more tries the user has - 0 once the code is burnt.
    attempts_left: int = 0
    verified_at: Optional[str] = None

    def can_retry(self) -> bool:
        """Only a wrong code leaves the OTP usable - any other failure needs a new code."""
        return not self.verified and self.error_code == self.INVALID and self.attempts_left > 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OtpVerifyResponse":
        error = data.get("error") if isinstance(data.get("error"), dict) else {}
        return cls(
            verified=bool(data.get("verified", False)),
            status=str(data.get("status") or "pending"),
            error_code=error.get("code"),
            error_message=error.get("message"),
            attempts_left=int(data.get("attempts_left") or 0),
            verified_at=data.get("verified_at"),
        )


@dataclass(frozen=True)
class DebtPaymentResponse:
    id: str
    external_id: Optional[str]
    amount: str
    paid_at: str
    #: Channel of the last delivered reminder before this payment (None if none).
    attributed_channel: Optional[str]
    #: Days after the due date (negative = early, 0 = on the due date).
    days_late: int

    def is_late(self) -> bool:
        return self.days_late > 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DebtPaymentResponse":
        return cls(
            id=str(data["id"]),
            external_id=data.get("external_id"),
            amount=str(data["amount"]),
            paid_at=str(data["paid_at"]),
            attributed_channel=data.get("attributed_channel"),
            days_late=int(data["days_late"]),
        )


@dataclass(frozen=True)
class DebtResponse:
    id: str
    external_id: Optional[str]
    name: str
    phone: str
    amount: str
    paid_amount: str
    remaining_amount: str
    currency: str
    due_date: str
    #: active, paused, paid, exhausted (every step sent, still unpaid) or cancelled.
    status: str
    environment: str
    next_reminder_at: Optional[str]
    paid_at: Optional[str]
    #: Channel of the last delivered reminder before the closing payment.
    paid_channel: Optional[str]
    paid_days_late: Optional[int]
    #: Only filled by ``debts.find()``.
    payments: List[DebtPaymentResponse] = field(default_factory=list)

    def is_paid(self) -> bool:
        return self.status == "paid"

    def is_active(self) -> bool:
        return self.status == "active"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DebtResponse":
        return cls(
            id=str(data["id"]),
            external_id=data.get("external_id"),
            name=str(data["name"]),
            phone=str(data["phone"]),
            amount=str(data["amount"]),
            paid_amount=str(data["paid_amount"]),
            remaining_amount=str(data["remaining_amount"]),
            currency=str(data["currency"]),
            due_date=str(data["due_date"]),
            status=str(data["status"]),
            environment=str(data.get("environment") or "production"),
            next_reminder_at=data.get("next_reminder_at"),
            paid_at=data.get("paid_at"),
            paid_channel=data.get("paid_channel"),
            paid_days_late=_int(data.get("paid_days_late")),
            payments=[DebtPaymentResponse.from_dict(payment) for payment in data.get("payments") or []],
        )


@dataclass(frozen=True)
class RecordPaymentResponse:
    payment: DebtPaymentResponse
    #: The debt after this payment - check ``is_paid()`` / ``remaining_amount``.
    debt: DebtResponse

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RecordPaymentResponse":
        return cls(payment=DebtPaymentResponse.from_dict(data["payment"]), debt=DebtResponse.from_dict(data["debt"]))


@dataclass(frozen=True)
class ScheduledMessageResponse:
    id: str
    #: active, paused, completed (a one-time schedule that was sent) or cancelled.
    status: str
    environment: str
    channel: str
    channel_account_id: Optional[int]
    sms_type: Optional[str]
    recipient: Optional[str]
    contact_group_id: Optional[int]
    template_id: Optional[int]
    variables: Optional[Dict[str, Any]]
    message: Optional[str]
    subject: Optional[str]
    photo_url: Optional[str]
    #: once or recurring.
    schedule_type: str
    starts_at: str
    #: interval, weekly or monthly - None for a one-time schedule.
    recurrence_type: Optional[str]
    interval_value: Optional[int]
    interval_unit: Optional[str]
    weekdays: Optional[List[int]]
    month_days: Optional[List[int]]
    #: When it is sent next - None when paused, completed or cancelled.
    next_run_at: Optional[str]
    last_run_at: Optional[str]
    #: Why the last send failed (e.g. insufficient balance); the schedule still moved on.
    last_error: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]

    def is_active(self) -> bool:
        return self.status == "active"

    def is_paused(self) -> bool:
        return self.status == "paused"

    def is_recurring(self) -> bool:
        return self.schedule_type == "recurring"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScheduledMessageResponse":
        return cls(
            id=str(data["id"]),
            status=str(data["status"]),
            environment=str(data.get("environment") or "production"),
            channel=str(data["channel"]),
            channel_account_id=_int(data.get("channel_account_id")),
            sms_type=data.get("sms_type"),
            recipient=data.get("recipient"),
            contact_group_id=_int(data.get("contact_group_id")),
            template_id=_int(data.get("template_id")),
            variables=data.get("variables"),
            message=data.get("message"),
            subject=data.get("subject"),
            photo_url=data.get("photo_url"),
            schedule_type=str(data["schedule_type"]),
            starts_at=str(data["starts_at"]),
            recurrence_type=data.get("recurrence_type"),
            interval_value=_int(data.get("interval_value")),
            interval_unit=data.get("interval_unit"),
            weekdays=data.get("weekdays"),
            month_days=data.get("month_days"),
            next_run_at=data.get("next_run_at"),
            last_run_at=data.get("last_run_at"),
            last_error=data.get("last_error"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


@dataclass(frozen=True)
class ScheduledMessageListResponse:
    #: Newest first.
    items: List[ScheduledMessageResponse]
    current_page: int
    last_page: int
    per_page: int
    total: int

    def has_more_pages(self) -> bool:
        return self.current_page < self.last_page

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScheduledMessageListResponse":
        meta = data.get("meta") or {}
        items = [ScheduledMessageResponse.from_dict(item) for item in data.get("scheduled_messages") or []]
        return cls(
            items=items,
            current_page=int(meta.get("current_page", 1)),
            last_page=int(meta.get("last_page", 1)),
            per_page=int(meta.get("per_page", len(items))),
            total=int(meta.get("total", len(items))),
        )
