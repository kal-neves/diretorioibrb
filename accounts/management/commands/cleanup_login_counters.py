from django.core.management.base import BaseCommand

from accounts.authentication import clear_expired_login_counters


class Command(BaseCommand):
    help = "Remove contadores de login cuja janela já terminou."

    def handle(self, *args, **options):
        count = clear_expired_login_counters()
        self.stdout.write(f"Contadores vencidos removidos: {count}.")
