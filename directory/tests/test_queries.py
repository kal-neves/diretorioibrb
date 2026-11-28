from dataclasses import asdict
from datetime import datetime, timezone as datetime_timezone

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from accounts.tests.test_services import example_mobile
from directory.models import Entry
from directory.queries import birthdays, directory_totals, list_entries


class DirectoryQueryTests(TestCase):
    def entry(self, name="Pessoa", category=Entry.Category.MEMBER, **fields):
        return Entry.objects.create(name=name, category=category, **fields)

    def test_search_is_accent_case_insensitive_partial_and_name_only(self):
        expected = self.entry("João ÁLvares", email="private@example.org")
        self.entry("Outra", spouse_name="João", contact_phone=example_mobile("BR"))
        self.assertEqual([card.id for card in list_entries(query="ÃO álV").items], [expected.pk])
        self.assertEqual(list_entries(query="private").total, 0)
        self.assertEqual(list_entries(query="example").total, 0)
        self.assertEqual(list_entries(query="joao", category=Entry.Category.PASTOR).total, 0)
        self.assertEqual(list_entries(category="ALL").items, ())

    def test_category_then_normalized_name_then_id(self):
        deacon = self.entry("A", Entry.Category.DEACON)
        pastor = self.entry("A", Entry.Category.PASTOR)
        z = self.entry("Z")
        first = self.entry("Álvaro")
        second = self.entry("alvaro")
        self.assertEqual([card.id for card in list_entries().items], [first.pk, second.pk, z.pk, pastor.pk, deacon.pk])

    def test_pagination_and_return_from_out_of_range(self):
        for index in range(21):
            self.entry(f"Pessoa {index:02}")
        first = list_entries()
        second = list_entries(page="2")
        self.assertEqual((len(first.items), first.next_page, first.previous_page), (20, 2, None))
        self.assertEqual((len(second.items), second.next_page, second.previous_page), (1, None, 1))
        self.assertFalse({card.id for card in first.items} & {card.id for card in second.items})
        for invalid in ("abc", "0", "-2", None, "1.5"):
            self.assertEqual(list_entries(page=invalid).number, 1)
        beyond = list_entries(page="999999999999999999999")
        self.assertEqual(beyond.items, ())
        self.assertEqual(beyond.previous_page, 2)

    def test_birthdays_all_results_day_name_id_and_local_month(self):
        late = self.entry("Ana", birth_day=29, birth_month=2)
        early = self.entry("Zé", birth_day=1, birth_month=2)
        for index in range(21):
            self.entry(f"Outra {index:02}", birth_day=15, birth_month=2)
        self.entry("Março", birth_day=1, birth_month=3)
        instant = datetime(2026, 3, 1, 1, tzinfo=datetime_timezone.utc)
        for invalid in (None, "abc", 0, 13, -1):
            result = birthdays(month=invalid, at=instant)
            self.assertEqual(result.month, 2)
            self.assertEqual(len(result.items), 23)
            self.assertEqual((result.items[0].id, result.items[-1].id), (early.pk, late.pk))
        self.assertEqual(len(birthdays(month="3", at=instant).items), 1)

    def test_projection_never_selects_email_or_accounts(self):
        self.entry(email="private@example.org", birth_day=1, birth_month=1)
        with CaptureQueriesContext(connection) as captured:
            card = list_entries().items[0]
            birthdays(month=1)
            directory_totals()
        self.assertNotIn("email", asdict(card))
        for query in captured.captured_queries:
            self.assertNotIn('"email"', query["sql"])
            self.assertNotIn("accounts_account", query["sql"])
            self.assertNotIn(" JOIN ", query["sql"])

    def test_totals_are_global_and_deletion_affects_all_queries(self):
        entry = self.entry("Ana", birth_day=1, birth_month=1)
        self.entry("B", Entry.Category.PASTOR)
        self.entry("C", Entry.Category.DEACON)
        list_entries(query="B", category=Entry.Category.PASTOR)
        self.assertEqual(asdict(directory_totals()), {"total": 3, "members": 1, "pastors": 1, "deacons": 1})
        entry.delete()
        self.assertEqual(directory_totals().total, 2)
        self.assertEqual(birthdays(month=1).items, ())
        self.assertEqual(list_entries(query="Ana").total, 0)
