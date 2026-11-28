from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from accounts.models import Account
from accounts.services import seed_initial_admin
from accounts.tests.test_services import FAST_HASHERS, example_mobile
from common.models import FormSubmission
from common.submissions import SubmissionProof, SubmissionRejected, issue_submission
from directory.models import Entry
from directory.services import create_entry, delete_entry, update_entry


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class DirectoryServiceTests(TestCase):
    def setUp(self):
        seed_initial_admin()
        self.operator = Account.objects.get()

    def create(self, **fields):
        return create_entry(operator_id=self.operator.pk,
                            **{"name": "José", "category": Entry.Category.MEMBER, **fields})

    def proof(self, operation="directory.create", binding=""):
        started = timezone.now().timestamp()
        token = issue_submission(session_key="directory-session", authenticated_at=started,
                                 operation=operation, binding=binding)
        return SubmissionProof(token, "directory-session", self.operator.access_version, started)

    def test_minimal_entry_and_no_relationships(self):
        entry = self.create(name=" José ")
        self.assertEqual(entry.name, "José")
        self.assertEqual(entry.search_name, "jose")
        self.assertIsNone(entry.contact_phone)
        self.assertIsNone(entry.birth_month)
        self.assertFalse(any(field.is_relation for field in Entry._meta.get_fields()))
        self.assertEqual(Account.objects.count(), 1)

    def test_optional_values_normalize_and_can_be_cleared(self):
        phone = example_mobile("BR")
        entry = self.create(contact_phone=phone, email=" pessoa@example.org ", spouse_name=" Ana ",
                            birth_day="29", birth_month="2")
        self.assertEqual(entry.email, "pessoa@example.org")
        self.assertEqual(entry.spouse_name, "Ana")
        entry = update_entry(operator_id=self.operator.pk, entry_id=entry.pk, contact_phone=" ",
                             email="", spouse_name=None, birth_day="", birth_month="", name="Ágata")
        entry.refresh_from_db()
        self.assertEqual(entry.search_name, "agata")
        for field in ("contact_phone", "email", "spouse_name", "birth_day", "birth_month"):
            self.assertIsNone(getattr(entry, field))

    def test_invalid_fields_and_birthdays(self):
        for fields in ({"name": " "}, {"category": "ALL"}, {"birth_day": 2}, {"birth_month": 2},
                       {"birth_day": 30, "birth_month": 2}, {"birth_day": 31, "birth_month": 4},
                       {"birth_day": 0, "birth_month": 1}, {"birth_day": 1, "birth_month": 13},
                       {"email": "inválido"}, {"contact_phone": "123"}, {"account_id": self.operator.pk}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.create(**fields)
        self.assertEqual(Entry.objects.count(), 0)

    def test_database_rejects_invalid_dates_category_and_name(self):
        entry = self.create()
        for fields in ({"birth_day": 1}, {"birth_month": 1}, {"birth_day": 30, "birth_month": 2},
                       {"birth_day": 31, "birth_month": 4}, {"category": "OTHER"}, {"name": " "}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                Entry.objects.filter(pk=entry.pk).update(**fields)

    def test_duplicate_contacts_are_independent_of_accounts(self):
        phone = example_mobile("BR")
        account = Account.objects.create(name="José", login_phone=phone, role=Account.Role.CONSULTATION)
        before = Account.objects.values().get(pk=account.pk)
        first = self.create(contact_phone=phone, email="same@example.org")
        second = self.create(contact_phone=phone, email="same@example.org")
        update_entry(operator_id=self.operator.pk, entry_id=first.pk, name="Outro")
        delete_entry(operator_id=self.operator.pk, entry_id=first.pk)
        self.assertEqual(Account.objects.values().get(pk=account.pk), before)
        account.delete()
        self.assertTrue(Entry.objects.filter(pk=second.pk).exists())

    def test_secretariat_can_manage_entries_but_consultation_and_pending_cannot(self):
        now = timezone.now()
        operator = Account.objects.create(name="Secretaria", login_phone=example_mobile("BR"),
                                          role=Account.Role.SECRETARIAT, must_change_password=False,
                                          created_at=now, first_password_changed_at=now)
        entry = create_entry(operator_id=operator.pk, name="Pessoa", category=Entry.Category.PASTOR)
        update_entry(operator_id=operator.pk, entry_id=entry.pk, name="Outra")
        for changes in ({"role": Account.Role.CONSULTATION}, {"must_change_password": True}, {"is_active": False}):
            Account.objects.filter(pk=operator.pk).update(**changes)
            with self.assertRaises(PermissionDenied):
                delete_entry(operator_id=operator.pk, entry_id=entry.pk)
            Account.objects.filter(pk=operator.pk).update(role=Account.Role.SECRETARIAT,
                                                          must_change_password=False, is_active=True)
        delete_entry(operator_id=operator.pk, entry_id=entry.pk)
        self.assertFalse(Entry.objects.filter(pk=entry.pk).exists())

    def test_submission_rollback_replay_and_session_revocation(self):
        proof = self.proof()
        with self.assertRaises(ValidationError):
            self.create(name="", submission=proof)
        self.assertIsNone(FormSubmission.objects.get().consumed_at)
        self.create(submission=proof)
        with self.assertRaises(SubmissionRejected):
            self.create(name="Outra", submission=proof)
        proof = self.proof()
        with self.assertRaises(PermissionDenied):
            self.create(submission=replace(proof, access_version=0))
        self.assertEqual(Entry.objects.count(), 1)

    def test_submission_binding_and_operation(self):
        entry = self.create()
        proof = self.proof("directory.update", str(entry.pk))
        with self.assertRaises(SubmissionRejected):
            delete_entry(operator_id=self.operator.pk, entry_id=entry.pk, submission=proof)
        other = self.create()
        with self.assertRaises(SubmissionRejected):
            update_entry(operator_id=self.operator.pk, entry_id=other.pk, name="Outra", submission=proof)
        update_entry(operator_id=self.operator.pk, entry_id=entry.pk, name="Outra", submission=proof)
        with self.assertRaises(SubmissionRejected):
            update_entry(operator_id=self.operator.pk, entry_id=entry.pk, name="Outra vez", submission=proof)

    def test_delete_consumes_proof_and_missing_target_has_no_effect(self):
        entry = self.create()
        entry_id = entry.pk
        proof = self.proof("directory.delete", str(entry_id))
        delete_entry(operator_id=self.operator.pk, entry_id=entry_id, submission=proof)
        self.assertIsNotNone(FormSubmission.objects.get().consumed_at)
        with self.assertRaises(ValidationError) as error:
            delete_entry(operator_id=self.operator.pk, entry_id=entry_id, submission=proof)
        self.assertEqual(error.exception.code, "entry_unavailable")
        self.assertEqual(Account.objects.count(), 1)

    def test_fixed_and_international_contacts(self):
        import phonenumbers

        for region in ("BR", "GB"):
            example = phonenumbers.example_number_for_type(region, phonenumbers.PhoneNumberType.FIXED_LINE)
            national = phonenumbers.format_number(example, phonenumbers.PhoneNumberFormat.NATIONAL)
            expected = phonenumbers.format_number(example, phonenumbers.PhoneNumberFormat.E164)
            self.assertEqual(self.create(contact_phone=national, country=region).contact_phone, expected)


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class DirectoryConcurrencyTests(TransactionTestCase):
    def test_concurrent_replay_creates_only_one_entry(self):
        seed_initial_admin()
        operator = Account.objects.get()
        started = timezone.now().timestamp()
        token = issue_submission(session_key="session", authenticated_at=started, operation="directory.create")
        proof = SubmissionProof(token, "session", operator.access_version, started)
        barrier = Barrier(2)

        def create(name):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                create_entry(operator_id=operator.pk, name=name, category=Entry.Category.MEMBER, submission=proof)
                return True
            except SubmissionRejected:
                return False
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(create, name) for name in ("Ana", "Maria")]
            self.assertEqual(sorted(future.result(timeout=20) for future in futures), [False, True])
        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(Account.objects.count(), 1)

