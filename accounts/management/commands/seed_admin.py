from django.core.management.base import BaseCommand, CommandError

from accounts.services import seed_initial_admin


class Command(BaseCommand):
    help = "Cria o administrador inicial em um terminal privado."

    def handle(self, *args, **options):
        if not self.stdout.isatty():
            raise CommandError("Execute em um terminal privado, sem redirecionar a saída.")
        password = seed_initial_admin()
        if password is None:
            self.stdout.write("O administrador inicial já existe. A senha foi preservada.")
            return
        self.stdout.write("Usuário: adminseed")
        self.stdout.write(f"Senha: {password}")
        self.stdout.write("Anote a senha e guarde-a em local seguro. Ela não será exibida novamente.")
