"""Transactional email.

A thin provider abstraction so the vendor lives in exactly one place. Adding a
second provider means adding a class, not editing call sites.

Providers
---------
``ResendProvider``  HTTP API for Resend. Used in production.
``ConsoleProvider`` Local development only. Writes the message to the log.
``MemoryProvider``  Test double. Keeps messages in memory for assertions.

Two rules are enforced here:

1. The API key is never logged, and neither is a reset link. The console
   provider is the single exception and only activates when ``EMAIL_PROVIDER``
   is explicitly set to ``console``, so it cannot run in production by accident.
2. Delivery happens server side only. The frontend never learns the key.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from .config import get_settings

logger = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"


@dataclass(frozen=True)
class EmailMessage:
    """An outbound message. Never carries a password or a secret."""

    to: str
    subject: str
    text: str
    html: str = ""


class EmailDeliveryError(Exception):
    """Raised when a provider could not deliver a message."""


class EmailProvider(Protocol):
    """Minimal provider contract."""

    name: str

    def send(self, message: EmailMessage) -> None:
        """Deliver the message or raise `EmailDeliveryError`."""


class ResendProvider:
    """Delivers through the Resend HTTP API using only the standard library."""

    name = "resend"

    def __init__(self, api_key: str, from_address: str, timeout: int = 10) -> None:
        self._api_key = api_key
        self._from = from_address
        self._timeout = timeout

    def send(self, message: EmailMessage) -> None:
        payload = json.dumps(
            {
                "from": self._from,
                "to": [message.to],
                "subject": message.subject,
                "text": message.text,
                "html": message.html or message.text,
            }
        ).encode("utf-8")

        # The key is passed in the header and is never included in logs.
        request = urllib.request.Request(
            RESEND_ENDPOINT,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                status = getattr(response, "status", 200)
        except urllib.error.HTTPError as exc:
            # Status only. The body can echo the submitted address, and the
            # request headers (which hold the key) are never read.
            raise EmailDeliveryError(
                f"{self.name} rejected the message with status {exc.code}"
            ) from None
        except urllib.error.URLError:
            raise EmailDeliveryError(f"{self.name} could not be reached") from None
        except (TimeoutError, OSError):
            raise EmailDeliveryError(f"{self.name} timed out") from None

        if status >= 300:
            raise EmailDeliveryError(
                f"{self.name} rejected the message with status {status}"
            )

        logger.info("Sent %s email to a requested address", self.name)


class ConsoleProvider:
    """Local development provider. Logs the message body.

    Only reachable when EMAIL_PROVIDER is explicitly ``console``, so a production
    deployment cannot print reset links to the log stream.
    """

    name = "console"

    def send(self, message: EmailMessage) -> None:
        logger.warning(
            "EMAIL_PROVIDER=console: development only. Not delivering email.\n"
            "  to: %s\n  subject: %s\n  body:\n%s",
            message.to,
            message.subject,
            message.text,
        )


@dataclass
class MemoryProvider:
    """Test provider. Retains messages so tests can assert on them."""

    name: str = "memory"
    sent: list[EmailMessage] = field(default_factory=list)

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)

    @property
    def last(self) -> EmailMessage | None:
        return self.sent[-1] if self.sent else None

    def clear(self) -> None:
        self.sent.clear()


def build_provider() -> EmailProvider | None:
    """Build the configured provider, or None when email is not set up.

    Returns None rather than guessing: an unconfigured deployment must fail
    safely, not silently print reset links or pretend to send mail.
    """
    settings = get_settings()
    provider = settings.email_provider

    if provider == "resend" and settings.email_api_key:
        return ResendProvider(
            api_key=settings.email_api_key,
            from_address=settings.email_from,
            timeout=settings.email_timeout_seconds,
        )

    if provider == "console":
        return ConsoleProvider()

    if provider == "memory":
        return MemoryProvider()

    return None


#: Process-wide test override. Set by the test suite so no network call and no
#: log output is possible.
_override: MemoryProvider | None = None


def set_provider_override(provider: EmailProvider | None) -> None:
    """Inject a provider for tests."""
    global _override
    _override = provider  # type: ignore[assignment]


def get_provider() -> EmailProvider | None:
    """Return the active provider: a test override if set, else configuration."""
    if _override is not None:
        return _override
    return build_provider()
