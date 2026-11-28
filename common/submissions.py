import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import FormSubmission


class SubmissionRejected(ValidationError):
    def __init__(self):
        super().__init__("Este formulário já foi enviado ou perdeu a validade. Confira a lista antes de tentar novamente.",
                         code="submission_rejected")


@dataclass(frozen=True)
class SubmissionProof:
    token: str = field(repr=False)
    session_key: str = field(repr=False)
    access_version: int
    authenticated_at: float


def digest(value, purpose):
    return salted_hmac(f"ibrb.submission.{purpose}", value, algorithm="sha256").hexdigest()


def issue_submission(*, session_key, authenticated_at, operation, binding=""):
    now = timezone.now()
    deadline = datetime.fromtimestamp(authenticated_at, tz=datetime_timezone.utc) + timedelta(hours=1)
    if not session_key or deadline <= now:
        raise SubmissionRejected()
    token = secrets.token_urlsafe(32)
    FormSubmission.objects.create(
        token_digest=digest(token, "token"),
        session_scope_digest=digest(f"{session_key}:{binding}", "scope"),
        operation=operation, created_at=now, expires_at=min(now + timedelta(hours=1), deadline),
    )
    return token


def validate_submission(proof, *, operation, binding=""):
    if not connection.in_atomic_block:
        raise RuntimeError("O formulário deve ser confirmado junto da operação.")
    if not proof.token or len(proof.token) > 100 or not proof.session_key:
        raise SubmissionRejected()
    submission = FormSubmission.objects.select_for_update().filter(token_digest=digest(proof.token, "token")).first()
    now = timezone.now()
    if (submission is None or submission.consumed_at is not None or submission.expires_at <= now
            or submission.operation != operation
            or not constant_time_compare(submission.session_scope_digest,
                                         digest(f"{proof.session_key}:{binding}", "scope"))):
        raise SubmissionRejected()
    return submission


def consume_submission(proof, *, operation, binding=""):
    submission = validate_submission(proof, operation=operation, binding=binding)
    submission.consumed_at = timezone.now()
    submission.save(update_fields=["consumed_at"])


def clear_expired_submissions():
    count, _ = FormSubmission.objects.filter(expires_at__lte=timezone.now()).delete()
    return count
