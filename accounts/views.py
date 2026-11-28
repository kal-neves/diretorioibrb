from django.contrib.auth import authenticate, logout
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .authentication import LoginRejected
from .forms import ChangePasswordForm, LoginForm, NewPasswordForm
from .middleware import access_redirect, pending_password_route, public_route
from .services import change_password, complete_required_password_change
from .sessions import ACCESS_VERSION, AUTHENTICATED_AT, refresh_after_password_change, start_session


def destination(account):
    if account.must_change_password:
        return reverse("accounts:required_password")
    return "/admin/" if account.is_staff else "/diretorio/"


def safe_next(request, value):
    if value.startswith("/") and not value.startswith("//") and url_has_allowed_host_and_scheme(
        value, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return value
    return ""


@public_route
@require_GET
def entry(request):
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    return HttpResponseRedirect(destination(request.user))


@public_route
@sensitive_post_parameters("password")
@require_http_methods(["GET", "POST"])
def sign_in(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect(destination(request.user))
    form = LoginForm(request.POST if request.method == "POST" else None)
    next_url = safe_next(request, request.POST.get("next", request.GET.get("next", "")))
    status = 200
    retry_after = None
    if request.method == "POST" and form.is_valid():
        try:
            account = authenticate(request, **form.cleaned_data)
            if account is None:
                raise LoginRejected()
            start_session(request, account)
            return HttpResponseRedirect(destination(account) if account.must_change_password else next_url or destination(account))
        except LoginRejected as error:
            form.add_error(None, error.message)
            retry_after = error.retry_after
            status = 429 if retry_after else 200
    response = render(request, "accounts/login.html", {"form": form, "next_url": next_url}, status=status)
    if retry_after:
        response["Retry-After"] = str(retry_after)
    return response


def password_errors(form, error):
    if hasattr(error, "message_dict"):
        for field, messages in error.message_dict.items():
            form.add_error(field if field in form.fields else None, messages)
    else:
        form.add_error("new_password", error)


def password_form(request, *, required):
    if required != request.user.must_change_password:
        return HttpResponseRedirect(destination(request.user))
    form_class = NewPasswordForm if required else ChangePasswordForm
    form = form_class(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        operation = complete_required_password_change if required else change_password
        try:
            account = operation(
                account_id=request.user.pk, expected_version=request.session[ACCESS_VERSION],
                authenticated_at=request.session[AUTHENTICATED_AT], **form.cleaned_data,
            )
        except ValidationError as error:
            if getattr(error, "code", None) == "account_unavailable":
                logout(request)
                return access_redirect(request, reverse("accounts:login"))
            password_errors(form, error)
        except PermissionDenied:
            logout(request)
            return access_redirect(request, reverse("accounts:login"))
        else:
            request.password_changed = True
            if not refresh_after_password_change(request, account):
                return redirect("accounts:login")
            return HttpResponseRedirect(destination(account))
    return render(request, "accounts/password.html", {"form": form, "required_change": required})


@pending_password_route
@sensitive_post_parameters("new_password", "confirmation")
@require_http_methods(["GET", "POST"])
def required_password(request):
    return password_form(request, required=True)


@sensitive_post_parameters("current_password", "new_password", "confirmation")
@require_http_methods(["GET", "POST"])
def voluntary_password(request):
    return password_form(request, required=False)


@pending_password_route
@require_POST
def sign_out(request):
    logout(request)
    return redirect("accounts:login")
