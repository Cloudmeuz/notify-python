"""Per-channel senders: ``notify.sms.send(...)``, ``notify.telegram.binding_link(...)``..."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Optional

from .responses import SendMessageResponse, TelegramBindingResponse

if TYPE_CHECKING:
    from .client import NotifyClient


class ChannelSender:
    def __init__(self, client: "NotifyClient", channel: str, universal: bool = False) -> None:
        self._client = client
        self.channel = channel
        self._universal = universal

    def send(
        self,
        to: str,
        message: Optional[str] = None,
        template_id: Optional[int] = None,
        variables: Optional[Mapping[str, Any]] = None,
        sms_type: Optional[str] = None,
        subject: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        photo_url: Optional[str] = None,
        channel_account_id: Optional[int] = None,
    ) -> SendMessageResponse:
        """Sends one message.

        ``variables`` fill a template's ``{{placeholders}}`` (only with ``template_id``).
        ``photo_url`` (Telegram/WhatsApp) is a public JPEG/PNG; the text becomes its caption.
        Every send carries an ``Idempotency-Key`` (generated when not given), so the
        automatic retry after a network failure never sends twice.
        """
        return self._client._send_message(
            self.channel,
            to,
            message=message,
            template_id=template_id,
            variables=variables,
            sms_type=sms_type,
            subject=subject,
            idempotency_key=idempotency_key,
            photo_url=photo_url,
            channel_account_id=channel_account_id,
            universal=self._universal,
        )

    def call(
        self,
        to: str,
        message: Optional[str] = None,
        template_id: Optional[int] = None,
        variables: Optional[Mapping[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> SendMessageResponse:
        """Alias of send() that reads naturally for voice: ``notify.voice.call(to=..., message="Text to speak")``."""
        return self.send(to, message, template_id, variables, idempotency_key=idempotency_key)


class TelegramChannelSender(ChannelSender):
    def binding_link(self, phone: str, channel_account_id: Optional[int] = None) -> TelegramBindingResponse:
        """Telegram cannot message a phone directly: send the returned link to the customer first.

        The same phone gets the same link again for 7 days. ``channel_account_id`` picks
        your own bot profile; None means your default bot or the platform bot.
        """
        return self._client._create_telegram_binding(phone, channel_account_id)


class PushChannelSender(ChannelSender):
    def register_device(self, phone: str, fcm_token: str, channel_account_id: Optional[int] = None) -> None:
        """Registers (or refreshes) a customer's FCM token, identified by phone - call it whenever your app gets or rotates one."""
        self._client._register_push_device(phone, fcm_token, channel_account_id)
