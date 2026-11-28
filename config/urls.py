from django.urls import include, path
from accounts.admin import site
from directory import admin as directory_admin


urlpatterns = [path("admin/", site.urls), path("diretorio/", include("directory.urls")),
               path("", include("accounts.urls"))]
