from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class AccountManager(BaseUserManager):
    def get_by_natural_key(self, identifier):
        if identifier == "adminseed":
            return self.get(seed_username=identifier)
        return self.get(login_phone=identifier)


class Account(AbstractBaseUser):
    class Role(models.TextChoices):
        CONSULTATION = "CONSULTATION", "Consulta"
        SECRETARIAT = "SECRETARIAT", "Secretaria"
        INITIAL_ADMIN = "INITIAL_ADMIN", "Administrador inicial"

    name = models.CharField("nome", max_length=200)
    login_phone = models.CharField("celular de login", max_length=16, unique=True, null=True, blank=True)
    seed_username = models.CharField(max_length=32, unique=True, null=True, blank=True, editable=False)
    role = models.CharField("perfil", max_length=20, choices=Role.choices, default=Role.CONSULTATION)
    is_active = models.BooleanField("ativa", default=True)
    must_change_password = models.BooleanField("troca de senha obrigatória", default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    first_password_changed_at = models.DateTimeField(null=True, blank=True, editable=False)
    access_version = models.PositiveBigIntegerField(default=1, editable=False)

    objects = AccountManager()
    USERNAME_FIELD = "login_phone"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        verbose_name = "conta de acesso"
        verbose_name_plural = "contas de acesso"
        constraints = [
            models.CheckConstraint(condition=Q(name__regex=r"\S"), name="account_name_not_blank"),
            models.CheckConstraint(
                condition=(
                    Q(role="INITIAL_ADMIN", seed_username="adminseed", seed_username__isnull=False,
                      login_phone__isnull=True, is_active=True)
                    | Q(role__in=["CONSULTATION", "SECRETARIAT"], seed_username__isnull=True,
                        login_phone__isnull=False, login_phone__regex=r"^\+[1-9][0-9]{1,14}$")
                ),
                name="account_identity_valid",
            ),
            models.CheckConstraint(condition=Q(access_version__gte=1), name="account_access_version_positive"),
            models.CheckConstraint(
                condition=Q(first_password_changed_at__isnull=True)
                | Q(first_password_changed_at__gte=F("created_at")),
                name="account_first_change_after_creation",
            ),
            models.CheckConstraint(
                condition=Q(role="INITIAL_ADMIN") | Q(first_password_changed_at__isnull=False)
                | Q(must_change_password=True),
                name="account_new_requires_password_change",
            ),
        ]
        indexes = [models.Index(
            fields=["created_at"], name="account_unused_created_idx",
            condition=Q(first_password_changed_at__isnull=True) & ~Q(role="INITIAL_ADMIN"),
        )]

    @property
    def is_staff(self):
        return self.role in {self.Role.SECRETARIAT, self.Role.INITIAL_ADMIN}

    def get_username(self):
        return self.seed_username or self.login_phone

    def __str__(self):
        return self.name
