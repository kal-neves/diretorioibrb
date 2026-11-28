from datetime import date

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .normalization import normalize_name


class Entry(models.Model):
    class Category(models.TextChoices):
        MEMBER = "MEMBER", "Membro"
        PASTOR = "PASTOR", "Pastor"
        DEACON = "DEACON", "Diácono"

    name = models.CharField("nome", max_length=200)
    search_name = models.CharField(max_length=600, editable=False)
    category = models.CharField("categoria", max_length=6, choices=Category.choices)
    contact_phone = models.CharField("contato", max_length=16, blank=True, null=True)
    email = models.EmailField("e-mail", max_length=254, blank=True, null=True)
    birth_day = models.PositiveSmallIntegerField("dia", blank=True, null=True)
    birth_month = models.PositiveSmallIntegerField("mês", blank=True, null=True)
    spouse_name = models.CharField("cônjuge", max_length=200, blank=True, null=True)

    class Meta:
        verbose_name = "entrada do diretório"
        verbose_name_plural = "entradas do diretório"
        indexes = [models.Index(fields=["birth_month", "birth_day"], name="directory_birthday_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(name__regex=r"\S"), name="directory_name_present"),
            models.CheckConstraint(condition=Q(search_name__regex=r"\S"), name="directory_search_present"),
            models.CheckConstraint(condition=Q(category__in=["MEMBER", "PASTOR", "DEACON"]),
                                   name="directory_category_valid"),
            models.CheckConstraint(condition=Q(contact_phone__isnull=True) | Q(contact_phone__regex=r"^\+[1-9][0-9]{1,14}$"),
                                   name="directory_phone_format"),
            models.CheckConstraint(condition=(
                Q(birth_day__isnull=True, birth_month__isnull=True)
                | (Q(birth_day__isnull=False, birth_month__isnull=False, birth_day__gte=1)
                   & (Q(birth_month__in=[1, 3, 5, 7, 8, 10, 12], birth_day__lte=31)
                      | Q(birth_month__in=[4, 6, 9, 11], birth_day__lte=30)
                      | Q(birth_month=2, birth_day__lte=29)))
            ), name="directory_birthday_valid"),
        ]

    def clean(self):
        super().clean()
        self.name = (self.name or "").strip()
        self.search_name = normalize_name(self.name)
        for field in ("contact_phone", "email", "spouse_name"):
            value = getattr(self, field)
            setattr(self, field, value.strip() or None if value is not None else None)
        if not self.name or not self.search_name:
            raise ValidationError({"name": "Informe o nome."})
        if self.birth_day is not None or self.birth_month is not None:
            try:
                date(2000, self.birth_month, self.birth_day)
            except (TypeError, ValueError):
                raise ValidationError({"birth_day": "Informe dia e mês válidos."}) from None

    def save(self, *args, **kwargs):
        self.search_name = normalize_name(self.name)
        if kwargs.get("update_fields") is not None and "name" in kwargs["update_fields"]:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"search_name"}
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name
