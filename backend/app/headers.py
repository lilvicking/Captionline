"""Security response headers.

The service returns JSON and serves FastAPI's own interactive documentation, so
the headers below are chosen to be strict for an API and inert for a
documentation page.

Why each one is here
--------------------
``X-Content-Type-Options``  Stops a browser from re-interpreting a response as
                           HTML or script. Every response here is JSON, and none
                           of it is meant to be rendered.
``X-Frame-Options: DENY``   No response may be framed, so a logged-in page cannot
                           be clickjacked.
``Referrer-Policy``         Keeps full paths and query strings (which carry reset
                           tokens) out of the ``Referer`` of a third-party
                           request.
``Permissions-Policy``      Locks down the powerful device APIs a transcription
                           UI never needs.
``Content-Security-Policy`` A JSON API pulls in nothing, so everything is denied
                           outright.
``Strict-Transport-Security`` Only meaningful over TLS, and actively harmful
                           locally, so it is emitted conditionally.
``Cache-Control: no-store`` A bearer token must never be written to a shared or
                           on-disk cache.

The CSP exception
-----------------
FastAPI's ``/docs`` and ``/redoc`` are HTML pages that load their JavaScript and
CSS from a public CDN. The strict policy below sets ``default-src 'none'``,
which would blank both pages, and ``/openapi.json`` is the schema those pages
fetch. Those three paths therefore get every header *except* the CSP, and they
are listed in ``CSP_EXEMPT_PATHS`` so the exclusion is visible rather than
implied. Everything the application itself serves is still covered.
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Deliberately deny-by-default: the API loads no script, style, frame, image,
#: font, or connection of its own.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)

HSTS_VALUE = "max-age=63072000; includeSubDomains"

X_FRAME_OPTIONS = "DENY"
REFERRER_POLICY = "strict-origin-when-cross-origin"
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), interest-cohort=()"

#: FastAPI's own pages. Excluded from the CSP only; every other header still
#: applies to them.
CSP_EXEMPT_PATHS = frozenset({"/docs", "/redoc", "/openapi.json"})

#: Endpoints whose responses carry a bearer token or a password-reset outcome.
#: None of those may be stored by a proxy, a CDN, or the browser.
NO_STORE_PATHS = frozenset(
    {
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/me",
        "/api/auth/reset-password",
        "/api/auth/change-password",
        "/api/auth/forgot-password",
    }
)


class SecurityHeadersMiddleware:
    """Add the hardening headers to every HTTP response.

    Implemented as a plain ASGI wrapper rather than `BaseHTTPMiddleware` so it
    adds no response buffering and no dependency on Starlette's middleware
    base classes. Responses that already carry a value keep it, so a route that
    needs a different `Cache-Control` is not silently overridden.
    """

    def __init__(self, app: ASGIApp, *, hsts_enabled: bool | None = None) -> None:
        self.app = app
        # None means "decide per request": emit HSTS only over HTTPS, because a
        # browser ignores the header on a plain-HTTP response anyway and a
        # misconfigured local proxy could pin localhost to HTTPS.
        self.hsts_enabled = hsts_enabled

    def _should_send_hsts(self, scope: Scope) -> bool:
        if self.hsts_enabled is not None:
            return self.hsts_enabled
        return scope.get("scheme") == "https"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        send_hsts = self._should_send_hsts(scope)
        headers = self._headers_for(path, send_hsts)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                for name, value in headers:
                    if name not in response_headers:
                        response_headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)

    def _headers_for(self, path: str, send_hsts: bool) -> list[tuple[str, str]]:
        headers: list[tuple[str, str]] = [
            ("x-content-type-options", "nosniff"),
            ("x-frame-options", X_FRAME_OPTIONS),
            ("referrer-policy", REFERRER_POLICY),
            ("permissions-policy", PERMISSIONS_POLICY),
        ]

        if path not in CSP_EXEMPT_PATHS:
            headers.append(("content-security-policy", CONTENT_SECURITY_POLICY))

        if send_hsts:
            headers.append(("strict-transport-security", HSTS_VALUE))

        if path in NO_STORE_PATHS:
            headers.append(("cache-control", "no-store"))

        return headers


__all__ = [
    "CONTENT_SECURITY_POLICY",
    "CSP_EXEMPT_PATHS",
    "HSTS_VALUE",
    "NO_STORE_PATHS",
    "SecurityHeadersMiddleware",
]
