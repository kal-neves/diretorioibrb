from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import StringIO
from threading import Barrier
from unittest.mock import patch

from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from accounts.models import Account, LoginCounter
from accounts.services import seed_initial_admin
from accounts.tests.test_services import FAST_HASHERS, example_mobile
from common.maintenance import acquire, record, run_daily
from common.models import FormSubmission, RoutineState
from directory.models import Entry, Photo
from directory.storage import StorageUnavailable


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class MaintenanceTests(TestCase):
    def test_cleanup_only_expired_data_and_preserves_directory(self):
        seed_initial_admin()
        now = timezone.now()
        Account.objects.create(name="Nova vencida", login_phone=example_mobile("BR"), created_at=now - timedelta(days=7))
        Account.objects.create(name="Nova válida", login_phone=example_mobile("GB"))
        Entry.objects.create(name="Independente", category="MEMBER")
        Session.objects.create(session_key="old", session_data="", expire_date=now - timedelta(seconds=1))
        Session.objects.create(session_key="current", session_data="", expire_date=now + timedelta(hours=1))
        for key, expiry in (("old", now), ("current", now + timedelta(minutes=1))):
            LoginCounter.objects.create(scope=LoginCounter.Scope.IP, key_digest=key,
                                        window_started_at=now - timedelta(minutes=15), expires_at=expiry)
        FormSubmission.objects.create(token_digest="t", session_scope_digest="s", operation="test",
                                      created_at=now - timedelta(hours=2), expires_at=now - timedelta(hours=1))
        self.assertEqual(run_daily(), "succeeded")
        self.assertEqual(Account.objects.count(), 2)
        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(list(Session.objects.values_list("pk", flat=True)), ["current"])
        state = RoutineState.objects.get()
        self.assertEqual(state.counts["accounts"], 1)
        self.assertEqual(state.counts["submissions"], 1)
        self.assertEqual(state.counts["login_counters"], 1)
        self.assertEqual(list(LoginCounter.objects.values_list("key_digest", flat=True)), ["current"])
        self.assertIsNotNone(state.last_succeeded_at)
        self.assertEqual(run_daily(), "already_done")
        self.assertEqual(run_daily(force=True), "succeeded")

    def test_lease_takeover_rejects_old_results(self):
        token, _ = acquire()
        self.assertEqual(run_daily(force=True), "running")
        RoutineState.objects.update(lease_until=timezone.now() - timedelta(seconds=1))
        replacement, _ = acquire()
        self.assertNotEqual(token, replacement)
        self.assertFalse(record(token, {"accounts": 999}, status="succeeded"))
        self.assertTrue(record(replacement, {}, status="succeeded"))

    def test_failure_preserves_previous_success_and_allows_retry(self):
        self.assertEqual(run_daily(), "succeeded")
        previous = RoutineState.objects.get().last_succeeded_at
        Photo.objects.create(state="PENDING_DELETE")
        with patch("common.maintenance.cleanup_photos", side_effect=StorageUnavailable("private")):
            self.assertEqual(run_daily(force=True), "failed")
        state = RoutineState.objects.get()
        self.assertEqual(state.last_succeeded_at, previous)
        self.assertEqual(state.last_error_code, "storage_unavailable")
        output = StringIO()
        call_command("maintenance_status", stdout=output)
        self.assertNotIn("private", output.getvalue())
        self.assertNotIn(str(state.run_token), output.getvalue())

    def test_budget_reports_partial_and_resumes(self):
        Session.objects.create(session_key="old", session_data="", expire_date=timezone.now() - timedelta(seconds=1))
        self.assertEqual(run_daily(budget_seconds=0), "partial")
        self.assertIsNone(RoutineState.objects.get().last_succeeded_at)
        self.assertEqual(run_daily(), "succeeded")

    @override_settings(DEBUG=False, MAINTENANCE_ENABLED=True, DEPLOYMENT_ENV="production", CRON_SECRET="test-cron-secret")
    def test_scheduler_uses_only_header_and_never_user_session(self):
        client = Client()
        url = "/internal/maintenance/"
        self.assertEqual(client.get(url).status_code, 401)
        self.assertEqual(client.get(url, {"secret": "test-cron-secret"}).status_code, 401)
        response = client.get(url, HTTP_AUTHORIZATION="Bearer test-cron-secret")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("test-cron-secret", response.content.decode())
        self.assertEqual(client.get("/diretorio/", HTTP_AUTHORIZATION="Bearer test-cron-secret").status_code, 302)
        self.assertEqual(client.get(url, {"force": "1"}, HTTP_AUTHORIZATION="Bearer test-cron-secret").status_code, 400)
        self.assertEqual(client.post(url, HTTP_AUTHORIZATION="Bearer test-cron-secret").status_code, 405)
        for overrides in ({"DEBUG": True}, {"DEPLOYMENT_ENV": "preview"}, {"MAINTENANCE_ENABLED": False}):
            with override_settings(**overrides):
                self.assertEqual(client.get(url, HTTP_AUTHORIZATION="Bearer test-cron-secret").status_code, 404)

    def test_day_boundary_is_belem(self):
        now = timezone.now().replace(hour=2, minute=30, second=0, microsecond=0)
        RoutineState.objects.create(key="daily", last_succeeded_at=now - timedelta(hours=2), status="succeeded")
        with patch("common.maintenance.timezone.now", return_value=now):
            self.assertEqual(acquire()[1], "already_done")
        with patch("common.maintenance.timezone.now", return_value=now + timedelta(hours=1)):
            self.assertIsNotNone(acquire()[0])

    def test_status_detects_missed_window_until_next_success(self):
        deadline = datetime(2026, 12, 1, 4, tzinfo=UTC)
        yesterday = deadline - timedelta(days=1)
        state = RoutineState.objects.create(key="daily", status="succeeded", last_succeeded_at=yesterday)
        with patch("django.utils.timezone.now", return_value=deadline - timedelta(seconds=1)):
            call_command("maintenance_status", stdout=StringIO())
        with patch("django.utils.timezone.now", return_value=deadline):
            with self.assertRaisesMessage(CommandError, "Manutenção atrasada"):
                call_command("maintenance_status", stdout=StringIO())
            state.refresh_from_db()
            self.assertEqual(state.last_succeeded_at, yesterday)
            self.assertEqual(run_daily(), "succeeded")
            call_command("maintenance_status", stdout=StringIO())

    def test_status_for_first_execution(self):
        deadline = datetime(2026, 12, 1, 4, tzinfo=UTC)
        with patch("django.utils.timezone.now", return_value=deadline - timedelta(seconds=1)):
            call_command("maintenance_status", stdout=StringIO())
        with patch("django.utils.timezone.now", return_value=deadline):
            with self.assertRaisesMessage(CommandError, "Manutenção atrasada"):
                call_command("maintenance_status", stdout=StringIO())


class MaintenanceConcurrencyTests(TransactionTestCase):
    def test_only_one_executor_acquires_lease(self):
        barrier = Barrier(2)

        def attempt():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return acquire()[0] is not None
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt) for _ in range(2)]
            self.assertEqual(sorted(item.result(timeout=20) for item in futures), [False, True])
