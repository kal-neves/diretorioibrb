from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Entry, Photo
from .storage import StorageUnavailable, photo_storage


def reserve_photo(data, width, height):
    return Photo.objects.create(lease_until=timezone.now() + timedelta(hours=1),
                                byte_size=len(data), width=width, height=height)


def attach_photo(entry, staged=None, remove=False):
    ids = [pk for pk in (entry.photo_id, staged.pk if staged else None) if pk]
    photos = {row.pk: row for row in Photo.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    if staged:
        new = photos.get(staged.pk)
        if new is None or new.state != Photo.State.STAGED or new.lease_until <= timezone.now():
            raise ValidationError({"photo": "O processamento da foto expirou. Selecione a imagem novamente."})
        new.state = Photo.State.ATTACHED
        new.lease_until = None
        new.save(update_fields=["state", "lease_until"])
    if (staged or remove) and entry.photo_id:
        old = photos[entry.photo_id]
        old.state = Photo.State.PENDING_DELETE
        old.next_attempt_at = timezone.now()
        old.save(update_fields=["state", "next_attempt_at"])
    if staged or remove:
        entry.photo_id = staged.pk if staged else None


def cleanup_photos(*, limit=100):
    removed = 0
    storage = photo_storage()
    for _ in range(limit):
        now = timezone.now()
        with transaction.atomic():
            candidate = (Photo.objects.select_for_update(skip_locked=True, of=("self",))
                         .filter(Q(state=Photo.State.STAGED, lease_until__lte=now)
                                 | Q(state=Photo.State.PENDING_DELETE))
                         .filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now))
                         .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
                         .exclude(entry__isnull=False).order_by("created_at").first())
            if candidate is None:
                break
            candidate.state = Photo.State.PENDING_DELETE
            candidate.lease_until = now + timedelta(minutes=10)
            candidate.attempt_count += 1
            candidate.save(update_fields=["state", "lease_until", "attempt_count"])
        try:
            storage.delete(candidate.object_key)
        except StorageUnavailable:
            Photo.objects.filter(pk=candidate.pk, lease_until=candidate.lease_until).update(
                lease_until=None, next_attempt_at=timezone.now() + timedelta(minutes=min(1440, 2 ** min(candidate.attempt_count, 11))),
                last_error_code="storage_unavailable")
        else:
            with transaction.atomic():
                row = Photo.objects.select_for_update().filter(pk=candidate.pk, lease_until=candidate.lease_until).first()
                if row and not Entry.objects.filter(photo=row).exists():
                    row.delete()
                    removed += 1
    return removed
