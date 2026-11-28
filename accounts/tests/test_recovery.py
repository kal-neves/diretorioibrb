from io import StringIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import Account
from accounts.services import recover_initial_admin, seed_initial_admin
from accounts.tests.test_services import FAST_HASHERS


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class RecoveryTests(TestCase):
    def test_recovery_changes_only_hash_and_version_and_revokes_session(self):
        password = seed_initial_admin()
        self.client.post("/login/", {"username": "adminseed", "password": password})
        before = Account.objects.values().get()
        replacement = recover_initial_admin()
        account = Account.objects.get()
        after = Account.objects.values().get()
        self.assertTrue(account.check_password(replacement))
        self.assertFalse(account.check_password(password))
        self.assertEqual(account.access_version, before["access_version"] + 1)
        for key in before.keys() - {"password", "access_version"}:
            self.assertEqual(before[key], after[key])
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        self.assertIsNone(seed_initial_admin())

    def test_missing_admin_does_not_create_one(self):
        with self.assertRaises(ValidationError):
            recover_initial_admin()
        self.assertFalse(Account.objects.exists())

    def test_command_requires_private_terminal_and_exact_confirmation(self):
        seed_initial_admin()
        before = Account.objects.get().password
        with self.assertRaises(CommandError):
            call_command("recover_admin", stdout=StringIO())
        output = StringIO()
        output.isatty = lambda: True
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="não"), self.assertRaises(CommandError):
            call_command("recover_admin", stdout=output)
        self.assertEqual(Account.objects.get().password, before)
        output.seek(0)
        output.truncate()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="RECUPERAR adminseed"):
            call_command("recover_admin", stdout=output)
        self.assertIn("Nova senha de adminseed:", output.getvalue())
        self.assertNotEqual(Account.objects.get().password, before)
