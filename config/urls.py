from django.urls import include, path
from accounts.admin import site


urlpatterns = [path("admin/", site.urls), path("", include("accounts.urls"))]
