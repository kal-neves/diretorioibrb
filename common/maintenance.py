from datetime import timedelta
from time import monotonic
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.contrib.sessions.models import Session
from django.db import DatabaseError, transaction
from django.utils import timezone

from accounts.models import Account, LoginCounter
from accounts.services import delete_expired_new_accounts
from directory.models import Photo
from directory.photos import cleanup_photos, due_photos
from directory.storage import StorageUnavailable

from .models import FormSubmission, RoutineState


def acquire(*, force=False):
    with transaction.atomic(durable=True):
        RoutineState.objects.get_or_create(key="daily")
        state = RoutineState.objects.select_for_update().get(pk="daily")
        now = timezone.now()
        today = timezone.localtime(now, ZoneInfo("America/Belem")).replace(hour=0, minute=0, second=0, microsecond=0)
        if state.lease_until and state.lease_until > now:
            return None, "running"
        if not force and state.status == "succeeded" and state.last_succeeded_at and state.last_succeeded_at >= today:
            return None, "already_done"
        state.run_token = uuid4()
        state.lease_until = now + timedelta(minutes=15)
        state.last_started_at = now
        state.status = "running"
        state.counts = {}
        state.last_error_code = ""
        state.save()
        return state.run_token, "running"


def record(token, counts, *, status="running", error=""):
    values = {"counts": counts, "status": status, "last_error_code": error}
    if status != "running":
        values.update(lease_until=None, run_token=None)
    if status == "succeeded":
        values["last_succeeded_at"] = timezone.now()
    return RoutineState.objects.filter(pk="daily", run_token=token, lease_until__gt=timezone.now()).update(**values) == 1


def prune(queryset):
    with transaction.atomic(durable=True):
        ids = list(queryset.select_for_update(skip_locked=True).order_by("pk").values_list("pk", flat=True)[:100])
        if not ids:
            return 0
        return queryset.filter(pk__in=ids).delete()[0]


def run_daily(*, force=False, budget_seconds=45):
    token, status = acquire(force=force)
    if token is None:
        return status
    deadline = monotonic() + budget_seconds
    counts = {}
    now = timezone.now()
    expired_accounts = Account.objects.filter(first_password_changed_at__isnull=True, created_at__lte=now - timedelta(days=7)).exclude(role=Account.Role.INITIAL_ADMIN)
    steps = [
        ("accounts", expired_accounts, lambda: delete_expired_new_accounts(max_batches=1)),
        ("sessions", Session.objects.filter(expire_date__lte=now), None),
        ("login_counters", LoginCounter.objects.filter(expires_at__lte=now), None),
        ("submissions", FormSubmission.objects.filter(expires_at__lte=now), None),
    ]
    try:
        incomplete = False
        for name, queryset, operation in steps:
            counts[name] = 0
            while queryset.exists() and monotonic() < deadline:
                if not record(token, counts):
                    return "lease_lost"
                count = operation() if operation else prune(queryset)
                counts[name] += count
                if not count:
                    break
            incomplete = queryset.exists() or incomplete
            if not record(token, counts):
                return "lease_lost"
        counts["photos"] = 0
        while due_photos().exists() and monotonic() < deadline:
            if not record(token, counts):
                return "lease_lost"
            removed = cleanup_photos(limit=1)
            counts["photos"] += removed
            if not record(token, counts):
                return "lease_lost"
            if not removed:
                break
        incomplete = incomplete or due_photos().exists()
        retry_pending = Photo.objects.filter(state="PENDING_DELETE").exclude(last_error_code="").exists()
        status = "partial" if incomplete or retry_pending else "succeeded"
        error = "photo_retry_pending" if retry_pending else "work_remaining" if incomplete else ""
        return status if record(token, counts, status=status, error=error) else "lease_lost"
    except (DatabaseError, StorageUnavailable) as error:
        code = "storage_unavailable" if isinstance(error, StorageUnavailable) else "database_unavailable"
        try:
            record(token, counts, status="failed", error=code)
        except DatabaseError:
            pass
        return "failed"
