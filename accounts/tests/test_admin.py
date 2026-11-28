from unittest.mock import patch

from django.contrib.admin.models import LogEntry
from django.db import OperationalError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts import services
from accounts.models import Account
from accounts.tests.test_services import FAST_HASHERS, example_mobile
from common.models import FormSubmission


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class AccountAdminTests(TestCase):
    def setUp(self):
        self.admin_password = services.seed_initial_admin()
        self.admin = Account.objects.get()
        self.secretary, temporary = services.create_account(
            operator_id=self.admin.pk, name="Secretaria", phone=example_mobile("GB"), role=Account.Role.SECRETARIAT,
        )
        services.change_password(account_id=self.secretary.pk, current_password=temporary,
                                 new_password="secretaria123", confirmation="secretaria123")
        self.account, self.temporary = services.create_account(
            operator_id=self.admin.pk, name="Consulta", phone=example_mobile("BR"),
        )
        self.login("adminseed", self.admin_password)
        self.add_url = reverse("admin:accounts_account_add")
        self.list_url = reverse("admin:accounts_account_changelist")

    def login(self, username, password, client=None):
        client = client or self.client
        client.post("/sair/")
        return client.post("/login/", {"username": username, "password": password})

    def change_url(self, account=None):
        return reverse("admin:accounts_account_change", args=[(account or self.account).pk])

    def operation_url(self, operation, account=None):
        return reverse("admin:accounts_account_operation", args=[(account or self.account).pk, operation])

    def token(self, url, client=None):
        response = (client or self.client).get(url)
        self.assertEqual(response.status_code, 200)
        return response.context["form"]["submission_token"].value()

    def create_payload(self, token):
        return {"name": "Conta nova", "phone": example_mobile("FR"), "country": "FR",
                "role": Account.Role.CONSULTATION, "submission_token": token}

    def test_admin_index_and_list_render_without_generic_permissions(self):
        self.assertContains(self.client.get("/admin/"), "Contas de acesso")
        response = self.client.get(self.list_url)
        self.assertContains(response, "adminseed")
        self.assertContains(response, "Secretaria")
        self.assertNotContains(response, "action-toggle")
        self.assertNotContains(response, "Histórico")

    def test_creation_shows_password_only_in_successful_response(self):
        payload = self.create_payload(self.token(self.add_url))
        response = self.client.post(self.add_url, payload)
        self.assertEqual(response.status_code, 200)
        password = response.context["temporary_password"]
        account = Account.objects.get(login_phone=payload["phone"])
        self.assertTrue(account.check_password(password))
        self.assertIn("no-store", response["Cache-Control"])
        repeat = self.client.post(self.add_url, payload)
        self.assertEqual(repeat.status_code, 409)
        self.assertNotContains(repeat, password, status_code=409)
        self.assertNotIn(password, str(dict(self.client.session)))
        self.assertNotContains(self.client.get(self.list_url), password)
        self.assertFalse(LogEntry.objects.exists())

    def test_correctable_error_preserves_token_without_creating_account(self):
        payload = self.create_payload(self.token(self.add_url))
        payload["phone"] = self.account.login_phone
        payload["country"] = "BR"
        response = self.client.post(self.add_url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(FormSubmission.objects.get().consumed_at)
        payload["phone"], payload["country"] = example_mobile("FR"), "FR"
        self.assertEqual(self.client.post(self.add_url, payload).status_code, 200)

    def test_secretary_sees_and_manages_only_consultation(self):
        self.login(self.secretary.login_phone, "secretaria123")
        response = self.client.get(self.list_url)
        self.assertContains(response, self.account.login_phone)
        self.assertEqual(list(response.context["cl"].result_list.values_list("pk", flat=True)), [self.account.pk])
        self.assertNotContains(response, "adminseed")
        for target in [self.admin, self.secretary]:
            self.assertEqual(self.client.get(self.change_url(target)).status_code, 404)
            self.assertEqual(self.client.post(self.operation_url("delete", target), {}).status_code, 404)
        payload = self.create_payload(self.token(self.add_url))
        payload.pop("role")
        response = self.client.post(self.add_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Account.objects.get(login_phone=payload["phone"]).role, Account.Role.CONSULTATION)

    def test_forged_privilege_fields_are_rejected(self):
        self.login(self.secretary.login_phone, "secretaria123")
        payload = self.create_payload(self.token(self.add_url))
        payload["role"] = Account.Role.SECRETARIAT
        self.assertEqual(self.client.post(self.add_url, payload).status_code, 400)
        payload.pop("role")
        for field in ["is_superuser", "is_staff", "seed_username", "password", "access_version", "groups"]:
            self.assertEqual(self.client.post(self.add_url, {**payload, field: "1"}).status_code, 400)
        self.assertFalse(Account.objects.filter(login_phone=payload["phone"]).exists())

    def test_initial_admin_only_readable_in_management(self):
        self.assertContains(self.client.get(self.change_url(self.admin)), "permanente")
        self.assertEqual(self.client.post(self.change_url(self.admin), {}).status_code, 403)
        for operation in ["activate", "deactivate", "delete", "restore"]:
            self.assertEqual(self.client.get(self.operation_url(operation, self.admin)).status_code, 403)

    def test_edit_and_profile_change_use_services_and_consume_token(self):
        url = self.change_url()
        payload = {"name": "Nome atualizado", "phone": self.account.login_phone, "role": Account.Role.SECRETARIAT,
                   "submission_token": self.token(url)}
        response = self.client.post(url, payload)
        self.assertRedirects(response, self.list_url, fetch_redirect_response=False)
        self.account.refresh_from_db()
        self.assertEqual(self.account.role, Account.Role.SECRETARIAT)
        version = self.account.access_version
        self.assertEqual(self.client.post(url, payload).status_code, 409)
        self.account.refresh_from_db()
        self.assertEqual(self.account.access_version, version)

    def test_confirmation_get_does_not_mutate_and_deactivation_replay_is_rejected(self):
        url = self.operation_url("deactivate")
        token = self.token(url)
        self.account.refresh_from_db()
        self.assertTrue(self.account.is_active)
        self.assertRedirects(self.client.post(url, {"submission_token": token}), self.list_url, fetch_redirect_response=False)
        self.account.refresh_from_db()
        self.assertFalse(self.account.is_active)
        self.assertEqual(self.client.post(url, {"submission_token": token}).status_code, 409)
        activate = self.operation_url("activate")
        self.assertEqual(self.client.post(activate, {"submission_token": self.token(activate)}).status_code, 302)
        self.account.refresh_from_db()
        self.assertTrue(self.account.is_active)

    def test_token_cannot_be_used_on_another_target_or_operation(self):
        token = self.token(self.operation_url("deactivate"))
        self.assertEqual(self.client.post(self.operation_url("activate"), {"submission_token": token}).status_code, 409)
        self.assertEqual(self.client.post(self.operation_url("deactivate", self.secretary), {"submission_token": token}).status_code, 409)
        self.secretary.refresh_from_db()
        self.assertTrue(self.secretary.is_active)

    def test_token_cannot_move_between_sessions_of_same_user(self):
        payload = self.create_payload(self.token(self.add_url))
        other = Client()
        self.login("adminseed", self.admin_password, other)
        self.assertEqual(other.post(self.add_url, payload).status_code, 409)

    def test_restore_issues_once_and_preserves_inactive_state(self):
        services.change_password(account_id=self.account.pk, current_password=self.temporary,
                                 new_password="consulta123", confirmation="consulta123")
        services.update_account(operator_id=self.admin.pk, account_id=self.account.pk, is_active=False)
        url = self.operation_url("restore")
        payload = {"submission_token": self.token(url)}
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)
        password = response.context["temporary_password"]
        self.account.refresh_from_db()
        self.assertTrue(self.account.check_password(password))
        self.assertFalse(self.account.is_active)
        repeat = self.client.post(url, payload)
        self.assertEqual(repeat.status_code, 409)
        self.account.refresh_from_db()
        self.assertTrue(self.account.check_password(password))
        self.assertNotContains(repeat, password, status_code=409)

    def test_new_account_cannot_receive_second_temporary_password(self):
        url = self.operation_url("restore")
        self.assertNotContains(self.client.get(self.change_url()), "Restaurar senha")
        response = self.client.post(url, {"submission_token": self.token(url)})
        self.assertEqual(response.status_code, 400)
        self.account.refresh_from_db()
        self.assertTrue(self.account.check_password(self.temporary))

    def test_delete_is_confirmed_and_does_not_write_history(self):
        url = reverse("admin:accounts_account_delete", args=[self.account.pk])
        payload = {"submission_token": self.token(url)}
        self.assertTrue(Account.objects.filter(pk=self.account.pk).exists())
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertFalse(Account.objects.filter(pk=self.account.pk).exists())
        self.assertEqual(self.client.post(url, payload).status_code, 404)
        self.assertFalse(LogEntry.objects.exists())

    def test_default_history_bulk_actions_and_permission_models_unavailable(self):
        self.assertEqual(self.client.get(reverse("admin:accounts_account_history", args=[self.account.pk])).status_code, 403)
        self.assertEqual(self.client.post(self.list_url, {"action": "delete_selected", "_selected_action": self.account.pk}).status_code, 405)
        self.assertEqual(self.client.get("/admin/auth/group/").status_code, 404)
        self.assertEqual(self.client.get("/admin/common/formsubmission/").status_code, 404)

    def test_consultation_and_pending_secretary_cannot_access_admin(self):
        self.login(self.account.login_phone, self.temporary)
        self.assertRedirects(self.client.get(self.add_url), "/primeiro-acesso/", fetch_redirect_response=False)
        services.change_password(account_id=self.account.pk, current_password=self.temporary,
                                 new_password="consulta123", confirmation="consulta123")
        self.login(self.account.login_phone, "consulta123")
        self.assertEqual(self.client.get(self.add_url).status_code, 403)
        password = services.restore_password(operator_id=self.admin.pk, account_id=self.secretary.pk)
        self.login(self.secretary.login_phone, password)
        self.assertRedirects(self.client.get(self.list_url), "/primeiro-acesso/", fetch_redirect_response=False)

    def test_session_revoked_between_middleware_and_mutation_is_rechecked(self):
        payload = self.create_payload(self.token(self.add_url))
        original = services.create_account

        def revoked(**kwargs):
            Account.objects.filter(pk=self.admin.pk).update(access_version=2)
            return original(**kwargs)

        with patch("accounts.admin.services.create_account", side_effect=revoked):
            response = self.client.post(self.add_url, payload)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Account.objects.filter(login_phone=payload["phone"]).exists())
        self.assertIsNone(FormSubmission.objects.get().consumed_at)

    def test_failed_response_after_commit_never_regenerates_password(self):
        payload = self.create_payload(self.token(self.add_url))
        with patch("accounts.admin.AccountAdmin.credential_response", side_effect=OperationalError("private")):
            response = self.client.post(self.add_url, payload)
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "operação foi concluída", status_code=503)
        self.assertTrue(Account.objects.filter(login_phone=payload["phone"]).exists())
        self.assertIsNotNone(FormSubmission.objects.get().consumed_at)
        self.login("adminseed", self.admin_password)
        self.assertEqual(self.client.post(self.add_url, payload).status_code, 409)

    def test_admin_does_not_bypass_login_limits_or_password_change_routes(self):
        self.assertRedirects(self.client.get("/admin/password_change/"), "/minha-senha/", fetch_redirect_response=False)
        self.client.post("/sair/")
        self.assertRedirects(self.client.post("/admin/login/", {"username": "adminseed", "password": self.admin_password}),
                             "/login/", fetch_redirect_response=False)

    def test_csrf_and_submission_token_are_both_required(self):
        client = Client(enforce_csrf_checks=True)
        client.get("/login/")
        client.post("/login/", {"username": "adminseed", "password": self.admin_password},
                    HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        payload = self.create_payload(self.token(self.add_url, client))
        self.assertEqual(client.post(self.add_url, payload).status_code, 403)
        payload.pop("submission_token")
        self.assertEqual(client.post(self.add_url, payload, HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value).status_code, 400)

    def test_changelist_rejects_hidden_field_lookups(self):
        for query in [{"password__startswith": "pbkdf2"}, {"access_version": "1"}, {"all": "1"}]:
            with self.subTest(query=query):
                self.assertEqual(self.client.get(self.list_url, query).status_code, 400)
