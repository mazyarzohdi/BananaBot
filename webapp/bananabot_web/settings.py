"""Django settings for BananaBot Web Panel."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BOT_DIR = BASE_DIR.parent  # /opt/BananaBot

_secret_file = BOT_DIR / "data" / ".django_secret"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if _secret_file.exists():
        try:
            SECRET_KEY = _secret_file.read_text(encoding="utf-8").strip()
        except Exception:
            SECRET_KEY = None
    if not SECRET_KEY:
        import secrets
        SECRET_KEY = secrets.token_urlsafe(50)
        try:
            _secret_file.parent.mkdir(parents=True, exist_ok=True)
            _secret_file.write_text(SECRET_KEY, encoding="utf-8")
        except Exception:
            pass

# Default to DEBUG=False in production unless DJANGO_DEBUG=1 is explicitly set
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

_web_domain = os.environ.get("WEB_DOMAIN", "").strip()
_allowed_hosts_env = os.environ.get("DJANGO_ALLOWED_HOSTS", "").strip()
if _allowed_hosts_env:
    ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_env.split(",") if h.strip()]
elif _web_domain:
    ALLOWED_HOSTS = [_web_domain, "127.0.0.1", "localhost"]
else:
    ALLOWED_HOSTS = ["*"]

# Security: Prevent Memory Exhaustion / Denial of Service via large uploads
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB

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
]
try:
    import whitenoise  # noqa: F401
    MIDDLEWARE.append("whitenoise.middleware.WhiteNoiseMiddleware")
except ImportError:
    pass

MIDDLEWARE.extend([
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "panel.middleware.TelegramEmbedMiddleware",
])

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

DB_TYPE = os.environ.get("DB_TYPE", "sqlite").strip().strip('\'"').lower()

if DB_TYPE == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "bananabot"),
            "USER": os.environ.get("DB_USER", "bananabot"),
            "PASSWORD": os.environ.get("DB_PASS", ""),
            "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("DB_PORT", "5432"),
            "OPTIONS": {
                "connect_timeout": 5,
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BOT_DB_PATH,
            "OPTIONS": {
                "timeout": 30,
            },
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
try:
    import whitenoise  # noqa: F401
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
except ImportError:
    pass

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 86400 * 7   # 7 days
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
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
