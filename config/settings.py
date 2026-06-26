import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


# ============================================================
# SECURITY
# ============================================================

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "CHANGE-THIS-TO-A-LONG-RANDOM-SECRET-KEY",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() == "true"

ALLOWED_HOSTS = [
    "5.223.90.183",
    "localhost",
    "127.0.0.1",
]

CSRF_TRUSTED_ORIGINS = [
    "http://5.223.90.183:8010",
]

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"


# ============================================================
# APPLICATIONS
# ============================================================

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Project apps
    "core",
    "users",
    "inventory",
    "customers",
    "pos",
    "delivery",
    "purchases",
    "services",
    "pets",
    "staffs",
]


# ============================================================
# MIDDLEWARE
# ============================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# ============================================================
# URL / WSGI
# ============================================================

ROOT_URLCONF = "config.urls"

WSGI_APPLICATION = "config.wsgi.application"


# ============================================================
# TEMPLATES
# ============================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# ============================================================
# DATABASE
# ============================================================

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# ============================================================
# PASSWORD VALIDATION
# ============================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# ============================================================
# LANGUAGE / TIME
# ============================================================

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Phnom_Penh"
USE_I18N = True
USE_TZ = True


# ============================================================
# STATIC / MEDIA
# ============================================================

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ============================================================
# LOGIN / LOGOUT
# ============================================================

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"


# ============================================================
# DEFAULT FIELD
# ============================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ============================================================
# ABA PAYWAY SETTINGS
# ============================================================
# For local test:
# - PayWay callback cannot call 127.0.0.1
# - Use your public server URL or ngrok/cloudflare tunnel
#
# Fill these after ABA gives you real/sandbox credentials.

PAYWAY_SANDBOX = os.environ.get("PAYWAY_SANDBOX", "True") == "True"

PAYWAY_MERCHANT_ID = os.environ.get("PAYWAY_MERCHANT_ID", "")
PAYWAY_API_KEY = os.environ.get("PAYWAY_API_KEY", "")

PAYWAY_CALLBACK_URL = os.environ.get(
    "PAYWAY_CALLBACK_URL",
    "http://5.223.90.183:8000/pos/aba-callback/",
)

PAYWAY_SANDBOX_QR_URL = os.environ.get(
    "PAYWAY_SANDBOX_QR_URL",
    "https://checkout-sandbox.payway.com.kh/api/payment-gateway/v1/payments/generate-qr",
)

PAYWAY_SANDBOX_CHECK_URL = os.environ.get(
    "PAYWAY_SANDBOX_CHECK_URL",
    "https://checkout-sandbox.payway.com.kh/api/payment-gateway/v1/payments/check-transaction-2",
)

PAYWAY_QR_URL = os.environ.get(
    "PAYWAY_QR_URL",
    "https://checkout.payway.com.kh/api/payment-gateway/v1/payments/generate-qr",
)

PAYWAY_CHECK_URL = os.environ.get(
    "PAYWAY_CHECK_URL",
    "https://checkout.payway.com.kh/api/payment-gateway/v1/payments/check-transaction-2",
)


# ============================================================
# Telegram Bot Alert
# Used for BUBU pet sale / preorder notification
# ============================================================

TELEGRAM_BOT_TOKEN = "8846065896:AAEudLU50XNCzAnCp0DzOtLAq3Gl4F5yfqQ"

TELEGRAM_CHAT_ID = "-1003776345220"

TELEGRAM_PET_INSTOCK_TOPIC_ID = "12"
TELEGRAM_PET_PREORDER_TOPIC_ID = "5"
TELEGRAM_PET_COMPLETE_TOPIC_ID = "17"

STAFF_TELEGRAM_BOT_TOKEN = "8972975243:AAE1kxnmGbgUBdhNiUJ9b-CSmpeXDKrNZRU"
STAFF_TELEGRAM_CHAT_ID = "-5069294554"