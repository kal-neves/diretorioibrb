from django.urls import include, path
from accounts.admin import site
from directory import admin as directory_admin
from common.views import maintenance


urlpatterns = [path("internal/maintenance/", maintenance, name="maintenance"),
               path("admin/", site.urls), path("diretorio/", include("directory.urls")),
               path("", include("accounts.urls"))]
