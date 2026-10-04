"""Official Python SDK for the CloudMe Notify multi-channel notification API."""

__version__ = "1.0.0"

from .auth import FileTokenStorage, MemoryTokenStorage, TokenStorage  # noqa: E402
from .client import NotifyClient  # noqa: E402
from .exceptions import (  # noqa: E402
    ApiError,
    AuthenticationError,
    ConfigurationError,
    ForbiddenError,
    InsufficientBalanceError,
    InvalidWebhookSignatureError,
    NetworkError,
    NotFoundError,
    NotifyError,
    RateLimitError,
    ServerError,
    SpendingLimitExceededError,
    ValidationError,
)
from .scheduled_messages import Recurrence  # noqa: E402
from .webhooks import WebhookEvent, WebhookVerifier  # noqa: E402

__all__ = [
    "__version__",
    "ApiError",
    "AuthenticationError",
    "ConfigurationError",
    "FileTokenStorage",
    "ForbiddenError",
    "InsufficientBalanceError",
    "InvalidWebhookSignatureError",
    "MemoryTokenStorage",
    "NetworkError",
    "NotFoundError",
    "NotifyClient",
    "NotifyError",
    "RateLimitError",
    "Recurrence",
    "ServerError",
    "SpendingLimitExceededError",
    "TokenStorage",
    "ValidationError",
    "WebhookEvent",
    "WebhookVerifier",
]
