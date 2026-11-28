from django.core.management.base import BaseCommand, CommandError

from directory.photos import cleanup_photos
from directory.storage import StorageUnavailable


class Command(BaseCommand):
    help = "Remove fotos sem referência e retoma remoções pendentes."

    def handle(self, *args, **options):
        try:
            count = cleanup_photos()
        except StorageUnavailable:
            raise CommandError("O armazenamento de fotos está indisponível.") from None
        self.stdout.write(f"Fotos removidas: {count}.")
