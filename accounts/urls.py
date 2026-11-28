from django.urls import path

from . import views


app_name = "accounts"
urlpatterns = [
    path("", views.entry, name="entry"),
    path("login/", views.sign_in, name="login"),
    path("primeiro-acesso/", views.required_password, name="required_password"),
    path("minha-senha/", views.voluntary_password, name="password"),
    path("sair/", views.sign_out, name="logout"),
]
