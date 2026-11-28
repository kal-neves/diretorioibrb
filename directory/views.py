from zoneinfo import ZoneInfo

from django.template.response import TemplateResponse
from django.http import Http404, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import Entry
from .storage import PhotoMissing, StorageUnavailable, photo_storage
from .queries import birthdays, directory_totals, list_entries


MONTHS = tuple(enumerate(("Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                          "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"), 1))


def listing_context(request):
    return {"page": list_entries(query=request.GET.get("q"), category=request.GET.get("category"),
                                 page=request.GET.get("page")), "categories": Entry.Category.choices,
            "list_url": reverse("directory:index")}


def birthday_context(request):
    now = timezone.now()
    result = birthdays(month=request.GET.get("month"), at=now)
    return {"birthday_list": result, "months": MONTHS, "month_name": dict(MONTHS)[result.month],
            "current_month": timezone.localtime(now, ZoneInfo("America/Belem")).month}


@require_GET
def index(request):
    return TemplateResponse(request, "directory/index.html", {
        **listing_context(request), **birthday_context(request), "totals": directory_totals(),
    })


@require_GET
def listing(request):
    return TemplateResponse(request, "directory/list.html", listing_context(request),
                            headers={"X-Directory-Fragment": "listing"})


@require_GET
def birthday_list(request):
    return TemplateResponse(request, "directory/birthdays.html", birthday_context(request),
                            headers={"X-Directory-Fragment": "birthdays"})


@require_GET
def photo(request, entry_id, photo_id):
    entry = Entry.objects.filter(pk=entry_id, photo_id=photo_id, photo__state="ATTACHED").first()
    if entry is None:
        raise Http404
    try:
        data = photo_storage().get(entry.photo.object_key)
    except PhotoMissing:
        raise Http404 from None
    except StorageUnavailable:
        return HttpResponse("Não foi possível carregar a foto.", status=503)
    if not Entry.objects.filter(pk=entry_id, photo_id=photo_id).exists():
        raise Http404
    from accounts.models import Account
    from accounts.sessions import ACCESS_VERSION, AUTHENTICATED_AT, account_session_is_current
    account = Account.objects.filter(pk=request.user.pk).first()
    if (account is None or account.must_change_password or not account_session_is_current(
            account, request.session.get(ACCESS_VERSION), request.session.get(AUTHENTICATED_AT))):
        return HttpResponse(status=401)
    return HttpResponse(data, content_type="image/jpeg", headers={"X-Content-Type-Options": "nosniff"})
