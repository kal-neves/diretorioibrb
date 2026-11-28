import secrets
from datetime import timedelta

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from common.phones import normalize_phone

from .models import Account
from .policies import is_expired_new_account, require_assign_role, require_manage_target


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


def locked_accounts(*account_ids):
    accounts = {account.pk: account for account in Account.objects.select_for_update()
                .filter(pk__in=account_ids).order_by("pk")}
    if len(accounts) != len(set(account_ids)):
        raise ValidationError("A conta não está mais disponível.", code="account_unavailable")
    return [accounts[account_id] for account_id in account_ids]


def save_account(account):
    account.name = account.name.strip()
    account.full_clean(validate_unique=False)
    account.save()


def duplicate_phone_error(error):
    if getattr(error.__cause__, "diag", None) and error.__cause__.diag.constraint_name == "accounts_account_login_phone_key":
        raise ValidationError({"login_phone": "Este celular já identifica uma conta."}) from None
    raise error


@sensitive_variables("password")
def create_account(*, operator_id, name, phone, country=None, role=Account.Role.CONSULTATION):
    normalized_phone = normalize_phone(phone, country, mobile_only=True)
    password = secrets.token_urlsafe(24)
    account = Account(name=name, login_phone=normalized_phone, role=role)
    account.set_password(password)
    try:
        with transaction.atomic(durable=True):
            operator, = locked_accounts(operator_id)
            require_assign_role(operator, role)
            save_account(account)
    except IntegrityError as error:
        duplicate_phone_error(error)
    return account, password


def update_account(*, operator_id, account_id, name=None, phone=None, country=None,
                   role=None, is_active=None):
    normalized_phone = normalize_phone(phone, country, mobile_only=True) if phone is not None else None
    try:
        with transaction.atomic(durable=True):
            operator, account = locked_accounts(operator_id, account_id)
            require_manage_target(operator, account)
            revoke = False
            if name is not None:
                account.name = name
            if normalized_phone is not None and normalized_phone != account.login_phone:
                account.login_phone = normalized_phone
                revoke = True
            if role is not None:
                if operator.role != Account.Role.INITIAL_ADMIN:
                    raise PermissionDenied("Somente o administrador inicial pode alterar perfis.")
                require_assign_role(operator, role)
                revoke = revoke or role != account.role
                account.role = role
            if is_active is not None:
                if not isinstance(is_active, bool):
                    raise ValidationError({"is_active": "Informe uma situação válida."})
                revoke = revoke or is_active != account.is_active
                account.is_active = is_active
            if revoke:
                account.access_version += 1
            save_account(account)
    except IntegrityError as error:
        duplicate_phone_error(error)
    return account


def delete_account(*, operator_id, account_id):
    with transaction.atomic(durable=True):
        operator, account = locked_accounts(operator_id, account_id)
        require_manage_target(operator, account)
        account.delete()


@sensitive_variables("password")
def restore_password(*, operator_id, account_id):
    with transaction.atomic(durable=True):
        operator, account = locked_accounts(operator_id, account_id)
        require_manage_target(operator, account)
        if account.first_password_changed_at is None:
            raise ValidationError("Contas novas não podem receber outra senha temporária.", code="first_change_pending")
        password = secrets.token_urlsafe(24)
        account.set_password(password)
        account.must_change_password = True
        account.access_version += 1
        save_account(account)
    return password


@sensitive_variables("current_password", "new_password", "confirmation")
def change_password(*, account_id, current_password, new_password, confirmation):
    with transaction.atomic(durable=True):
        account, = locked_accounts(account_id)
        if not account.is_active or is_expired_new_account(account):
            raise PermissionDenied("Esta conta não tem acesso permitido.")
        if not account.check_password(current_password):
            raise ValidationError({"current_password": "Senha atual inválida."})
        if new_password != confirmation:
            raise ValidationError({"confirmation": "As senhas não coincidem."})
        validate_password(new_password, account)
        account.set_password(new_password)
        account.must_change_password = False
        if account.first_password_changed_at is None:
            account.first_password_changed_at = timezone.now()
        account.access_version += 1
        save_account(account)
    return account


def delete_expired_new_accounts(*, batch_size=100):
    if not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("O tamanho do lote deve ser positivo.")
    deleted = 0
    while True:
        with transaction.atomic(durable=True):
            cutoff = timezone.now() - timedelta(days=7)
            accounts = list(Account.objects.select_for_update(skip_locked=True)
                            .filter(first_password_changed_at__isnull=True, created_at__lte=cutoff)
                            .exclude(role=Account.Role.INITIAL_ADMIN).order_by("pk")[:batch_size])
            if not accounts:
                return deleted
            for account in accounts:
                if is_expired_new_account(account):
                    account.delete()
                    deleted += 1
