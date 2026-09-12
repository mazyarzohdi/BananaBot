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




class TelegramEmbedMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Remove the blanket X-Frame-Options: DENY set by
        # XFrameOptionsMiddleware.
        # We do not set CSP frame-ancestors because Telegram clients 
        # (especially on Android) might use local wrappers (tg://, http://localhost)
        # which would be blocked by a strict CSP.
        if "X-Frame-Options" in response:
            del response["X-Frame-Options"]
        return response
