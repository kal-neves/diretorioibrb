import json
from http.client import HTTPException
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings

from .images import MAX_BYTES


class StorageUnavailable(Exception):
    pass


class PhotoMissing(Exception):
    pass


def check_key(key):
    if not re.fullmatch(r"[a-f0-9]{32}\.jpg", key):
        raise StorageUnavailable from None
    return key


class LocalPhotoStorage:
    def path(self, key):
        return Path(settings.PHOTO_STORAGE_ROOT) / check_key(key)

    def put(self, key, data):
        try:
            path = self.path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as file:
                file.write(data)
        except OSError:
            raise StorageUnavailable from None

    def get(self, key):
        try:
            with self.path(key).open("rb") as file:
                data = file.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise StorageUnavailable
            return data
        except FileNotFoundError:
            raise PhotoMissing from None
        except OSError:
            raise StorageUnavailable from None

    def delete(self, key):
        try:
            self.path(key).unlink(missing_ok=True)
        except OSError:
            raise StorageUnavailable from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SupabasePhotoStorage:
    def request(self, method, path, data=None, content_type="application/json"):
        base = settings.SUPABASE_URL.rstrip("/")
        parsed = urlsplit(base)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment
                or parsed.path or not settings.SUPABASE_STORAGE_KEY or not settings.SUPABASE_PHOTO_BUCKET):
            raise StorageUnavailable
        request = Request(base + "/storage/v1/" + path, data=data, method=method, headers={
            "Authorization": "Bearer " + settings.SUPABASE_STORAGE_KEY,
            "apikey": settings.SUPABASE_STORAGE_KEY, "Content-Type": content_type, "x-upsert": "false",
        })
        try:
            with build_opener(NoRedirect).open(request, timeout=10) as response:
                result = response.read(MAX_BYTES + 1)
                if len(result) > MAX_BYTES:
                    raise StorageUnavailable
                return result
        except HTTPError as error:
            try:
                code = json.loads(error.read(4096)).get("code")
            except (ValueError, AttributeError):
                code = None
            if error.code in {400, 404} and code == "NoSuchKey":
                raise PhotoMissing from None
            raise StorageUnavailable from None
        except (URLError, OSError, ValueError, HTTPException):
            raise StorageUnavailable from None

    def bucket(self):
        bucket = quote(settings.SUPABASE_PHOTO_BUCKET, safe="")
        try:
            metadata = json.loads(self.request("GET", "bucket/" + bucket))
            if metadata.get("public") is not False:
                raise StorageUnavailable
        except (ValueError, AttributeError, PhotoMissing):
            raise StorageUnavailable from None
        return bucket

    def put(self, key, data):
        try:
            self.request("POST", f"object/{self.bucket()}/{check_key(key)}", data, "image/jpeg")
        except PhotoMissing:
            raise StorageUnavailable from None

    def get(self, key):
        return self.request("GET", f"object/authenticated/{self.bucket()}/{check_key(key)}")

    def delete(self, key):
        bucket = self.bucket()
        try:
            self.request("DELETE", f"object/{bucket}", json.dumps({"prefixes": [check_key(key)]}).encode())
        except PhotoMissing:
            pass


def photo_storage():
    if settings.PHOTO_STORAGE_BACKEND == "local" and settings.DEBUG:
        return LocalPhotoStorage()
    if settings.PHOTO_STORAGE_BACKEND == "supabase":
        return SupabasePhotoStorage()
    raise StorageUnavailable
