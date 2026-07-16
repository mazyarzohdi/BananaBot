"""Django settings for BananaBot Web Panel."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BOT_DIR = BASE_DIR.parent  # /opt/BananaBot

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "change-me-in-production")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "panel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "panel.middleware.TelegramEmbedMiddleware",
]

ROOT_URLCONF = "bananabot_web.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "panel.context_processors.reseller_context",
            ],
        },
    },
]

WSGI_APPLICATION = "bananabot_web.wsgi.application"

# BananaBot shares the same SQLite database
BOT_DB_PATH = os.environ.get(
    "BOT_DB_PATH",
    str(BOT_DIR / "data" / "bot.db"),
)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BOT_DB_PATH,
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "fa-ir"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = False

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 86400 * 7   # 7 days
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# Telegram shows this panel inside its own page (Mini App webview / embedded
# frame on desktop clients), which browsers treat as a cross-site/third-party
# context. Cookies default to SameSite=Lax, which browsers silently refuse to
# send back in that context — the session looks like it "logs in" once, then
# instantly appears logged out. SameSite=None (with Secure, already required
# for HTTPS) fixes this. This has no effect when DEBUG=1 / running over plain
# HTTP for local testing, since Secure cookies aren't sent over HTTP anyway.
if not DEBUG:
    SESSION_COOKIE_SAMESITE = "None"
    CSRF_COOKIE_SAMESITE = "None"

# Needed for Django's CSRF check to accept POSTs (e.g. the settings forms)
# once the panel is reachable at a real domain instead of only "*".
_web_domain = os.environ.get("WEB_DOMAIN", "").strip()
CSRF_TRUSTED_ORIGINS = []
if _web_domain:
    CSRF_TRUSTED_ORIGINS = [f"https://{_web_domain}", f"http://{_web_domain}"]

# Telegram Bot token (read from bot's .env for OTP verification)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Admin telegram IDs (comma-separated)
ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "[]")
import json as _json
try:
    _ids = _json.loads(ADMIN_IDS_RAW)
    ADMIN_TELEGRAM_IDS = [int(x) for x in _ids]
except Exception:
    ADMIN_TELEGRAM_IDS = [
        int(x.strip()) for x in ADMIN_IDS_RAW.strip("[]").split(",") if x.strip().isdigit()
    ]

# Web path prefix e.g. "/panel"
WEB_PATH = os.environ.get("WEB_PATH", "/panel").rstrip("/")
