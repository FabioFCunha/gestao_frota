from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError

from .models import User


INPUT = {"class": "form-input"}
SELECT = {"class": "form-input"}


class FleetAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if settings.DEBUG:
            self.fields["password"].required = False

    username = forms.CharField(
        label="E-mail (login)",
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "username",
                "autofocus": True,
                "placeholder": "seu@email.com",
            }
        ),
    )

    def clean(self):
        email = self.cleaned_data.get("username", "").strip()
        user = User.objects.filter(email__iexact=email).first()
        if user:
            self.cleaned_data["username"] = user.username

        if settings.DEBUG and user:
            if not user.is_active:
                raise ValidationError("Este usuário está inativo.")
            self.user_cache = user
            return self.cleaned_data

        return super().clean()


class UserForm(forms.ModelForm):
    initial_password = forms.CharField(
        label="Senha inicial",
        required=False,
        widget=forms.PasswordInput(
            attrs={
                **INPUT,
                "autocomplete": "new-password",
                "placeholder": "Mínimo de 8 caracteres",
            }
        ),
        help_text="O usuário deverá trocar esta senha no primeiro acesso.",
    )
    initial_password_confirmation = forms.CharField(
        label="Confirmar senha inicial",
        required=False,
        widget=forms.PasswordInput(
            attrs={
                **INPUT,
                "autocomplete": "new-password",
                "placeholder": "Repita a senha inicial",
            }
        ),
    )
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.none(),
        required=False,
        label="Perfil",
        widget=forms.SelectMultiple(attrs={**SELECT, "size": 5}),
    )

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "email",
            "functional_id",
            "whatsapp",
            "groups",
            "is_active",
        ]
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
        self.fields["functional_id"].required = True
        self.fields["whatsapp"].required = True
        self.fields["groups"].help_text = "O perfil define as permissões deste usuário."
        if self.instance and self.instance.pk:
            self.fields["initial_password"].help_text = (
                "Preencha somente se quiser definir uma nova senha inicial e exigir troca no próximo acesso."
            )

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

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("initial_password", "")
        confirmation = cleaned.get("initial_password_confirmation", "")

        if not self.instance.pk and not password:
            self.add_error("initial_password", "Informe a senha inicial.")

        if password:
            if len(password) < 8:
                self.add_error("initial_password", "A senha deve ter pelo menos 8 caracteres.")
            if password != confirmation:
                self.add_error("initial_password_confirmation", "As senhas não conferem.")
        elif confirmation:
            self.add_error("initial_password", "Informe a senha inicial.")

        return cleaned


class FleetPasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(
        label="Senha atual",
        widget=forms.PasswordInput(attrs={**INPUT, "autocomplete": "current-password"}),
    )
    new_password1 = forms.CharField(
        label="Nova senha",
        widget=forms.PasswordInput(attrs={**INPUT, "autocomplete": "new-password"}),
        help_text="A senha deve ter pelo menos 8 caracteres.",
    )
    new_password2 = forms.CharField(
        label="Confirmar nova senha",
        widget=forms.PasswordInput(attrs={**INPUT, "autocomplete": "new-password"}),
    )


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
