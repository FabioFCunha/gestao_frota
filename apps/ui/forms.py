from django import forms
from apps.fleet.models import (
    Driver, Vehicle, VehicleFine, VehicleFineStatus,
    VehicleStatus, Brand, VehicleModel, Contract, Renter,
    AdministrativeUnit, Base, Workshop, Sector, VehicleStatus, SEIProcess,
    SEIProcessStatus, VehicleExitOrder
)

INPUT = {'class': 'form-input'}
SELECT = {'class': 'form-input'}

class CRLVUploadForm(forms.Form):
    file=forms.FileField(widget=forms.FileInput(attrs={**INPUT,'accept':'.pdf,.jpg,.jpeg,.png'}))
    def clean_file(self):
        f=self.cleaned_data['file']
        if f.name.rsplit('.',1)[-1].lower() not in {'pdf','jpg','jpeg','png'}: raise forms.ValidationError('Envie PDF, JPG ou PNG.')
        return f
class CRLVConfirmForm(forms.Form):
    document_id = forms.UUIDField(widget=forms.HiddenInput())
    plate = forms.CharField(max_length=8, label="Placa", widget=forms.TextInput(attrs=INPUT))
    renavam = forms.CharField(max_length=20, required=False, label="RENAVAM", widget=forms.TextInput(attrs=INPUT))
    chassi = forms.CharField(max_length=17, required=False, label="Chassi", widget=forms.TextInput(attrs=INPUT))
    exercise = forms.IntegerField(min_value=2000, max_value=2100, label="Exercício do CRLV", widget=forms.NumberInput(attrs=INPUT))
    brand = forms.CharField(max_length=100, required=False, label="Marca", widget=forms.TextInput(attrs=INPUT))
    model = forms.CharField(max_length=150, required=False, label="Modelo", widget=forms.TextInput(attrs=INPUT))
    version = forms.CharField(max_length=100, required=False, label="Versão", widget=forms.TextInput(attrs=INPUT))
    manufacture_year = forms.IntegerField(min_value=1900, max_value=2100, required=False, label="Ano de fabricação", widget=forms.NumberInput(attrs=INPUT))
    model_year = forms.IntegerField(min_value=1900, max_value=2100, required=False, label="Ano modelo", widget=forms.NumberInput(attrs=INPUT))
    color = forms.CharField(max_length=50, required=False, label="Cor", widget=forms.TextInput(attrs=INPUT))
    fuel = forms.CharField(max_length=50, required=False, label="Combustível", widget=forms.TextInput(attrs=INPUT))
    category = forms.CharField(max_length=50, required=False, label="Categoria", widget=forms.TextInput(attrs=INPUT))
    vehicle_type = forms.CharField(max_length=100, required=False, label="Espécie / tipo", widget=forms.TextInput(attrs=INPUT))
    motor = forms.CharField(max_length=100, required=False, label="Motor", widget=forms.TextInput(attrs=INPUT))
    power_cylinder = forms.CharField(max_length=100, required=False, label="Potência / cilindrada", widget=forms.TextInput(attrs=INPUT))
    gross_weight = forms.CharField(max_length=50, required=False, label="PBT", widget=forms.TextInput(attrs=INPUT))
    cmt = forms.CharField(max_length=50, required=False, label="CMT", widget=forms.TextInput(attrs=INPUT))
    axles = forms.CharField(max_length=20, required=False, label="Eixos", widget=forms.TextInput(attrs=INPUT))
    seating = forms.CharField(max_length=20, required=False, label="Lotação", widget=forms.TextInput(attrs=INPUT))
    bodywork = forms.CharField(max_length=100, required=False, label="Carroceria", widget=forms.TextInput(attrs=INPUT))


class CRLVVehicleCreateForm(CRLVConfirmForm):
    sector = forms.ModelChoiceField(
        queryset=Sector.objects.filter(active=True).order_by("name"),
        label="Setor",
        widget=forms.Select(attrs=SELECT),
    )
    status = forms.ModelChoiceField(
        queryset=VehicleStatus.objects.filter(active=True).order_by("name"),
        label="Situação",
        widget=forms.Select(attrs=SELECT),
    )

class LicensingCalendarForm(forms.ModelForm):
    plate_finals = forms.MultipleChoiceField(
        choices=[(str(i), str(i)) for i in range(10)],
        label="Finais das placas",
        required=True,
        help_text="Selecione todos os finais que compartilham este prazo.",
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        from apps.fleet.models import LicensingCalendar
        model = LicensingCalendar
        fields = ["exercise", "due_date", "notes"]
        labels = {
            "exercise": "Exercício",
            "due_date": "Data-limite",
            "notes": "Observações",
        }
        help_texts = {
            "exercise": "Ano do calendário oficial do DETRAN-RJ.",
            "due_date": "Data final para regularização do licenciamento.",
            "notes": "Informe, por exemplo, se o prazo foi prorrogado.",
        }
        widgets = {
            "exercise": forms.NumberInput(attrs={**INPUT, "min": 2020, "max": 2100}),
            "due_date": forms.DateInput(attrs={**INPUT, "type": "date"}),
            "notes": forms.Textarea(attrs={**INPUT, "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and not self.is_bound:
            from apps.fleet.models import LicensingCalendar
            self.fields["plate_finals"].initial = list(
                LicensingCalendar.objects.filter(
                    exercise=self.instance.exercise,
                    due_date=self.instance.due_date,
                    notes=self.instance.notes,
                ).values_list("plate_final", flat=True)
            )


class DriverForm(forms.ModelForm):
    renewal_date = forms.DateField(
        label="Data da Renovação",
        required=False,
        widget=forms.DateInput(format='%Y-%m-%d', attrs={**INPUT, 'type': 'date'}),
        help_text="Preencha apenas se estiver registrando uma renovação de CNH."
    )

    class Meta:
        model = Driver
        fields = ['name', 'sectors', 'registration', 'unit', 'phone', 'email', 'cpf', 'birth_date', 'cnh_number', 'cnh_category', 'cnh_expiration', 'renewal_date', 'active']
        labels = {
            'name': 'Nome',
            'registration': 'Matrícula',
            'unit': 'Unidade Administrativa',
            'phone': 'Telefone',
            'email': 'E-mail',
            'cpf': 'CPF',
            'birth_date': 'Data de nascimento',
            'cnh_number': 'Nº CNH',
            'cnh_category': 'Categoria CNH',
            'cnh_expiration': 'Validade CNH',
            'active': 'Situação',
        }
        widgets = {
            'name': forms.TextInput(attrs={**INPUT, 'placeholder': 'Nome completo'}),
            'registration': forms.TextInput(attrs={**INPUT, 'placeholder': 'Matrícula ou Registro'}),
            'unit': forms.Select(attrs=SELECT),
            'phone': forms.TextInput(attrs={**INPUT, 'placeholder': '(00) 00000-0000'}),
            'email': forms.EmailInput(attrs={**INPUT, 'placeholder': 'email@exemplo.com'}),
            'cpf': forms.TextInput(attrs={**INPUT, 'placeholder': '000.000.000-00'}),
            'birth_date': forms.DateInput(format='%Y-%m-%d', attrs={**INPUT, 'type': 'date'}),
            'cnh_number': forms.TextInput(attrs={**INPUT, 'placeholder': 'Número da CNH'}),
            'cnh_category': forms.TextInput(attrs={**INPUT, 'placeholder': 'Ex: AB, D, E'}),
            'cnh_expiration': forms.DateInput(format='%Y-%m-%d', attrs={**INPUT, 'type': 'date'}),
            'active': forms.Select(choices=[(True, 'Ativo'), (False, 'Inativo')], attrs=SELECT),
        }

    def __init__(self, *args, user=None, requested_sector=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.fleet.models import Sector
        from apps.fleet.driver_scope import effective_driver_sector_slugs

        allowed = effective_driver_sector_slugs(user) if user is not None else {"adm", "lei-seca"}
        self._requested_sector = requested_sector
        self._allowed_sector_slugs = allowed
        self._preserved_sector_ids = set()
        if "sectors" in self.fields:
            self.fields["sectors"].queryset = Sector.objects.filter(slug__in=allowed)
            self.fields["sectors"].required = True
            self.fields["sectors"].widget = forms.CheckboxSelectMultiple(choices=self.fields["sectors"].choices)
            if not self.instance._state.adding:
                self._preserved_sector_ids = set(
                    self.instance.sectors.exclude(slug__in=allowed).values_list("pk", flat=True)
                )
            elif requested_sector in allowed:
                self.initial["sectors"] = list(Sector.objects.filter(slug=requested_sector))
            elif len(allowed) == 1:
                self.initial["sectors"] = list(Sector.objects.filter(slug__in=allowed))

    def _save_m2m(self):
        super()._save_m2m()
        if self._preserved_sector_ids:
            self.instance.sectors.add(*self._preserved_sector_ids)

    def save(self, commit=True):
        driver = super().save(commit=False)
        renewal_date = self.cleaned_data.get('renewal_date')

        if commit:
            driver.save()
            self.save_m2m()
            if renewal_date and driver.cnh_expiration:
                from apps.fleet.models import DriverCNHHistory
                DriverCNHHistory.objects.create(
                    driver=driver,
                    renewal_date=renewal_date,
                    new_expiration=driver.cnh_expiration,
                    cnh_number=driver.cnh_number or "",
                    cnh_category=driver.cnh_category or "",
                )

        return driver


class DriverVehicleAssignmentForm(forms.Form):
    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        label='Veículo',
        widget=forms.Select(attrs=SELECT),
        help_text='O veículo selecionado passará a ficar vinculado a este motorista.',
    )
    sei_number = forms.CharField(
        label='Nº do SEI',
        required=False,
        max_length=100,
        widget=forms.TextInput(
            attrs={**INPUT, 'placeholder': 'Opcional'}
        ),
    )
    custody_started_on = forms.DateField(
        label='Início da vigência do SEI',
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
        self.fields['vehicle'].queryset = Vehicle.objects.filter(active=True).select_related('brand', 'model').prefetch_related('plate_history').order_by('plate_history__plate')
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
            'brand', 'model', 'version', 'manufacture_year', 'model_year',
            'color', 'fuel', 'category', 'vehicle_type', 'motor', 'power_cylinder',
            'gross_weight', 'cmt', 'axles', 'seating', 'bodywork', 'renavam',
            'contract', 'renter', 'unit', 'base',
            'status', 'armored', 'custody_info', 'notes',
        ]
        labels = {
            'brand': 'Marca', 'model': 'Modelo', 'version': 'Versão',
            'manufacture_year': 'Ano de fabricação', 'model_year': 'Ano modelo',
            'color': 'Cor', 'fuel': 'Combustível', 'category': 'Categoria',
            'vehicle_type': 'Espécie / tipo', 'motor': 'Motor',
            'power_cylinder': 'Potência / cilindrada', 'gross_weight': 'PBT',
            'cmt': 'CMT', 'axles': 'Eixos', 'seating': 'Lotação',
            'bodywork': 'Carroceria', 'renavam': 'RENAVAM', 'contract': 'Contrato',
            'renter': 'Locadora', 'unit': 'Unidade Administrativa',
            'base': 'Base', 'status': 'Situação', 'armored': 'Blindado',
            'custody_info': 'SEI / Acautelamento', 'notes': 'Observações',
        }
        widgets = {
            'brand': forms.Select(attrs=SELECT),
            'model': forms.Select(attrs=SELECT),
            'version': forms.TextInput(attrs=INPUT),
            'manufacture_year': forms.NumberInput(attrs=INPUT),
            'model_year': forms.NumberInput(attrs=INPUT),
            'color': forms.TextInput(attrs={**INPUT, 'placeholder': 'Ex: PRETO'}),
            'fuel': forms.TextInput(attrs=INPUT),
            'category': forms.TextInput(attrs=INPUT),
            'vehicle_type': forms.TextInput(attrs=INPUT),
            'motor': forms.TextInput(attrs=INPUT),
            'power_cylinder': forms.TextInput(attrs=INPUT),
            'gross_weight': forms.TextInput(attrs=INPUT),
            'cmt': forms.TextInput(attrs=INPUT),
            'axles': forms.TextInput(attrs=INPUT),
            'seating': forms.TextInput(attrs=INPUT),
            'bodywork': forms.TextInput(attrs=INPUT),
            'renavam': forms.TextInput(attrs={**INPUT, 'placeholder': 'Número do RENAVAM'}),
            'contract': forms.Select(attrs=SELECT),
            'renter': forms.Select(attrs=SELECT),
            'unit': forms.Select(attrs=SELECT),
            'base': forms.Select(attrs=SELECT),
            'status': forms.Select(attrs=SELECT),
            'custody_info': forms.TextInput(attrs={**INPUT, 'placeholder': 'SEI-420001/...'}),
            'notes': forms.Textarea(attrs={**INPUT, 'rows': 3}),
        }


class VehicleExitOrderForm(forms.ModelForm):
    class Meta:
        model = VehicleExitOrder
        fields = ["vehicle", "driver", "departed_at", "destination", "reason", "notes"]
        labels = {
            "vehicle": "Viatura", "driver": "Motorista", "departed_at": "Data e hora efetivas da saída",
            "destination": "Destino", "reason": "Motivo da retirada", "notes": "Observações",
        }
        widgets = {
            "vehicle": forms.Select(attrs=SELECT), "driver": forms.Select(attrs=SELECT),
            "departed_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={**INPUT, "type": "datetime-local"}),
            "destination": forms.TextInput(attrs={**INPUT, "maxlength": 255}),
            "reason": forms.Textarea(attrs={**INPUT, "rows": 3}),
            "notes": forms.Textarea(attrs={**INPUT, "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle"].queryset = Vehicle.objects.filter(active=True).select_related("brand", "model").prefetch_related("plate_history").order_by("brand__name", "model__name")
        self.fields["vehicle"].label_from_instance = self.label_from_instance
        self.fields["driver"].queryset = Driver.objects.filter(active=True).order_by("name")

    @staticmethod
    def label_from_instance(vehicle):
        plate = next(
            (item.plate for item in vehicle.plate_history.all()
             if item.kind == 'CURRENT' and item.ends_on is None),
            'Sem placa',
        )
        description = ' '.join(
            part for part in [
                vehicle.brand.name if vehicle.brand else '',
                vehicle.model.name if vehicle.model else '',
            ] if part
        )
        return f'{plate} — {description or "Veículo sem modelo"}'


class VehicleExitOrderReturnForm(forms.Form):
    returned_at = forms.DateTimeField(
        label="Data e hora efetivas do retorno",
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={**INPUT, "type": "datetime-local"}),
    )
    return_notes = forms.CharField(
        label="Observações do retorno", required=False,
        widget=forms.Textarea(attrs={**INPUT, "rows": 3}),
    )


class ContractForm(forms.ModelForm):
    vehicles = forms.ModelMultipleChoiceField(
        queryset=Vehicle.objects.none(),
        label='Vincular veículos',
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'vehicle-checkbox'}),
    )
    sei = forms.CharField(
        label='SEI',
        required=False,
        max_length=80,
        widget=forms.TextInput(attrs={**INPUT, 'placeholder': 'Digite o número do SEI'}),
    )

    class Meta:
        model = Contract
        fields = ['number', 'renter', 'starts_on', 'ends_on']
        labels = {
            'number': 'Nome do contrato',
            'renter': 'Nome da locadora',
            'starts_on': 'Data de início',
            'ends_on': 'Data de encerramento',
        }
        widgets = {
            'number': forms.TextInput(attrs={**INPUT, 'placeholder': 'Nome ou número do contrato'}),
            'renter': forms.Select(attrs=SELECT),
            'starts_on': forms.DateInput(format='%Y-%m-%d', attrs={**INPUT, 'type': 'date'}),
            'ends_on': forms.DateInput(format='%Y-%m-%d', attrs={**INPUT, 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vehicles'].queryset = (
            Vehicle.objects.filter(active=True)
            .select_related('brand', 'model')
            .prefetch_related('plate_history')
            .order_by('brand__name', 'model__name')
        )
        self.fields['vehicles'].label_from_instance = self.label_vehicle

        if self.instance and self.instance.pk:
            self.fields['vehicles'].initial = self.instance.vehicles.values_list('pk', flat=True)
            relation = self.instance.sei_processes.select_related('process').first()
            if relation:
                self.fields['sei'].initial = relation.process.sei_number

    @staticmethod
    def label_vehicle(vehicle):
        plate = next(
            (item.plate for item in vehicle.plate_history.all()
             if item.kind == 'CURRENT' and not item.ends_on),
            'Sem placa',
        )
        description = ' '.join(
            part for part in [vehicle.brand.name if vehicle.brand else '', vehicle.model.name if vehicle.model else '']
            if part
        )
        return f'{plate} — {description or "Veículo sem modelo"}'

    def save(self, commit=True):
        contract = super().save(commit=commit)
        if not commit:
            return contract

        from apps.fleet.models import SEIProcessRelation

        selected_vehicle_ids = set(self.cleaned_data.get('vehicles', []).values_list('pk', flat=True))
        Vehicle.objects.filter(contract=contract).exclude(pk__in=selected_vehicle_ids).update(contract=None)
        Vehicle.objects.filter(pk__in=selected_vehicle_ids).update(contract=contract)

        contract.sei_processes.all().delete()
        sei_number = self.cleaned_data.get('sei', '').strip()
        if sei_number:
            process = SEIProcess.objects.filter(sei_number=sei_number).first()
            if not process:
                status, _ = SEIProcessStatus.objects.get_or_create(name='Aberto')
                process = SEIProcess.objects.create(
                    sei_number=sei_number,
                    status=status,
                    created_by=getattr(self, '_user', None),
                )
            SEIProcessRelation.objects.create(
                process=process,
                content_object=contract,
                created_by=getattr(self, '_user', None),
            )
        return contract


class VehicleContractForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ['contract']
        labels = {'contract': 'Contrato'}
        widgets = {'contract': forms.Select(attrs=SELECT)}


class FineForm(forms.ModelForm):
    vehicle = forms.ModelChoiceField(queryset=Vehicle.objects.none(), label='Placa do veículo', widget=forms.Select(attrs=SELECT))
    driver = forms.ModelChoiceField(queryset=Driver.objects.none(), label='Motorista vinculado', required=False, widget=forms.Select(attrs=SELECT))

    class Meta:
        model = VehicleFine
        fields = ['vehicle', 'auto_number', 'agency', 'status', 'date', 'amount', 'due_date', 'notes']
        labels = {'vehicle':'Placa do veículo','auto_number':'Nº do Auto de Infração','agency':'Órgão Autuador','status':'Situação','date':'Data da Infração','amount':'Valor (R$)','due_date':'Vencimento','notes':'Observações / Processo SEI'}
        widgets = {
            'vehicle': forms.Select(attrs=SELECT),
            'auto_number': forms.TextInput(attrs={**INPUT, 'placeholder':'RA20629234'}),
            'agency': forms.TextInput(attrs={**INPUT, 'placeholder':'SMTR, PRF, DETRO...'}),
            'status': forms.Select(attrs=SELECT),
            'date': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={**INPUT, 'type':'datetime-local'}),
            'amount': forms.NumberInput(attrs={**INPUT, 'step':'0.01', 'placeholder':'0.00'}),
            'due_date': forms.DateInput(format='%Y-%m-%d', attrs={**INPUT, 'type':'date'}),
            'notes': forms.Textarea(attrs={**INPUT, 'rows':3, 'placeholder':'Processo SEI, observações...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vehicle'].queryset = Vehicle.objects.filter(active=True).select_related('brand','model').prefetch_related('plate_history').order_by('brand__name','model__name')
        self.fields['vehicle'].label_from_instance = self.label_from_instance
        self.fields['driver'].queryset = Driver.objects.order_by('name')
        # BaseModel assigns a UUID before the object is saved, so ``pk`` is
        # not evidence that a new VehicleFine has a vehicle relation.
        # Accessing ``instance.vehicle`` without a FK raises
        # RelatedObjectDoesNotExist.
        if not self.instance._state.adding and self.instance.vehicle_id:
            assignment = self.instance.vehicle.driver_assignments.filter(is_active=True).select_related('driver').first()
            if assignment:
                self.fields['driver'].initial = assignment.driver_id

    @staticmethod
    def label_from_instance(vehicle):
        plate = next((p.plate for p in vehicle.plate_history.all() if p.kind == 'CURRENT' and not p.ends_on), 'Sem placa')
        description = ' '.join(part for part in [vehicle.brand.name if vehicle.brand else '', vehicle.model.name if vehicle.model else ''] if part)
        return f'{plate} — {description or "Veículo sem modelo"}'


class FineStatusForm(forms.ModelForm):
    class Meta:
        model = VehicleFine
        fields = ['status']
        labels = {'status': 'Situação'}
        widgets = {'status': forms.Select(attrs=SELECT)}

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


class RevisionActionForm(forms.Form):
    workshop = forms.ModelChoiceField(
        queryset=Workshop.objects.filter(active=True).order_by('name'),
        label='Oficina cadastrada',
        required=False,
        widget=forms.Select(attrs=SELECT),
    )
    workshop_name = forms.CharField(
        label='Oficina (digitar)',
        required=False,
        max_length=150,
        widget=forms.TextInput(attrs={**INPUT, 'placeholder': 'Digite o nome da oficina, se não estiver na lista'}),
    )
    sent_date = forms.DateField(
        label='Data enviada para revisão',
        required=False,
        widget=forms.DateInput(attrs={**INPUT, 'type': 'date'}),
    )
    return_date = forms.DateField(
        label='Data de retorno da revisão',
        required=False,
        widget=forms.DateInput(attrs={**INPUT, 'type': 'date'}),
    )
    service = forms.CharField(
        label='Serviço',
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={**INPUT, 'placeholder': 'Revisão preventiva'}),
    )
    completion_mileage = forms.IntegerField(
        label='KM no retorno',
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={**INPUT, 'min': 0, 'placeholder': 'KM registrada na saída da oficina'}),
    )
    resulting_status = forms.ModelChoiceField(
        queryset=VehicleStatus.objects.filter(active=True).order_by('name'),
        label='Situação após retorno',
        required=False,
        widget=forms.Select(attrs=SELECT),
    )
    notes = forms.CharField(
        label='Observações',
        required=False,
        widget=forms.Textarea(attrs={**INPUT, 'rows': 3}),
    )


class VehiclePositionForm(forms.Form):
    sector = forms.ModelChoiceField(
        label="Setor de destino",
        queryset=None,
        empty_label=None,
    )
    active = forms.ChoiceField(
        label="Situação operacional",
        choices=(("true", "Ativa"), ("false", "Inativa")),
    )
    reason = forms.CharField(
        label="Motivo da alteração",
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Ex.: Transferência da ADM para a Lei Seca; encerramento do contrato..."}),
        min_length=5,
    )

    def __init__(self, *args, **kwargs):
        from apps.fleet.models import Sector
        super().__init__(*args, **kwargs)
        self.fields["sector"].queryset = Sector.objects.filter(slug__in=["adm", "lei-seca"]).order_by("name")



class CNHUploadForm(forms.Form):
    file = forms.FileField(
        label="Arquivo da CNH em PDF",
        widget=forms.FileInput(attrs={**INPUT, "accept": ".pdf,application/pdf"}),
    )

    def clean_file(self):
        file_obj = self.cleaned_data["file"]
        if not file_obj.name.lower().endswith(".pdf"):
            raise forms.ValidationError("Envie a CNH em arquivo PDF.")
        return file_obj


class BrazilianDateInput(forms.DateInput):
    input_type = "text"

    def __init__(self, attrs=None):
        defaults = {"placeholder": "dd/mm/aaaa", "inputmode": "numeric", "autocomplete": "off"}
        defaults.update(attrs or {})
        super().__init__(format="%d/%m/%Y", attrs=defaults)

    def format_value(self, value):
        if isinstance(value, str):
            from datetime import datetime
            raw = value.strip()
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    value = datetime.strptime(raw[:10], fmt).date()
                    break
                except ValueError:
                    continue
        return super().format_value(value)


class BrazilianDateField(forms.DateField):
    input_formats = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", BrazilianDateInput())
        kwargs.setdefault("input_formats", self.input_formats)
        super().__init__(*args, **kwargs)


class CNHDriverCreateForm(DriverForm):
    birth_date = BrazilianDateField(label="Data de nascimento", required=False)
    cnh_expiration = BrazilianDateField(label="Validade CNH", required=False)

    class Meta(DriverForm.Meta):
        fields = [
            "name", "cpf", "birth_date", "cnh_number", "cnh_category",
            "cnh_expiration", "cnh_issue_date", "cnh_first_issue_date",
            "identity_document", "issuing_authority", "issuing_state",
            "nationality", "father_name", "mother_name", "location",
        ]

    document_id = forms.UUIDField(widget=forms.HiddenInput())
    cnh_issue_date = BrazilianDateField(label="Data de emissão da CNH", required=False)
    cnh_first_issue_date = BrazilianDateField(label="Primeira habilitação", required=False)
    identity_document = forms.CharField(label="Documento de identidade", max_length=70, required=False, widget=forms.TextInput(attrs=INPUT))
    issuing_authority = forms.CharField(label="Órgão emissor", max_length=50, required=False, widget=forms.TextInput(attrs=INPUT))
    issuing_state = forms.CharField(label="UF emissora", max_length=12, required=False, widget=forms.TextInput(attrs=INPUT))
    nationality = forms.CharField(label="Nacionalidade", max_length=60, required=False, widget=forms.TextInput(attrs=INPUT))
    father_name = forms.CharField(label="Filiação — pai", max_length=150, required=False, widget=forms.TextInput(attrs=INPUT))
    mother_name = forms.CharField(label="Filiação — mãe", max_length=150, required=False, widget=forms.TextInput(attrs=INPUT))
    location = forms.CharField(label="Local de emissão", max_length=70, required=False, widget=forms.TextInput(attrs=INPUT))

    def __init__(self, *args, user=None, requested_sector=None, **kwargs):
        super().__init__(*args, user=user, requested_sector=requested_sector, **kwargs)
        # Renovação é um evento administrativo, não um dado impresso na CNH.
        self.fields.pop("renewal_date", None)

    def save(self, commit=True):
        driver = super().save(commit=commit)
        if commit:
            from apps.fleet.models import Sector
            allowed = getattr(self, "_allowed_sector_slugs", set())
            sector_slug = self._requested_sector if self._requested_sector in allowed else None
            if sector_slug is None and len(allowed) == 1:
                sector_slug = next(iter(allowed))
            if sector_slug:
                sector = Sector.objects.filter(slug=sector_slug, active=True).first()
                if sector:
                    driver.sectors.add(sector)
        return driver

    def clean_cpf(self):
        value = "".join(ch for ch in (self.cleaned_data.get("cpf") or "") if ch.isdigit())
        if not value:
            return ""
        if len(value) != 11:
            raise forms.ValidationError("O CPF deve conter 11 dígitos.")
        return f"{value[:3]}.{value[3:6]}.{value[6:9]}-{value[9:]}"
