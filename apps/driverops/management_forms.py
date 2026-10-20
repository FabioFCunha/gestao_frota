import re
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from apps.fleet.models import Driver, Vehicle, VehiclePlate
from .models import Company, Member, CompanyVehicle


class MemberChoice(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return (obj.driver.name if obj.driver_id else obj.user.get_full_name() or obj.user.username) + " · " + obj.user.username


class AssignedVehicleChoice(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return obj.label


class CompanyForm(UserCreationForm):
    company_name = forms.CharField(label="Nome da empresa", max_length=160)
    manager_name = forms.CharField(label="Nome do primeiro gestor", max_length=150)
    email = forms.EmailField(label="E-mail do gestor")

    class Meta:
        model = get_user_model()
        fields = ['company_name', 'manager_name', 'username', 'email', 'password1', 'password2']
        labels = {'username': 'Login do gestor'}

    def clean_company_name(self):
        name = " ".join(self.cleaned_data['company_name'].split())
        if Company.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError('Essa empresa já existe.')
        return name

    def save_company(self):
        user = super().save(commit=False)
        parts = self.cleaned_data['manager_name'].split(maxsplit=1)
        user.first_name, user.last_name = parts[0], parts[1] if len(parts) > 1 else ''
        user.email = self.cleaned_data['email']
        user.is_staff = False
        user.is_superuser = False
        user.save()
        company = Company.objects.create(name=self.cleaned_data['company_name'])
        Member.objects.create(company=company, user=user, role=Member.MANAGER)
        return company


class MemberForm(UserCreationForm):
    name = forms.CharField(label="Nome completo", max_length=150)
    email = forms.EmailField(label="E-mail", required=False)
    role = forms.ChoiceField(label="Perfil", choices=[("driver", "Motorista"), ("manager", "Gestor")])
    vehicles = AssignedVehicleChoice(label="Veículos autorizados", required=False,
        queryset=CompanyVehicle.objects.none(), widget=forms.CheckboxSelectMultiple)
    existing_driver = forms.ModelChoiceField(label="Usar motorista já cadastrado (opcional)", required=False,
        queryset=Driver.objects.none())

    class Meta:
        model = get_user_model()
        fields = ["name", "username", "email", "role", "password1", "password2", "vehicles", "existing_driver"]
        labels = {"username": "Usuário para entrar"}
        help_texts = {"username": "Esse será o login no aplicativo."}

    def __init__(self, *args, company, platform=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Senha inicial"
        self.fields["password2"].label = "Confirme a senha"
        self.fields["vehicles"].queryset = CompanyVehicle.objects.filter(company=company, active=True).order_by("label")
        self.fields["existing_driver"].queryset = Driver.objects.filter(active=True, member__isnull=True)
        if platform:
            self.fields['role'].choices = [(Member.MANAGER, 'Gestor')]
            self.fields['vehicles'].widget = forms.HiddenInput()
            self.fields['existing_driver'].widget = forms.HiddenInput()


    def clean(self):
        data = super().clean()
        if data.get("role") == Member.MANAGER and (data.get("vehicles") or data.get("existing_driver")):
            raise forms.ValidationError("Gestores não precisam de motorista nem veículos autorizados. Deixe esses campos vazios.")
        return data


class VehicleChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        plate = obj.plate_history.filter(kind="CURRENT", ends_on=None).first()
        return str(plate.plate if plate else "Sem placa") + " · " + str(obj.model or obj.brand or "Veículo cadastrado")


class VehicleForm(forms.Form):
    existing_vehicle = VehicleChoiceField(label="Usar veículo já cadastrado (opcional)", required=False,
                                          queryset=Vehicle.objects.none())
    plate = forms.CharField(label="Placa do veículo novo", max_length=8, required=False,
                            help_text="Preencha para cadastrar um veículo novo. Exemplo: ABC1D23.")
    label = forms.CharField(label="Identificação no aplicativo", max_length=100, required=False,
                            help_text="Exemplo: ABC1D23 · Carro de atendimento.")
    mileage = forms.IntegerField(label="KM atual do veículo novo", min_value=0, max_value=9999999, required=False)
    drivers = MemberChoice(label="Motoristas autorizados", required=False,
        queryset=Member.objects.none(), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, company, platform=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["drivers"].queryset = Member.objects.filter(company=company,role="driver",active=True).select_related("driver","user")
        if platform:
            self.fields["existing_vehicle"].queryset = Vehicle.objects.filter(active=True,companyvehicle__isnull=True)
        else:
            self.fields.pop("existing_vehicle")

    def clean_plate(self):
        value = re.sub(r"[^A-Z0-9]", "", self.cleaned_data["plate"].upper())
        if value and not re.fullmatch(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}",value):
            raise forms.ValidationError("Informe uma placa brasileira válida, como ABC1D23 ou ABC1234.")
        if value and VehiclePlate.objects.filter(plate=value,kind="CURRENT",ends_on=None).exists():
            raise forms.ValidationError("Esta placa já está cadastrada. O administrador pode vincular um veículo existente.")
        return value

    def clean(self):
        data = super().clean()
        existing = data.get("existing_vehicle")
        if existing:
            if data.get("plate") or data.get("mileage") is not None:
                raise forms.ValidationError("Ao usar veículo existente, deixe placa e KM do veículo novo vazios.")
            if not data.get("label"):
                raise forms.ValidationError("Informe a identificação do veículo existente no aplicativo.")
        elif not data.get("plate") and "plate" not in self.errors:
            self.add_error("plate","Informe a placa para cadastrar o veículo.")
        return data


class AssignmentForm(forms.Form):
    drivers = forms.ModelMultipleChoiceField(label="Motoristas autorizados", required=False,
        queryset=Member.objects.none(), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, company, vehicle, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["drivers"].queryset = Member.objects.filter(company=company,role="driver",active=True).select_related("user","driver")
        if not self.is_bound:
            self.initial["drivers"] = vehicle.drivers.values_list("pk",flat=True)
