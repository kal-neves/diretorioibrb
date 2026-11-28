from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.policies import require_manager
from accounts.services import confirm_submission, locked_accounts, recheck_submission_session
from common.phones import normalize_phone
from common.submissions import validate_submission

from .models import Entry
from .images import process_photo
from .photos import attach_photo, reserve_photo
from .storage import photo_storage


EDITABLE_FIELDS = {"name", "category", "contact_phone", "email", "birth_day", "birth_month", "spouse_name"}


def validate_entry(entry, changes, country):
    if changes.keys() - EDITABLE_FIELDS:
        raise ValidationError("Há campos que não podem ser alterados.")
    for field, value in changes.items():
        if field in {"name", "contact_phone", "email", "spouse_name"} and isinstance(value, str):
            value = value.strip()
            if field != "name":
                value = value or None
        if field == "contact_phone":
            value = normalize_phone(value, country) if value and value.strip() else None
        if field in {"birth_day", "birth_month"} and value == "":
            value = None
        setattr(entry, field, value)
    entry.full_clean(exclude=["search_name"])


def locked_entry(entry_id):
    try:
        return Entry.objects.select_for_update().get(pk=entry_id)
    except Entry.DoesNotExist:
        raise ValidationError("A entrada não está mais disponível.", code="entry_unavailable") from None


def prepare_photo(operator_id, entry_id, submission, upload, changes, country):
    if upload is None:
        return None
    with transaction.atomic(durable=True):
        operator, = locked_accounts(operator_id)
        require_manager(operator)
        recheck_submission_session(operator, submission)
        entry = locked_entry(entry_id) if entry_id else Entry()
        if submission:
            validate_submission(submission, operation="directory.update" if entry_id else "directory.create",
                                binding=str(entry_id) if entry_id else "")
        validate_entry(entry, changes, country)
    data, width, height = process_photo(upload)
    with transaction.atomic(durable=True):
        staged = reserve_photo(data, width, height)
    photo_storage().put(staged.object_key, data)
    return staged


def create_entry(*, operator_id, name, category, country=None, submission=None, photo=None, remove_photo=False, **fields):
    if photo is not None and remove_photo:
        raise ValidationError({"photo": "Escolha substituir ou remover a foto."})
    fields = {**fields, "name": name, "category": category}
    staged = prepare_photo(operator_id, None, submission, photo, fields, country)
    with transaction.atomic(durable=True):
        operator, = locked_accounts(operator_id)
        require_manager(operator)
        confirm_submission(operator, submission, "directory.create")
        entry = Entry()
        validate_entry(entry, fields, country)
        attach_photo(entry, staged)
        entry.save()
        recheck_submission_session(operator, submission)
    return entry


def update_entry(*, operator_id, entry_id, country=None, submission=None, photo=None, remove_photo=False, **changes):
    if photo is not None and remove_photo:
        raise ValidationError({"photo": "Escolha substituir ou remover a foto."})
    staged = prepare_photo(operator_id, entry_id, submission, photo, changes, country)
    with transaction.atomic(durable=True):
        operator, = locked_accounts(operator_id)
        require_manager(operator)
        entry = locked_entry(entry_id)
        confirm_submission(operator, submission, "directory.update", binding=str(entry_id))
        validate_entry(entry, changes, country)
        attach_photo(entry, staged, remove_photo)
        entry.save()
        recheck_submission_session(operator, submission)
    return entry


def delete_entry(*, operator_id, entry_id, submission=None):
    with transaction.atomic(durable=True):
        operator, = locked_accounts(operator_id)
        require_manager(operator)
        entry = locked_entry(entry_id)
        confirm_submission(operator, submission, "directory.delete", binding=str(entry_id))
        attach_photo(entry, remove=True)
        entry.delete()
        recheck_submission_session(operator, submission)
