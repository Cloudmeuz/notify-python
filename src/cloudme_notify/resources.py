"""Grouped API resources: ``notify.otp``, ``notify.templates``, ``notify.reports``, ``notify.debts``."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from .exceptions import ValidationError
from .responses import (
    DebtResponse,
    OtpSendResponse,
    OtpVerifyResponse,
    RecordPaymentResponse,
    TemplateResponse,
)

if TYPE_CHECKING:
    from .client import NotifyClient

Number = Union[int, float, str]


def _without_none(data: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


class OtpClient:
    """The platform generates, delivers and checks the code - your app never sees it (except in sandbox)."""

    def __init__(self, client: "NotifyClient") -> None:
        self._client = client

    def send(self, to: str, channel: str = "sms") -> OtpSendResponse:
        """``channel``: sms (default), telegram, whatsapp or email. Keep ``otp_id`` for verify().

        Never retried automatically - a retry could deliver a second code.
        Raises RateLimitError (``OTP_RESEND_TOO_SOON``) when a code was sent too recently.
        """
        return OtpSendResponse.from_dict(self._client._request("POST", "otp/send", json={"to": to, "channel": channel}))

    def verify(self, otp_id: str, code: str) -> OtpVerifyResponse:
        """A wrong, expired, burnt or used code is a normal result, not an exception - check ``verified``."""
        try:
            response = self._client._request("POST", "otp/verify", json={"otp_id": otp_id, "code": code})
        except ValidationError as error:
            if str(error.error_code or "").startswith("OTP_"):
                return OtpVerifyResponse.from_dict(error.response_body or {})
            raise

        return OtpVerifyResponse.from_dict(response)


class TemplatesClient:
    def __init__(self, client: "NotifyClient") -> None:
        self._client = client

    def list(self, channel: Optional[str] = None) -> List[TemplateResponse]:
        """System templates plus your approved ones, for the channels your API client may send on."""
        response = self._client._request("GET", "templates", params=_without_none({"channel": channel}), retryable=True)
        return [TemplateResponse.from_dict(template) for template in response.get("templates") or []]


class ReportsClient:
    """Rows are plain dicts: date/month, channel, count, amount."""

    def __init__(self, client: "NotifyClient") -> None:
        self._client = client

    def daily(self, from_date: Optional[date] = None, to_date: Optional[date] = None) -> List[Dict[str, Any]]:
        return self._report("reports/daily", from_date, to_date)

    def monthly(self, from_date: Optional[date] = None, to_date: Optional[date] = None) -> List[Dict[str, Any]]:
        return self._report("reports/monthly", from_date, to_date)

    def _report(self, path: str, from_date: Optional[date], to_date: Optional[date]) -> List[Dict[str, Any]]:
        params = _without_none({
            "from": from_date.strftime("%Y-%m-%d") if from_date else None,
            "to": to_date.strftime("%Y-%m-%d") if to_date else None,
        })
        return list(self._client._request("GET", path, params=params, retryable=True).get("data") or [])


class DebtsClient:
    """Hand a debt over for collection and report payments. Requires the ``debts:manage`` scope."""

    def __init__(self, client: "NotifyClient") -> None:
        self._client = client

    def create(
        self,
        name: str,
        phone: str,
        amount: Number,
        due_date: Union[date, str],
        external_id: Optional[str] = None,
        email: Optional[str] = None,
        currency: Optional[str] = None,
        description: Optional[str] = None,
        strategy_id: Optional[str] = None,
    ) -> DebtResponse:
        """With ``external_id`` the call is idempotent, so only then is it retried automatically.

        ``strategy_id``: dashboard -> Collection -> Strategies -> API ID; None = your default strategy.
        """
        body = _without_none({
            "name": name,
            "phone": phone,
            "amount": amount,
            "due_date": due_date.strftime("%Y-%m-%d") if isinstance(due_date, date) else due_date,
            "external_id": external_id,
            "email": email,
            "currency": currency,
            "description": description,
            "strategy_id": strategy_id,
        })
        response = self._client._request("POST", "debts", json=body, retryable=external_id is not None)
        return DebtResponse.from_dict(response["debt"])

    def find(self, debt_id: str) -> DebtResponse:
        """The debt with all its payments."""
        response = self._client._request("GET", f"debts/{debt_id}", retryable=True)
        return DebtResponse.from_dict({**response["debt"], "payments": response.get("payments") or []})

    def record_payment(
        self,
        debt_id: str,
        amount: Number,
        paid_at: Optional[Union[datetime, str]] = None,
        external_id: Optional[str] = None,
    ) -> RecordPaymentResponse:
        """Reports a (partial) payment; paying off the rest closes the debt. Raises ValidationError
        ``EXCEEDS_REMAINING``, ``DEBT_CLOSED`` or ``INVALID_AMOUNT``."""
        body = _without_none({
            "amount": amount,
            "paid_at": paid_at.isoformat() if isinstance(paid_at, datetime) else paid_at,
            "external_id": external_id,
        })
        response = self._client._request("POST", f"debts/{debt_id}/payments", json=body, retryable=external_id is not None)
        return RecordPaymentResponse.from_dict(response)

    def cancel(self, debt_id: str) -> DebtResponse:
        """Stops collecting: no more reminders, no more payments."""
        return DebtResponse.from_dict(self._client._request("POST", f"debts/{debt_id}/cancel")["debt"])
