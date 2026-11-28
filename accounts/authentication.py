import ipaddress
import math
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.debug import sensitive_variables

from common.phones import normalize_phone

from .models import Account, LoginCounter
from .policies import is_expired_new_account


WINDOW = timedelta(minutes=15)
INVALID_CREDENTIALS = "Celular ou usuário e senha não conferem."


class LoginRejected(Exception):
    def __init__(self, message=INVALID_CREDENTIALS, *, retry_after=None):
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)


def client_ip(request):
    source = "HTTP_X_VERCEL_FORWARDED_FOR" if settings.TRUST_VERCEL_PROXY else "REMOTE_ADDR"
    try:
        address = ipaddress.ip_address(request.META.get(source, ""))
    except ValueError:
        raise LoginRejected("Não foi possível identificar a conexão. Tente novamente.") from None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return str(address)


def locked_counter(scope, value):
    digest = salted_hmac(f"ibrb.login.{scope}", value, algorithm="sha256").hexdigest()
    now = timezone.now()
    counter, _ = LoginCounter.objects.select_for_update().get_or_create(
        scope=scope, key_digest=digest,
        defaults={"window_started_at": now, "expires_at": now + WINDOW},
    )
    now = timezone.now()
    if counter.expires_at <= now:
        counter.window_started_at = now
        counter.expires_at = now + WINDOW
        counter.count = 0
        counter.save(update_fields=["window_started_at", "expires_at", "count"])
    return counter


def blocked(counter):
    seconds = max(1, math.ceil((counter.expires_at - timezone.now()).total_seconds()))
    return LoginRejected(f"Tente novamente em {math.ceil(seconds / 60)} minuto(s).", retry_after=seconds)


@sensitive_variables("password")
def authenticate_attempt(*, identifier, password, country, ip):
    identifier = identifier.strip()[:254]
    invalid_phone = None
    if identifier != "adminseed":
        try:
            identifier = normalize_phone(identifier, country, mobile_only=True)
        except ValidationError as error:
            invalid_phone = error.messages[0]
    account = None
    rejection = None
    with transaction.atomic():
        ip_counter = locked_counter(LoginCounter.Scope.IP, ip)
        if ip_counter.count >= 30:
            rejection = blocked(ip_counter)
        else:
            ip_counter.count += 1
            ip_counter.save(update_fields=["count"])
            pair_counter = locked_counter(LoginCounter.Scope.IDENTIFIER_IP, f"{ip}|{identifier}")
            if pair_counter.count >= 5:
                rejection = blocked(pair_counter)
            else:
                if not invalid_phone:
                    query = {"seed_username": identifier} if identifier == "adminseed" else {"login_phone": identifier}
                    account = Account.objects.select_for_update().filter(**query).first()
                if account is None:
                    make_password(password)
                    rejection = LoginRejected(invalid_phone or INVALID_CREDENTIALS)
                elif not check_password(password, account.password):
                    rejection = LoginRejected()
                elif not account.is_active:
                    rejection = LoginRejected("Esta conta está desativada. Procure a secretaria.")
                elif is_expired_new_account(account):
                    rejection = LoginRejected("O prazo desta conta terminou. Procure a secretaria.")
                if rejection:
                    pair_counter.count += 1
                    pair_counter.save(update_fields=["count"])
    if rejection:
        raise rejection
    return account


def clear_expired_login_counters():
    count, _ = LoginCounter.objects.filter(expires_at__lte=timezone.now()).delete()
    return count
