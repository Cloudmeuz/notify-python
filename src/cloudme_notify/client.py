"""Entry point of the Notify Python SDK.

.. code-block:: python

    from cloudme_notify import NotifyClient

    notify = NotifyClient(
        client_id=os.environ["NOTIFY_CLIENT_ID"],
        api_key=os.environ["NOTIFY_API_KEY"],
        private_key="/secure/path/private.pem",
        base_url=NotifyClient.SANDBOX_URL,
    )

    notify.sms.send(to="+998901234567", message="Buyurtmangiz tayyor")

Authentication, token refresh, request signing, retries, idempotency and error
mapping are handled internally.
"""

from __future__ import annotations

import os
import secrets
from typing import Any, Dict, Mapping, Optional, Union

import httpx

from . import __version__
from ._http import HttpClient
from .auth import MemoryTokenStorage, SignatureSigner, TokenManager, TokenStorage
from .channels import ChannelSender, PushChannelSender, TelegramChannelSender
from .exceptions import AuthenticationError, ConfigurationError
from .resources import DebtsClient, OtpClient, ReportsClient, TemplatesClient
from .responses import BalanceResponse, MessageStatusResponse, SendMessageResponse, TelegramBindingResponse
from .scheduled_messages import ScheduledMessagesClient

#: Channels with their own /messages/{channel} endpoint.
NAMED_CHANNELS = ("sms", "telegram", "whatsapp", "voice", "email", "push")


class NotifyClient:
    PRODUCTION_URL = "https://api.notify.cloudme.uz/api/v1"
    SANDBOX_URL = "https://sandbox.notify.cloudme.uz/api/v1"

    def __init__(
        self,
        client_id: str,
        api_key: str,
        private_key: Union[str, bytes, os.PathLike],
        base_url: str,
        token_storage: Optional[TokenStorage] = None,
        timeout: float = 10.0,
        connect_timeout: float = 5.0,
        max_retries: int = 3,
        locale: Optional[str] = None,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        """
        :param private_key: PEM text/bytes, or a path to the PEM file of the API client's RSA key.
        :param base_url: ``NotifyClient.PRODUCTION_URL``, ``NotifyClient.SANDBOX_URL`` or your own deployment's.
        :param token_storage: where the token pair is kept between calls (default: this object's memory).
        :param locale: language of error messages and hints - "uz", "uz-Cyrl", "ru" or "en" (Uzbek when omitted).
        :param transport: an httpx transport override - for tests (``httpx.MockTransport``).
        """
        if not (client_id or "").strip() or not (api_key or "").strip():
            raise ConfigurationError("client_id and api_key are required.")
        if not (base_url or "").strip():
            raise ConfigurationError("base_url is required.")

        headers = {"User-Agent": f"cloudme-notify-python/{__version__}"}
        if locale and locale.strip():
            headers["Accept-Language"] = locale.strip()

        self._httpx = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            headers=headers,
            transport=transport,
        )
        self._http = HttpClient(self._httpx, max_retries)
        self._tokens = TokenManager(self._http, SignatureSigner(private_key), token_storage or MemoryTokenStorage(), client_id, api_key)

        self.sms = ChannelSender(self, "sms")
        self.telegram = TelegramChannelSender(self, "telegram")
        self.whatsapp = ChannelSender(self, "whatsapp")
        self.voice = ChannelSender(self, "voice")
        self.email = ChannelSender(self, "email")
        self.push = PushChannelSender(self, "push")
        self.otp = OtpClient(self)
        self.templates = TemplatesClient(self)
        self.reports = ReportsClient(self)
        self.debts = DebtsClient(self)
        self.scheduled_messages = ScheduledMessagesClient(self)

    def channel(self, channel: str) -> ChannelSender:
        """A channel chosen at runtime; one this version does not know goes through the universal POST /messages."""
        return ChannelSender(self, channel, universal=channel not in NAMED_CHANNELS)

    def message(self, message_id: str) -> MessageStatusResponse:
        return MessageStatusResponse.from_dict(self._request("GET", f"messages/{message_id}", retryable=True))

    def balance(self) -> BalanceResponse:
        return BalanceResponse.from_dict(self._request("GET", "balance", retryable=True))

    def close(self) -> None:
        self._httpx.close()

    def __enter__(self) -> "NotifyClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def _send_message(
        self,
        channel: str,
        to: str,
        message: Optional[str] = None,
        template_id: Optional[int] = None,
        variables: Optional[Mapping[str, Any]] = None,
        sms_type: Optional[str] = None,
        subject: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        photo_url: Optional[str] = None,
        channel_account_id: Optional[int] = None,
        universal: bool = False,
    ) -> SendMessageResponse:
        # The universal endpoint takes the channel in the body and calls the
        # recipient "recipient"; the per-channel endpoints call it "to".
        target = {"channel": channel, "recipient": to} if universal else {"to": to}
        body = {
            **target,
            "message": message,
            "template_id": template_id,
            "variables": dict(variables) if variables else None,
            "sms_type": sms_type,
            "subject": subject,
            "photo_url": photo_url,
            "channel_account_id": channel_account_id,
        }

        # A generated key makes the automatic retry after a network failure
        # safe: the server returns the first result instead of sending twice.
        response = self._request(
            "POST",
            "messages" if universal else f"messages/{channel}",
            json={key: value for key, value in body.items() if value is not None},
            idempotency_key=idempotency_key or secrets.token_hex(16),
            retryable=True,
        )
        return SendMessageResponse.from_dict(response)

    def _register_push_device(self, phone: str, fcm_token: str, channel_account_id: Optional[int] = None) -> None:
        body = {"phone": phone, "fcm_token": fcm_token, "channel_account_id": channel_account_id}
        self._request("POST", "push/devices", json={key: value for key, value in body.items() if value is not None}, retryable=True)

    def _create_telegram_binding(self, phone: str, channel_account_id: Optional[int] = None) -> TelegramBindingResponse:
        # Safe to retry: the API returns the same pending link for the same phone.
        body = {"phone": phone, "channel_account_id": channel_account_id}
        response = self._request("POST", "telegram/bindings", json={key: value for key, value in body.items() if value is not None}, retryable=True)
        return TelegramBindingResponse.from_dict(response)

    def _request(
        self,
        method: str,
        path: str,
        json: Optional[Mapping[str, Any]] = None,
        params: Optional[Mapping[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        retryable: bool = False,
    ) -> Dict[str, Any]:
        token = self._tokens.get_access_token()

        try:
            return self._http.request(method, path, json, params, token, idempotency_key, retryable)
        except AuthenticationError:
            # The cached token looked valid but the server refused it (e.g.
            # revoked) - re-authenticate once and repeat the call.
            token = self._tokens.force_reauthenticate()
            return self._http.request(method, path, json, params, token, idempotency_key, retryable)
