from dataclasses import dataclass
from zoneinfo import ZoneInfo

from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.db.models.functions import Collate
from django.utils import timezone

from .models import Entry
from .normalization import normalize_name


PAGE_SIZE = 20
DISPLAY_FIELDS = ("id", "name", "category", "contact_phone", "birth_day", "birth_month", "spouse_name")


@dataclass(frozen=True)
class DirectoryCard:
    id: int
    name: str
    category: str
    contact_phone: str | None
    birth_day: int | None
    birth_month: int | None
    spouse_name: str | None


@dataclass(frozen=True)
class DirectoryPage:
    items: tuple[DirectoryCard, ...]
    query: str
    category: str
    number: int
    total: int
    total_pages: int

    @property
    def previous_page(self):
        return min(self.number - 1, self.total_pages) if self.number > 1 else None

    @property
    def next_page(self):
        return self.number + 1 if self.number < self.total_pages else None


@dataclass(frozen=True)
class BirthdayList:
    month: int
    items: tuple[DirectoryCard, ...]


@dataclass(frozen=True)
class DirectoryTotals:
    total: int
    members: int
    pastors: int
    deacons: int


def cards(queryset):
    return tuple(DirectoryCard(**row) for row in queryset.values(*DISPLAY_FIELDS))


def positive_integer(value, fallback):
    try:
        result = int(str(value))
    except (TypeError, ValueError):
        return fallback
    return result if result > 0 else fallback


def list_entries(*, query="", category="", page=1):
    query = (query or "").strip()
    category = category or ""
    entries = Entry.objects.all()
    if query:
        entries = entries.filter(search_name__contains=normalize_name(query))
    if category:
        entries = entries.filter(category=category) if category in Entry.Category.values else entries.none()
    total = entries.count()
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    number = positive_integer(page, 1)
    category_order = Case(
        When(category=Entry.Category.MEMBER, then=Value(0)),
        When(category=Entry.Category.PASTOR, then=Value(1)),
        default=Value(2), output_field=IntegerField(),
    )
    items = ()
    if number <= total_pages:
        offset = (number - 1) * PAGE_SIZE
        items = cards(entries.order_by(category_order, Collate("search_name", "C"), "pk")[offset:offset + PAGE_SIZE])
    return DirectoryPage(items, query, category, number, total, total_pages)


def birthdays(*, month=None, at=None):
    current_month = timezone.localtime(at or timezone.now(), ZoneInfo("America/Belem")).month
    selected = positive_integer(month, current_month)
    if selected > 12:
        selected = current_month
    entries = Entry.objects.filter(birth_month=selected).order_by("birth_day", Collate("search_name", "C"), "pk")
    return BirthdayList(selected, cards(entries))


def directory_totals():
    return DirectoryTotals(**Entry.objects.aggregate(
        total=Count("pk"), members=Count("pk", filter=Q(category=Entry.Category.MEMBER)),
        pastors=Count("pk", filter=Q(category=Entry.Category.PASTOR)),
        deacons=Count("pk", filter=Q(category=Entry.Category.DEACON)),
    ))
