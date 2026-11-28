from datetime import timedelta

from django.contrib import admin, messages
from django.contrib.admin.models import LogEntry
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponseBadRequest, HttpResponseNotAllowed
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from common.submissions import SubmissionProof, SubmissionRejected, issue_submission

from . import services
from .admin_forms import AccountManagementForm, SubmissionForm
from .models import Account
from .policies import is_expired_new_account, require_manage_target, require_manager
from .sessions import ACCESS_VERSION, AUTHENTICATED_AT, session_is_current
from .views import sign_out


class ChurchAdminSite(admin.AdminSite):
    site_header = "Administração IBRB"
    site_title = "IBRB"
    index_title = "Administração"
    site_url = None
    enable_nav_sidebar = False

    def has_permission(self, request):
        return session_is_current(request) and request.user.is_staff and not request.user.must_change_password

    def login(self, request, extra_context=None):
        return redirect("accounts:login")

    def logout(self, request, extra_context=None):
        return sign_out(request)

    def password_change(self, request, extra_context=None):
        return redirect("accounts:password")

    def password_change_done(self, request, extra_context=None):
        return redirect("accounts:password")

    def get_log_entries(self, request):
        return LogEntry.objects.none()


site = ChurchAdminSite(name="admin")


@admin.register(Account, site=site)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "identity", "role", "access_state", "password_state", "account_actions")
    list_per_page = 20
    list_max_show_all = 0
    actions = None
    ordering = ("name", "pk")
    show_full_result_count = False
    change_list_template = "admin/accounts/account/list.html"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.role == Account.Role.SECRETARIAT:
            queryset = queryset.filter(role=Account.Role.CONSULTATION)
        return queryset

    def changelist_view(self, request, extra_context=None):
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET"])
        if set(request.GET) - {"p", "o", "e"}:
            return HttpResponseBadRequest("Parâmetros de consulta não permitidos.")
        return super().changelist_view(request, extra_context)

    def has_module_permission(self, request):
        return self.admin_site.has_permission(request)

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request) and (
            obj is None or request.user.role == Account.Role.INITIAL_ADMIN or obj.role == Account.Role.CONSULTATION
        )

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj) and (obj is None or obj.role != Account.Role.INITIAL_ADMIN)

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)

    def get_urls(self):
        return [path("<int:object_id>/operation/<str:operation>/", self.admin_site.admin_view(self.operation_view),
                     name="accounts_account_operation")] + super().get_urls()

    @admin.display(description="Celular de login ou usuário")
    def identity(self, obj):
        return obj.get_username()

    @admin.display(description="Situação de acesso")
    def access_state(self, obj):
        return "Ativa" if obj.is_active else "Desativada"

    @admin.display(description="Troca de senha")
    def password_state(self, obj):
        if obj.role == Account.Role.INITIAL_ADMIN:
            return "Permanente"
        if obj.first_password_changed_at is None:
            if is_expired_new_account(obj):
                return "Prazo inicial encerrado"
            deadline = timezone.localtime(obj.created_at + timedelta(days=7)).strftime("%d/%m/%Y %H:%M")
            return f"Aguardando primeira troca até {deadline} (Belém)"
        return "Troca após restauração" if obj.must_change_password else "Sem pendência"

    @admin.display(description="Ações")
    def account_actions(self, obj):
        if obj.role == Account.Role.INITIAL_ADMIN:
            return "Conta permanente"
        return format_html('<a href="{}">Gerenciar conta</a>', reverse("admin:accounts_account_change", args=[obj.pk]))

    def context(self, request, *, title, account=None):
        return {**self.admin_site.each_context(request), "opts": self.model._meta,
                "title": title, "account": account, "list_url": reverse("admin:accounts_account_changelist")}

    def target(self, request, object_id):
        account = self.get_object(request, object_id)
        if account is None:
            raise Http404("Esta conta não está disponível. Atualize a lista.")
        return account

    def token(self, request, operation, account=None):
        return issue_submission(session_key=request.session.session_key,
                                authenticated_at=request.session[AUTHENTICATED_AT], operation=operation,
                                binding=str(account.pk) if account else "")

    def proof(self, request, form):
        return SubmissionProof(token=form.cleaned_data["submission_token"], session_key=request.session.session_key,
                               access_version=request.session[ACCESS_VERSION],
                               authenticated_at=request.session[AUTHENTICATED_AT])

    def add_error(self, form, error):
        if hasattr(error, "message_dict"):
            for field, errors in error.message_dict.items():
                field = "phone" if field == "login_phone" else field
                form.add_error(field if field in form.fields else None, errors)
        else:
            form.add_error(None, error)

    @sensitive_variables("password")
    def credential_response(self, request, account, password, title):
        request.operation_committed = True
        context = self.context(request, title=title, account=account)
        context.update(temporary_password=password,
                       first_change_deadline=account.created_at + timedelta(days=7) if account.first_password_changed_at is None else None)
        return TemplateResponse(request, "admin/accounts/account/credential.html", context)

    def add_view(self, request, form_url="", extra_context=None):
        return self.edit_view(request)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        return self.edit_view(request, object_id)

    @sensitive_variables("password")
    def edit_view(self, request, object_id=None):
        require_manager(request.user)
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])
        account = self.target(request, object_id) if object_id else None
        context = self.context(request, title="Editar conta de acesso" if account else "Criar conta de acesso", account=account)
        if account and account.role == Account.Role.INITIAL_ADMIN:
            if request.method != "GET":
                raise PermissionDenied
            return TemplateResponse(request, "admin/accounts/account/permanent.html", context)
        if account:
            require_manage_target(request.user, account)
        operation = "account.update" if account else "account.create"
        initial = {"name": account.name, "phone": account.login_phone, "role": account.role} if account else {"role": Account.Role.CONSULTATION}
        if request.method == "GET":
            initial["submission_token"] = self.token(request, operation, account)
        form = AccountManagementForm(request.POST if request.method == "POST" else None,
                                     initial=initial, operator=request.user)
        status = 200
        if request.method == "POST" and form.is_valid():
            values = {key: value for key, value in form.cleaned_data.items() if key != "submission_token"}
            try:
                if account:
                    services.update_account(operator_id=request.user.pk, account_id=account.pk,
                                            submission=self.proof(request, form), **values)
                    request.operation_committed = True
                else:
                    account, password = services.create_account(operator_id=request.user.pk,
                                                                submission=self.proof(request, form), **values)
                    request.operation_committed = True
                    return self.credential_response(request, account, password, "Conta criada")
            except ValidationError as error:
                self.add_error(form, error)
                status = 409 if isinstance(error, SubmissionRejected) else 400
            else:
                request.operation_committed = True
                messages.success(request, "Conta atualizada.")
                return redirect("admin:accounts_account_changelist")
        elif request.method == "POST":
            status = 400
        context.update(form=form, creating=account is None,
                       can_restore=account is not None and account.first_password_changed_at is not None)
        return TemplateResponse(request, "admin/accounts/account/form.html", context, status=status)

    def delete_view(self, request, object_id, extra_context=None):
        return self.operation_view(request, object_id, "delete")

    @sensitive_variables("password")
    def operation_view(self, request, object_id, operation):
        require_manager(request.user)
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])
        actions = {
            "activate": ("Ativar conta", "O acesso será permitido, respeitando eventual troca de senha pendente."),
            "deactivate": ("Desativar conta", "A conta será preservada e perderá acesso, inclusive nas sessões abertas."),
            "restore": ("Restaurar senha", "Será emitida uma senha temporária. A situação ativa ou desativada será preservada."),
            "delete": ("Deletar conta", "A conta será excluída definitivamente e perderá acesso."),
        }
        if operation not in actions:
            raise Http404
        account = self.target(request, object_id)
        require_manage_target(request.user, account)
        title, explanation = actions[operation]
        context = self.context(request, title=title, account=account)
        context["explanation"] = explanation
        initial = {"submission_token": self.token(request, f"account.{operation}", account)} if request.method == "GET" else None
        form = SubmissionForm(request.POST if request.method == "POST" else None, initial=initial)
        status = 200
        if request.method == "POST" and form.is_valid():
            values = {"operator_id": request.user.pk, "account_id": account.pk, "submission": self.proof(request, form)}
            try:
                if operation == "delete":
                    services.delete_account(**values)
                    request.operation_committed = True
                elif operation == "restore":
                    password = services.restore_password(**values)
                    request.operation_committed = True
                    account.refresh_from_db()
                    return self.credential_response(request, account, password, "Senha restaurada")
                else:
                    services.update_account(**values, is_active=operation == "activate")
                    request.operation_committed = True
            except ValidationError as error:
                self.add_error(form, error)
                status = 409 if isinstance(error, SubmissionRejected) else 400
            else:
                request.operation_committed = True
                messages.success(request, "Operação concluída.")
                return redirect("admin:accounts_account_changelist")
        elif request.method == "POST":
            status = 400
        context["form"] = form
        return TemplateResponse(request, "admin/accounts/account/confirm.html", context, status=status)

    def history_view(self, request, object_id, extra_context=None):
        raise PermissionDenied

    def save_model(self, request, obj, form, change):
        raise PermissionDenied

    def delete_model(self, request, obj):
        raise PermissionDenied

    def delete_queryset(self, request, queryset):
        raise PermissionDenied

    def log_addition(self, request, obj, message):
        pass

    def log_change(self, request, obj, message):
        pass

    def log_deletions(self, request, queryset):
        pass
