from datetime import timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from common.models import RoutineState


class Command(BaseCommand):
    help = "Mostra o último resultado da manutenção, sem dados pessoais."

    def handle(self, *args, **options):
        state = RoutineState.objects.filter(pk="daily").first()
        now = timezone.localtime(timezone.now(), ZoneInfo("America/Belem"))
        if state is None:
            self.stdout.write("A manutenção ainda não foi executada.")
        else:
            status = state.status
            if status == "running" and state.lease_until <= now:
                status = "interrupted"
            self.stdout.write(f"Estado: {status}")
            self.stdout.write(f"Último início: {state.last_started_at}")
            self.stdout.write(f"Último sucesso: {state.last_succeeded_at}")
            self.stdout.write(f"Contagens: {state.counts}")
            self.stdout.write(f"Falha: {state.last_error_code or 'nenhuma'}")

        expected_since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now.hour == 0:
            if state is None or (state.last_succeeded_at is None and state.last_started_at
                                 and state.last_started_at >= expected_since):
                return
            expected_since -= timedelta(days=1)
        if state is None or state.last_succeeded_at is None or state.last_succeeded_at < expected_since:
            raise CommandError("Manutenção atrasada. Consulte o agendador e execute run_maintenance.")
