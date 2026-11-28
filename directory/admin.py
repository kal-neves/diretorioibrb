from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponseBadRequest, HttpResponseNotAllowed
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from accounts.admin import site
from accounts.admin_forms import SubmissionForm
from accounts.policies import require_manager
from accounts.sessions import ACCESS_VERSION, AUTHENTICATED_AT
from common.submissions import SubmissionProof, SubmissionRejected, issue_submission

from . import services
from .forms import EntryForm
from .models import Entry
from .queries import list_entries
from .storage import StorageUnavailable


@admin.register(Entry, site=site)
class EntryAdmin(admin.ModelAdmin):
    actions = None

    def has_module_permission(self, request):
        return self.admin_site.has_permission(request)

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def get_urls(self):
        wrap = self.admin_site.admin_view
        return [
            path("", wrap(self.changelist_view), name="directory_entry_changelist"),
            path("add/", wrap(self.add_view), name="directory_entry_add"),
            path("<int:object_id>/change/", wrap(self.change_view), name="directory_entry_change"),
            path("<int:object_id>/delete/", wrap(self.delete_view), name="directory_entry_delete"),
        ]

    def context(self, request, title):
        return {**self.admin_site.each_context(request), "opts": self.model._meta, "title": title,
                "list_url": reverse("admin:directory_entry_changelist")}

    def changelist_view(self, request, extra_context=None):
        require_manager(request.user)
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET"])
        if set(request.GET) - {"q", "category", "page"}:
            return HttpResponseBadRequest("Parâmetros de consulta não permitidos.")
        context = self.context(request, "Entradas do diretório")
        context.update(page=list_entries(query=request.GET.get("q"), category=request.GET.get("category"),
                                         page=request.GET.get("page")), categories=Entry.Category.choices)
        return TemplateResponse(request, "admin/directory/entry/list.html", context)

    def add_view(self, request, form_url="", extra_context=None):
        return self.edit_view(request)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        return self.edit_view(request, object_id)

    def delete_view(self, request, object_id, extra_context=None):
        return self.edit_view(request, object_id, deleting=True)

    def edit_view(self, request, object_id=None, deleting=False):
        require_manager(request.user)
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])
        entry = None
        if object_id is not None:
            try:
                entry = Entry.objects.get(pk=object_id)
            except Entry.DoesNotExist:
                raise Http404("Esta entrada não está disponível. Atualize a lista.") from None
        operation = "directory.delete" if deleting else "directory.update" if entry else "directory.create"
        title = "Excluir entrada" if deleting else "Editar entrada" if entry else "Adicionar entrada"
        initial = {field: getattr(entry, field) for field in services.EDITABLE_FIELDS} if entry else {}
        if request.method == "GET":
            initial["submission_token"] = issue_submission(
                session_key=request.session.session_key, authenticated_at=request.session[AUTHENTICATED_AT],
                operation=operation, binding=str(entry.pk) if entry else "",
            )
        form_class = SubmissionForm if deleting else EntryForm
        form = form_class(request.POST if request.method == "POST" else None, request.FILES or None, initial=initial)
        status = 200
        if request.method == "POST" and form.is_valid():
            proof = SubmissionProof(form.cleaned_data["submission_token"], request.session.session_key,
                                    request.session[ACCESS_VERSION], request.session[AUTHENTICATED_AT])
            values = {key: value for key, value in form.cleaned_data.items() if key != "submission_token"}
            try:
                if deleting:
                    services.delete_entry(operator_id=request.user.pk, entry_id=entry.pk, submission=proof)
                elif entry:
                    services.update_entry(operator_id=request.user.pk, entry_id=entry.pk, submission=proof, **values)
                else:
                    services.create_entry(operator_id=request.user.pk, submission=proof, **values)
            except StorageUnavailable:
                form.add_error(None, "Não foi possível salvar a foto. A entrada anterior foi preservada. Selecione a foto novamente para tentar salvar.")
                status = 503
            except ValidationError as error:
                if getattr(error, "code", None) == "entry_unavailable":
                    raise Http404("Esta entrada não está disponível. Atualize a lista.") from None
                if hasattr(error, "message_dict"):
                    for field, errors in error.message_dict.items():
                        form.add_error(field if field in form.fields else None, errors)
                else:
                    form.add_error(None, error)
                status = 409 if isinstance(error, SubmissionRejected) else 400
            else:
                request.operation_committed = True
                messages.success(request, "Entrada excluída." if deleting else "Entrada salva.")
                return redirect("admin:directory_entry_changelist")
        elif request.method == "POST":
            status = 400
        context = self.context(request, title)
        context.update(form=form, entry=entry, deleting=deleting, photo_reselect=bool(request.FILES))
        return TemplateResponse(request, "admin/directory/entry/form.html", context, status=status)

    def save_model(self, request, obj, form, change):
        raise PermissionDenied

    def delete_model(self, request, obj):
        raise PermissionDenied

    def delete_queryset(self, request, queryset):
        raise PermissionDenied
