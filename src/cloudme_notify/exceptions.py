"""Exceptions raised by the Notify SDK.

Every API-level failure is a :class:`NotifyError` subclass chosen from the
HTTP status (and, for 402, the error code). A local misconfiguration raises
:class:`ConfigurationError` instead, before any request is made.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional


class ConfigurationError(ValueError):
    """The SDK was set up wrongly (missing credentials, unreadable private key...)."""


class NotifyError(Exception):
    """Base class for every API-level failure."""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        status_code: Optional[int] = None,
        response_body: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.response_body: Optional[Dict[str, Any]] = dict(response_body) if response_body is not None else None

    def _error_field(self, name: str) -> Any:
        error = (self.response_body or {}).get("error")
        return error.get(name) if isinstance(error, dict) else None

    @property
    def hint(self) -> Optional[str]:
        """What to do about this error (``error.hint``), in the requested locale."""
        value = self._error_field("hint")
        return value if isinstance(value, str) else None

    @property
    def docs_url(self) -> Optional[str]:
        """Link to this error code in the dashboard API docs (``error.docs_url``)."""
        value = self._error_field("docs_url")
        return value if isinstance(value, str) else None

    @property
    def required_scope(self) -> Optional[str]:
        """``SCOPE_FORBIDDEN`` only: the scope the API client is missing, e.g. ``"sms:send"``."""
        value = self._error_field("required_scope")
        return value if isinstance(value, str) else None

    @property
    def missing_variables(self) -> List[str]:
        """``MISSING_TEMPLATE_VARIABLE`` only: template variables that were not sent."""
        value = self._error_field("missing_variables")
        return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


class ApiError(NotifyError):
    """An unexpected HTTP status not covered by a more specific class."""


class AuthenticationError(NotifyError):
    """401 - credentials, signature or token rejected."""


class ForbiddenError(NotifyError):
    """403 - missing scope, revoked client, environment mismatch, IP not allowed..."""


class NotFoundError(NotifyError):
    """404 - unknown id, or it belongs to another company/environment."""


class InsufficientBalanceError(NotifyError):
    """402 ``INSUFFICIENT_BALANCE`` - the wallet cannot pay for the message."""


class SpendingLimitExceededError(InsufficientBalanceError):
    """402 ``SPENDING_LIMIT_EXCEEDED`` - a daily or monthly company spending cap would be exceeded."""


class ValidationError(NotifyError):
    """422 - a documented error code, or field-level validation failures in :attr:`errors`."""

    def __init__(
        self,
        message: str,
        errors: Optional[Mapping[str, List[str]]] = None,
        error_code: Optional[str] = None,
        status_code: Optional[int] = None,
        response_body: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, status_code, response_body)
        self.errors: Dict[str, List[str]] = dict(errors or {})


class RateLimitError(NotifyError):
    """429 - too many requests; :attr:`retry_after_seconds` says how long to wait."""

    def __init__(
        self,
        message: str,
        retry_after_seconds: Optional[int] = None,
        error_code: Optional[str] = None,
        status_code: Optional[int] = None,
        response_body: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message, error_code, status_code, response_body)
        self.retry_after_seconds = retry_after_seconds


class ServerError(NotifyError):
    """5xx - Notify could not process the request."""


class NetworkError(NotifyError):
    """The API could not be reached (DNS, timeout, connection reset...)."""


class InvalidWebhookSignatureError(NotifyError):
    """A webhook's signature or timestamp is invalid, or its body is not JSON."""
