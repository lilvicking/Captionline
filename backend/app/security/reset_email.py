"""Password reset email.

The reset link is built from `FRONTEND_URL`, so a deployment never needs a code
change to point at a different domain, and `captionline.pro` is not hardcoded
anywhere. The raw token appears only in the emailed link; it is never logged, and
it is never included in any API response.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote, urlencode

from ..config import get_settings
from ..email import EmailMessage

#: Frontend path that consumes the token. Matches the route in the web app.
RESET_PATH = "/reset-password"

SUBJECT = "Reset your Captionline password"


def build_reset_url(raw_token: str, frontend_url: str | None = None) -> str:
    """Build the single-use reset link from the configured frontend origin.

    The token is percent-encoded into the query string, and the origin comes from
    configuration only, so this can never become an open redirect.
    """
    settings = get_settings()
    base = (frontend_url or settings.frontend_url).rstrip("/")

    return f"{base}{RESET_PATH}?{urlencode({'token': raw_token})}"


def _expiry_sentence(expires_at: datetime) -> str:
    minutes = max(int((expires_at.timestamp() - datetime.now().timestamp()) // 60), 0)
    return f"about {minutes} minutes"


def build_password_reset_email(
    *, recipient: str, raw_token: str, expires_at: datetime
) -> EmailMessage:
    """Compose the reset message. The password is never part of it."""
    reset_url = build_reset_url(raw_token)
    window = _expiry_sentence(expires_at)

    text = (
        "Someone requested a password reset for your Captionline account.\n\n"
        f"Reset your password: {reset_url}\n\n"
        f"This link can be used once and expires in {window}.\n\n"
        "If you did not request this, you can ignore this email. "
        "Your password will not change until someone uses the link above.\n"
    )

    html = f"""<!doctype html>
<html lang="en">
  <body style="margin:0;padding:0;background:#f7f7f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#16161a;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#ffffff;border:1px solid #dcdce2;border-radius:10px;">
            <tr>
              <td style="padding:28px 28px 8px;">
                <p style="margin:0;font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#ff0033;">Captionline</p>
                <h1 style="margin:12px 0 0;font-size:20px;line-height:1.3;">Reset your password</h1>
              </td>
            </tr>
            <tr>
              <td style="padding:8px 28px 0;font-size:15px;line-height:1.6;color:#3c3c45;">
                <p style="margin:0 0 16px;">Someone requested a password reset for your Captionline account.</p>
                <p style="margin:0 0 24px;">
                  <a href="{quote(reset_url, safe=':/?&amp;=')}"
                     style="display:inline-block;background:#ff0033;color:#ffffff;text-decoration:none;font-weight:600;font-size:15px;padding:12px 20px;border-radius:10px;">
                    Reset password
                  </a>
                </p>
                <p style="margin:0 0 8px;font-size:14px;color:#6a6a75;">
                  This link can be used once and expires in {window}.
                </p>
                <p style="margin:0;font-size:14px;color:#6a6a75;">
                  If you did not request this, you can ignore this email. Your password will not
                  change until someone uses the link above.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    return EmailMessage(to=recipient, subject=SUBJECT, text=text, html=html)
