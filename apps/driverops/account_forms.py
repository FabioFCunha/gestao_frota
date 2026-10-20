from django import forms
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q
from apps.accounts.forms import UserForm
from apps.accounts.models import User
from apps.fleet.models import Driver
from .models import Member, CompanyVehicle


class CompanyUserForm(UserForm):
    role = forms.ChoiceField(label='Perfil de acesso', choices=Member._meta.get_field('role').choices)
    driver = forms.ModelChoiceField(label='Motorista cadastrado pela CNH', queryset=Driver.objects.none(), required=False)
    vehicles = forms.ModelMultipleChoiceField(label='Veículos autorizados no aplicativo', queryset=CompanyVehicle.objects.none(), required=False, widget=forms.CheckboxSelectMultiple)

    class Meta(UserForm.Meta):
        pass

    def __init__(self, *args, company, member=None, **kwargs):
        self.company, self.member = company, member
        super().__init__(*args, **kwargs)
        for name in ('groups', 'sectors', 'functional_id'):
            self.fields.pop(name, None)
        self.fields['email'].widget.attrs['placeholder'] = 'usuario@empresa.com'
        self.fields['whatsapp'].required = False
        eligible = Q(member__isnull=True)
        if member and member.driver_id:
            eligible |= Q(pk=member.driver_id)
        self.fields['driver'].queryset = Driver.objects.filter((eligible & Q(active=True)) | (Q(pk=member.driver_id) if member and member.driver_id else Q(pk__in=[]))).order_by('name')
        self.fields['vehicles'].queryset = CompanyVehicle.objects.filter(company=company, active=True).order_by('label')
        if member:
            self.initial.update(role=member.role, driver=member.driver_id, is_active=member.active and member.user.is_active,
                vehicles=list(member.companyvehicle_set.filter(company=company).values_list('pk', flat=True)))
            if member.driver_id:
                self.fields['driver'].disabled = True
                self.fields['role'].disabled = True

    def clean_email(self):
        email = super().clean_email()
        if User.objects.filter(username__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Este e-mail já está em uso como login.')
        return email

    def clean_whatsapp(self):
        value = self.cleaned_data.get('whatsapp', '').strip()
        if value and len(''.join(c for c in value if c.isdigit())) < 10:
            raise forms.ValidationError('Informe um telefone válido.')
        return value

    def clean(self):
        data = super().clean()
        if data.get('role') == Member.DRIVER and not data.get('driver'):
            self.add_error('driver', 'Cadastre o motorista pela CNH e selecione-o para liberar o aplicativo.')
        if data.get('role') == Member.MANAGER and (data.get('driver') or data.get('vehicles')):
            raise forms.ValidationError('Gestores usam o desktop. Motorista e veículos são exclusivos do acesso operacional.')
        if data.get('initial_password'):
            validate_password(data['initial_password'], self.instance)
        return data
