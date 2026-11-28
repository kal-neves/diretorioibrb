from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, local
from unittest.mock import patch

import phonenumbers
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from accounts.models import Account
from accounts.policies import is_expired_new_account
from accounts.services import (
    change_password, create_account, delete_account, delete_expired_new_accounts,
    restore_password, seed_initial_admin, update_account,
)
from common.phones import normalize_phone


FAST_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


def example_mobile(region):
    number = phonenumbers.example_number_for_type(region, phonenumbers.PhoneNumberType.MOBILE)
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class AccountServiceTests(TestCase):
    def setUp(self):
        seed_initial_admin()
        self.admin = Account.objects.get()
        self.account, self.temporary = create_account(
            operator_id=self.admin.pk, name="  Conta de teste  ", phone=example_mobile("BR"),
        )

    def first_change(self, account=None, password=None):
        return change_password(
            account_id=(account or self.account).pk, current_password=password or self.temporary,
            new_password="definitiva123", confirmation="definitiva123",
        )

    def secretary(self):
        account, password = create_account(
            operator_id=self.admin.pk, name="Secretaria", phone=example_mobile("GB"),
            role=Account.Role.SECRETARIAT,
        )
        return self.first_change(account, password)

    def test_creation_and_first_change(self):
        self.assertEqual(self.account.name, "Conta de teste")
        self.assertTrue(self.account.must_change_password)
        self.assertTrue(self.account.check_password(self.temporary))
        account = self.first_change()
        self.assertFalse(account.must_change_password)
        self.assertIsNotNone(account.first_password_changed_at)
        self.assertEqual(account.access_version, 2)
        self.assertTrue(account.check_password("definitiva123"))

    def test_duplicate_formatted_phone_is_rejected(self):
        number = phonenumbers.parse(self.account.login_phone)
        formatted = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL)
        with self.assertRaises(ValidationError):
            create_account(operator_id=self.admin.pk, name="Duplicada", phone=formatted, country="BR")
        self.assertEqual(Account.objects.count(), 2)

    def test_invalid_name_does_not_create_partial_account(self):
        with self.assertRaises(ValidationError):
            create_account(operator_id=self.admin.pk, name="   ", phone=example_mobile("GB"))
        self.assertEqual(Account.objects.count(), 2)

    def test_consultation_and_pending_secretary_cannot_manage(self):
        with self.assertRaises(PermissionDenied):
            create_account(operator_id=self.account.pk, name="Outra", phone=example_mobile("GB"))
        secretary, _ = create_account(
            operator_id=self.admin.pk, name="Secretaria", phone=example_mobile("GB"),
            role=Account.Role.SECRETARIAT,
        )
        with self.assertRaises(PermissionDenied):
            update_account(operator_id=secretary.pk, account_id=self.account.pk, is_active=False)

    def test_secretary_cannot_promote_or_manage_another_secretary(self):
        secretary = self.secretary()
        for target in [self.account, secretary, self.admin]:
            with self.subTest(target=target.role), self.assertRaises(PermissionDenied):
                update_account(operator_id=secretary.pk, account_id=target.pk, role=Account.Role.SECRETARIAT)
        with self.assertRaises(PermissionDenied):
            create_account(operator_id=secretary.pk, name="Outra", phone=example_mobile("FR"),
                           role=Account.Role.SECRETARIAT)

    def test_secretary_can_manage_consultation(self):
        secretary = self.secretary()
        account = update_account(operator_id=secretary.pk, account_id=self.account.pk, is_active=False)
        self.assertFalse(account.is_active)
        delete_account(operator_id=secretary.pk, account_id=account.pk)
        self.assertFalse(Account.objects.filter(pk=self.account.pk).exists())

    def test_restore_preserves_first_change_and_inactive_state(self):
        account = self.first_change()
        first_change = account.first_password_changed_at
        update_account(operator_id=self.admin.pk, account_id=account.pk, is_active=False)
        password = restore_password(operator_id=self.admin.pk, account_id=account.pk)
        account.refresh_from_db()
        self.assertFalse(account.is_active)
        self.assertTrue(account.must_change_password)
        self.assertEqual(account.first_password_changed_at, first_change)
        self.assertTrue(account.check_password(password))
        self.assertEqual(account.access_version, 4)

    def test_new_account_cannot_receive_another_temporary_password(self):
        with self.assertRaises(ValidationError):
            restore_password(operator_id=self.admin.pk, account_id=self.account.pk)
        self.account.refresh_from_db()
        self.assertTrue(self.account.check_password(self.temporary))

    def test_password_failure_keeps_state(self):
        cases = [
            ("wrong", "nova12345", "nova12345"),
            (self.temporary, "nova12345", "different"),
            (self.temporary, "onlyletters", "onlyletters"),
        ]
        for current, password, confirmation in cases:
            with self.subTest(current=current == self.temporary), self.assertRaises(ValidationError):
                change_password(account_id=self.account.pk, current_password=current,
                                new_password=password, confirmation=confirmation)
        self.account.refresh_from_db()
        self.assertTrue(self.account.must_change_password)
        self.assertIsNone(self.account.first_password_changed_at)
        self.assertEqual(self.account.access_version, 1)

    def test_access_changes_only_increase_version(self):
        for changes in [
            {"is_active": False}, {"is_active": True},
            {"phone": example_mobile("GB")}, {"role": Account.Role.SECRETARIAT},
        ]:
            previous = self.account.access_version
            self.account = update_account(operator_id=self.admin.pk, account_id=self.account.pk, **changes)
            self.assertGreater(self.account.access_version, previous)
        same = update_account(operator_id=self.admin.pk, account_id=self.account.pk, name="Novo nome")
        self.assertEqual(same.access_version, self.account.access_version)

    def test_initial_admin_cannot_be_modified_by_management(self):
        for changes in [{"is_active": False}, {"role": Account.Role.CONSULTATION}]:
            with self.assertRaises(PermissionDenied):
                update_account(operator_id=self.admin.pk, account_id=self.admin.pk, **changes)
        with self.assertRaises(PermissionDenied):
            delete_account(operator_id=self.admin.pk, account_id=self.admin.pk)

    def test_exact_seven_day_boundary_blocks_first_change_and_deletes(self):
        now = timezone.now()
        Account.objects.filter(pk=self.account.pk).update(created_at=now - timedelta(days=7))
        self.account.refresh_from_db()
        self.assertFalse(is_expired_new_account(self.account, now=now - timedelta(microseconds=1)))
        self.assertTrue(is_expired_new_account(self.account, now=now))
        with patch("accounts.policies.timezone.now", return_value=now):
            with self.assertRaises(PermissionDenied):
                self.first_change()
            self.assertEqual(delete_expired_new_accounts(), 1)
            self.assertEqual(delete_expired_new_accounts(), 0)

    def test_cleanup_preserves_used_restored_and_initial_accounts(self):
        self.first_change()
        restore_password(operator_id=self.admin.pk, account_id=self.account.pk)
        Account.objects.update(created_at=timezone.now() - timedelta(days=30))
        self.assertEqual(delete_expired_new_accounts(batch_size=1), 0)
        self.assertEqual(Account.objects.count(), 2)

    def test_cleanup_deletes_inactive_unused_but_not_recent_accounts(self):
        update_account(operator_id=self.admin.pk, account_id=self.account.pk, is_active=False)
        Account.objects.filter(pk=self.account.pk).update(created_at=timezone.now() - timedelta(days=8))
        recent, _ = create_account(operator_id=self.admin.pk, name="Recente", phone=example_mobile("GB"))
        self.assertEqual(delete_expired_new_accounts(batch_size=1), 1)
        self.assertTrue(Account.objects.filter(pk=recent.pk).exists())


class PhoneTests(TestCase):
    def test_international_and_national_formats_match(self):
        for region in ["BR", "GB", "US", "FR"]:
            phone = example_mobile(region)
            national = phonenumbers.format_number(phonenumbers.parse(phone), phonenumbers.PhoneNumberFormat.NATIONAL)
            with self.subTest(region=region):
                self.assertEqual(normalize_phone(phone, mobile_only=True), phone)
                self.assertEqual(normalize_phone(national, region, mobile_only=True), phone)

    def test_country_is_required_without_international_code(self):
        with self.assertRaises(ValidationError) as result:
            normalize_phone("(11) 96123-4567", mobile_only=True)
        self.assertEqual(result.exception.code, "country_required")

    def test_country_mismatch_and_invalid_input(self):
        for phone, country in [(example_mobile("BR"), "US"), ("123", "BR"),
                               ("+5511961234567 ext 2", None), ("abc", None)]:
            with self.subTest(phone=phone), self.assertRaises(ValidationError):
                normalize_phone(phone, country)

    def test_landline_allowed_for_contact_but_not_login(self):
        number = phonenumbers.example_number_for_type("BR", phonenumbers.PhoneNumberType.FIXED_LINE)
        phone = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
        self.assertEqual(normalize_phone(phone), phone)
        with self.assertRaises(ValidationError):
            normalize_phone(phone, mobile_only=True)

    def test_ambiguous_country_needs_confirmation(self):
        with patch("common.phones.phonenumbers.region_codes_for_country_code", return_value=("US", "CA")), \
                patch("common.phones.phonenumbers.is_valid_number_for_region", return_value=True):
            with self.assertRaises(ValidationError) as result:
                normalize_phone(example_mobile("US"))
            self.assertEqual(result.exception.code, "country_required")
            self.assertEqual(normalize_phone(example_mobile("US"), "US"), example_mobile("US"))


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class AccountConcurrencyTests(TransactionTestCase):
    def race(self, operation):
        barrier = Barrier(2)

        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return operation()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker) for _ in range(2)]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_seed_returns_only_one_password(self):
        results = self.race(seed_initial_admin)
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(Account.objects.count(), 1)

    def test_concurrent_creation_does_not_duplicate_phone(self):
        seed_initial_admin()
        admin = Account.objects.get()

        def create():
            try:
                create_account(operator_id=admin.pk, name="Concorrente", phone=example_mobile("BR"))
                return True
            except ValidationError:
                return False

        self.assertEqual(sorted(self.race(create)), [False, True])
        self.assertEqual(Account.objects.filter(login_phone=example_mobile("BR")).count(), 1)

    def test_concurrent_cleanup_deletes_each_candidate_once(self):
        seed_initial_admin()
        admin = Account.objects.get()
        for country in ["BR", "GB", "FR"]:
            create_account(operator_id=admin.pk, name="Vencida", phone=example_mobile(country))
        Account.objects.exclude(pk=admin.pk).update(created_at=timezone.now() - timedelta(days=8))
        self.assertEqual(sum(self.race(lambda: delete_expired_new_accounts(batch_size=1))), 3)
        self.assertEqual(list(Account.objects.values_list("pk", flat=True)), [admin.pk])

    def test_first_change_racing_cleanup_has_no_partial_outcome(self):
        seed_initial_admin()
        admin = Account.objects.get()
        account, password = create_account(
            operator_id=admin.pk, name="Primeiro acesso", phone=example_mobile("BR"),
        )
        boundary = timezone.now()
        Account.objects.filter(pk=account.pk).update(created_at=boundary - timedelta(days=7))
        barrier = Barrier(2)
        clock = local()

        def worker(operation, instant):
            close_old_connections()
            clock.now = instant
            try:
                barrier.wait(timeout=10)
                return operation()
            finally:
                close_old_connections()

        def first_change():
            try:
                change_password(account_id=account.pk, current_password=password,
                                new_password="definitiva123", confirmation="definitiva123")
                return True
            except (ValidationError, PermissionDenied):
                return False

        with patch("accounts.services.timezone.now", side_effect=lambda: clock.now):
            with ThreadPoolExecutor(max_workers=2) as executor:
                change = executor.submit(worker, first_change, boundary - timedelta(microseconds=1))
                cleanup = executor.submit(worker, delete_expired_new_accounts, boundary)
                changed, deleted = change.result(timeout=20), cleanup.result(timeout=20)
        if changed:
            account.refresh_from_db()
            self.assertIsNotNone(account.first_password_changed_at)
            self.assertFalse(account.must_change_password)
            self.assertTrue(account.check_password("definitiva123"))
            self.assertEqual(deleted, 0)
        else:
            self.assertFalse(Account.objects.filter(pk=account.pk).exists())
            self.assertEqual(deleted, 1)
