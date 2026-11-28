from zoneinfo import ZoneInfo

from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import Entry
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
