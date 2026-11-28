from django import forms

from .forms import LoginForm
from .models import Account


class SubmissionForm(forms.Form):
    submission_token = forms.CharField(max_length=100, widget=forms.HiddenInput)

    def clean(self):
        cleaned = super().clean()
        unexpected = set(self.data) - set(self.fields) - {"csrfmiddlewaretoken"}
        if unexpected:
            raise forms.ValidationError("O formulário contém campos não permitidos.")
        return cleaned


class AccountManagementForm(SubmissionForm):
    name = forms.CharField(label="Nome", max_length=200)
    phone = forms.CharField(label="Celular de login", max_length=100)
    country = forms.ChoiceField(label="País", required=False, choices=LoginForm.base_fields["country"].choices)
    role = forms.ChoiceField(label="Perfil", choices=[
        (Account.Role.CONSULTATION, "Consulta"), (Account.Role.SECRETARIAT, "Secretaria"),
    ])

    def __init__(self, *args, operator, **kwargs):
        super().__init__(*args, **kwargs)
        if operator.role != Account.Role.INITIAL_ADMIN:
            self.fields.pop("role")
