import secrets

from django.db import IntegrityError, transaction
from django.views.decorators.debug import sensitive_variables

from .models import Account


@sensitive_variables("password")
def seed_initial_admin():
    if Account.objects.filter(seed_username="adminseed").exists():
        return None
    password = secrets.token_urlsafe(24)
    account = Account(
        name="adminseed", seed_username="adminseed", role=Account.Role.INITIAL_ADMIN,
        must_change_password=False,
    )
    account.set_password(password)
    try:
        with transaction.atomic(durable=True):
            account.save(force_insert=True)
    except IntegrityError:
        if Account.objects.filter(seed_username="adminseed").exists():
            return None
        raise
    return password
