from django.core.exceptions import PermissionDenied
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import Account


@receiver(pre_delete, sender=Account)
def protect_initial_admin(sender, instance, **kwargs):
    if instance.role == Account.Role.INITIAL_ADMIN:
        raise PermissionDenied("O administrador inicial não pode ser excluído.")
