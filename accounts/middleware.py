from django.conf import settings
from django.contrib.auth import SESSION_KEY, logout
from django.contrib.sessions.exceptions import SessionInterrupted
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import DatabaseError
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.utils.deprecation import MiddlewareMixin

from .sessions import session_is_current


def public_route(view):
    view.public_route = True
    return view


def pending_password_route(view):
    view.pending_password_route = True
    return view


def staff_route(view):
    view.staff_route = True
    return view


def access_redirect(request, destination, *, status=401):
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return HttpResponse(status=status, headers={"X-Access-Redirect": destination})
    return HttpResponseRedirect(destination)


def unavailable(request):
    if getattr(request, "password_changed", False):
        message = "A senha foi alterada, mas não foi possível manter a sessão. Entre novamente com a nova senha."
    elif getattr(request, "operation_committed", False):
        message = "A operação foi concluída, mas houve uma falha na resposta. Confira a lista antes de tentar novamente. Senhas temporárias não serão exibidas novamente."
    else:
        message = "Não foi possível acessar o sistema agora. Tente novamente mais tarde."
    response = HttpResponse(message, status=503, content_type="text/plain; charset=utf-8")
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path=settings.SESSION_COOKIE_PATH,
                           domain=settings.SESSION_COOKIE_DOMAIN, samesite=settings.SESSION_COOKIE_SAMESITE)
    add_never_cache_headers(response)
    return response


class PrivateSessionMiddleware(SessionMiddleware):
    def process_response(self, request, response):
        try:
            response = super().process_response(request, response)
        except (DatabaseError, SessionInterrupted):
            response = unavailable(request)
        add_never_cache_headers(response)
        return response


class AccessMiddleware(MiddlewareMixin):
    def process_view(self, request, view, args, kwargs):
        try:
            return self.check_access(request, view)
        except DatabaseError:
            return unavailable(request)

    def check_access(self, request, view):
        if getattr(view, "operational_route", False):
            return None
        had_session = SESSION_KEY in request.session
        if not session_is_current(request):
            if had_session:
                logout(request)
            if getattr(view, "public_route", False):
                return None
            return access_redirect(request, reverse("accounts:login"))
        if request.user.must_change_password:
            if not getattr(view, "pending_password_route", False):
                return access_redirect(request, reverse("accounts:required_password"), status=403)
        is_admin = "admin" in request.resolver_match.namespaces
        if (getattr(view, "staff_route", False) or is_admin) and not request.user.is_staff:
            return HttpResponse("Acesso não permitido.", status=403, content_type="text/plain; charset=utf-8")
        return None

    def process_exception(self, request, exception):
        if isinstance(exception, (DatabaseError, SessionInterrupted)):
            return unavailable(request)
        return None
