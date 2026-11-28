import re
from urllib.parse import urlsplit

from .base import *  # noqa: F403


TRUST_VERCEL_PROXY = os.environ.get("VERCEL") == "1"
ALLOWED_HOSTS = [host.strip().lower() for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if host.strip()]
if TRUST_VERCEL_PROXY and DEPLOYMENT_ENV == "preview":
    ALLOWED_HOSTS.append(required("VERCEL_URL"))
_label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
if not ALLOWED_HOSTS or any(not re.fullmatch(rf"{_label}(?:\.{_label})*", host) for host in ALLOWED_HOSTS):
    raise ImproperlyConfigured("Informe nomes de host individuais em DJANGO_ALLOWED_HOSTS.")

if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5:
    raise ImproperlyConfigured("Gere uma chave aleatória para DJANGO_SECRET_KEY.")
if MAINTENANCE_ENABLED and (not CRON_SECRET or CRON_SECRET == SECRET_KEY):
    raise ImproperlyConfigured("Defina um CRON_SECRET próprio para a manutenção.")

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 86400
if TRUST_VERCEL_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

STATIC_URL = "/static/"
PHOTO_STORAGE_BACKEND = "supabase"
SUPABASE_URL = required("SUPABASE_URL")
_storage_url = urlsplit(SUPABASE_URL)
if (_storage_url.scheme != "https" or not _storage_url.hostname or _storage_url.username is not None
        or _storage_url.path not in {"", "/"} or _storage_url.query or _storage_url.fragment):
    raise ImproperlyConfigured("Informe a URL HTTPS do projeto Supabase em SUPABASE_URL.")
SUPABASE_STORAGE_KEY = required("SUPABASE_STORAGE_KEY")
SUPABASE_PHOTO_BUCKET = required("SUPABASE_PHOTO_BUCKET")
if DATABASES["default"]["OPTIONS"]["sslmode"] not in {"require", "verify-ca", "verify-full"}:
    raise ImproperlyConfigured("A conexão de produção com PostgreSQL exige TLS.")
