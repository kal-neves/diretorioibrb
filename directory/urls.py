from django.urls import path

from . import views


app_name = "directory"
urlpatterns = [path("", views.index, name="index"), path("lista/", views.listing, name="listing"),
               path("aniversariantes/", views.birthday_list, name="birthdays")]
