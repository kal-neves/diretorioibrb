from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch
from urllib.error import HTTPError

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import Account
from accounts.services import create_account, change_password, seed_initial_admin
from accounts.tests.test_services import FAST_HASHERS, example_mobile
from common.models import FormSubmission
from common.submissions import SubmissionProof, SubmissionRejected, issue_submission
from directory.images import MAX_BYTES, process_photo
from directory.models import Entry, Photo
from directory.photos import cleanup_photos
from directory.services import create_entry, delete_entry, update_entry
from directory.storage import LocalPhotoStorage, PhotoMissing, StorageUnavailable, SupabasePhotoStorage


def upload(format="JPEG", size=(40, 30), **options):
    stream = BytesIO()
    Image.new("RGB", size, "red").save(stream, format=format, **options)
    return SimpleUploadedFile("nome-privado.dat", stream.getvalue(), content_type="application/octet-stream")


class ImageTests(SimpleTestCase):
    def test_formats_reencoded_without_metadata_and_orientation_preserved(self):
        for format in ("JPEG", "PNG", "WEBP"):
            exif = Image.Exif()
            exif[274] = 6
            exif[315] = "Nome privado"
            data, width, height = process_photo(upload(format, exif=exif))
            self.assertEqual((width, height), (30, 40))
            with Image.open(BytesIO(data)) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertFalse(image.getexif())
            self.assertNotIn(b"Nome privado", data)

    def test_size_dimensions_invalid_content_and_animation(self):
        animated = BytesIO()
        Image.new("RGB", (10, 10), "red").save(animated, format="PNG", save_all=True,
                                               append_images=[Image.new("RGB", (10, 10), "blue")], duration=100)
        cases = [BytesIO(b"<svg></svg>"), BytesIO(b"a" * (MAX_BYTES + 1)), BytesIO(animated.getvalue()),
                 upload(size=(1201, 1)), BytesIO(upload().read()[:30]), upload("GIF")]
        for case in cases:
            with self.subTest(case=type(case)), self.assertRaises(ValidationError):
                process_photo(case)


@override_settings(PASSWORD_HASHERS=FAST_HASHERS, DEBUG=True, PHOTO_STORAGE_BACKEND="local")
class PhotoTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        settings = override_settings(PHOTO_STORAGE_ROOT=self.temporary.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.password = seed_initial_admin()
        self.admin = Account.objects.get()
        self.client.post("/login/", {"username": "adminseed", "password": self.password})

    def create(self, **values):
        return create_entry(operator_id=self.admin.pk, name="Pessoa", category="MEMBER", photo=upload(), **values)

    def proof(self):
        now = timezone.now().timestamp()
        token = issue_submission(session_key="test", authenticated_at=now, operation="directory.create")
        return SubmissionProof(token, "test", self.admin.access_version, now)

    def url(self, entry):
        return reverse("directory:photo", args=[entry.pk, entry.photo_id])

    def expire_staged(self):
        Photo.objects.filter(state="STAGED").update(lease_until=timezone.now() - timedelta(seconds=1))

    def test_create_replace_remove_and_delete_queue_files(self):
        entry = self.create()
        first = entry.photo
        self.assertEqual(first.state, "ATTACHED")
        self.assertTrue(Path(self.temporary.name, first.object_key).exists())
        old_url = self.url(entry)
        entry = update_entry(operator_id=self.admin.pk, entry_id=entry.pk, photo=upload("PNG"))
        first.refresh_from_db()
        self.assertEqual(first.state, "PENDING_DELETE")
        self.assertEqual(self.client.get(old_url).status_code, 404)
        self.assertEqual(cleanup_photos(), 1)
        self.assertFalse(Path(self.temporary.name, first.object_key).exists())
        update_entry(operator_id=self.admin.pk, entry_id=entry.pk, remove_photo=True)
        entry.refresh_from_db()
        self.assertIsNone(entry.photo_id)
        self.assertEqual(cleanup_photos(), 1)
        entry = update_entry(operator_id=self.admin.pk, entry_id=entry.pk, photo=upload())
        delete_entry(operator_id=self.admin.pk, entry_id=entry.pk)
        self.assertEqual(cleanup_photos(), 1)
        self.assertFalse(Photo.objects.exists())
        self.assertEqual(Account.objects.count(), 1)

    def test_storage_failure_preserves_entry_and_submission_and_retains_reservation(self):
        entry = self.create()
        original = entry.photo_id
        with patch.object(LocalPhotoStorage, "put", side_effect=StorageUnavailable), self.assertRaises(StorageUnavailable):
            update_entry(operator_id=self.admin.pk, entry_id=entry.pk, name="Alterado", photo=upload())
        entry.refresh_from_db()
        self.assertEqual((entry.name, entry.photo_id), ("Pessoa", original))
        self.assertEqual(Photo.objects.filter(state="STAGED").count(), 1)
        self.expire_staged()
        self.assertEqual(cleanup_photos(), 1)
        self.assertEqual(Photo.objects.get().pk, original)

    def test_commit_failure_after_upload_is_reconciled_without_consuming_token(self):
        proof = self.proof()
        with patch("directory.services.attach_photo", side_effect=ValidationError("falha")), self.assertRaises(ValidationError):
            self.create(submission=proof)
        self.assertFalse(Entry.objects.exists())
        self.assertIsNone(FormSubmission.objects.get().consumed_at)
        self.assertEqual(len(list(Path(self.temporary.name).iterdir())), 1)
        self.expire_staged()
        self.assertEqual(cleanup_photos(), 1)
        self.create(submission=proof)
        with patch.object(LocalPhotoStorage, "put") as put, self.assertRaises(SubmissionRejected):
            self.create(submission=proof)
        put.assert_not_called()

    def test_revocation_during_upload_prevents_attachment(self):
        proof = self.proof()
        original_put = LocalPhotoStorage.put

        def put(storage, key, data):
            original_put(storage, key, data)
            Account.objects.filter(pk=self.admin.pk).update(access_version=2)

        with patch.object(LocalPhotoStorage, "put", put), self.assertRaises(PermissionDenied):
            self.create(submission=proof)
        self.assertFalse(Entry.objects.exists())
        self.expire_staged()
        self.assertEqual(cleanup_photos(), 1)

    def test_cleanup_retries_errors_and_never_deletes_attached_or_active_upload(self):
        entry = self.create()
        Photo.objects.create(lease_until=timezone.now() + timedelta(hours=1))
        self.assertEqual(cleanup_photos(), 0)
        update_entry(operator_id=self.admin.pk, entry_id=entry.pk, remove_photo=True)
        with patch.object(LocalPhotoStorage, "delete", side_effect=StorageUnavailable):
            self.assertEqual(cleanup_photos(), 0)
        row = Photo.objects.get(state="PENDING_DELETE")
        self.assertEqual(row.last_error_code, "storage_unavailable")
        self.assertEqual(row.attempt_count, 1)
        self.assertEqual(cleanup_photos(), 0)
        Photo.objects.filter(pk=row.pk).update(next_attempt_at=timezone.now())
        self.assertEqual(cleanup_photos(), 1)

    def test_private_endpoint_and_revoked_session(self):
        entry = self.create()
        url = self.url(entry)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(Client().get(url).status_code, 302)
        account, temporary = create_account(operator_id=self.admin.pk, name="Consulta", phone=example_mobile("BR"))
        reader = Client()
        reader.post("/login/", {"username": account.login_phone, "password": temporary})
        self.assertEqual(reader.get(url).status_code, 302)
        change_password(account_id=account.pk, current_password=temporary, new_password="consulta123", confirmation="consulta123")
        reader.post("/login/", {"username": account.login_phone, "password": "consulta123"})
        self.assertEqual(reader.get(url).status_code, 200)
        Account.objects.filter(pk=account.pk).update(is_active=False)
        self.assertEqual(reader.get(url).status_code, 302)
        with patch.object(LocalPhotoStorage, "get", side_effect=PhotoMissing):
            self.assertEqual(self.client.get(url).status_code, 404)
        with patch.object(LocalPhotoStorage, "get", side_effect=StorageUnavailable):
            self.assertEqual(self.client.get(url).status_code, 503)

    def test_old_or_unattached_id_never_reads_storage(self):
        entry = self.create()
        other = Photo.objects.create(lease_until=timezone.now() + timedelta(hours=1))
        with patch.object(LocalPhotoStorage, "get") as get:
            self.assertEqual(self.client.get(reverse("directory:photo", args=[entry.pk, other.pk])).status_code, 404)
        get.assert_not_called()

    def test_admin_upload_and_total_body_limit(self):
        url = reverse("admin:directory_entry_add")
        response = self.client.get(url)
        token = response.context["form"]["submission_token"].value()
        payload = {"name": "Pessoa", "category": "MEMBER", "submission_token": token, "photo": upload()}
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(Photo.objects.get().state, "ATTACHED")
        response = self.client.post(url, b"x" * (2 * 1024 * 1024 + 1), content_type="application/octet-stream")
        self.assertEqual(response.status_code, 413)
        self.assertIn("no-store", response["Cache-Control"])

    def test_read_rechecks_revocation_and_replacement_during_download(self):
        entry = self.create()
        url = self.url(entry)
        original_get = LocalPhotoStorage.get

        def revoke(storage, key):
            data = original_get(storage, key)
            Account.objects.filter(pk=self.admin.pk).update(access_version=2)
            return data

        with patch.object(LocalPhotoStorage, "get", revoke):
            self.assertEqual(self.client.get(url).status_code, 401)

    def test_cleanup_protects_referenced_objects_even_if_state_is_inconsistent(self):
        entry = self.create()
        Photo.objects.filter(pk=entry.photo_id).update(state="PENDING_DELETE")
        self.assertEqual(cleanup_photos(), 0)
        self.assertTrue(Path(self.temporary.name, entry.photo.object_key).exists())

    def test_expired_upload_cannot_attach_after_cleanup(self):
        original_put = LocalPhotoStorage.put

        def put(storage, key, data):
            original_put(storage, key, data)
            self.expire_staged()
            self.assertEqual(cleanup_photos(), 1)

        with patch.object(LocalPhotoStorage, "put", put), self.assertRaises(ValidationError):
            self.create()
        self.assertFalse(Entry.objects.exists())
        self.assertFalse(Photo.objects.exists())

    def test_invalid_form_does_not_upload_or_reserve(self):
        with patch.object(LocalPhotoStorage, "put") as put, self.assertRaises(ValidationError):
            create_entry(operator_id=self.admin.pk, name="", category="MEMBER", photo=upload())
        put.assert_not_called()
        self.assertFalse(Photo.objects.exists())


@override_settings(SUPABASE_URL="https://example.supabase.co", SUPABASE_STORAGE_KEY="test-secret", SUPABASE_PHOTO_BUCKET="photos")
class StorageTests(SimpleTestCase):
    def test_supabase_private_bucket_checked_and_payload_contract(self):
        storage = SupabasePhotoStorage()
        with patch.object(storage, "request", side_effect=[b'{"public": false}', b'{}']) as request:
            storage.put("a" * 32 + ".jpg", b"jpeg")
        self.assertEqual(request.call_args_list[0].args, ("GET", "bucket/photos"))
        self.assertEqual(request.call_args_list[1].args, ("POST", "object/photos/" + "a" * 32 + ".jpg", b"jpeg", "image/jpeg"))
        with patch.object(storage, "request", return_value=b'{"public": true}') as request, self.assertRaises(StorageUnavailable):
            storage.get("a" * 32 + ".jpg")
        self.assertEqual(request.call_count, 1)

    def test_errors_do_not_expose_credentials_and_only_missing_key_is_idempotent(self):
        storage = SupabasePhotoStorage()
        for status, body, exception in [(404, b'{"code":"NoSuchKey"}', PhotoMissing),
                                         (404, b'{"code":"NoSuchBucket"}', StorageUnavailable),
                                         (401, b'test-secret', StorageUnavailable)]:
            error = HTTPError("https://example.supabase.co", status, "private", {}, BytesIO(body))
            with patch("directory.storage.build_opener") as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaises(exception) as caught:
                    storage.request("GET", "object/authenticated/photos/key")
                self.assertNotIn("test-secret", str(caught.exception))


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class PhotoConcurrencyTests(TransactionTestCase):
    def test_concurrent_cleanup_claims_each_object_once(self):
        Photo.objects.create(state="PENDING_DELETE")
        barrier = Barrier(2)

        def cleanup():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return cleanup_photos()
            finally:
                close_old_connections()

        def delete(key):
            self.assertFalse(connection.in_atomic_block)

        with patch("directory.photos.photo_storage") as storage:
            storage.return_value.delete.side_effect = delete
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(cleanup) for _ in range(2)]
                self.assertEqual(sum(future.result(timeout=20) for future in futures), 1)
            self.assertEqual(storage.return_value.delete.call_count, 1)

    def test_simultaneous_replay_attaches_once_and_external_io_has_no_transaction(self):
        seed_initial_admin()
        operator = Account.objects.get()
        started = timezone.now().timestamp()
        token = issue_submission(session_key="test", authenticated_at=started, operation="directory.create")
        proof = SubmissionProof(token, "test", operator.access_version, started)
        barrier = Barrier(2)

        def put(key, data):
            self.assertFalse(connection.in_atomic_block)
            barrier.wait(timeout=10)

        def create():
            close_old_connections()
            try:
                create_entry(operator_id=operator.pk, name="Pessoa", category="MEMBER", photo=upload(), submission=proof)
                return True
            except SubmissionRejected:
                return False
            finally:
                close_old_connections()

        with patch("directory.services.photo_storage") as storage:
            storage.return_value.put.side_effect = put
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(create) for _ in range(2)]
                self.assertEqual(sorted(future.result(timeout=20) for future in futures), [False, True])
        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(Photo.objects.filter(state="ATTACHED").count(), 1)
        self.assertEqual(Photo.objects.filter(state="STAGED").count(), 1)
