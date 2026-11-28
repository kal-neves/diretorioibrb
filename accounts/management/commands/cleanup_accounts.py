from django.core.management.base import BaseCommand

from accounts.services import delete_expired_new_accounts


class Command(BaseCommand):
    help = "Exclui contas novas que não concluíram a primeira troca em sete dias."

    def handle(self, *args, **options):
        count = delete_expired_new_accounts()
        self.stdout.write(f"Contas novas vencidas excluídas: {count}.")
