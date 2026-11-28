from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils.crypto import constant_time_compare
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_GET

from .maintenance import run_daily


@require_GET
@sensitive_variables("secret", "provided")
def maintenance(request):
    secret = settings.CRON_SECRET
    if settings.DEBUG or not settings.MAINTENANCE_ENABLED or settings.DEPLOYMENT_ENV != "production":
        return HttpResponse(status=404)
    provided = request.headers.get("Authorization", "")
    if not secret or not constant_time_compare(provided, f"Bearer {secret}"):
        return HttpResponse(status=401)
    if request.GET:
        return HttpResponse(status=400)
    status = run_daily()
    response_codes = {"succeeded": 200, "already_done": 200, "running": 409}
    return JsonResponse({"status": status}, status=response_codes.get(status, 503))


maintenance.operational_route = True
