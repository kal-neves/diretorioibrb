from django.core.management.base import BaseCommand, CommandError

from common.maintenance import run_daily


class Command(BaseCommand):
    help = "Executa a manutenção diária e registra seu resultado."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Executa novamente mesmo após sucesso no dia atual.")

    def handle(self, *args, **options):
        status = run_daily(force=options["force"])
        if status not in {"succeeded", "already_done"}:
            raise CommandError(f"Manutenção não concluída: {status}. Consulte maintenance_status.")
        self.stdout.write(f"Manutenção: {status}.")
