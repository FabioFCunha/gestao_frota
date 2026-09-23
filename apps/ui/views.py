from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models import Count, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from .forms import DriverForm, DriverVehicleAssignmentForm, VehicleForm, FineForm
from apps.fleet.models import VehiclePlate

class FleetLoginView(LoginView):
    template_name = "ui/login.html"
    redirect_authenticated_user = True


@login_required
def dashboard(request):
    from apps.fleet.services import get_dashboard_metrics, get_operational_alerts
    metrics = get_dashboard_metrics({})
    alerts = get_operational_alerts({})
    context = {
        "metrics": metrics,
        "alerts": alerts,
    }
    return render(request, "ui/dashboard.html", context)


@login_required
def vehicle_list(request):
    from apps.fleet.models import Vehicle
    qs = Vehicle.objects.select_related('status', 'brand', 'model').prefetch_related('plate_history', 'custody_records').all()
    q = request.GET.get('q', '')
    if q:
        qs = qs.filter(
            Q(plate_history__plate__icontains=q) |
            Q(renavam__icontains=q) |
            Q(contract__number__icontains=q)
        ).distinct()
    context = {"vehicles": qs[:50], "q": q}
    return render(request, "ui/vehicle_list.html", context)


@login_required
def vehicle_dossier(request, pk):
    import re
    from apps.fleet.models import Vehicle, VehiclePlate, VehicleMileage, VehicleCustody
    from django.shortcuts import get_object_or_404

    vehicle = get_object_or_404(
        Vehicle.objects.select_related(
            'status', 'brand', 'model', 'unit', 'base', 'renter', 'contract'
        ),
        pk=pk
    )
    plates = VehiclePlate.objects.filter(vehicle=vehicle).order_by('-starts_on')
    current_plates = plates.filter(ends_on__isnull=True, kind='CURRENT')
    reserved_plates = plates.filter(ends_on__isnull=True, kind='RESERVED')
    latest_km = VehicleMileage.objects.filter(vehicle=vehicle).order_by('-date').first()
    km_history = VehicleMileage.objects.filter(vehicle=vehicle).order_by('-date')[:10]
    maintenances = vehicle.maintenances.select_related('status', 'type', 'workshop').order_by('-entered_at')[:10]
    fines = vehicle.fines.select_related('status').order_by('-date')[:10]
    inspections = vehicle.inspections.select_related('type', 'status').order_by('-date')[:10]
    active_assignments = vehicle.driver_assignments.filter(is_active=True).select_related('driver')
    custody_records = vehicle.custody_records.select_related('created_by').all()
    active_driver = active_assignments.first().driver if active_assignments.exists() else None

    # Parse structured notes
    notes = vehicle.notes or ''
    motorista = ''
    motorista_tel = ''
    oficina = ''
    km_prox_revisao = None
    obs_list = []

    for line in notes.split('\n'):
        line = line.strip()
        if line.startswith('[MOTORISTA]'):
            parts = line.replace('[MOTORISTA]', '').strip().split('| Tel:')
            motorista = parts[0].strip()
            if len(parts) > 1:
                motorista_tel = parts[1].strip()
        elif line.startswith('[OFICINA]'):
            oficina = line.replace('[OFICINA]', '').strip()
        elif line.startswith('[KM_PROX_REVISAO]'):
            try:
                km_prox_revisao = int(line.replace('[KM_PROX_REVISAO]', '').strip())
            except ValueError:
                pass
        elif line.startswith('[OBS]'):
            obs_list.append(line.replace('[OBS]', '').strip())

    # Calculate revision status
    km_atual = latest_km.mileage if latest_km else 0
    km_faltando = None
    revisao_status = None
    if km_prox_revisao and km_atual:
        km_faltando = km_prox_revisao - km_atual
        if km_faltando <= 0:
            revisao_status = 'VENCIDA'
        elif km_faltando <= 2000:
            revisao_status = 'PROXIMA'
        else:
            revisao_status = 'OK'

    if request.method == 'POST' and request.POST.get('action') == 'add_custody':
        from datetime import datetime
        kind = request.POST.get('kind') or VehicleCustody.OUTRO
        allowed_kinds = {value for value, _ in VehicleCustody.KIND_CHOICES}
        reference = (request.POST.get('reference') or '').strip()
        starts_on_raw = request.POST.get('starts_on') or ''
        starts_on = None
        if starts_on_raw:
            try:
                starts_on = datetime.fromisoformat(starts_on_raw)
                if timezone.is_naive(starts_on):
                    starts_on = timezone.make_aware(starts_on)
            except ValueError:
                starts_on = None
        notes_custody = (request.POST.get('custody_notes') or '').strip()
        if kind not in allowed_kinds:
            messages.error(request, 'Tipo de registro inválido.')
        elif not reference:
            messages.error(request, 'Informe o SEI ou referência do acautelamento.')
        else:
            record = VehicleCustody(
                vehicle=vehicle,
                kind=kind,
                reference=reference,
                starts_on=starts_on or timezone.now(),
                notes=notes_custody,
                created_by=request.user,
            )
            record.save()
            messages.success(request, 'Registro de SEI/acautelamento adicionado ao veículo.')
            return redirect('vehicle_dossier', pk=vehicle.pk)

    context = {
        'vehicle': vehicle,
        'current_plates': current_plates,
        'reserved_plates': reserved_plates,
        'all_plates': plates,
        'latest_km': latest_km,
        'km_history': km_history,
        'maintenances': maintenances,
        'fines': fines,
        'inspections': inspections,
        'active_driver': active_driver,
        'custody_records': custody_records,
        'custody_kinds': VehicleCustody.KIND_CHOICES,
        'motorista': motorista,
        'motorista_tel': motorista_tel,
        'oficina': oficina,
        'km_prox_revisao': km_prox_revisao,
        'km_atual': km_atual,
        'km_faltando': km_faltando,
        'revisao_status': revisao_status,
        'obs_list': obs_list,
    }
    return render(request, "ui/dossier.html", context)


@login_required
def contract_list(request):
    from apps.fleet.models import Contract
    qs = Contract.objects.select_related('renter').all().order_by('ends_on')
    q = request.GET.get('q', '')
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(renter__name__icontains=q))
    context = {"contracts": qs[:50], "q": q}
    return render(request, "ui/contract_list.html", context)


@login_required
def driver_list(request):
    from apps.fleet.models import Driver
    from django.db.models import Prefetch
    from apps.fleet.models import VehicleDriverAssignment

    active_assignments = VehicleDriverAssignment.objects.filter(is_active=True).select_related(
        'vehicle__brand', 'vehicle__model'
    ).prefetch_related('vehicle__plate_history')

    qs = Driver.objects.prefetch_related(
        Prefetch('vehicle_assignments', queryset=active_assignments, to_attr='active_assignments')
    ).order_by('name')

    q = request.GET.get('q', '')
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q))
    from django.utils.timezone import now
    context = {"drivers": qs, "q": q, "today": now().date()}
    return render(request, "ui/driver_list.html", context)


@login_required
def maintenance_list(request):
    import re
    from apps.fleet.models import Vehicle, VehicleMileage
    
    qs = Vehicle.objects.select_related('brand', 'model').prefetch_related('plate_history')
    
    q = request.GET.get('q', '')
    if q:
        qs = qs.filter(
            Q(plate_history__plate__icontains=q) |
            Q(brand__name__icontains=q) |
            Q(model__name__icontains=q)
        ).distinct()

    vehicles_data = []
    
    # We need current mileages
    mileages = {}
    for m in VehicleMileage.objects.order_by('-date'):
        if m.vehicle_id not in mileages:
            mileages[m.vehicle_id] = m.mileage

    for v in qs:
        # Get active plate
        plate = "-"
        for p in v.plate_history.all():
            if not p.ends_on and p.kind == 'CURRENT':
                plate = p.plate
                break
                
        # Parse next revision from notes
        km_prox_revisao = None
        notes = v.notes or ''
        for line in notes.split('\n'):
            line = line.strip()
            if line.startswith('[KM_PROX_REVISAO]'):
                try:
                    km_prox_revisao = int(line.replace('[KM_PROX_REVISAO]', '').strip())
                except ValueError:
                    pass

        km_atual = mileages.get(v.id, 0)
        km_faltando = None
        revisao_status = None
        
        if km_prox_revisao and km_atual:
            km_faltando = km_prox_revisao - km_atual
            if km_faltando <= 0:
                revisao_status = 'VENCIDA'
            elif km_faltando <= 2000:
                revisao_status = 'PROXIMA'
            else:
                revisao_status = 'OK'
                
        if km_prox_revisao:
            vehicles_data.append({
                'id': v.id,
                'plate': plate,
                'brand_model': f"{v.brand.name if v.brand else ''} {v.model.name if v.model else ''}",
                'km_atual': km_atual,
                'km_prox_revisao': km_prox_revisao,
                'km_faltando': km_faltando,
                'revisao_status': revisao_status
            })

    # Sort by urgency (vencida first, then proxima, then OK)
    def sort_key(x):
        status = x['revisao_status']
        if status == 'VENCIDA': return 0
        if status == 'PROXIMA': return 1
        return 2

    vehicles_data.sort(key=lambda x: (sort_key(x), x['km_faltando'] if x['km_faltando'] is not None else 999999))

    context = {"vehicles_data": vehicles_data, "q": q}
    return render(request, "ui/maintenance_list.html", context)


@login_required
def fine_list(request):
    from apps.fleet.models import VehicleFine
    qs = VehicleFine.objects.select_related('vehicle', 'status').prefetch_related('vehicle__plate_history').order_by('-date')
    q = request.GET.get('q', '')
    if q:
        qs = qs.filter(
            Q(vehicle__plate_history__plate__icontains=q) |
            Q(auto_number__icontains=q) |
            Q(agency__icontains=q)
        ).distinct()
    context = {"fines": qs[:50], "q": q}
    return render(request, "ui/fine_list.html", context)



@login_required
def driver_create(request):
    if request.method == 'POST':
        form = DriverForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Motorista cadastrado com sucesso!')
            return redirect('driver_list')
    else:
        form = DriverForm()
    return render(request, 'ui/form.html', {'form': form, 'title': 'Cadastrar Motorista', 'back_url': 'driver_list'})


@login_required
def driver_edit(request, pk):
    from apps.fleet.models import Driver

    driver = get_object_or_404(Driver, pk=pk)
    if request.method == 'POST':
        form = DriverForm(request.POST, instance=driver)
        if form.is_valid():
            form.save()
            messages.success(request, 'Dados do motorista atualizados com sucesso!')
            return redirect('driver_list')
    else:
        form = DriverForm(instance=driver)
    return render(request, 'ui/form.html', {'form': form, 'title': f'Editar Motorista: {driver.name}', 'back_url': 'driver_list'})


@login_required
def driver_assign_vehicle(request, pk):
    from apps.fleet.models import Driver
    from apps.fleet.services import assign_driver_to_vehicle

    driver = get_object_or_404(Driver, pk=pk)
    if request.method == 'POST':
        form = DriverVehicleAssignmentForm(request.POST)
        if form.is_valid():
            assign_driver_to_vehicle(
                vehicle=form.cleaned_data['vehicle'],
                driver=driver,
                user=request.user,
                notes=form.cleaned_data['notes'],
            )
            messages.success(request, 'Veículo vinculado ao motorista com sucesso!')
            return redirect('driver_list')
    else:
        form = DriverVehicleAssignmentForm()
    return render(request, 'ui/form.html', {'form': form, 'title': f'Vincular veículo: {driver.name}', 'back_url': 'driver_list'})

@login_required
def vehicle_create(request):
    if request.method == 'POST':
        form = VehicleForm(request.POST)
        if form.is_valid():
            vehicle = form.save(commit=False)
            vehicle.created_by = request.user
            vehicle.save()
            plate_str = form.cleaned_data['plate']
            if plate_str:
                VehiclePlate.objects.create(vehicle=vehicle, plate=plate_str, kind='CURRENT', starts_on=timezone.now(), changed_by=request.user)
            res_plate_str = form.cleaned_data.get('reserved_plate')
            if res_plate_str:
                VehiclePlate.objects.create(vehicle=vehicle, plate=res_plate_str, kind='RESERVED', starts_on=timezone.now(), changed_by=request.user)
            messages.success(request, 'Veículo cadastrado com sucesso!')
            return redirect('vehicle_list')
    else:
        form = VehicleForm()
    return render(request, 'ui/form.html', {'form': form, 'title': 'Cadastrar Veículo', 'back_url': 'vehicle_list'})

@login_required
def fine_create(request):
    if request.method == 'POST':
        form = FineForm(request.POST)
        if form.is_valid():
            plate_str = form.cleaned_data['plate']
            plate_record = VehiclePlate.objects.filter(plate__iexact=plate_str).select_related('vehicle').first()
            if not plate_record:
                messages.error(request, f'Placa {plate_str} não encontrada no sistema.')
                return render(request, 'ui/form.html', {'form': form, 'title': 'Cadastrar Multa', 'back_url': 'fine_list'})
            fine = form.save(commit=False)
            fine.vehicle = plate_record.vehicle
            fine.created_by = request.user
            fine.save()
            messages.success(request, 'Multa cadastrada com sucesso!')
            return redirect('fine_list')
    else:
        form = FineForm()
    return render(request, 'ui/form.html', {'form': form, 'title': 'Cadastrar Multa', 'back_url': 'fine_list'})

@login_required
def maintenance_create(request):
    from .forms import MaintenanceForm
    from apps.fleet.models import VehiclePlate
    from django.contrib import messages
    from django.shortcuts import redirect
    
    if request.method == 'POST':
        form = MaintenanceForm(request.POST)
        if form.is_valid():
            plate_str = form.cleaned_data['plate']
            plate_record = VehiclePlate.objects.filter(plate__iexact=plate_str).select_related('vehicle').first()
            if not plate_record:
                messages.error(request, f'Placa {plate_str} não encontrada.')
                return render(request, 'ui/form.html', {'form': form, 'title': 'Registrar Manutenção', 'back_url': 'maintenance_list'})
            maintenance = form.save(commit=False)
            maintenance.vehicle = plate_record.vehicle
            maintenance.created_by = request.user
            maintenance.save()
            messages.success(request, 'Manutenção registrada com sucesso!')
            return redirect('maintenance_list')
    else:
        initial = {}
        if request.GET.get('plate'):
            initial['plate'] = request.GET.get('plate')
        form = MaintenanceForm(initial=initial)
    return render(request, 'ui/form.html', {'form': form, 'title': 'Registrar Manutenção', 'back_url': 'maintenance_list'})

@login_required
def km_import(request):
    from .forms import KMImportForm
    from apps.fleet.models import VehicleMileage
    import pandas as pd
    
    if request.method == 'POST':
        form = KMImportForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES['csv_file']
            try:
                encodings = ['utf-8', 'utf-16', 'latin1', 'cp1252']
                separators = [';', ',', '	']
                df = None
                col_placa = None
                col_km = None
                
                for enc in encodings:
                    for sep in separators:
                        try:
                            csv_file.seek(0)
                            raw_bytes = csv_file.read()
                            decoded_text = raw_bytes.decode(enc)
                            import io
                            text_io = io.StringIO(decoded_text)
                            
                            temp_df = pd.read_csv(text_io, sep=sep)
                            if len(temp_df.columns) < 2:
                                continue
                                
                            c_placa = next((c for c in temp_df.columns if c.strip().lower() == 'placa' or 'placa' in str(c).lower()), None)
                            c_km = next((c for c in temp_df.columns if 'km' in str(c).lower() or 'quilometragem' in str(c).lower() or 'hod' in str(c).lower()), None)
                            
                            if c_placa and c_km:
                                df = temp_df
                                col_placa = c_placa
                                col_km = c_km
                                break
                        except Exception:
                            continue
                    if df is not None:
                        break
                
                if not col_placa or not col_km:
                    messages.error(request, 'Não foi possível identificar as colunas Placa e Quilometragem no CSV.')
                    return render(request, 'ui/form.html', {'form': form, 'title': 'Importar KM (Prime)', 'back_url': 'maintenance_list', 'enctype': 'multipart/form-data'})
                
                created = 0
                for _, row in df.iterrows():
                    placa = str(row[col_placa]).strip().upper()
                    km_raw = row[col_km]
                    try:
                        km = int(float(km_raw))
                    except (ValueError, TypeError):
                        continue
                    
                    if not placa or km <= 0:
                        continue
                        
                    plate_record = VehiclePlate.objects.filter(plate__iexact=placa).select_related('vehicle').first()
                    if plate_record:
                        vehicle = plate_record.vehicle
                        latest_km = VehicleMileage.objects.filter(vehicle=vehicle).order_by('-date').first()
                        if not latest_km or latest_km.mileage < km:
                            VehicleMileage.objects.create(
                                vehicle=vehicle,
                                mileage=km,
                                date=timezone.now(),
                                origin='INTEGRACAO',
                                recorded_by=request.user,
                                notes='Importado via CSV Prime'
                            )
                            created += 1
                messages.success(request, f'Importação concluída! {created} quilometragens atualizadas.')
                return redirect('maintenance_list')
            except Exception as e:
                messages.error(request, f'Erro ao processar arquivo: {str(e)}')
    else:
        form = KMImportForm()
    return render(request, 'ui/form.html', {'form': form, 'title': 'Importar KM (Prime)', 'back_url': 'maintenance_list', 'enctype': 'multipart/form-data'})
