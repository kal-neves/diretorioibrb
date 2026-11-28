import sys

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.views.decorators.debug import sensitive_variables

from accounts.services import recover_initial_admin


class Command(BaseCommand):
    help = "Recupera a senha de adminseed em terminal privado e revoga suas sessões."

    @sensitive_variables("password")
    def handle(self, *args, **options):
        if not self.stdout.isatty() or not sys.stdin.isatty():
            raise CommandError("Execute em terminal privado, sem redirecionar entrada ou saída.")
        self.stdout.write("A senha atual deixará de funcionar e as sessões serão revogadas.")
        if input("Digite RECUPERAR adminseed para confirmar: ") != "RECUPERAR adminseed":
            raise CommandError("Recuperação cancelada. Nenhuma senha foi alterada.")
        try:
            password = recover_initial_admin()
        except ValidationError as error:
            raise CommandError(error.messages[0]) from None
        self.stdout.write(f"Nova senha de adminseed: {password}")
        self.stdout.write("Guarde a senha em local seguro. Ela não será exibida novamente.")
