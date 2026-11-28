from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from accounts.models import Account
from accounts.services import create_account, seed_initial_admin
from accounts.tests.test_services import FAST_HASHERS, example_mobile
from common.models import FormSubmission
from common.submissions import SubmissionProof, SubmissionRejected, clear_expired_submissions, issue_submission


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SubmissionTests(TestCase):
    def setUp(self):
        seed_initial_admin()
        self.admin = Account.objects.get()
        self.started = timezone.now().timestamp()
        token = issue_submission(session_key="session-one", authenticated_at=self.started, operation="account.create")
        self.proof = SubmissionProof(token, "session-one", self.admin.access_version, self.started)

    def create(self, proof=None, name="Nova", phone=None):
        return create_account(operator_id=self.admin.pk, name=name, phone=phone or example_mobile("BR"),
                              submission=proof or self.proof)

    def test_replay_rejected_even_when_payload_changes(self):
        account, password = self.create()
        for phone in [example_mobile("BR"), example_mobile("GB")]:
            with self.assertRaises(SubmissionRejected):
                self.create(phone=phone)
        self.assertEqual(Account.objects.count(), 2)
        self.assertTrue(Account.objects.get(pk=account.pk).check_password(password))
        row = FormSubmission.objects.get()
        self.assertIsNotNone(row.consumed_at)
        self.assertNotIn(password, str(row.__dict__))
        self.assertNotIn(self.proof.token, str(row.__dict__))
        self.assertNotIn("session-one", str(row.__dict__))

    def test_failed_mutation_rolls_back_token_and_can_be_corrected(self):
        with self.assertRaises(ValidationError):
            self.create(name=" ")
        self.assertIsNone(FormSubmission.objects.get().consumed_at)
        self.create()
        self.assertIsNotNone(FormSubmission.objects.get().consumed_at)

    def test_other_session_or_unknown_token_rejected(self):
        for proof in [replace(self.proof, session_key="other"), replace(self.proof, token="wrong")]:
            with self.assertRaises(SubmissionRejected):
                self.create(proof)
        self.assertEqual(Account.objects.count(), 1)

    def test_expired_token_and_revoked_operator_rejected(self):
        row = FormSubmission.objects.get()
        FormSubmission.objects.update(created_at=timezone.now() - timedelta(hours=2),
                                      expires_at=timezone.now() - timedelta(hours=1))
        with self.assertRaises(SubmissionRejected):
            self.create()
        row.expires_at = timezone.now() + timedelta(minutes=10)
        row.save(update_fields=["expires_at"])
        Account.objects.filter(pk=self.admin.pk).update(access_version=2)
        with self.assertRaises(PermissionDenied):
            self.create()
        self.assertIsNone(FormSubmission.objects.get().consumed_at)

    def test_operation_binding_and_deadline(self):
        token = issue_submission(session_key="session-one", authenticated_at=self.started - 3500,
                                 operation="account.update", binding="42")
        with self.assertRaises(SubmissionRejected):
            self.create(replace(self.proof, token=token))
        row = FormSubmission.objects.exclude(operation="account.create").get()
        self.assertLessEqual((row.expires_at - timezone.now()).total_seconds(), 100)

    def test_cleanup_keeps_current_tokens(self):
        FormSubmission.objects.update(created_at=timezone.now() - timedelta(hours=2),
                                      expires_at=timezone.now() - timedelta(hours=1))
        issue_submission(session_key="other", authenticated_at=self.started, operation="account.create")
        self.assertEqual(clear_expired_submissions(), 1)
        self.assertEqual(FormSubmission.objects.count(), 1)


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SubmissionConcurrencyTests(TransactionTestCase):
    def test_same_token_with_different_payload_commits_only_one_creation(self):
        seed_initial_admin()
        admin = Account.objects.get()
        now = timezone.now().timestamp()
        token = issue_submission(session_key="session", authenticated_at=now, operation="account.create")
        proof = SubmissionProof(token, "session", admin.access_version, now)
        barrier = Barrier(2)

        def create(region):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                create_account(operator_id=admin.pk, name="Concorrente", phone=example_mobile(region), submission=proof)
                return True
            except SubmissionRejected:
                return False
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(create, region) for region in ["BR", "GB"]]
            self.assertEqual(sorted(f.result(timeout=20) for f in futures), [False, True])
        self.assertEqual(Account.objects.count(), 2)
