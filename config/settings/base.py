import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


def required(name):
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(f"Defina a variável de ambiente {name}.")
    return value


BASE_DIR = Path(__file__).resolve().parents[2]
SECRET_KEY = required("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = []
INSTALLED_APPS = [
    "django.contrib.admin.apps.SimpleAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts.apps.AccountsConfig",
    "common.apps.CommonConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "accounts.middleware.PrivateSessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.AccessMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": required("DB_NAME"),
    "USER": required("DB_USER"),
    "PASSWORD": required("DB_PASSWORD"),
    "HOST": required("DB_HOST"),
    "PORT": os.environ.get("DB_PORT", "5432"),
    "CONN_MAX_AGE": 0,
    "DISABLE_SERVER_SIDE_CURSORS": True,
    "OPTIONS": {"sslmode": os.environ.get("DB_SSLMODE", "require"), "prepare_threshold": None},
}}
AUTH_USER_MODEL = "accounts.Account"
AUTHENTICATION_BACKENDS = ["accounts.backends.PhoneBackend"]
AUTH_PASSWORD_VALIDATORS = [{"NAME": "accounts.validators.PasswordPolicy"}]
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Belem"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 3600
SESSION_SAVE_EVERY_REQUEST = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
