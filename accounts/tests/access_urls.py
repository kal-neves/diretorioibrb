from django.http import HttpResponse
from django.urls import include, path

from accounts.middleware import staff_route


def protected(request):
    return HttpResponse("Conteúdo protegido")


@staff_route
def staff_only(request):
    return HttpResponse("Conteúdo administrativo")


urlpatterns = [
    path("", include("accounts.urls")),
    path("diretorio/", protected),
    path("fragmento/", protected),
    path("foto/", protected),
    path("operacao/", protected),
    path("secretaria/", staff_only),
    path("admin/", include(([path("", protected)], "admin"), namespace="admin")),
]
