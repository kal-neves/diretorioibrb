from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.db import OperationalError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Account
from accounts.services import (
    change_password, create_account, delete_account, restore_password,
    seed_initial_admin, update_account,
)
from accounts.sessions import ACCESS_VERSION, AUTHENTICATED_AT
from accounts.tests.test_services import FAST_HASHERS, example_mobile


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, ROOT_URLCONF="accounts.tests.access_urls")
class AccessTests(TestCase):
    def setUp(self):
        self.admin_password = seed_initial_admin()
        self.admin = Account.objects.get()
        self.account, self.password = create_account(
            operator_id=self.admin.pk, name="Conta de teste", phone=example_mobile("BR"),
        )

    def login(self, client=None, *, admin=False, next_url=""):
        client = client or self.client
        return client.post("/login/", {
            "username": "adminseed" if admin else self.account.login_phone,
            "password": self.admin_password if admin else self.password,
            "next": next_url,
        })

    def complete_first_change(self, client=None):
        client = client or self.client
        response = client.post("/primeiro-acesso/", {
            "new_password": "definitiva123", "confirmation": "definitiva123",
        })
        self.password = "definitiva123"
        self.account.refresh_from_db()
        return response

    def activate(self):
        self.login()
        self.complete_first_change()

    def test_anonymous_routes_are_protected_by_default(self):
        for path in ["/diretorio/", "/foto/", "/fragmento/", "/operacao/", "/admin/", "/minha-senha/"]:
            for method in [self.client.get, self.client.post]:
                with self.subTest(path=path, method=method.__name__):
                    response = method(path)
                    self.assertRedirects(response, "/login/", fetch_redirect_response=False)
                    self.assertIn("no-store", response["Cache-Control"])

    def test_pending_password_blocks_all_protected_channels(self):
        self.assertRedirects(self.login(), "/primeiro-acesso/", fetch_redirect_response=False)
        for path in ["/diretorio/", "/foto/", "/fragmento/", "/operacao/", "/admin/", "/minha-senha/", "/login/"]:
            with self.subTest(path=path):
                response = self.client.post(path)
                self.assertRedirects(response, "/primeiro-acesso/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/primeiro-acesso/").status_code, 200)
        self.assertNotIn(self.password, str(dict(self.client.session)))

    def test_first_change_needs_no_temporary_password_in_form_or_session(self):
        self.login()
        old_key = self.client.session.session_key
        started_at = self.client.session[AUTHENTICATED_AT]
        page = self.client.get("/primeiro-acesso/")
        self.assertNotContains(page, 'name="current_password"')
        self.assertNotContains(page, self.password)
        self.assertRedirects(self.complete_first_change(), "/diretorio/", fetch_redirect_response=False)
        self.assertNotEqual(self.client.session.session_key, old_key)
        self.assertEqual(self.client.session[AUTHENTICATED_AT], started_at)
        self.assertEqual(self.client.get("/diretorio/").status_code, 200)

    def test_admin_login_does_not_require_first_change(self):
        self.assertRedirects(self.login(admin=True), "/admin/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/admin/").status_code, 200)
        self.assertRedirects(self.client.get("/primeiro-acesso/"), "/admin/", fetch_redirect_response=False)

    def test_consultation_is_denied_both_staff_decorator_and_admin_namespace(self):
        self.activate()
        self.assertEqual(self.client.get("/admin/").status_code, 403)
        self.assertEqual(self.client.get("/secretaria/").status_code, 403)

    def test_absolute_expiry_does_not_slide_or_depend_on_database_expiry(self):
        self.activate()
        session = self.client.session
        started = timezone.now() - timedelta(minutes=59)
        session[AUTHENTICATED_AT] = started.timestamp()
        session.set_expiry(timezone.now() + timedelta(days=1))
        session.save()
        self.assertEqual(self.client.get("/diretorio/").status_code, 200)
        self.assertEqual(self.client.session[AUTHENTICATED_AT], started.timestamp())
        with patch("accounts.sessions.timezone.now", return_value=started + timedelta(hours=1)):
            self.assertRedirects(self.client.get("/diretorio/"), "/login/", fetch_redirect_response=False)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_voluntary_change_revokes_other_sessions_without_extending_current(self):
        self.activate()
        other = Client()
        self.login(other)
        started_at = self.client.session[AUTHENTICATED_AT]
        deadline = self.client.session.get_expiry_date()
        previous_key = self.client.session.session_key
        response = self.client.post("/minha-senha/", {
            "current_password": self.password, "new_password": "novasenha123", "confirmation": "novasenha123",
        })
        self.assertRedirects(response, "/diretorio/", fetch_redirect_response=False)
        self.assertNotEqual(previous_key, self.client.session.session_key)
        self.assertEqual(self.client.session[AUTHENTICATED_AT], started_at)
        self.assertEqual(self.client.session.get_expiry_date(), deadline)
        self.assertEqual(self.client.get("/diretorio/").status_code, 200)
        self.assertRedirects(other.get("/diretorio/"), "/login/", fetch_redirect_response=False)

    def test_deactivate_then_reactivate_never_restores_old_session(self):
        self.activate()
        update_account(operator_id=self.admin.pk, account_id=self.account.pk, is_active=False)
        update_account(operator_id=self.admin.pk, account_id=self.account.pk, is_active=True)
        self.assertRedirects(self.client.get("/diretorio/"), "/login/", fetch_redirect_response=False)

    def test_deleted_account_loses_session(self):
        self.activate()
        delete_account(operator_id=self.admin.pk, account_id=self.account.pk)
        self.assertRedirects(self.client.get("/foto/"), "/login/", fetch_redirect_response=False)

    def test_phone_or_role_changes_revoke_existing_session(self):
        for changes in [{"phone": example_mobile("GB")}, {"role": Account.Role.SECRETARIAT}]:
            with self.subTest(changes=changes):
                self.activate() if self.account.must_change_password else self.login()
                self.account = update_account(operator_id=self.admin.pk, account_id=self.account.pk, **changes)
                self.assertRedirects(self.client.get("/diretorio/"), "/login/", fetch_redirect_response=False)

    def test_restoration_revokes_then_requires_new_change_preserving_first_change(self):
        self.activate()
        first_change = self.account.first_password_changed_at
        self.password = restore_password(operator_id=self.admin.pk, account_id=self.account.pk)
        self.assertRedirects(self.client.get("/diretorio/"), "/login/", fetch_redirect_response=False)
        self.assertRedirects(self.login(), "/primeiro-acesso/", fetch_redirect_response=False)
        self.complete_first_change()
        self.assertEqual(self.account.first_password_changed_at, first_change)

    def test_pending_account_expiring_after_login_is_blocked(self):
        self.login()
        Account.objects.filter(pk=self.account.pk).update(created_at=timezone.now() - timedelta(days=7))
        self.assertRedirects(self.client.get("/primeiro-acesso/"), "/login/", fetch_redirect_response=False)

    def test_missing_or_invalid_session_metadata_is_rejected(self):
        self.activate()
        for value in [None, "invalid", float("nan"), timezone.now().timestamp() + 300]:
            self.login()
            session = self.client.session
            session[AUTHENTICATED_AT] = value
            session.save()
            with self.subTest(value=value):
                self.assertRedirects(self.client.get("/diretorio/"), "/login/", fetch_redirect_response=False)

    def test_ajax_access_failure_returns_status_and_destination_without_html(self):
        response = self.client.get("/fragmento/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["X-Access-Redirect"], "/login/")
        self.assertEqual(response.content, b"")
        self.login()
        response = self.client.get("/foto/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["X-Access-Redirect"], "/primeiro-acesso/")

    def test_external_next_is_rejected_and_local_next_is_kept(self):
        for next_url in ["https://example.invalid/", "//example.invalid/", "/\\example.invalid/"]:
            self.client = Client()
            with self.subTest(next_url=next_url):
                self.assertRedirects(self.login(admin=True, next_url=next_url), "/admin/", fetch_redirect_response=False)
        self.client = Client()
        self.assertRedirects(self.login(admin=True, next_url="/minha-senha/"), "/minha-senha/", fetch_redirect_response=False)

    def test_logout_is_post_only_and_invalidates_session(self):
        self.login()
        key = self.client.session.session_key
        self.assertEqual(self.client.get("/sair/").status_code, 405)
        self.assertRedirects(self.client.post("/sair/"), "/login/", fetch_redirect_response=False)
        self.assertFalse(Session.objects.filter(session_key=key).exists())

    def test_login_rate_limit_returns_429_and_retry_after(self):
        for _ in range(5):
            response = self.client.post("/login/", {"username": "adminseed", "password": "wrong"})
            self.assertEqual(response.status_code, 200)
        response = self.login(admin=True)
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response["Retry-After"]), 0)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_csrf_is_required_for_login_password_change_and_logout(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.login(client).status_code, 403)
        client.get("/login/")
        csrf = client.cookies["csrftoken"].value
        response = client.post("/login/", {"username": self.account.login_phone, "password": self.password},
                               HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.post("/primeiro-acesso/", {"new_password": "abc12345", "confirmation": "abc12345"}).status_code, 403)
        self.assertEqual(client.post("/sair/").status_code, 403)
        self.assertEqual(client.post("/sair/", HTTP_X_CSRFTOKEN=csrf).status_code, 403)
        csrf = client.cookies["csrftoken"].value
        self.assertEqual(client.post("/sair/", HTTP_X_CSRFTOKEN=csrf).status_code, 302)

    def test_database_failure_denies_access_without_debug_details(self):
        with patch("accounts.backends.authenticate_attempt", side_effect=OperationalError("private database detail")):
            response = self.login()
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "private database detail", status_code=503)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.login()
        with patch("accounts.backends.PhoneBackend.get_user", side_effect=OperationalError("private")):
            response = self.client.get("/diretorio/")
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "Conteúdo protegido", status_code=503)

    def test_password_committed_before_session_failure_can_be_used_again(self):
        self.login()
        with patch("django.contrib.sessions.backends.db.SessionStore.save", side_effect=OperationalError("private")):
            response = self.client.post("/primeiro-acesso/", {
                "new_password": "definitiva123", "confirmation": "definitiva123",
            })
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "senha foi alterada", status_code=503)
        self.account.refresh_from_db()
        self.assertTrue(self.account.check_password("definitiva123"))
        self.password = "definitiva123"
        self.assertRedirects(self.login(), "/diretorio/", fetch_redirect_response=False)

    def test_stale_session_cannot_overwrite_password_restored_during_request(self):
        self.activate()
        original_operation = change_password

        def revoke_then_change(**kwargs):
            restore_password(operator_id=self.admin.pk, account_id=self.account.pk)
            return original_operation(**kwargs)

        with patch("accounts.views.change_password", side_effect=revoke_then_change):
            response = self.client.post("/minha-senha/", {
                "current_password": self.password, "new_password": "novasenha123", "confirmation": "novasenha123",
            })
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)
        self.account.refresh_from_db()
        self.assertTrue(self.account.must_change_password)
        self.assertFalse(self.account.check_password("novasenha123"))

    def test_invalid_new_password_keeps_restricted_session(self):
        self.login()
        response = self.client.post("/primeiro-acesso/", {"new_password": "short", "confirmation": "short"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'value="short"')
        self.account.refresh_from_db()
        self.assertTrue(self.account.must_change_password)
        self.assertRedirects(self.client.get("/diretorio/"), "/primeiro-acesso/", fetch_redirect_response=False)
