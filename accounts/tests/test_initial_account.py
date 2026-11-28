from io import StringIO

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Account
from accounts.services import seed_initial_admin
from accounts.validators import PasswordPolicy


class InitialAccountTests(TestCase):
    def test_initialization_preserves_existing_password(self):
        password = seed_initial_admin()
        account = Account.objects.get()
        self.assertTrue(account.check_password(password))
        self.assertNotEqual(account.password, password)
        self.assertFalse(account.must_change_password)
        self.assertIsNone(account.login_phone)
        self.assertIsNone(account.first_password_changed_at)
        self.assertIsNone(seed_initial_admin())
        account.refresh_from_db()
        self.assertTrue(account.check_password(password))
        self.assertEqual(Account.objects.count(), 1)

    def test_initial_admin_cannot_be_deleted_in_bulk(self):
        seed_initial_admin()
        with self.assertRaises(PermissionDenied), transaction.atomic():
            Account.objects.all().delete()
        self.assertEqual(Account.objects.count(), 1)

    def test_database_rejects_inactive_initial_admin(self):
        seed_initial_admin()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Account.objects.update(is_active=False)

    def test_command_refuses_captured_output_before_creating_account(self):
        with self.assertRaises(CommandError):
            call_command("seed_admin", stdout=StringIO())
        self.assertFalse(Account.objects.exists())

    def test_interactive_command_displays_password_only_once(self):
        output = StringIO()
        output.isatty = lambda: True
        call_command("seed_admin", stdout=output)
        self.assertIn("Senha:", output.getvalue())
        output.seek(0)
        output.truncate()
        call_command("seed_admin", stdout=output)
        self.assertNotIn("Senha:", output.getvalue())
        self.assertIn("preservada", output.getvalue())

    def test_password_policy_does_not_require_symbols_or_uppercase(self):
        validator = PasswordPolicy()
        validator.validate("abcdefgh1")
        for password in ["abc123", "abcdefgh", "12345678"]:
            with self.subTest(password=password), self.assertRaises(ValidationError):
                validator.validate(password)


class AccountConstraintTests(TestCase):
    def test_invalid_identity_or_initial_state_is_rejected(self):
        cases = [
            {"login_phone": None},
            {"login_phone": "11999999999"},
            {"seed_username": "other"},
            {"role": "OTHER"},
            {"name": "   "},
            {"access_version": 0},
            {"must_change_password": False},
        ]
        for changes in cases:
            values = {"name": "Conta de teste", "login_phone": "+5511999999999", **changes}
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                Account.objects.create(**values)

    def test_login_phone_is_unique(self):
        Account.objects.create(name="Conta A", login_phone="+5511999999999")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Account.objects.create(name="Conta B", login_phone="+5511999999999")
