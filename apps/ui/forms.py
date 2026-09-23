from django import forms
from apps.fleet.models import (
    Driver, Vehicle, VehicleFine, VehicleFineStatus,
    VehicleStatus, Brand, VehicleModel, Contract, Renter,
    AdministrativeUnit, Base
)

INPUT = {'class': 'form-input'}
SELECT = {'class': 'form-input'}


class DriverForm(forms.ModelForm):
    class Meta:
        model = Driver
        fields = ['name', 'registration', 'unit', 'phone', 'email', 'cnh_number', 'cnh_category', 'cnh_expiration']
        labels = {
            'name': 'Nome',
            'registration': 'Matrícula',
            'unit': 'Unidade Administrativa',
            'phone': 'Telefone',
            'email': 'E-mail',
            'cnh_number': 'Nº CNH',
            'cnh_category': 'Categoria CNH',
            'cnh_expiration': 'Validade CNH',
        }
        widgets = {
            'name': forms.TextInput(attrs={**INPUT, 'placeholder': 'Nome completo'}),
            'registration': forms.TextInput(attrs={**INPUT, 'placeholder': 'Matrícula ou Registro'}),
            'unit': forms.Select(attrs=SELECT),
            'phone': forms.TextInput(attrs={**INPUT, 'placeholder': '(00) 00000-0000'}),
            'email': forms.EmailInput(attrs={**INPUT, 'placeholder': 'email@exemplo.com'}),
            'cnh_number': forms.TextInput(attrs={**INPUT, 'placeholder': 'Número da CNH'}),
            'cnh_category': forms.TextInput(attrs={**INPUT, 'placeholder': 'Ex: AB, D, E'}),
            'cnh_expiration': forms.DateInput(attrs={**INPUT, 'type': 'date'}),
        }


class DriverVehicleAssignmentForm(forms.Form):
    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        label='Veículo',
        widget=forms.Select(attrs=SELECT),
        help_text='O veículo selecionado passará a ficar vinculado a este motorista.',
    )
    sei_number = forms.CharField(
        label='SEI do acautelamento',
        required=False,
        max_length=100,
        widget=forms.TextInput(
            attrs={**INPUT, 'placeholder': 'Opcional'}
        ),
    )
    custody_started_on = forms.DateField(
        label='Início do acautelamento',
        required=False,
        widget=forms.DateInput(
            attrs={**INPUT, 'type': 'date'}
        ),
    )
    custody_ended_on = forms.DateField(
        label='Fim do acautelamento',
        required=False,
        widget=forms.DateInput(
            attrs={**INPUT, 'type': 'date'}
        ),
    )

    notes = forms.CharField(
        label='Observação',
        required=False,
        widget=forms.Textarea(attrs={**INPUT, 'rows': 3, 'placeholder': 'Opcional'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vehicle'].queryset = Vehicle.objects.select_related('brand', 'model').prefetch_related('plate_history').order_by('plate_history__plate')
        self.fields['vehicle'].label_from_instance = self.label_from_instance

    def label_from_instance(self, vehicle):
        plate = next(
            (item.plate for item in vehicle.plate_history.all() if item.kind == 'CURRENT' and not item.ends_on),
            'Sem placa',
        )
        description = ' '.join(part for part in [vehicle.brand.name if vehicle.brand else '', vehicle.model.name if vehicle.model else ''] if part)
        return f'{plate} — {description or "Veículo sem modelo"}'


class VehicleForm(forms.ModelForm):
    plate = forms.CharField(
        max_length=8, label='Placa',
        widget=forms.TextInput(attrs={**INPUT, 'placeholder': 'ABC1D23'}),
    )
    reserved_plate = forms.CharField(
        max_length=8, label='Placa reservada', required=False,
        widget=forms.TextInput(attrs={**INPUT, 'placeholder': 'Opcional'}),
    )

    class Meta:
        model = Vehicle
        fields = [
            'brand', 'model', 'color', 'renavam',
            'contract', 'renter', 'unit', 'base',
            'status', 'armored', 'custody_info', 'notes',
        ]
        labels = {
            'brand': 'Marca', 'model': 'Modelo', 'color': 'Cor',
            'renavam': 'RENAVAM', 'contract': 'Contrato',
            'renter': 'Locadora', 'unit': 'Unidade Administrativa',
            'base': 'Base', 'status': 'Situação', 'armored': 'Blindado',
            'custody_info': 'SEI / Acautelamento', 'notes': 'Observações',
        }
        widgets = {
            'brand': forms.Select(attrs=SELECT),
            'model': forms.Select(attrs=SELECT),
            'color': forms.TextInput(attrs={**INPUT, 'placeholder': 'Ex: PRETO'}),
            'renavam': forms.TextInput(attrs={**INPUT, 'placeholder': 'Número do RENAVAM'}),
            'contract': forms.Select(attrs=SELECT),
            'renter': forms.Select(attrs=SELECT),
            'unit': forms.Select(attrs=SELECT),
            'base': forms.Select(attrs=SELECT),
            'status': forms.Select(attrs=SELECT),
            'custody_info': forms.TextInput(attrs={**INPUT, 'placeholder': 'SEI-420001/...'}),
            'notes': forms.Textarea(attrs={**INPUT, 'rows': 3}),
        }


class FineForm(forms.ModelForm):
    plate = forms.CharField(
        max_length=8, label='Placa do veículo',
        widget=forms.TextInput(attrs={**INPUT, 'placeholder': 'ABC1D23'}),
    )

    class Meta:
        model = VehicleFine
        fields = ['auto_number', 'agency', 'status', 'date', 'amount', 'due_date', 'notes']
        labels = {
            'auto_number': 'Nº do Auto de Infração',
            'agency': 'Órgão Autuador',
            'status': 'Situação',
            'date': 'Data da Infração',
            'amount': 'Valor (R$)',
            'due_date': 'Vencimento',
            'notes': 'Observações / Processo SEI',
        }
        widgets = {
            'auto_number': forms.TextInput(attrs={**INPUT, 'placeholder': 'RA20629234'}),
            'agency': forms.TextInput(attrs={**INPUT, 'placeholder': 'SMTR, PRF, DETRO...'}),
            'status': forms.Select(attrs=SELECT),
            'date': forms.DateTimeInput(attrs={**INPUT, 'type': 'datetime-local'}),
            'amount': forms.NumberInput(attrs={**INPUT, 'step': '0.01', 'placeholder': '0.00'}),
            'due_date': forms.DateInput(attrs={**INPUT, 'type': 'date'}),
            'notes': forms.Textarea(attrs={**INPUT, 'rows': 3, 'placeholder': 'Processo SEI, observações...'}),
        }

from apps.fleet.models import Maintenance

class MaintenanceForm(forms.ModelForm):
    plate = forms.CharField(
        max_length=8, label='Placa do veículo',
        widget=forms.TextInput(attrs={**INPUT, 'placeholder': 'ABC1D23'}),
    )
    field_order = ['plate', 'type', 'status', 'workshop', 'mileage', 'service', 'entered_at', 'exited_at', 'notes']

    class Meta:
        model = Maintenance
        fields = ['type', 'status', 'workshop', 'mileage', 'service', 'entered_at', 'exited_at', 'notes']
        labels = {
            'type': 'Tipo',
            'status': 'Situação',
            'workshop': 'Oficina',
            'mileage': 'KM da manutenção',
            'service': 'Serviço',
            'entered_at': 'Entrada',
            'exited_at': 'Saída',
            'notes': 'Observações',
        }
        widgets = {
            'type': forms.Select(attrs=SELECT),
            'status': forms.Select(attrs=SELECT),
            'workshop': forms.Select(attrs=SELECT),
            'mileage': forms.NumberInput(attrs={**INPUT, 'min': 0, 'placeholder': 'Ex: 40200'}),
            'service': forms.TextInput(attrs={**INPUT, 'placeholder': 'Ex: Revisão 40.000km, Troca de pneu...'}),
            'entered_at': forms.DateTimeInput(attrs={**INPUT, 'type': 'datetime-local'}),
            'exited_at': forms.DateTimeInput(attrs={**INPUT, 'type': 'datetime-local'}),
            'notes': forms.Textarea(attrs={**INPUT, 'rows': 3}),
        }

class KMImportForm(forms.Form):
    csv_file = forms.FileField(
        label='Arquivo CSV (Exportado da Prime)',
        widget=forms.FileInput(attrs={'class': 'form-input'})
    )
