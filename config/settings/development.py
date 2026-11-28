from .base import *  # noqa: F403

if os.environ.get("VERCEL_ENV") in {"production", "preview"}:
    raise ImproperlyConfigured("Use config.settings.production nas publicações da Vercel.")

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
PHOTO_STORAGE_BACKEND = os.environ.get("PHOTO_STORAGE_BACKEND", "local")
PHOTO_STORAGE_ROOT = Path(os.environ.get("PHOTO_STORAGE_ROOT", BASE_DIR / ".private-photos"))
