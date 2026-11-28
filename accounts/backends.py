from django.contrib.auth.backends import BaseBackend
from django.core.exceptions import PermissionDenied
from django.views.decorators.debug import sensitive_variables

from .authentication import authenticate_attempt, client_ip
from .models import Account


class PhoneBackend(BaseBackend):
    @sensitive_variables("password")
    def authenticate(self, request, username=None, password=None, country=None, **kwargs):
        if request is None or username is None or password is None:
            raise PermissionDenied
        return authenticate_attempt(identifier=username, password=password, country=country, ip=client_ip(request))

    def get_user(self, user_id):
        return Account.objects.filter(pk=user_id).first()
