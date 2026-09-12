"""Middleware needed for the panel to work as a Telegram Mini App.

Django's default XFrameOptionsMiddleware sends `X-Frame-Options: DENY`,
which blocks the page from being embedded in *any* frame. Telegram Desktop
(and some other Telegram clients) render Mini Apps inside an embedded
webview that behaves like an iframe, so DENY silently breaks the Mini App
there (blank/white screen, page "refuses to connect"). Mobile clients are
less strict, which is why this can look like it "mostly works" until
someone opens it on desktop.

We replace the blanket DENY with a Content-Security-Policy that only
allows framing from Telegram's own domains, which keeps the page safe from
being embedded on arbitrary third-party sites while still letting Telegram
itself display it.
"""




from django.conf import settings

TELEGRAM_ALLOWED_FRAME_ANCESTORS = (
    "'self' https://web.telegram.org https://webk.telegram.org "
    "https://webz.telegram.org https://*.telegram.org https://*.web.telegram.org"
)


class TelegramEmbedMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        path = request.path.rstrip("/")
        admin_prefix = f"{settings.WEB_PATH}/admin"

        # Admin routes must never be framed under any circumstances (prevent Clickjacking)
        if path.startswith(admin_prefix) or path == admin_prefix:
            response["X-Frame-Options"] = "DENY"
            response["Content-Security-Policy"] = "frame-ancestors 'none'"
            return response

        # User and Mini App routes: only allow framing from official Telegram domains
        if "X-Frame-Options" in response:
            del response["X-Frame-Options"]
        response["Content-Security-Policy"] = f"frame-ancestors {TELEGRAM_ALLOWED_FRAME_ANCESTORS}"
        return response
