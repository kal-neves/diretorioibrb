from unittest.mock import patch

from django.contrib.admin.models import LogEntry
from django.db import OperationalError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts import services as accounts
from accounts.models import Account
from accounts.tests.test_services import FAST_HASHERS, example_mobile
from common.models import FormSubmission
from directory.models import Entry


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class DirectoryWebTests(TestCase):
    def setUp(self):
        self.password = accounts.seed_initial_admin()
        self.admin = Account.objects.get()
        self.secretary, temporary = accounts.create_account(
            operator_id=self.admin.pk, name="Secretaria", phone=example_mobile("GB"), role=Account.Role.SECRETARIAT)
        accounts.change_password(account_id=self.secretary.pk, current_password=temporary,
                                 new_password="secretaria123", confirmation="secretaria123")
        self.reader, temporary = accounts.create_account(operator_id=self.admin.pk, name="Consulta",
                                                          phone=example_mobile("BR"))
        accounts.change_password(account_id=self.reader.pk, current_password=temporary,
                                 new_password="consulta123", confirmation="consulta123")
        self.entry = Entry.objects.create(name="João", category=Entry.Category.MEMBER,
                                           email="privado@example.org", birth_day=3, birth_month=2,
                                           contact_phone=example_mobile("BR"))
        self.add_url = reverse("admin:directory_entry_add")
        self.list_url = reverse("admin:directory_entry_changelist")
        self.change_url = reverse("admin:directory_entry_change", args=[self.entry.pk])
        self.delete_url = reverse("admin:directory_entry_delete", args=[self.entry.pk])
        self.login("adminseed", self.password)

    def login(self, username, password, client=None):
        client = client or self.client
        client.post("/sair/")
        return client.post("/login/", {"username": username, "password": password})

    def payload(self, url=None):
        response = self.client.get(url or self.add_url)
        self.assertEqual(response.status_code, 200)
        return {"name": "Ana", "category": "PASTOR", "submission_token": response.context["form"]["submission_token"].value()}

    def test_secretariat_crud_uses_services_without_accounts_or_history(self):
        self.login(self.secretary.login_phone, "secretaria123")
        before = list(Account.objects.order_by("pk").values())
        self.assertContains(self.client.get("/admin/"), "Entradas do diretório")
        payload = self.payload()
        payload.update(contact_phone=example_mobile("BR"), email="privado@example.org")
        self.assertRedirects(self.client.post(self.add_url, payload), self.list_url)
        self.assertEqual(self.client.post(self.add_url, payload).status_code, 409)
        payload = self.payload(self.change_url)
        payload.update(name="José", birth_day=29, birth_month=2)
        self.assertRedirects(self.client.post(self.change_url, payload), self.list_url)
        self.entry.refresh_from_db()
        self.assertEqual((self.entry.name, self.entry.search_name), ("José", "jose"))
        self.assertIsNone(self.entry.email)
        self.assertEqual(self.client.post(self.change_url, payload).status_code, 409)
        token = self.payload(self.delete_url)["submission_token"]
        self.assertTrue(Entry.objects.filter(pk=self.entry.pk).exists())
        self.assertRedirects(self.client.post(self.delete_url, {"submission_token": token}), self.list_url)
        self.assertEqual(self.client.post(self.delete_url, {"submission_token": token}).status_code, 404)
        self.assertFalse(LogEntry.objects.exists())
        self.assertEqual(list(Account.objects.order_by("pk").values()), before)

    def test_validation_preserves_token_and_rejects_forged_fields(self):
        payload = self.payload()
        payload.update(birth_day=31, birth_month=2)
        self.assertEqual(self.client.post(self.add_url, payload).status_code, 400)
        self.assertIsNone(FormSubmission.objects.get().consumed_at)
        payload.update(birth_day=29, operator_id=self.admin.pk)
        self.assertEqual(self.client.post(self.add_url, payload).status_code, 400)
        payload.pop("operator_id")
        self.assertRedirects(self.client.post(self.add_url, payload), self.list_url)

    def test_csrf_and_submission_required(self):
        client = Client(enforce_csrf_checks=True)
        client.get("/login/")
        client.post("/login/", {"username": "adminseed", "password": self.password,
                               "csrfmiddlewaretoken": client.cookies["csrftoken"].value})
        response = client.get(self.add_url)
        data = {"name": "Nova", "category": "MEMBER", "submission_token": response.context["form"]["submission_token"].value()}
        self.assertEqual(client.post(self.add_url, data).status_code, 403)
        data["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
        data.pop("submission_token")
        self.assertEqual(client.post(self.add_url, data).status_code, 400)
        self.assertEqual(Entry.objects.count(), 1)

    def test_no_alternative_admin_writes_or_hidden_lookups(self):
        for params in ({"email__contains": "privado"}, {"action": "delete_selected"}):
            self.assertEqual(self.client.get(self.list_url, params).status_code, 400)
        self.assertEqual(self.client.post(self.list_url, {}).status_code, 405)
        self.assertEqual(self.client.get(f"/admin/directory/entry/{self.entry.pk}/history/").status_code, 404)
        self.assertNotContains(self.client.get(self.list_url), self.entry.email)
        self.assertContains(self.client.get(self.change_url), self.entry.email)

    def test_readonly_roles_and_anonymous_are_protected_everywhere(self):
        routes = ["/diretorio/", "/diretorio/lista/", "/diretorio/aniversariantes/", self.add_url, self.list_url,
                  self.change_url, self.delete_url]
        anonymous = Client()
        for url in routes:
            self.assertEqual(anonymous.get(url).status_code, 302)
            result = anonymous.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(result.status_code, 401)
            self.assertEqual(result["X-Access-Redirect"], "/login/")
        self.login(self.reader.login_phone, "consulta123")
        for url in routes:
            self.assertEqual(self.client.get(url).status_code, 403 if url.startswith("/admin/") else 200)
        for url in (self.add_url, self.change_url, self.delete_url):
            self.assertEqual(self.client.post(url, {}).status_code, 403)

    def test_pending_and_revoked_sessions_cannot_fetch_fragments(self):
        self.login(self.reader.login_phone, "consulta123")
        Account.objects.filter(pk=self.reader.pk).update(must_change_password=True)
        response = self.client.get("/diretorio/lista/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["X-Access-Redirect"], "/primeiro-acesso/")
        self.reader.refresh_from_db()
        Account.objects.filter(pk=self.reader.pk).update(access_version=self.reader.access_version + 1)
        response = self.client.get("/diretorio/aniversariantes/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.content, b"")

    def test_listing_and_birthdays_are_independent_and_private(self):
        self.login(self.reader.login_phone, "consulta123")
        response = self.client.get("/diretorio/", {"q": "inexistente", "month": 2})
        self.assertEqual(response.context["page"].total, 0)
        self.assertEqual(response.context["totals"].total, 1)
        self.assertContains(response, "João")
        for url, kind in (("/diretorio/lista/", "listing"), ("/diretorio/aniversariantes/", "birthdays")):
            fragment = self.client.get(url, {"q": "joao", "month": 2})
            self.assertEqual(fragment["X-Directory-Fragment"], kind)
            self.assertIn("no-store", fragment["Cache-Control"])
            self.assertContains(fragment, "João")
            self.assertNotContains(fragment, "privado@example.org")
            self.assertNotContains(fragment, "<!doctype")
            self.assertNotContains(fragment, "adminseed")
            self.assertEqual(self.client.post(url, {}).status_code, 405)
        self.assertNotContains(response, "privado@example.org")
        self.assertNotContains(response, "Administração")

    def test_filters_pagination_and_fallback_preserve_other_section(self):
        for index in range(21):
            Entry.objects.create(name=f"Álvaro {index:02}", category="DEACON")
        response = self.client.get("/diretorio/", {"q": "alvaro", "category": "DEACON", "month": 2, "page": 2})
        self.assertEqual(len(response.context["page"].items), 1)
        self.assertEqual(response.context["birthday_list"].month, 2)
        self.assertContains(response, 'name="month" value="2"')
        self.assertContains(response, 'name="page" value="2"')
        self.assertContains(response, "category=DEACON&amp;page=1&amp;month=2")
        response = self.client.get("/diretorio/", {"page": 999, "category": "UNKNOWN"})
        self.assertContains(response, "Nenhuma entrada encontrada")

    def test_text_is_escaped_and_contact_link_is_generated(self):
        Entry.objects.filter(pk=self.entry.pk).update(name='<script>alert("x")</script>')
        response = self.client.get("/diretorio/", {"month": 2})
        self.assertNotContains(response, '<script>alert("x")</script>')
        self.assertContains(response, "&lt;script&gt;")
        self.assertContains(response, f"https://wa.me/{self.entry.contact_phone[1:]}")

    def test_database_failure_is_not_an_empty_list(self):
        with patch("directory.views.list_entries", side_effect=OperationalError("private detail")):
            response = self.client.get("/diretorio/lista/")
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "private detail", status_code=503)
        self.assertNotIn("X-Directory-Fragment", response)

    def test_response_failure_after_commit_does_not_duplicate(self):
        payload = self.payload()
        with patch("directory.admin.messages.success", side_effect=OperationalError("private detail")):
            response = self.client.post(self.add_url, payload)
        self.assertContains(response, "A operação foi concluída", status_code=503)
        self.assertEqual(Entry.objects.count(), 2)
        self.login("adminseed", self.password)
        self.assertEqual(self.client.post(self.add_url, payload).status_code, 409)

    def test_tokens_cannot_move_between_operations_targets_or_sessions(self):
        payload = self.payload(self.change_url)
        token = payload["submission_token"]
        self.assertEqual(self.client.post(self.add_url, payload).status_code, 409)
        self.assertEqual(self.client.post(self.delete_url, {"submission_token": token}).status_code, 409)
        other = Entry.objects.create(name="Outra", category="MEMBER")
        self.assertEqual(self.client.post(reverse("admin:directory_entry_change", args=[other.pk]), payload).status_code, 409)
        self.login("adminseed", self.password)
        self.assertEqual(self.client.post(self.change_url, payload).status_code, 409)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.name, "João")

    def test_fixed_contact_has_phone_link_without_assuming_whatsapp(self):
        import phonenumbers

        phone = phonenumbers.example_number_for_type("GB", phonenumbers.PhoneNumberType.FIXED_LINE)
        formatted = phonenumbers.format_number(phone, phonenumbers.PhoneNumberFormat.E164)
        Entry.objects.filter(pk=self.entry.pk).update(contact_phone=formatted)
        response = self.client.get("/diretorio/")
        self.assertContains(response, f"tel:{formatted}")
        self.assertNotContains(response, "https://wa.me/")
