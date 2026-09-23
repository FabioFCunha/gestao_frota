from django import forms
from django.contrib.auth.models import Group, Permission

from .models import User


INPUT = {"class": "form-input"}
SELECT = {"class": "form-input"}


class UserForm(forms.ModelForm):
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.none(),
        required=False,
        label="Perfil",
        widget=forms.SelectMultiple(attrs={**SELECT, "size": 5}),
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "functional_id", "whatsapp", "groups", "is_active"]
        labels = {
            "first_name": "Nome",
            "last_name": "Sobrenome",
            "email": "E-mail (login)",
            "functional_id": "ID funcional",
            "whatsapp": "WhatsApp",
            "groups": "Perfil",
            "is_active": "Situação",
        }
        widgets = {
            "first_name": forms.TextInput(attrs={**INPUT, "placeholder": "Nome completo"}),
            "last_name": forms.HiddenInput(),
            "email": forms.EmailInput(attrs={**INPUT, "placeholder": "usuario@orgao.gov.br"}),
            "functional_id": forms.TextInput(attrs={**INPUT, "placeholder": "ID funcional"}),
            "whatsapp": forms.TextInput(attrs={**INPUT, "placeholder": "(21) 99999-9999"}),
            "is_active": forms.Select(
                choices=[(True, "Ativo"), (False, "Inativo")],
                attrs=SELECT,
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["groups"].queryset = Group.objects.order_by("name")
        self.fields["groups"].help_text = "O perfil define as permissões deste usuário."

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        qs = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Este e-mail já está cadastrado.")
        return email

    def clean_functional_id(self):
        value = self.cleaned_data["functional_id"].strip()
        qs = User.objects.filter(functional_id__iexact=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Este ID funcional já está cadastrado.")
        return value

    def clean_whatsapp(self):
        value = self.cleaned_data["whatsapp"].strip()
        if len("".join(ch for ch in value if ch.isdigit())) < 10:
            raise forms.ValidationError("Informe um número de WhatsApp válido.")
        return value


class GroupForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.none(),
        required=False,
        label="Permissões",
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Group
        fields = ["name", "permissions"]
        labels = {"name": "Nome do perfil"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["permissions"].queryset = (
            Permission.objects
            .filter(content_type__app_label__in=["fleet", "accounts"])
            .select_related("content_type")
            .order_by("content_type__model", "codename")
        )
