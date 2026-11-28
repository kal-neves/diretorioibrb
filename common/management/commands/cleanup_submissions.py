from django.core.management.base import BaseCommand

from common.submissions import clear_expired_submissions


class Command(BaseCommand):
    help = "Remove controles de formulário vencidos."

    def handle(self, *args, **options):
        self.stdout.write(f"Controles vencidos removidos: {clear_expired_submissions()}.")
