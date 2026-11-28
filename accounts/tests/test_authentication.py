from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import authenticate
from django.db import close_old_connections
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from accounts.authentication import LoginRejected, authenticate_attempt, clear_expired_login_counters, client_ip
from accounts.models import Account, LoginCounter
from accounts.services import create_account, seed_initial_admin, update_account
from accounts.tests.test_services import FAST_HASHERS, example_mobile


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, AUTHENTICATION_BACKENDS=["accounts.backends.PhoneBackend"])
class LoginTests(TestCase):
    def setUp(self):
        self.password = seed_initial_admin()
        self.admin = Account.objects.get()

    def attempt(self, password=None, identifier="adminseed", ip="127.0.0.1", country=None):
        return authenticate_attempt(identifier=identifier, password=password or self.password, country=country, ip=ip)

    def test_admin_login_uses_django_backend_without_initial_change(self):
        request = RequestFactory().post("/login/")
        account = authenticate(request, username="adminseed", password=self.password)
        self.assertEqual(account.pk, self.admin.pk)
        self.assertFalse(account.must_change_password)
        self.assertIsNone(authenticate(None, username="adminseed", password=self.password))

    def test_five_failures_block_correct_password_until_window_expires(self):
        now = timezone.now()
        with patch("accounts.authentication.timezone.now", return_value=now):
            for _ in range(5):
                with self.assertRaises(LoginRejected) as result:
                    self.attempt(password="wrong")
                self.assertIsNone(result.exception.retry_after)
            with self.assertRaises(LoginRejected) as result:
                self.attempt()
            self.assertEqual(result.exception.retry_after, 900)
        with patch("accounts.authentication.timezone.now", return_value=now + timedelta(minutes=15)):
            self.assertEqual(self.attempt().pk, self.admin.pk)

    def test_thirty_attempts_per_ip_include_successes(self):
        for _ in range(30):
            self.attempt()
        with self.assertRaises(LoginRejected) as result:
            self.attempt()
        self.assertIsNotNone(result.exception.retry_after)
        self.assertEqual(self.attempt(ip="127.0.0.2").pk, self.admin.pk)

    def test_formats_share_same_counter(self):
        account, password = create_account(operator_id=self.admin.pk, name="Teste", phone=example_mobile("BR"))
        for _ in range(5):
            with self.assertRaises(LoginRejected):
                self.attempt(password="wrong", identifier=account.login_phone)
        with self.assertRaises(LoginRejected) as result:
            self.attempt(password=password, identifier=account.login_phone[3:], country="BR")
        self.assertIsNotNone(result.exception.retry_after)

    def test_inactive_and_expired_messages_require_valid_password(self):
        account, password = create_account(operator_id=self.admin.pk, name="Teste", phone=example_mobile("BR"))
        update_account(operator_id=self.admin.pk, account_id=account.pk, is_active=False)
        with self.assertRaises(LoginRejected) as wrong:
            self.attempt(password="wrong", identifier=account.login_phone)
        self.assertNotIn("desativada", str(wrong.exception))
        with self.assertRaises(LoginRejected) as inactive:
            self.attempt(password=password, identifier=account.login_phone)
        self.assertIn("desativada", str(inactive.exception))
        update_account(operator_id=self.admin.pk, account_id=account.pk, is_active=True)
        Account.objects.filter(pk=account.pk).update(created_at=timezone.now() - timedelta(days=7))
        with self.assertRaises(LoginRejected) as expired:
            self.attempt(password=password, identifier=account.login_phone)
        self.assertIn("prazo", str(expired.exception))

    def test_nonexistent_identity_has_generic_error_and_no_plaintext_counter(self):
        with self.assertRaises(LoginRejected) as result:
            self.attempt(password="wrong", identifier=example_mobile("BR"))
        self.assertEqual(str(result.exception), "Celular ou usuário e senha não conferem.")
        for counter in LoginCounter.objects.all():
            self.assertEqual(len(counter.key_digest), 64)
            self.assertNotIn("127.0.0.1", counter.key_digest)
            self.assertNotIn(example_mobile("BR"), counter.key_digest)

    def test_cleanup_removes_only_expired_counters(self):
        self.attempt()
        LoginCounter.objects.filter(scope=LoginCounter.Scope.IP).update(
            window_started_at=timezone.now() - timedelta(hours=1),
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertEqual(clear_expired_login_counters(), 1)
        self.assertEqual(LoginCounter.objects.count(), 1)

    def test_client_headers_do_not_choose_ip(self):
        request = RequestFactory().get("/", REMOTE_ADDR="::ffff:127.0.0.1",
                                       HTTP_X_FORWARDED_FOR="8.8.8.8", HTTP_X_REAL_IP="8.8.4.4")
        self.assertEqual(client_ip(request), "127.0.0.1")
        request.META["REMOTE_ADDR"] = "invalid"
        with self.assertRaises(LoginRejected):
            client_ip(request)


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class LoginConcurrencyTests(TransactionTestCase):
    def test_concurrent_failures_do_not_exceed_five_password_checks(self):
        seed_initial_admin()
        barrier = Barrier(8)

        def attempt():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                authenticate_attempt(identifier="adminseed", password="wrong", country=None, ip="127.0.0.1")
            except LoginRejected as error:
                return error.retry_after is not None
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(attempt) for _ in range(8)]
            blocked = [future.result(timeout=30) for future in futures]
        self.assertEqual(sum(blocked), 3)
        self.assertEqual(LoginCounter.objects.get(scope=LoginCounter.Scope.IP).count, 8)
        self.assertEqual(LoginCounter.objects.get(scope=LoginCounter.Scope.IDENTIFIER_IP).count, 5)
