import math
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.contrib.auth import login, logout, update_session_auth_hash
from django.utils import timezone

from .policies import is_expired_new_account


AUTHENTICATED_AT = "authenticated_at"
ACCESS_VERSION = "access_version"


def start_session(request, account):
    login(request, account, backend="accounts.backends.PhoneBackend")
    started_at = timezone.now()
    request.session[AUTHENTICATED_AT] = started_at.timestamp()
    request.session[ACCESS_VERSION] = account.access_version
    request.session.set_expiry(started_at + timedelta(hours=1))


def session_is_current(request):
    return account_session_is_current(
        request.user, request.session.get(ACCESS_VERSION), request.session.get(AUTHENTICATED_AT),
    )


def account_session_is_current(account, access_version, started_at):
    if not account.is_authenticated:
        return False
    if type(started_at) not in (float, int) or not math.isfinite(started_at):
        return False
    elapsed = timezone.now().timestamp() - started_at
    return (
        0 <= elapsed < 3600
        and account.is_active
        and access_version == account.access_version
        and not is_expired_new_account(account)
    )


def refresh_after_password_change(request, account):
    started_at = request.session[AUTHENTICATED_AT]
    deadline = datetime.fromtimestamp(started_at, tz=datetime_timezone.utc) + timedelta(hours=1)
    if deadline <= timezone.now():
        logout(request)
        return False
    update_session_auth_hash(request, account)
    request.user = account
    request.session[ACCESS_VERSION] = account.access_version
    request.session[AUTHENTICATED_AT] = started_at
    request.session.set_expiry(deadline)
    return True
