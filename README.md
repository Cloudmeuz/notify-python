# cloudme-notify

Official Python SDK for the **CloudMe Notify** multi-channel notification API — SMS, Telegram, WhatsApp, Voice, Email and Push through one client, plus OTP, debt collection and scheduled messages.

Request signing, token exchange and refresh, retries, idempotency and error mapping are handled for you — you never implement Notify's security protocol yourself.

Using Django? Install [`cloudme-notify-django`](https://pypi.org/project/cloudme-notify-django/) on top of this package.

## Requirements

- Python 3.9+
- Your Notify `client_id`, `api_key` and RSA **private key** (generated when you created an API client in the Notify dashboard -> API clients)

## Installation

```bash
pip install cloudme-notify
```

## Quick start

```python
import os
from cloudme_notify import NotifyClient

notify = NotifyClient(
    client_id=os.environ["NOTIFY_CLIENT_ID"],
    api_key=os.environ["NOTIFY_API_KEY"],
    private_key="/secure/path/private.pem",   # a file path, or the PEM text itself
    base_url=NotifyClient.SANDBOX_URL,        # NotifyClient.PRODUCTION_URL for real sends
    locale="uz",                              # optional: language of error messages - uz, uz-Cyrl, ru, en
)

response = notify.sms.send(to="+998901234567", message="Buyurtmangiz tayyor")
response.message_id   # "0f6c1a52-..."
response.status       # "queued"
```

The first call signs your credentials and exchanges them for an access token; the token is cached and refreshed automatically from then on.

## Sandbox

A sandbox API client (`nk_test_...` key) works only against `NotifyClient.SANDBOX_URL`, a production one only against `NotifyClient.PRODUCTION_URL` (`ENVIRONMENT_MISMATCH` otherwise). Sandbox sends never reach a real provider and never charge your balance, but return a real `message_id`, `status` and `price`; `response.environment` is `"sandbox"`.

## Sending messages

Every channel has the same `send()`:

```python
notify.sms.send(to="+998901234567", message="Salom!", sms_type="service")
notify.telegram.send(to="+998901234567", message="<b>Tayyor</b>", photo_url="https://example.com/a.jpg")
notify.whatsapp.send(to="+998901234567", message="*Tayyor*")
notify.email.send(to="user@example.com", subject="Hisob-faktura", message="...")
notify.push.send(to="+998901234567", subject="Yangi xabar", message="...")
notify.voice.call(to="+998901234567", message="Buyurtmangiz tayyor")

# with a template instead of free text
notify.sms.send(to="+998901234567", template_id=42, variables={"name": "Aziz"})

# a channel chosen at runtime
notify.channel("sms").send(to="+998901234567", message="...")
```

- Free text that matches none of your templates waits for moderation: `response.is_held_for_moderation()`. Send OTP codes and urgent messages with a template or the OTP API.
- Telegram supports HTML (`<b>`, `<i>`, `<u>`, `<a href>`); WhatsApp uses `*bold*`, `_italic_`, `~strike~`. `photo_url` (Telegram/WhatsApp) turns the text into the photo's caption.
- `channel_account_id=7` sends through one of your own sender profiles (dashboard -> Channels).

### Templates

```python
for template in notify.templates.list(channel="sms"):
    print(template.id, template.name, template.variables)
```

### Telegram: link the phone first

Telegram cannot message a phone number directly. Send the customer the binding link once; after they press Start, Telegram messages to that phone are delivered:

```python
binding = notify.telegram.binding_link("+998901234567")
binding.bound   # True once linked
binding.link    # "https://t.me/notify_bot?start=..." - send it via SMS/email
```

### Push devices

```python
notify.push.register_device(phone="+998901234567", fcm_token=token_from_your_app)
```

### Idempotency

Every send carries an `Idempotency-Key` (generated if you don't pass one), so the automatic retry after a network failure never sends twice. Pass your own to make retries across processes safe too:

```python
notify.sms.send(to="+998901234567", message="...", idempotency_key=f"order-{order.id}")
```

## One-time codes (OTP)

Notify generates, delivers and checks the code — your app never sees or stores it:

```python
otp = notify.otp.send(to="+998901234567")          # channel="sms" | "telegram" | "whatsapp" | "email"
# keep otp.otp_id (e.g. in the session)

result = notify.otp.verify(otp.otp_id, code_from_user)
result.verified       # True / False
result.error_code     # OTP_INVALID | OTP_EXPIRED | OTP_ATTEMPTS_EXCEEDED | OTP_ALREADY_VERIFIED
result.can_retry()    # only a wrong code with attempts left
```

A wrong code is a result, not an exception. Sending too soon raises `RateLimitError` (`retry_after_seconds`). Neither call is retried automatically. In sandbox `otp.code` contains the code for testing.

## Scheduled messages

Send later — once, or on a recurring timetable — then edit, pause, resume or cancel. These are the same schedules as the dashboard's Scheduled messages page. Requires the `schedules:manage` scope plus the channel's send scope.

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from cloudme_notify import Recurrence

schedule = notify.scheduled_messages.create(
    channel="sms",
    starts_at=datetime(2026, 10, 6, 10, 0, tzinfo=ZoneInfo("Asia/Tashkent")),  # or "2026-10-06T10:00:00+05:00"
    recipient="+998901234567",
    message="Eslatma: bugun soat 15:00 da uchrashuv",
)

notify.scheduled_messages.create(
    channel="telegram",
    starts_at="2026-10-05T09:00:00+05:00",
    contact_group_id=12,                      # dashboard -> Contacts -> Groups -> API ID (production only)
    message="Salom, {{name}}! Haftalik yangiliklar...",
    recurrence=Recurrence.weekly([1, 4]),     # Recurrence.every(2, "hours"), Recurrence.monthly([1, 15])
)

notify.scheduled_messages.update(schedule.id, channel="sms", starts_at="2026-10-07T10:00:00+05:00",
                                 recipient="+998901234567", message="Uchrashuv ertaga")   # replaces everything
notify.scheduled_messages.pause(schedule.id)
notify.scheduled_messages.resume(schedule.id)    # continues at the next occurrence; missed ones are skipped
notify.scheduled_messages.cancel(schedule.id)
notify.scheduled_messages.find(schedule.id).last_error
notify.scheduled_messages.list(status="active").items
```

Errors: `ValidationError` with `error_code` `SCHEDULE_STATE_INVALID`, `SCHEDULE_START_PASSED`, `TEMPLATE_NOT_FOUND`, `CONTACT_GROUP_NOT_FOUND` or `SANDBOX_GROUP_UNSUPPORTED`. A naive `datetime` (or a string without offset) is read as Asia/Tashkent time.

## Debt collection

Hand a debt over and Notify reminds the debtor channel by channel following a collection strategy until you report it paid. Requires the `debts:manage` scope.

```python
from datetime import date

debt = notify.debts.create(
    name="Aziz Karimov",
    phone="+998901234567",
    amount=1250000,
    due_date=date(2026, 10, 15),
    external_id="INV-1001",       # your reference - makes create() idempotent
)

result = notify.debts.record_payment(debt.id, 1250000, external_id="PAY-5001")
result.debt.is_paid()                 # True -> reminders stop
result.payment.attributed_channel     # "sms" - the reminder that got them to pay

notify.debts.find(debt.id).payments
notify.debts.cancel(debt.id)
```

## Receiving webhooks

Register a webhook per API client (dashboard -> API clients -> Webhook) and verify every request with its signing secret. Always pass the **raw** body:

```python
from cloudme_notify import InvalidWebhookSignatureError, WebhookVerifier

verifier = WebhookVerifier(os.environ["NOTIFY_WEBHOOK_SECRET"])

try:
    event = verifier.parse(raw_body_bytes, request_headers)
except InvalidWebhookSignatureError:
    ...  # respond 401

if event.event == "message.failed":
    mark_failed(event.message_id, event.error_code)
# a retried delivery carries the same event.id - dedupe on it; respond 2xx within 5 seconds
```

## Status, balance and reports

```python
notify.message(response.message_id).status        # "delivered"
notify.balance().balance                            # "1000000.00"
notify.reports.daily(date(2026, 10, 1), date(2026, 10, 7))     # [{"date", "channel", "count", "amount"}, ...]
notify.reports.monthly()
```

## Error handling

| Exception | When |
| --- | --- |
| `ValidationError` | 422 - `error_code`, field `errors` |
| `InsufficientBalanceError` / `SpendingLimitExceededError` | 402 |
| `ForbiddenError` | 403 - `required_scope` on `SCOPE_FORBIDDEN` |
| `NotFoundError` | 404 |
| `RateLimitError` | 429 - `retry_after_seconds` |
| `AuthenticationError` | 401 that survived one automatic re-authentication |
| `ServerError` / `NetworkError` | 5xx / unreachable, after retries |
| `ConfigurationError` | bad local setup (missing credentials, unreadable key) |

All API errors derive from `NotifyError` and expose `error_code`, `status_code`, `hint`, `docs_url` and `response_body`:

```python
from cloudme_notify import NotifyError

try:
    notify.sms.send(to="+998901234567", message="...")
except NotifyError as error:
    log.warning("%s: %s (%s)", error.error_code, error, error.hint)
```

## Configuration

```python
NotifyClient(
    ...,
    token_storage=FileTokenStorage("/var/cache/notify/tokens.json"),  # reuse tokens across runs
    timeout=10.0, connect_timeout=5.0, max_retries=3,
)
```

The default `MemoryTokenStorage` lives as long as the client object. Implement `get()`, `put(tokens)` and `clear()` over Redis or your database to share tokens between processes (the Django package does this with Django's cache). `NotifyClient` can be used as a context manager to close its HTTP connections.

## Testing your code

Pass an `httpx.MockTransport` as `transport=` to answer requests in-process — no network calls.

## License

MIT
