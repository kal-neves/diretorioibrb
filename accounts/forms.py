import phonenumbers
from django import forms


class LoginForm(forms.Form):
    username = forms.CharField(label="Celular ou usuário", max_length=254,
                               widget=forms.TextInput(attrs={"autocomplete": "username"}))
    country = forms.ChoiceField(label="País", required=False,
                                choices=[("", "Selecione")] + [(code, code) for code in sorted(phonenumbers.SUPPORTED_REGIONS)])
    password = forms.CharField(label="Senha", max_length=1024, strip=False,
                               widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class NewPasswordForm(forms.Form):
    new_password = forms.CharField(
        label="Nova senha", max_length=1024, strip=False,
        help_text="Use pelo menos oito caracteres, incluindo uma letra e um número.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    confirmation = forms.CharField(label="Confirmar nova senha", max_length=1024, strip=False,
                                   widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))


class ChangePasswordForm(NewPasswordForm):
    current_password = forms.CharField(label="Senha atual", max_length=1024, strip=False,
                                       widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
    field_order = ["current_password", "new_password", "confirmation"]
