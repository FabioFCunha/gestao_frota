from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models import Count, Q, Prefetch
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.utils import timezone
from .forms import DriverForm, DriverVehicleAssignmentForm, VehicleForm, VehicleContractForm, FineForm, RevisionActionForm
from apps.accounts.forms import FleetAuthenticationForm
from apps.accounts.decorators import module_permission
from apps.fleet.models import VehiclePlate

class FleetLoginView(LoginView):
    template_name = "ui/login.html"
    authentication_form = FleetAuthenticationForm
    redirect_authenticated_user = True


@login_required
def dashboard(request):
    from datetime import timedelta
    from apps.fleet.models import Vehicle, VehiclePlate, Maintenance, VehicleFine
    from apps.fleet.services import get_dashboard_metrics, get_operational_alerts

    metrics = get_dashboard_metrics({})
    alerts = get_operational_alerts({})

    today = timezone.now().date()
    fine_warning_date = today + timedelta(days=30)

    # --- Build lookup sets for each situation ---

    active_maintenance_ids = set(
        Maintenance.objects
        .filter(status__name__in=["Aberta", "Em andamento"])
        .values_list("vehicle_id", flat=True)
    )

    fine_due_ids = set(
        VehicleFine.objects
        .filter(
            due_date__isnull=False,
            due_date__gte=today,
            due_date__lte=fine_warning_date,
            status__name__in=["Pendente", "Em análise", "Em recurso"],
        )
        .values_list("vehicle_id", flat=True)
    )

    contract_attention_ids = set(
        Vehicle.objects
        .filter(
            contract__isnull=False,
            contract__ends_on__lte=fine_warning_date,
            contract__ends_on__gte=today,
        )
        .values_list("id", flat=True)
    )

    # Separate overdue vs upcoming revisions
    revision_vencida_ids = set()
    revision_proxima_ids = set()
    revision_by_vehicle = {}
    for item in alerts.get("revisoes_vencidas", []):
        revision_by_vehicle[item["vehicle_id"]] = item
        if item["status"] == "DEVIDA":
            revision_vencida_ids.add(item["vehicle_id"])
        elif item["status"] == "PROXIMA":
            revision_proxima_ids.add(item["vehicle_id"])

    # --- Load all vehicles ---
    from django.db.models import Prefetch
    from apps.fleet.models import VehicleDriverAssignment, VehicleMileage

    vehicles = (
        Vehicle.objects
        .select_related("status", "contract", "brand", "model")
        .prefetch_related(
            "plate_history",
            Prefetch("driver_assignments", queryset=VehicleDriverAssignment.objects.filter(is_active=True).select_related("driver"), to_attr="active_drivers"),
            Prefetch("mileage_history", queryset=VehicleMileage.objects.order_by("-date", "-created_at"), to_attr="recent_mileage")
        )
        .order_by("brand__name", "model__name")
    )

    # --- Priority ordering weights ---
    PRIORITY_ORDER = {
        "revisao-vencida": 0,
        "manutencao": 1,
        "multa": 2,
        "contrato": 3,
        "revisao-proxima": 4,
        "normal": 5,
    }

    plate_rows = []
    for vehicle in vehicles:
        current_plate = next(
            (
                p.plate
                for p in vehicle.plate_history.all()
                if p.ends_on is None and p.kind == VehiclePlate.CURRENT
            ),
            None,
        )
        if not current_plate:
            continue

        attention = []

        if vehicle.id in revision_vencida_ids:
            attention.append("revisao_vencida")
        if vehicle.id in revision_proxima_ids:
            attention.append("revisao_proxima")
        if vehicle.id in active_maintenance_ids or (
            vehicle.status and "manutenção" in vehicle.status.name.lower()
        ):
            attention.append("manutencao")
        if vehicle.id in fine_due_ids:
            attention.append("multa")
        if vehicle.id in contract_attention_ids:
            attention.append("contrato")

        # Determine dominant priority for card styling
        if "revisao_vencida" in attention:
            priority = "revisao-vencida"
            priority_label = "Revisão vencida"
        elif "manutencao" in attention:
            priority = "manutencao"
            priority_label = "Em manutenção"
        elif "multa" in attention:
            priority = "multa"
            priority_label = "Multa a vencer"
        elif "contrato" in attention:
            priority = "contrato"
            priority_label = "Contrato a vencer"
        elif "revisao_proxima" in attention:
            priority = "revisao-proxima"
            priority_label = "Revisão próxima"
        else:
            priority = "normal"
            priority_label = "Operacional"

        # Extract mileage and driver
        current_mileage = vehicle.recent_mileage[0].mileage if vehicle.recent_mileage else None
        active_driver = vehicle.active_drivers[0].driver if vehicle.active_drivers else None

        from apps.fleet.services import get_vehicle_revision_status
        revision = get_vehicle_revision_status(vehicle=vehicle)
        if revision:
            rev_dict = {
                "status": revision["status"],
                "km_prox_revisao": revision["next_revision_km"],
                "km_faltando": revision["km_remaining"],
                "ultrapassado": max(0, -revision["km_remaining"]) if revision["km_remaining"] is not None else 0
            }
        else:
            rev_dict = None

        plate_rows.append({
            "id": vehicle.id,
            "plate": current_plate,
            "model": vehicle.model.name if vehicle.model else "",
            "priority": priority,
            "priority_label": priority_label,
            "alerts": " ".join(attention),
            "mileage": current_mileage,
            "driver_name": active_driver.name if active_driver else None,
            "cnh_expiration": active_driver.cnh_expiration if active_driver else None,
            "revision_info": rev_dict,
        })

    # Sort: problems first (by priority weight), then alphabetically by plate
    plate_rows.sort(key=lambda r: (PRIORITY_ORDER.get(r["priority"], 99), r["plate"]))

    # --- Build counts for the indicator strip ---
    plate_alert_counts = {
        "revisao_vencida": sum(1 for r in plate_rows if "revisao_vencida" in r["alerts"]),
        "revisao_proxima": sum(1 for r in plate_rows if "revisao_proxima" in r["alerts"]),
        "manutencao": sum(1 for r in plate_rows if "manutencao" in r["alerts"]),
        "multa": sum(1 for r in plate_rows if "multa" in r["alerts"]),
        "contrato": sum(1 for r in plate_rows if "contrato" in r["alerts"]),
    }

    context = {
        "metrics": metrics,
        "plate_rows": plate_rows,
        "plate_alert_counts": plate_alert_counts,
    }
    return render(request, "ui/dashboard.html", context)

@login_required
@module_permission("fleet.view_vehicle")
def vehicle_list(request):
    from apps.fleet.models import Vehicle
    from apps.fleet.models import Vehicle, VehicleDriverAssignment, VehicleCustody

    active_assignments = (
        VehicleDriverAssignment.objects
        .filter(is_active=True)
        .select_related('driver')
        .prefetch_related(
            Prefetch(
                'custodies',
                queryset=VehicleCustody.objects.order_by('-started_on'),
                to_attr='active_custodies',
            )
        )
    )
    qs = (
        Vehicle.objects
        .select_related('status', 'brand', 'model')
        .prefetch_related(
            'plate_history',
            Prefetch('driver_assignments', queryset=active_assignments, to_attr='active_driver_assignments'),
        )
        .all()
    )
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
@module_permission("fleet.view_vehicle")
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
    active_assignment = (
        vehicle.driver_assignments
        .filter(is_active=True)
        .select_related('driver')
        .prefetch_related(
            Prefetch(
                'custodies',
                queryset=VehicleCustody.objects.order_by('-started_on'),
                to_attr='ordered_custodies',
            )
        )
        .first()
    )
    active_driver = active_assignment.driver if active_assignment else None
    active_custody = None
    if active_assignment:
        active_custody = next(
            (custody for custody in active_assignment.ordered_custodies if custody.ended_on is None),
            None,
        )

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

    # Calculate revision status using the official WW Trans rule.
    from apps.fleet.services import get_vehicle_revision_status

    revision = get_vehicle_revision_status(vehicle=vehicle)

    km_atual = revision["current_km"]
    km_prox_revisao = revision["next_revision_km"]
    km_faltando = revision["km_remaining"]
    revisao_status = revision["status"]

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
        'active_assignment': active_assignment,
        'active_custody': active_custody,
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
@module_permission("fleet.view_contract")
def contract_list(request):
    from apps.fleet.models import Contract
    qs = Contract.objects.select_related('renter').all().order_by('ends_on')
    q = request.GET.get('q', '')
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(renter__name__icontains=q))
    context = {"contracts": qs[:50], "q": q}
    return render(request, "ui/contract_list.html", context)


@login_required
@module_permission("fleet.view_contract")
def contract_detail(request, pk):
    from apps.fleet.models import Contract, Vehicle, VehicleDriverAssignment, VehicleCustody, VehiclePlate

    contract = get_object_or_404(
        Contract.objects.select_related('renter'),
        pk=pk,
    )

    active_assignments = (
        VehicleDriverAssignment.objects
        .filter(is_active=True)
        .select_related('driver')
        .prefetch_related(
            Prefetch(
                'custodies',
                queryset=VehicleCustody.objects.order_by('-started_on'),
                to_attr='ordered_custodies',
            )
        )
    )

    vehicles = (
        Vehicle.objects
        .filter(contract=contract)
        .select_related('brand', 'model', 'status')
        .prefetch_related(
            'plate_history',
            Prefetch(
                'driver_assignments',
                queryset=active_assignments,
                to_attr='active_driver_assignments',
            ),
        )
        .order_by('brand__name', 'model__name')
    )

    vehicle_rows = []
    for vehicle in vehicles:
        current_plate = next(
            (plate.plate for plate in vehicle.plate_history.all()
             if plate.ends_on is None and plate.kind == VehiclePlate.CURRENT),
            None,
        )
        assignment = vehicle.active_driver_assignments[0] if vehicle.active_driver_assignments else None
        active_custody = None
        if assignment:
            active_custody = next(
                (custody for custody in assignment.ordered_custodies if custody.ended_on is None),
                None,
            )

        vehicle_rows.append({
            'vehicle': vehicle,
            'plate': current_plate,
            'driver': assignment.driver if assignment else None,
            'custody': active_custody,
        })

    context = {
        'contract': contract,
        'vehicle_rows': vehicle_rows,
        'vehicle_count': len(vehicle_rows),
    }
    return render(request, "ui/contract_detail.html", context)


@login_required
@module_permission("fleet.view_driver")
def driver_list(request):
    from apps.fleet.models import Driver
    from django.db.models import Prefetch
    from apps.fleet.models import VehicleDriverAssignment

    active_assignments = VehicleDriverAssignment.objects.filter(is_active=True).select_related(
        'vehicle__brand', 'vehicle__model'
    ).prefetch_related('vehicle__plate_history')

    status = request.GET.get('status', 'active')
    qs = Driver.objects.prefetch_related(
        Prefetch('vehicle_assignments', queryset=active_assignments, to_attr='active_assignments')
    ).order_by('name')

    if status == 'inactive':
        qs = qs.filter(active=False)
    else:
        qs = qs.filter(active=True)

    q = request.GET.get('q', '')
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q))
    from django.utils.timezone import now
    context = {"drivers": qs, "q": q, "status": status, "today": now().date()}
    return render(request, "ui/driver_list.html", context)


@login_required
@module_permission("fleet.view_maintenance")
def maintenance_list(request):
    from apps.fleet.models import Vehicle, VehicleMileage, Maintenance
    from apps.fleet.services import get_vehicle_revision_status

    qs = (
        Vehicle.objects
        .select_related('brand', 'model', 'status')
        .prefetch_related(
            'plate_history',
            'mileage_history',
            'maintenances__type',
            'maintenances__status',
            'maintenances__workshop',
        )
    )

    q = request.GET.get('q', '')
    if q:
        qs = qs.filter(
            Q(plate_history__plate__icontains=q) |
            Q(brand__name__icontains=q) |
            Q(model__name__icontains=q)
        ).distinct()

    vehicles_data = []

    for v in qs:
        plate = "-"
        for p in v.plate_history.all():
            if not p.ends_on and p.kind == 'CURRENT':
                plate = p.plate
                break

        revision = get_vehicle_revision_status(vehicle=v)

        active_revision = (
            v.maintenances
            .filter(type__name__iexact='Revisão', exited_at__isnull=True)
            .select_related('workshop', 'type', 'status')
            .order_by('-entered_at')
            .first()
        )

        last_revision = None
        if revision.get('last_revision_id'):
            last_revision = next(
                (m for m in v.maintenances.all() if str(m.id) == str(revision['last_revision_id'])),
                None,
            )

        vehicles_data.append({
            'id': v.id,
            'plate': plate,
            'brand_model': f"{v.brand.name if v.brand else ''} {v.model.name if v.model else ''}".strip() or '-',
            'km_atual': revision['current_km'],
            'km_prox_revisao': revision['next_revision_km'],
            'km_faltando': revision['km_remaining'],
            'revisao_status': revision['status'],
            'last_revision_km': revision['last_revision_km'],
            'has_history': revision['has_history'],
            'active_revision': active_revision,
            'last_revision': last_revision,
            'last_revision_id': revision.get('last_revision_id'),
            'last_revision_entered_at': revision.get('last_revision_entered_at'),
            'last_revision_exited_at': revision.get('last_revision_exited_at'),
            'last_revision_workshop': revision.get('last_revision_workshop', ''),
            'last_revision_workshop_name': revision.get('last_revision_workshop_name', ''),
            'last_revision_service': revision.get('last_revision_service', ''),
            'last_revision_completion_mileage': revision.get('last_revision_completion_mileage'),
            'vehicle_status': v.status.name if v.status else '-',
        })

    def sort_key(x):
        if x['active_revision']:
            return (0, 0)
        status_order = {
            'DEVIDA': 1,
            'PROXIMA': 2,
            'SEM_HISTORICO': 3,
            'OK': 4,
        }
        return (
            status_order.get(x['revisao_status'], 5),
            x['km_faltando'] if x['km_faltando'] is not None else 999999,
        )

    vehicles_data.sort(key=sort_key)

    context = {
        "vehicles_data": vehicles_data,
        "q": q,
        "revision_action_form": RevisionActionForm(),
    }
    return render(request, "ui/maintenance_list.html", context)


@login_required
@module_permission("fleet.change_maintenance")
def revision_action(request, pk):
    from datetime import datetime, time
    from apps.fleet.models import Vehicle, Maintenance, MaintenanceType, MaintenanceStatus
    from apps.fleet.services import (
        get_vehicle_revision_status,
        open_maintenance,
        complete_maintenance,
        change_vehicle_status,
    )

    vehicle = get_object_or_404(Vehicle, pk=pk)

    if request.method != 'POST':
        return redirect('maintenance_list')

    action = (request.POST.get('action') or '').strip().lower()
    form = RevisionActionForm(request.POST)

    def date_to_datetime(value):
        if not value:
            return None
        return timezone.make_aware(datetime.combine(value, time.min))

    def apply_common_fields(maintenance):
        maintenance.workshop = form.cleaned_data.get('workshop')
        maintenance.workshop_name = (form.cleaned_data.get('workshop_name') or '').strip()
        maintenance.service = form.cleaned_data.get('service') or maintenance.service
        maintenance.notes = form.cleaned_data.get('notes') or maintenance.notes
        sent_date = form.cleaned_data.get('sent_date')
        if sent_date:
            maintenance.entered_at = date_to_datetime(sent_date)
        return maintenance

    if action == 'open':
        if not form.is_valid():
            messages.error(request, 'Verifique os dados da revisão.')
            return redirect('maintenance_list')

        if Maintenance.objects.filter(
            vehicle=vehicle,
            type__name__iexact='Revisão',
            exited_at__isnull=True,
        ).exists():
            messages.error(request, 'Este veículo já está com uma revisão em andamento.')
            return redirect('maintenance_list')

        revision_type = MaintenanceType.objects.filter(name__iexact='Revisão', active=True).first()
        open_status = MaintenanceStatus.objects.filter(name__iexact='Aberta', active=True).first()

        if not revision_type or not open_status:
            messages.error(request, 'Os cadastros de tipo "Revisão" e status "Aberta" precisam existir.')
            return redirect('maintenance_list')

        revision = get_vehicle_revision_status(vehicle=vehicle)
        current_km = revision['current_km'] or 0
        sent_date = form.cleaned_data.get('sent_date') or timezone.localdate()

        maintenance = Maintenance.objects.create(
            vehicle=vehicle,
            type=revision_type,
            status=open_status,
            workshop=form.cleaned_data.get('workshop'),
            workshop_name=(form.cleaned_data.get('workshop_name') or '').strip(),
            mileage=current_km,
            service=(form.cleaned_data.get('service') or 'Revisão preventiva').strip(),
            entered_at=date_to_datetime(sent_date),
            notes=(form.cleaned_data.get('notes') or '').strip(),
            opened_by=request.user,
        )

        try:
            open_maintenance(maintenance=maintenance, user=request.user)
        except ValueError as exc:
            maintenance.delete()
            messages.error(request, str(exc))
        else:
            messages.success(request, f'Viatura {vehicle} enviada para revisão.')
        return redirect('maintenance_list')

    if action in ('complete', 'edit'):
        maintenance_id = request.POST.get('maintenance_id')

        # A conclusão da revisão depende apenas dos dados operacionais
        # (data de retorno + KM). Campos auxiliares do formulário não podem
        # impedir o fechamento de uma revisão já aberta.
        maintenance = get_object_or_404(
            Maintenance.objects.select_related('vehicle', 'status', 'type', 'vehicle_status_before_opening'),
            pk=maintenance_id,
            vehicle=vehicle,
            type__name__iexact='Revisão',
        )

        form_is_valid = form.is_valid()
        cleaned = form.cleaned_data if form_is_valid else {}

        from datetime import date as date_class

        sent_date_raw = (request.POST.get('sent_date') or '').strip()
        return_date_raw = (request.POST.get('return_date') or '').strip()
        completion_mileage_raw = (request.POST.get('completion_mileage') or '').strip()

        try:
            sent_date = cleaned.get('sent_date') if form_is_valid else (
                date_class.fromisoformat(sent_date_raw) if sent_date_raw else None
            )
        except ValueError:
            messages.error(request, 'A data de envio da revisão é inválida.')
            return redirect('maintenance_list')

        try:
            return_date = cleaned.get('return_date') if form_is_valid else (
                date_class.fromisoformat(return_date_raw) if return_date_raw else None
            )
        except ValueError:
            messages.error(request, 'A data de retorno da revisão é inválida.')
            return redirect('maintenance_list')

        if sent_date and return_date and return_date < sent_date:
            messages.error(request, 'A data de retorno não pode ser anterior à data de envio para revisão.')
            return redirect('maintenance_list')

        if completion_mileage_raw:
            try:
                completion_mileage = int(completion_mileage_raw)
            except ValueError:
                messages.error(request, 'A quilometragem de retorno é inválida.')
                return redirect('maintenance_list')
        else:
            completion_mileage = cleaned.get('completion_mileage') if form_is_valid else None

        if return_date and completion_mileage is None:
            messages.error(request, 'Informe a quilometragem registrada no retorno da revisão.')
            return redirect('maintenance_list')

        if completion_mileage is not None and completion_mileage < 0:
            messages.error(request, 'A quilometragem de retorno não pode ser negativa.')
            return redirect('maintenance_list')

        if (
            completion_mileage is not None
            and maintenance.mileage is not None
            and completion_mileage < maintenance.mileage
        ):
            messages.error(request, 'A quilometragem de retorno não pode ser menor que a quilometragem de entrada.')
            return redirect('maintenance_list')

        if form_is_valid:
            workshop = cleaned.get('workshop')
            workshop_name = (cleaned.get('workshop_name') or '').strip()
            service = (cleaned.get('service') or '').strip()
            notes = (cleaned.get('notes') or '').strip()
        else:
            workshop = maintenance.workshop
            workshop_name = (request.POST.get('workshop_name') or '').strip()
            service = (request.POST.get('service') or '').strip()
            notes = (request.POST.get('notes') or '').strip()

        maintenance.workshop = workshop
        maintenance.workshop_name = workshop_name
        maintenance.service = service or maintenance.service
        maintenance.notes = notes or maintenance.notes
        if sent_date:
            maintenance.entered_at = date_to_datetime(sent_date)

        if not return_date:
            open_status = MaintenanceStatus.objects.filter(name__iexact='Aberta', active=True).first()
            if not open_status:
                messages.error(request, 'Status de manutenção "Aberta" não encontrado.')
                return redirect('maintenance_list')

            maintenance.status = open_status
            maintenance.exited_at = None
            maintenance.completion_mileage = None
            maintenance.opened_by = maintenance.opened_by or request.user
            maintenance.resolved_by = None
            maintenance.save(update_fields=[
                'workshop', 'workshop_name', 'service', 'notes', 'entered_at',
                'status', 'exited_at', 'completion_mileage', 'opened_by',
                'resolved_by', 'updated_at'
            ])

            try:
                change_vehicle_status(
                    vehicle=vehicle,
                    status_name='Em manutenção',
                    user=request.user,
                    reason='Revisão sem data de retorno',
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, 'Revisão salva sem data de retorno. O veículo permanece EM REVISÃO.')
            return redirect('maintenance_list')

        # Se o usuário informou retorno + KM, a revisão deve ser encerrada.
        # A situação após o retorno pode ser escolhida no formulário; se ficar
        # vazia, recuperamos a situação anterior à abertura da revisão.
        resulting_status = cleaned.get('resulting_status') if form_is_valid else None
        if resulting_status is None:
            resulting_status = maintenance.vehicle_status_before_opening or vehicle.status

        if resulting_status is None:
            messages.error(request, 'Não foi possível determinar a situação da viatura após o retorno.')
            return redirect('maintenance_list')

        maintenance.save(update_fields=[
            'workshop', 'workshop_name', 'service', 'notes', 'entered_at', 'updated_at'
        ])

        try:
            complete_maintenance(
                maintenance=maintenance,
                user=request.user,
                resulting_status=resulting_status.name,
                reason='Retorno/edição da revisão',
                completion_mileage=completion_mileage,
                exited_at=date_to_datetime(return_date),
                allow_already_completed=(action == 'edit'),
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                f'Revisão registrada. Próxima revisão calculada em {completion_mileage + 10000:,} km.'.replace(',', '.')
            )
        return redirect('maintenance_list')

    if action == 'initialize':
        if not form.is_valid():
            messages.error(request, 'Informe os dados do histórico.')
            return redirect('maintenance_list')

        if get_vehicle_revision_status(vehicle=vehicle)['has_history']:
            messages.info(request, 'Este veículo já possui histórico de revisão.')
            return redirect('maintenance_list')

        last_revision_km = form.cleaned_data.get('completion_mileage')
        sent_date = form.cleaned_data.get('sent_date')
        return_date = form.cleaned_data.get('return_date')
        if last_revision_km is None:
            messages.error(request, 'Informe a quilometragem da última revisão concluída.')
            return redirect('maintenance_list')

        revision_type = MaintenanceType.objects.filter(name__iexact='Revisão', active=True).first()
        completed_status = MaintenanceStatus.objects.filter(name__iexact='Concluída', active=True).first()
        if not revision_type or not completed_status:
            messages.error(request, 'Os cadastros de tipo "Revisão" e status "Concluída" precisam existir.')
            return redirect('maintenance_list')

        maintenance = Maintenance.objects.create(
            vehicle=vehicle,
            type=revision_type,
            status=completed_status,
            workshop=form.cleaned_data.get('workshop'),
            workshop_name=(form.cleaned_data.get('workshop_name') or '').strip(),
            mileage=last_revision_km,
            completion_mileage=last_revision_km if return_date else None,
            service=form.cleaned_data.get('service') or 'Revisão preventiva — histórico inicial',
            entered_at=date_to_datetime(sent_date) or timezone.now(),
            exited_at=date_to_datetime(return_date) if return_date else None,
            notes=form.cleaned_data.get('notes') or 'Histórico inicializado pelo sistema.',
            resolved_by=request.user if return_date else None,
        )
        if not return_date:
            open_status = MaintenanceStatus.objects.filter(name__iexact='Aberta', active=True).first()
            if open_status:
                maintenance.status = open_status
                maintenance.save(update_fields=['status', 'updated_at'])
                change_vehicle_status(
                    vehicle=vehicle,
                    status_name='Em manutenção',
                    user=request.user,
                    reason='Histórico de revisão sem retorno',
                )

        if return_date:
            messages.success(
                request,
                f'Histórico atualizado. Próxima revisão: {last_revision_km + 10000:,} km.'.replace(',', '.')
            )
        else:
            messages.success(request, 'Histórico salvo sem data de retorno. O veículo permanece EM REVISÃO.')
        return redirect('maintenance_list')

    messages.error(request, 'Ação de revisão inválida.')
    return redirect('maintenance_list')

@login_required
@module_permission("fleet.view_vehiclefine")
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
@module_permission("fleet.add_driver")
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
@module_permission("fleet.change_driver")
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
@module_permission("fleet.change_driver")
def driver_assign_vehicle(request, pk):
    from apps.fleet.models import Driver
    from apps.fleet.services import assign_driver_to_vehicle

    driver = get_object_or_404(Driver, pk=pk)

    if request.method == 'POST':
        form = DriverVehicleAssignmentForm(request.POST)

        if form.is_valid():
            try:
                assign_driver_to_vehicle(
                    vehicle=form.cleaned_data['vehicle'],
                    driver=driver,
                    user=request.user,
                    notes=form.cleaned_data['notes'],
                    sei_number=form.cleaned_data['sei_number'],
                    custody_started_on=form.cleaned_data['custody_started_on'],
                    custody_ended_on=form.cleaned_data['custody_ended_on'],
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(
                    request,
                    'Veículo vinculado ao motorista com sucesso!'
                )
                return redirect('driver_list')
    else:
        form = DriverVehicleAssignmentForm()

    return render(
        request,
        'ui/form.html',
        {
            'form': form,
            'title': f'Vincular veículo: {driver.name}',
            'back_url': 'driver_list',
        },
    )


@login_required
@module_permission("fleet.add_vehicle")
def vehicle_quick_create(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método não permitido.'}, status=405)

    from apps.fleet.models import Brand, VehicleModel, AdministrativeUnit, Base
    entity = (request.POST.get('entity') or '').strip()
    name = (request.POST.get('name') or '').strip()
    if not name:
        return JsonResponse({'error': 'Informe o nome.'}, status=400)

    try:
        if entity == 'brand':
            obj = Brand.objects.filter(name__iexact=name).first()
            if not obj:
                obj = Brand.objects.create(name=name)
            return JsonResponse({'id': str(obj.id), 'name': obj.name})

        if entity == 'model':
            brand_id = request.POST.get('brand_id')
            if not brand_id:
                return JsonResponse({'error': 'Selecione a marca do modelo.'}, status=400)
            brand = get_object_or_404(Brand, pk=brand_id)
            obj = VehicleModel.objects.filter(brand=brand, name__iexact=name).first()
            if not obj:
                obj = VehicleModel.objects.create(brand=brand, name=name)
            return JsonResponse({'id': str(obj.id), 'name': obj.name, 'brand_id': str(brand.id)})

        if entity == 'unit':
            acronym = (request.POST.get('acronym') or '').strip()
            if not acronym:
                return JsonResponse({'error': 'Informe a sigla da Unidade Administrativa.'}, status=400)
            obj = AdministrativeUnit.objects.filter(acronym__iexact=acronym).first()
            if not obj:
                obj = AdministrativeUnit.objects.filter(name__iexact=name).first()
            if not obj:
                obj = AdministrativeUnit.objects.create(name=name, acronym=acronym)
            return JsonResponse({'id': str(obj.id), 'name': obj.name, 'acronym': obj.acronym})

        if entity == 'base':
            unit_id = request.POST.get('unit_id')
            if not unit_id:
                return JsonResponse({'error': 'Selecione a Unidade Administrativa da base.'}, status=400)
            unit = get_object_or_404(AdministrativeUnit, pk=unit_id)
            obj = Base.objects.filter(unit=unit, name__iexact=name).first()
            if not obj:
                obj = Base.objects.create(name=name, unit=unit)
            return JsonResponse({'id': str(obj.id), 'name': obj.name, 'unit_id': str(unit.id)})

        return JsonResponse({'error': 'Tipo de cadastro inválido.'}, status=400)
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=400)


@login_required
@module_permission("fleet.add_vehicle")
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
    return render(request, 'ui/form.html', {'form': form, 'title': 'Cadastrar Veículo', 'back_url': 'vehicle_list', 'quick_create': True})

@login_required
@module_permission("fleet.change_vehicle")
def vehicle_contract_edit(request, pk):
    from apps.fleet.models import Vehicle

    vehicle = get_object_or_404(Vehicle, pk=pk)
    if request.method == 'POST':
        form = VehicleContractForm(request.POST, instance=vehicle)
        if form.is_valid():
            form.save()
            messages.success(request, 'Contrato do veículo atualizado com sucesso!')
            return redirect('vehicle_list')
    else:
        form = VehicleContractForm(instance=vehicle)

    return render(
        request,
        'ui/form.html',
        {
            'form': form,
            'title': f'Contrato do veículo: {vehicle}',
            'back_url': 'vehicle_list',
        },
    )


@login_required
@module_permission("fleet.add_vehiclefine")
def fine_create(request):
    # Consome mensagens pendentes de outras telas para não exibi-las no cadastro de multas.
    from django.contrib.messages import get_messages
    list(get_messages(request))

    if request.method == 'POST':
        form = FineForm(request.POST)
        if form.is_valid():
            fine = form.save(commit=False)
            fine.created_by = request.user
            fine.save()
            messages.success(request, 'Multa cadastrada com sucesso!')
            return redirect('fine_list')
    else:
        form = FineForm()
    return render(request, 'ui/form.html', {'form': form, 'title': 'Cadastrar Multa', 'back_url': 'fine_list'})


@login_required
@module_permission("fleet.change_vehiclefine")
def fine_edit(request, pk):
    # A ação da lista é específica para alterar apenas a situação da multa.
    from django.contrib.messages import get_messages
    list(get_messages(request))

    from apps.fleet.models import VehicleFine
    from .forms import FineStatusForm
    fine = get_object_or_404(VehicleFine, pk=pk)
    if request.method == 'POST':
        form = FineStatusForm(request.POST, instance=fine)
        if form.is_valid():
            form.save()
            messages.success(request, 'Situação da multa atualizada com sucesso!')
            return redirect('fine_list')
    else:
        form = FineStatusForm(instance=fine)
    return render(request, 'ui/form.html', {'form': form, 'title': f'Alterar Situação: {fine.auto_number}', 'back_url': 'fine_list'})

@login_required
@module_permission("fleet.add_maintenance")
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
@module_permission("fleet.add_vehiclemileage")
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
