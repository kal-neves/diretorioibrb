from django import forms

from accounts.admin_forms import SubmissionForm
from accounts.forms import LoginForm

from .models import Entry


class EntryForm(SubmissionForm):
    name = forms.CharField(label="Nome", max_length=200)
    category = forms.ChoiceField(label="Categoria", choices=[("", "Selecione")] + Entry.Category.choices)
    contact_phone = forms.CharField(label="Contato", max_length=100, required=False)
    country = forms.ChoiceField(label="País do contato", required=False, choices=LoginForm.base_fields["country"].choices)
    email = forms.EmailField(label="E-mail", max_length=254, required=False,
                            help_text="Visível somente na administração.")
    birth_day = forms.IntegerField(label="Dia do aniversário", min_value=1, max_value=31, required=False)
    birth_month = forms.IntegerField(label="Mês do aniversário", min_value=1, max_value=12, required=False)
    spouse_name = forms.CharField(label="Cônjuge", max_length=200, required=False)
    photo = forms.FileField(label="Foto recortada", required=False, widget=forms.FileInput(attrs={"accept": "image/jpeg", "hidden": True}))
    remove_photo = forms.BooleanField(label="Remover foto atual", required=False)

    def clean(self):
        cleaned = super().clean()
        if set(self.files) - {"photo"} or len(self.files.getlist("photo")) > 1:
            raise forms.ValidationError("Envie apenas uma foto.")
        return cleaned
