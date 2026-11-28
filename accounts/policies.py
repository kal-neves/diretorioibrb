from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from .models import Account


def is_expired_new_account(account, *, now=None):
    return (
        account.role != Account.Role.INITIAL_ADMIN
        and account.first_password_changed_at is None
        and account.created_at <= (now or timezone.now()) - timedelta(days=7)
    )


def require_manager(operator):
    if (not operator.is_active or operator.must_change_password
            or is_expired_new_account(operator) or not operator.is_staff):
        raise PermissionDenied("Esta conta não pode realizar operações administrativas.")


def require_manage_target(operator, target):
    require_manager(operator)
    if target.role == Account.Role.INITIAL_ADMIN:
        raise PermissionDenied("Esta operação não é permitida para o administrador inicial.")
    if operator.role == Account.Role.SECRETARIAT and target.role != Account.Role.CONSULTATION:
        raise PermissionDenied("A secretaria pode gerenciar somente contas de consulta.")


def require_assign_role(operator, role):
    require_manager(operator)
    if role not in {Account.Role.CONSULTATION, Account.Role.SECRETARIAT}:
        raise PermissionDenied("Perfil de conta inválido.")
    if role == Account.Role.SECRETARIAT and operator.role != Account.Role.INITIAL_ADMIN:
        raise PermissionDenied("Somente o administrador inicial pode conceder esse perfil.")
