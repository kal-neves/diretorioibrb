from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.policies import require_manager
from accounts.services import confirm_submission, locked_accounts, recheck_submission_session
from common.phones import normalize_phone

from .models import Entry


EDITABLE_FIELDS = {"name", "category", "contact_phone", "email", "birth_day", "birth_month", "spouse_name"}


def save_entry(entry, changes, country):
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
    entry.save()


def locked_entry(entry_id):
    try:
        return Entry.objects.select_for_update().get(pk=entry_id)
    except Entry.DoesNotExist:
        raise ValidationError("A entrada não está mais disponível.", code="entry_unavailable") from None


def create_entry(*, operator_id, name, category, country=None, submission=None, **fields):
    with transaction.atomic(durable=True):
        operator, = locked_accounts(operator_id)
        require_manager(operator)
        confirm_submission(operator, submission, "directory.create")
        entry = Entry()
        save_entry(entry, {**fields, "name": name, "category": category}, country)
        recheck_submission_session(operator, submission)
    return entry


def update_entry(*, operator_id, entry_id, country=None, submission=None, **changes):
    with transaction.atomic(durable=True):
        operator, = locked_accounts(operator_id)
        require_manager(operator)
        entry = locked_entry(entry_id)
        confirm_submission(operator, submission, "directory.update", binding=str(entry_id))
        save_entry(entry, changes, country)
        recheck_submission_session(operator, submission)
    return entry


def delete_entry(*, operator_id, entry_id, submission=None):
    with transaction.atomic(durable=True):
        operator, = locked_accounts(operator_id)
        require_manager(operator)
        entry = locked_entry(entry_id)
        confirm_submission(operator, submission, "directory.delete", binding=str(entry_id))
        entry.delete()
        recheck_submission_session(operator, submission)
