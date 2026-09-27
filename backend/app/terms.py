"""Versioned legal text, in exactly one place.

Why this module exists
----------------------
The Terms of Service and the Privacy Notice are the only parts of Captionline
that change without a code change to the service: publishing revised text is a
business decision, not a deployment. `app/plans.py` is the single source of truth
for prices and allowances for the same reason, and this file is its legal
counterpart.

The rule this file enforces is therefore: **the version recorded against a user
comes from here and from nowhere else.** When the legal text changes, bump the
version and the effective date here. New registrations then record the new
values automatically, and `GET /api/legal/versions` reports the same values so
the frontend never hardcodes a version string that can quietly drift away from
what the backend actually stores.

Deliberate placeholders
-----------------------
Nothing in this file is legal text, and no value here should be read as a
statement of fact about a company, a jurisdiction, or a mailbox.

* `SUPPORT_EMAIL` is `None` unless an operator explicitly sets it. No inbound
  support mailbox has been verified yet, and telling a user to write to an
  address nobody reads is worse than admitting there is not one, so no plausible
  looking address is guessed.
* `GOVERNING_LAW_PLACEHOLDER` says plainly that it is a placeholder. Inventing a
  country, a state, or a company entity here would be a fabricated legal claim,
  so the text is left visible and obviously unfilled.

Both must be resolved before launch.
"""

from __future__ import annotations

import os

# --- Terms of Service --------------------------------------------------------

#: Bump whenever the Terms of Service text changes. This is a *label* for a
#: specific published text, not a revision counter, so a date is unambiguous.
TERMS_VERSION = "2026-09-27"

#: The date the text identified by `TERMS_VERSION` took effect. It can lag
#: `TERMS_VERSION` when a version is published before it is enforceable.
TERMS_EFFECTIVE_DATE = "2026-09-27"

# --- Privacy Notice ----------------------------------------------------------

PRIVACY_VERSION = "2026-09-27"
PRIVACY_EFFECTIVE_DATE = "2026-09-27"

# --- Support contact ---------------------------------------------------------

#: Name of the environment variable holding the support mailbox. Declared here
#: rather than in `app/config.py` because it is a legal-text setting, not a
#: service setting, and `config.py` is not this phase's to change.
SUPPORT_EMAIL_ENV_VAR = "SUPPORT_EMAIL"


def resolve_support_email() -> str | None:
    """Read the support mailbox from the environment, or None when unset.

    An empty or whitespace-only value is treated as unset: a blank mailbox in
    the environment is a misconfiguration, and `""` is not an address anyone can
    write to.
    """
    raw = os.getenv(SUPPORT_EMAIL_ENV_VAR)
    if raw is None:
        return None

    value = raw.strip()
    return value or None


#: None unless `SUPPORT_EMAIL` is set to a real, monitored inbox. The frontend
#: asks `/api/legal/versions` whether one exists instead of rendering a link to
#: an address that may not be monitored.
SUPPORT_EMAIL: str | None = resolve_support_email()


def support_email_configured() -> bool:
    """Whether a support mailbox is configured."""
    return bool(SUPPORT_EMAIL)


# --- Governing law -----------------------------------------------------------

#: PLACEHOLDER. MUST BE REPLACED BEFORE LAUNCH with the jurisdiction a lawyer
#: has actually chosen, and with the contracting entity's registered name.
#
#: It is a visible placeholder rather than a plausible value on purpose: a
#: guessed country or a guessed company name would be a fabricated legal claim
#: baked into the code, and would be very easy to ship by accident. The literal
#: text is meant to be obviously wrong to anyone reading the rendered page.
GOVERNING_LAW_PLACEHOLDER = "[governing jurisdiction to be confirmed]"


__all__ = [
    "GOVERNING_LAW_PLACEHOLDER",
    "PRIVACY_EFFECTIVE_DATE",
    "PRIVACY_VERSION",
    "SUPPORT_EMAIL",
    "SUPPORT_EMAIL_ENV_VAR",
    "TERMS_EFFECTIVE_DATE",
    "TERMS_VERSION",
    "resolve_support_email",
    "support_email_configured",
]
