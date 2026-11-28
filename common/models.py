from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class FormSubmission(models.Model):
    token_digest = models.CharField(max_length=64, unique=True)
    session_scope_digest = models.CharField(max_length=64)
    operation = models.CharField(max_length=40)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(expires_at__gt=F("created_at")), name="submission_valid_window"),
            models.CheckConstraint(condition=Q(consumed_at__isnull=True) | Q(consumed_at__gte=F("created_at")),
                                   name="submission_consumed_after_creation"),
        ]
