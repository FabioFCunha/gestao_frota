from .exit_order_bdt import exit_order_bdt_rows
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models import Count, Q, Prefetch
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.utils.dateparse import parse_date
import uuid
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import JsonResponse, Http404
from django.contrib import messages
from django.utils import timezone
from .forms import DriverForm, DriverVehicleAssignmentForm, VehicleForm, VehicleContractForm, FineForm, RevisionActionForm, VehicleExitOrderForm, VehicleExitOrderReturnForm, VehiclePositionForm, CRLVUploadForm, CRLVConfirmForm, CRLVVehicleCreateForm, LicensingCalendarForm
from apps.accounts.forms import FleetAuthenticationForm
from apps.accounts.decorators import module_permission
from apps.fleet.models import VehiclePlate, Renter
from apps.fleet.sector_scope import apply_sector_scope, validate_vehicle_scope

from apps.fleet.services import get_vehicle_revision_interval

class FleetLoginView(LoginView):
    template_name = "ui/login.html"
    authentication_form = FleetAuthenticationForm
    redirect_authenticated_user = True


@login_required
def dashboard(request):
    from datetime import timedelta
    from apps.fleet.models import Vehicle, VehiclePlate, Maintenance, VehicleFine
    from apps.fleet.services import get_dashboard_metrics, get_operational_alerts, get_crlv_alerts
    from apps.fleet.crlv import normalize_plate
    from apps.fleet.sector_scope import apply_sector_scope

    requested_sector = request.GET.get("sector")
    scoped_vehicles = apply_sector_scope(Vehicle.objects.filter(active=True), request.user, requested_sector)
    scoped_vehicle_ids = scoped_vehicles.values_list("id", flat=True)

    metrics = get_dashboard_metrics({"vehicle__in": scoped_vehicle_ids})
    alerts = get_operational_alerts({"vehicle__in": scoped_vehicle_ids})
    crlv_alerts = get_crlv_alerts(scoped_vehicles)
    crlv_overdue_plates = {normalize_plate(item["plate"]) for item in crlv_alerts["overdue"]}

    today = timezone.now().date()
    fine_warning_date = today + timedelta(days=30)

    # --- Build lookup sets for each situation ---

    active_maintenance_ids = set(
        Maintenance.objects
        .filter(status__name__in=["Aberta", "Em andamento"], vehicle_id__in=scoped_vehicle_ids)
        .values_list("vehicle_id", flat=True)
    )

    fine_due_ids = set(
        VehicleFine.objects
        .filter(
            vehicle_id__in=scoped_vehicle_ids,
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
            id__in=scoped_vehicle_ids,
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
        scoped_vehicles
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
        "crlv-vencido": 1,
        "manutencao": 2,
        "multa": 3,
        "contrato": 4,
        "revisao-proxima": 5,
        "normal": 6,
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

        if normalize_plate(current_plate) in crlv_overdue_plates:
            attention.append("crlv_vencido")
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
        if "crlv_vencido" in attention:
            priority = "crlv-vencido"
            priority_label = "CRLV vencido"
        elif "revisao_vencida" in attention:
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
                "interval_km": revision["interval_km"],
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
        "crlv_vencido": sum(1 for r in plate_rows if "crlv_vencido" in r["alerts"]),
        "revisao_vencida": sum(1 for r in plate_rows if "revisao_vencida" in r["alerts"]),
        "revisao_proxima": sum(1 for r in plate_rows if "revisao_proxima" in r["alerts"]),
        "manutencao": sum(1 for r in plate_rows if "manutencao" in r["alerts"]),
        "multa": sum(1 for r in plate_rows if "multa" in r["alerts"]),
        "contrato": sum(1 for r in plate_rows if "contrato" in r["alerts"]),
    }

    from apps.fleet.sector_scope import can_select_sector

    # Pendências de vistoria vinculadas somente às viaturas do escopo do usuário.
    # Consultamos o histórico da vistoria, mas exibimos sempre a placa atual para
    # evitar duplicação por mudanças anteriores de placa.
    from apps.fleet.models import VehicleInspection
    pending_inspection_qs = (
        VehicleInspection.objects
        .filter(
            vehicle_id__in=scoped_vehicle_ids,
            status__name__in=["Reprovada", "Com ressalvas"],
        )
        .select_related("vehicle", "status")
        .prefetch_related("vehicle__plate_history")
        .order_by("-date", "-created_at")
    )
    pending_inspections = []
    for inspection in pending_inspection_qs:
        inspection_plate = next(
            (
                p.plate for p in inspection.vehicle.plate_history.all()
                if p.kind == VehiclePlate.CURRENT and p.ends_on is None
            ),
            "Sem placa atual",
        )
        pending_inspections.append({
            "id": inspection.id,
            "vehicle_id": inspection.vehicle_id,
            "plate": inspection_plate,
            "status": inspection.status.name,
            "date": inspection.date,
        })

    context = {
        "show_sector_filter": can_select_sector(request.user),
        "requested_sector": requested_sector,
        "metrics": metrics,
        "plate_rows": plate_rows,
        "plate_alert_counts": plate_alert_counts,
        "dashboard_alerts": {
            "contracts_expired": alerts.get("expired_contracts", []),
            "contracts_expiring": alerts.get("expiring_contracts", []),
            "fines_pending": alerts.get("pending_fines", []),
            "inspections_pending": pending_inspections,
            "cnh_expired": alerts.get("expired_cnh", []),
        },
        "crlv_alerts": crlv_alerts,
    }
    return render(request, "ui/dashboard.html", context)

@login_required
@module_permission("fleet.view_vehicle")
def vehicle_list(request):
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
    from apps.fleet.sector_scope import apply_sector_scope
    qs = apply_sector_scope(qs, request.user, request.GET.get("sector"))
    active_filter = request.GET.get('active', 'active')
    if active_filter == 'inactive':
        qs = qs.filter(active=False)
    elif active_filter != 'all':
        active_filter = 'active'
        qs = qs.filter(active=True)
    q = request.GET.get('q', '')
    if q:
        qs = qs.filter(
            Q(plate_history__plate__icontains=q) |
            Q(renavam__icontains=q) |
            Q(contract__number__icontains=q)
        ).distinct()
    from apps.fleet.sector_scope import (
        allowed_sector_slugs,
        can_manage_vehicle_status,
    )

    allowed_sectors = allowed_sector_slugs(request.user)
    requested_sector = request.GET.get("sector")
    from apps.fleet.sector_scope import can_select_sector
    show_sector_filter = can_select_sector(request.user)

    context = {
        "vehicles": qs[:50],
        "q": q,
        "active_filter": active_filter,
        "can_manage_vehicle_status": can_manage_vehicle_status(request.user),
        "allowed_sectors": allowed_sectors,
        "requested_sector": requested_sector,
        "show_sector_filter": show_sector_filter,
    }
    return render(request, "ui/vehicle_list.html", context)


@login_required
@module_permission("fleet.manage_vehicle_status")
def vehicle_set_active(request, pk):
    from apps.fleet.models import Vehicle
    from apps.fleet.services import set_vehicle_active
    from apps.fleet.sector_scope import can_manage_vehicle_status
    if not can_manage_vehicle_status(request.user):
        raise PermissionDenied("Somente o Administrador ADM pode alterar a situação da viatura.")
    if request.method != "POST":
        raise Http404
    vehicle = get_object_or_404(Vehicle.objects.select_related("sector"), pk=pk)
    validate_vehicle_scope(request.user, vehicle, request.GET.get("sector"))
    if not request.user.is_system_creator and not request.user.is_superuser and (not vehicle.sector or vehicle.sector.slug != "adm"):
        raise PermissionDenied("O Administrador ADM só pode administrar viaturas atualmente alocadas à ADM.")
    active = request.POST.get("active") == "true"
    try:
        set_vehicle_active(vehicle=vehicle, active=active, user=request.user, reason=request.POST.get("reason", "").strip())
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Viatura {'ativada' if active else 'inativada'} com sucesso.")
    return redirect(request.POST.get("next") or "vehicle_list")


@login_required
@module_permission("fleet.manage_vehicle_status")
def vehicle_position_edit(request, pk):
    from apps.fleet.models import Vehicle
    from apps.fleet.sector_scope import can_manage_vehicle_status
    from apps.fleet.services import change_vehicle_position

    if not can_manage_vehicle_status(request.user):
        raise PermissionDenied("Somente o Administrador ADM pode alterar a situação ou a posição da viatura.")

    vehicle = get_object_or_404(
        Vehicle.objects.select_related("sector", "brand", "model"),
        pk=pk,
    )
    validate_vehicle_scope(request.user, vehicle, request.GET.get("sector"))
    if not request.user.is_system_creator and not request.user.is_superuser and (not vehicle.sector or vehicle.sector.slug != "adm"):
        raise PermissionDenied("O Administrador ADM só pode administrar viaturas atualmente alocadas à ADM.")

    initial = {"sector": vehicle.sector, "active": "true" if vehicle.active else "false"}
    if request.method == "POST":
        form = VehiclePositionForm(request.POST, initial=initial)
        if form.is_valid():
            try:
                change_vehicle_position(
                    vehicle=vehicle,
                    sector=form.cleaned_data["sector"],
                    active=form.cleaned_data["active"] == "true",
                    user=request.user,
                    reason=form.cleaned_data["reason"],
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, "Posição da viatura atualizada com sucesso.")
                return redirect("vehicle_dossier", pk=vehicle.pk)
    else:
        form = VehiclePositionForm(initial=initial)

    return render(request, "ui/form.html", {
        "form": form,
        "title": "Alterar posição da viatura",
        "subtitle": f"Placa: {vehicle.plate_history.filter(kind='CURRENT', ends_on__isnull=True).values_list('plate', flat=True).first() or 'Sem placa'}",
        "back_url": "vehicle_dossier",
        "back_url_url": reverse("vehicle_dossier", kwargs={"pk": vehicle.pk}),
    })
@login_required
@module_permission("fleet.view_vehicle")
def bdt_list(request):
    """
    Tela de consulta dos BDTs sincronizados do Horus.

    Os dados sao carregados dinamicamente pelo frontend
    atraves do endpoint /api/bdts/.
    """
    from apps.fleet.models import Vehicle, VehiclePlate

    vehicle_filter = request.GET.get("vehicle")
    filtered_vehicle = None
    if vehicle_filter:
        try:
            from apps.fleet.sector_scope import apply_sector_scope
            filtered_vehicle = apply_sector_scope(Vehicle.objects.all(), request.user, request.GET.get("sector")).get(pk=vehicle_filter)
        except (Vehicle.DoesNotExist, ValueError):
            filtered_vehicle = None
    current_plate = None
    if filtered_vehicle:
        current_plate = (
            VehiclePlate.objects.filter(
                vehicle=filtered_vehicle,
                kind="CURRENT",
                ends_on__isnull=True,
            ).values_list("plate", flat=True).first()
        )
    return render(request, "ui/bdt_list.html", {
        "filtered_vehicle_plate": current_plate,
        "filtered_vehicle_id": vehicle_filter,
    })


@login_required
@module_permission("fleet.change_vehicle")
def vehicle_crlv(request, pk):
    from apps.fleet.models import Document, Vehicle, AuditLog
    from apps.fleet.services import confirm_crlv, stage_crlv_document

    vehicle = get_object_or_404(Vehicle.objects.prefetch_related("plate_history"), pk=pk)
    validate_vehicle_scope(request.user, vehicle, request.GET.get("sector"))
    current = vehicle.plate_history.filter(kind="CURRENT", ends_on__isnull=True).first()
    upload_form, confirm_form, preview = CRLVUploadForm(), None, None
    if request.method == "POST" and request.POST.get("step") == "upload":
        upload_form = CRLVUploadForm(request.POST, request.FILES)
        if upload_form.is_valid():
            document, preview = stage_crlv_document(vehicle=vehicle, file_obj=upload_form.cleaned_data["file"], user=request.user)
            aliases = {
                "CHEV": "Chevrolet", "GM": "Chevrolet",
                "VW": "Volkswagen", "MB": "Mercedes-Benz", "M.BENZ": "Mercedes-Benz",
            }
            brand_value = str(preview.get("brand_raw", "") or vehicle.brand.name if vehicle.brand else "").strip()
            brand_value = aliases.get(brand_value.upper(), brand_value)
            confirm_form = CRLVConfirmForm(initial={
                "document_id": document.id,
                "plate": preview.get("plate") or (current.plate if current else ""),
                "renavam": preview.get("renavam") or vehicle.renavam,
                "chassi": preview.get("chassi") or vehicle.chassi,
                "exercise": preview.get("exercise") or vehicle.crlv_exercise,
                "brand": brand_value or "",
                "model": preview.get("model_raw") or (vehicle.model.name if vehicle.model else ""),
                "version": preview.get("version") or vehicle.version,
                "manufacture_year": preview.get("manufacture_year") or vehicle.manufacture_year,
                "model_year": preview.get("model_year") or vehicle.model_year,
                "color": preview.get("color") or vehicle.color,
                "fuel": preview.get("fuel") or vehicle.fuel,
                "category": preview.get("category") or vehicle.category,
                "vehicle_type": preview.get("vehicle_type") or vehicle.vehicle_type,
                "motor": preview.get("motor") or vehicle.motor,
                "power_cylinder": preview.get("power_cylinder") or vehicle.power_cylinder,
                "gross_weight": preview.get("gross_weight") or vehicle.gross_weight,
                "cmt": preview.get("cmt") or vehicle.cmt,
                "axles": preview.get("axles") or vehicle.axles,
                "seating": preview.get("seating") or vehicle.seating,
                "bodywork": preview.get("bodywork") or vehicle.bodywork,
            })
    elif request.method == "POST":
        confirm_form = CRLVConfirmForm(request.POST)
        if confirm_form.is_valid():
            try:
                data = confirm_form.cleaned_data.copy()
                document_id = data.pop("document_id")
                document = Document.objects.get(pk=document_id)
                from django.contrib.contenttypes.models import ContentType
                vehicle_type = ContentType.objects.get_for_model(Vehicle)
                if (
                    document.document_type.name.casefold() != "crlv"
                    or not document.relations.filter(content_type=vehicle_type, object_id=vehicle.id).exists()
                ):
                    raise ValueError("O documento informado não é um CRLV vinculado a este veículo.")
                extraction_audit = AuditLog.objects.filter(
                    entity_type="document",
                    entity_id=document.id,
                    action="ANEXO DE CRLV PARA CONFERÊNCIA",
                ).order_by("-created_at").first()
                extracted_data = dict(extraction_audit.new_values or {}) if extraction_audit else {}
                extracted_data.update({
                    "reviewed": True,
                    "source": "CRLV",
                    "form_values": {k: (str(v) if hasattr(v, "pk") else v) for k, v in data.items()},
                })
                confirm_crlv(vehicle=vehicle, document=document, user=request.user, extracted_data=extracted_data, **data)
            except (Document.DoesNotExist, ValueError) as exc:
                confirm_form.add_error(None, str(exc))
            else:
                messages.success(request, "CRLV confirmado e prontuário atualizado.")
                return redirect("vehicle_dossier", pk=vehicle.pk)
    return render(request, "ui/crlv_form.html", {"vehicle": vehicle, "upload_form": upload_form, "confirm_form": confirm_form, "preview": preview, "current_plate": current.plate if current else ""})


@login_required
@module_permission("fleet.view_licensingcalendar")
def licensing_calendar(request):
    from django.db import transaction
    from apps.fleet.models import LicensingCalendar

    can_edit = (
        request.user.is_system_creator
        or request.user.has_perm("fleet.add_licensingcalendar")
        or request.user.has_perm("fleet.change_licensingcalendar")
    )
    editing = (
        LicensingCalendar.objects.filter(pk=request.GET.get("edit")).first()
        if request.GET.get("edit") else None
    )
    form = LicensingCalendarForm(instance=editing)

    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied

        instance = (
            LicensingCalendar.objects.filter(pk=request.POST.get("calendar_id")).first()
            if request.POST.get("calendar_id") else None
        )
        old_exercise = instance.exercise if instance else None
        old_due_date = instance.due_date if instance else None
        old_notes = instance.notes if instance else None
        old_group_finals = []
        if instance:
            old_group_finals = list(
                LicensingCalendar.objects.filter(
                    exercise=old_exercise,
                    due_date=old_due_date,
                    notes=old_notes,
                ).values_list("plate_final", flat=True)
            )

        form = LicensingCalendarForm(request.POST, instance=instance)
        if form.is_valid():
            exercise = form.cleaned_data["exercise"]
            due_date = form.cleaned_data["due_date"]
            notes = form.cleaned_data["notes"]
            selected_finals = {int(value) for value in form.cleaned_data["plate_finals"]}

            with transaction.atomic():
                # Ao editar um grupo no mesmo exercício, retirar apenas os finais
                # que foram desmarcados. Calendários de outros exercícios são preservados.
                if instance and exercise == old_exercise:
                    LicensingCalendar.objects.filter(
                        exercise=old_exercise,
                        due_date=old_due_date,
                        notes=old_notes,
                        plate_final__in=old_group_finals,
                    ).exclude(plate_final__in=selected_finals).delete()

                for plate_final in selected_finals:
                    entry = LicensingCalendar.objects.filter(
                        exercise=exercise,
                        plate_final=plate_final,
                    ).first()
                    if entry:
                        entry.due_date = due_date
                        entry.notes = notes
                        entry.save(update_fields=["due_date", "notes", "updated_at"])
                    else:
                        LicensingCalendar.objects.create(
                            exercise=exercise,
                            plate_final=plate_final,
                            due_date=due_date,
                            notes=notes,
                            created_by=request.user,
                        )

            messages.success(request, "Calendário de licenciamento salvo com sucesso.")
            return redirect("licensing_calendar")

    # Agrupar linhas com o mesmo exercício, prazo e observações para exibir
    # os finais de placa como um único grupo na tabela.
    grouped = {}
    for item in LicensingCalendar.objects.all():
        key = (item.exercise, item.due_date, item.notes)
        if key not in grouped:
            grouped[key] = {
                "id": item.id,
                "exercise": item.exercise,
                "due_date": item.due_date,
                "notes": item.notes,
                "plate_finals": [],
            }
        grouped[key]["plate_finals"].append(item.plate_final)

    calendars = sorted(
        grouped.values(),
        key=lambda row: (-row["exercise"], row["due_date"], row["plate_finals"][0]),
    )
    for row in calendars:
        row["plate_finals_label"] = ", ".join(str(value) for value in sorted(row["plate_finals"]))

    return render(request, "ui/licensing_calendar.html", {
        "calendars": calendars,
        "form": form,
        "can_edit": can_edit,
        "editing": editing,
    })


@login_required
@module_permission("fleet.view_vehicle")
def vehicle_dossier(request, pk):
    import re
    from apps.fleet.models import Vehicle, VehiclePlate, VehicleMileage, VehicleCustody, VehicleExitOrder, VehicleCRLV
    from django.shortcuts import get_object_or_404

    from apps.fleet.sector_scope import validate_vehicle_scope
    vehicle = get_object_or_404(
        Vehicle.objects.select_related(
            'status', 'brand', 'model', 'unit', 'base', 'renter', 'contract', 'sector'
        ),
        pk=pk
    )
    validate_vehicle_scope(request.user, vehicle, request.GET.get("sector"))
    from apps.fleet.models import BDT
    from apps.fleet.utils import normalize_km
    from django.core.paginator import Paginator

    bdt_qs = BDT.objects.filter(vehicle=vehicle).select_related('driver').order_by('-started_at', '-created_at')
    bdt_page = Paginator(bdt_qs, 3).get_page(request.GET.get('bdt_page', 1))
    bdt_total_km = 0
    bdt_total_valid = True
    for started, ended in bdt_qs.values_list('started_km', 'ended_km'):
        start_value, end_value = normalize_km(started), normalize_km(ended)
        if start_value is None or end_value is None or end_value < start_value:
            bdt_total_valid = False
            continue
        bdt_total_km += end_value - start_value
    bdt_summary = {
        'total': bdt_qs.count(),
        'open': bdt_qs.filter(ended_at__isnull=True, horus_active=True).count(),
        'closed': bdt_qs.filter(Q(ended_at__isnull=False) | Q(horus_active=False)).count(),
        'latest': bdt_qs.first(),
        'total_km': bdt_total_km if bdt_total_valid else None,
    }
    bdt_inconsistencies = sum(
        1 for bdt in bdt_qs
        if normalize_km(bdt.started_km) is None
        or normalize_km(bdt.ended_km) is None
        or normalize_km(bdt.ended_km) < normalize_km(bdt.started_km)
    )
    bdt_latest_operational = next(
        (bdt for bdt in bdt_qs if normalize_km(bdt.started_km) is not None
         and normalize_km(bdt.ended_km) is not None
         and normalize_km(bdt.ended_km) >= normalize_km(bdt.started_km)),
        None,
    )
    bdt_latest_distance = None
    if bdt_latest_operational:
        bdt_latest_distance = normalize_km(bdt_latest_operational.ended_km) - normalize_km(bdt_latest_operational.started_km)
    plates = VehiclePlate.objects.filter(vehicle=vehicle).order_by('-starts_on')
    current_plates = plates.filter(ends_on__isnull=True, kind='CURRENT')
    reserved_plates = plates.filter(ends_on__isnull=True, kind='RESERVED')
    latest_km = VehicleMileage.objects.filter(vehicle=vehicle).order_by('-date').first()
    km_history = VehicleMileage.objects.filter(vehicle=vehicle).order_by('-date')[:10]
    maintenances = vehicle.maintenances.select_related('status', 'type', 'workshop').order_by('-entered_at')[:10]
    fines = vehicle.fines.select_related('status').order_by('-date')[:10]
    inspections = vehicle.inspections.select_related('type', 'status').order_by('-date')[:10]
    exit_orders = vehicle.exit_orders.select_related('driver', 'opened_by', 'closed_by').order_by('-departed_at')[:10]
    pending_exit_order = next((order for order in exit_orders if order.state == VehicleExitOrder.State.PENDING), None)
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
    active_custody = VehicleCustody.objects.filter(vehicle=vehicle, ended_on__isnull=True).first()
    latest_crlv = vehicle.crlvs.select_related('document').order_by('-exercise', '-confirmed_at').first()

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
    bdt_revision_due = bool(
        bdt_latest_operational and km_prox_revisao is not None
        and normalize_km(bdt_latest_operational.ended_km) >= km_prox_revisao
    )

    if request.method == 'POST':
        from datetime import datetime
        from apps.fleet.models import Driver
        from apps.fleet.services import start_vehicle_custody, transfer_vehicle_custody, end_vehicle_custody
        action = request.POST.get('action')
        permission = 'fleet.add_vehiclecustody' if action == 'start_custody' else 'fleet.change_vehiclecustody'
        if action in {'start_custody', 'transfer_custody', 'end_custody'}:
            if not (request.user.is_superuser or request.user.has_perm(permission)):
                raise PermissionDenied
            try:
                if action == 'start_custody':
                    start_vehicle_custody(vehicle=vehicle, driver=Driver.objects.get(pk=request.POST.get('driver')),
                        user=request.user, sei_number=request.POST.get('sei_number', ''),
                        started_on=datetime.fromisoformat(request.POST.get('started_on')).date(),
                        notes=request.POST.get('notes', ''))
                elif action == 'transfer_custody':
                    transfer_vehicle_custody(custody=active_custody,
                        new_driver=Driver.objects.get(pk=request.POST.get('new_driver')), user=request.user,
                        transferred_at=datetime.fromisoformat(request.POST.get('transferred_at')),
                        notes=request.POST.get('notes', ''))
                else:
                    end_vehicle_custody(custody=active_custody, user=request.user,
                        ended_on=datetime.fromisoformat(request.POST.get('ended_on')).date(),
                        assignment_ended_at=datetime.fromisoformat(request.POST.get('assignment_ended_at')),
                        notes=request.POST.get('notes', ''))
                messages.success(request, 'Acautelamento atualizado com sucesso.')
            except (Driver.DoesNotExist, TypeError, ValueError) as exc:
                messages.error(request, str(exc))
            return redirect('vehicle_dossier', pk=vehicle.pk)

    context = {
        'vehicle': vehicle,
        'latest_crlv': latest_crlv,
        'current_plates': current_plates,
        'reserved_plates': reserved_plates,
        'all_plates': plates,
        'latest_km': latest_km,
        'km_history': km_history,
        'maintenances': maintenances,
        'fines': fines,
        'inspections': inspections,
        'exit_orders': exit_orders,
        'pending_exit_order': pending_exit_order,
        'can_close_exit_order_ids': {str(order.id) for order in exit_orders if order.state == VehicleExitOrder.State.PENDING and order.opened_by_id == request.user.id},
        'active_driver': active_driver,
        'active_assignment': active_assignment,
        'active_custody': active_custody,
        'all_drivers': __import__('apps.fleet.models', fromlist=['Driver']).Driver.objects.filter(active=True).order_by('name'),
        'can_start_custody': request.user.is_superuser or request.user.has_perm('fleet.add_vehiclecustody'),
        'can_change_custody': request.user.is_superuser or request.user.has_perm('fleet.change_vehiclecustody'),
        'motorista': motorista,
        'motorista_tel': motorista_tel,
        'oficina': oficina,
        'km_prox_revisao': km_prox_revisao,
        'km_atual': km_atual,
        'km_faltando': km_faltando,
        'revisao_status': revisao_status,
        'obs_list': obs_list,
        'bdt_page': bdt_page,
        'bdt_summary': bdt_summary,
        'bdt_latest_operational': bdt_latest_operational,
        'bdt_latest_distance': bdt_latest_distance,
        'bdt_revision_due': bdt_revision_due,
        'bdt_operational_km': normalize_km(bdt_latest_operational.ended_km) if bdt_latest_operational else None,
        'bdt_latest_date': bdt_latest_operational.ended_at if bdt_latest_operational else None,
        'bdt_latest_external_id': bdt_latest_operational.external_id if bdt_latest_operational else None,
        'bdt_latest_started_km': normalize_km(bdt_latest_operational.started_km) if bdt_latest_operational else None,
        'bdt_latest_ended_km': normalize_km(bdt_latest_operational.ended_km) if bdt_latest_operational else None,
        'bdt_inconsistencies': bdt_inconsistencies,
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
@module_permission("fleet.add_contract")
def contract_create(request):
    from .forms import ContractForm

    if request.method == 'POST':
        form = ContractForm(request.POST)
        form._user = request.user
        if form.is_valid():
            contract = form.save()
            messages.success(request, 'Contrato incluído com sucesso!')
            return redirect('contract_detail', pk=contract.pk)
    else:
        form = ContractForm()
    return render(request, 'ui/form.html', {
        'form': form,
        'title': 'Incluir Contrato',
        'back_url_url': reverse('contract_list'),
        'quick_renter': True,
    })


@login_required
@module_permission("fleet.change_contract")
def contract_edit(request, pk):
    from apps.fleet.models import Contract
    from .forms import ContractForm

    contract = get_object_or_404(Contract, pk=pk)
    if request.method == 'POST':
        form = ContractForm(request.POST, instance=contract)
        form._user = request.user
        if form.is_valid():
            form.save()
            messages.success(request, 'Contrato atualizado com sucesso!')
            return redirect('contract_detail', pk=contract.pk)
    else:
        form = ContractForm(instance=contract)
    return render(request, 'ui/form.html', {
        'form': form,
        'title': f'Editar Contrato: {contract.number}',
        'back_url_url': reverse('contract_detail', kwargs={'pk': contract.pk}),
        'quick_renter': True,
    })


@login_required
@module_permission("fleet.view_contract")
def contract_detail(request, pk):
    from apps.fleet.models import Contract, Vehicle, VehicleDriverAssignment, VehicleCustody, VehiclePlate

    from apps.fleet.sector_scope import apply_sector_scope
    scoped_vehicle_ids = apply_sector_scope(Vehicle.objects.all(), request.user, request.GET.get("sector")).values_list("id", flat=True)
    contract = get_object_or_404(
        Contract.objects.select_related('renter').filter(vehicles__in=scoped_vehicle_ids).distinct(),
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
        active_custody = VehicleCustody.objects.filter(vehicle=vehicle, ended_on__isnull=True).first()

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
    from apps.fleet.models import Driver, VehicleDriverAssignment
    from django.db.models import Prefetch
    from django.utils.timezone import now
    from apps.fleet.driver_scope import (
        apply_driver_sector_scope, apply_driver_vehicle_scope,
        can_show_driver_sector_filter,
    )

    requested_sector = request.GET.get("sector")
    active_assignments = apply_driver_vehicle_scope(
        VehicleDriverAssignment.objects.filter(is_active=True),
        request.user, requested_sector, lookup="vehicle__sector__slug",
    ).select_related("vehicle__brand", "vehicle__model").prefetch_related("vehicle__plate_history")

    status = request.GET.get("status", "active")
    qs = apply_driver_sector_scope(
        Driver.objects.all(), request.user, requested_sector,
    ).prefetch_related(
        "sectors",
        Prefetch("vehicle_assignments", queryset=active_assignments, to_attr="active_assignments"),
    ).order_by("name")

    if status == "inactive":
        qs = qs.filter(active=False)
    elif status == "cnh_vencida":
        qs = qs.filter(active=True, cnh_expiration__lt=now().date())
    else:
        qs = qs.filter(active=True)

    q = request.GET.get("q", "")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q))

    context = {
        "drivers": qs, "q": q, "status": status, "today": now().date(),
        "requested_sector": requested_sector,
        "show_sector_filter": can_show_driver_sector_filter(request.user),
    }
    return render(request, "ui/driver_list.html", context)


@login_required
@module_permission("fleet.view_maintenance")
def maintenance_list(request):
    from apps.fleet.models import Vehicle, VehicleMileage, Maintenance
    from apps.fleet.services import get_vehicle_revision_status
    from apps.fleet.sector_scope import apply_sector_scope, can_select_sector
    requested_sector = request.GET.get("sector")

    qs = (
        Vehicle.objects.filter(active=True)
        .select_related('brand', 'model', 'status')
        .prefetch_related(
            'plate_history',
            'mileage_history',
            'maintenances__type',
            'maintenances__status',
            'maintenances__workshop',
        )
    )
    qs = apply_sector_scope(qs, request.user, requested_sector)

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
            'revision_interval_km': get_vehicle_revision_interval(vehicle=v),
            'km_faltando': revision['km_remaining'],
            'revision_interval_km': revision['interval_km'],
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
        "requested_sector": requested_sector,
        "show_sector_filter": can_select_sector(request.user),
    }
    return render(request, "ui/maintenance_list.html", context)


@login_required
@module_permission("fleet.change_maintenance")
def revision_action(request, pk):
    from datetime import datetime, time
    from apps.fleet.models import Vehicle, Maintenance, MaintenanceType, MaintenanceStatus
    from apps.fleet.services import (
        get_vehicle_revision_status,
        get_vehicle_revision_interval,
        open_maintenance,
        complete_maintenance,
        change_vehicle_status,
    )

    vehicle = get_object_or_404(Vehicle, pk=pk)
    validate_vehicle_scope(request.user, vehicle, request.GET.get("sector"))

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
                f'Revisão registrada. Próxima revisão calculada em {completion_mileage + get_vehicle_revision_interval(vehicle=vehicle):,} km.'.replace(',', '.')
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
                f'Histórico atualizado. Próxima revisão: {last_revision_km + get_vehicle_revision_interval(vehicle=vehicle):,} km.'.replace(',', '.')
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
    from django.db.models import Prefetch
    from apps.fleet.models import VehicleDriverAssignment
    qs = VehicleFine.objects.select_related('vehicle', 'status').prefetch_related(
        'vehicle__plate_history',
        Prefetch(
            'vehicle__driver_assignments',
            queryset=VehicleDriverAssignment.objects.filter(is_active=True).select_related('driver'),
            to_attr='active_driver_assignments',
        ),
    ).order_by('-date')
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
    from urllib.parse import urlencode
    requested_sector = request.GET.get("sector")
    list_url = reverse("driver_list")
    if requested_sector in {"adm", "lei-seca"}:
        list_url += "?" + urlencode({"sector": requested_sector})
    if request.method == 'POST':
        form = DriverForm(request.POST, user=request.user, requested_sector=requested_sector)
        if form.is_valid():
            form.save()
            messages.success(request, 'Motorista cadastrado com sucesso!')
            return redirect(list_url)
    else:
        form = DriverForm(user=request.user, requested_sector=requested_sector)
    return render(request, 'ui/form.html', {'form': form, 'title': 'Cadastrar Motorista', 'back_url': 'driver_list', 'back_url_url': list_url})


@login_required
@module_permission("fleet.change_driver")
def driver_edit(request, pk):
    from apps.fleet.models import Driver

    from apps.fleet.driver_scope import apply_driver_sector_scope
    from urllib.parse import urlencode
    requested_sector = request.GET.get("sector")
    list_url = reverse("driver_list")
    if requested_sector in {"adm", "lei-seca"}:
        list_url += "?" + urlencode({"sector": requested_sector})
    driver = get_object_or_404(
        apply_driver_sector_scope(Driver.objects.all(), request.user, requested_sector),
        pk=pk,
    )
    if request.method == 'POST':
        form = DriverForm(request.POST, instance=driver, user=request.user, requested_sector=requested_sector)
        if form.is_valid():
            form.save()
            messages.success(request, 'Dados do motorista atualizados com sucesso!')
            return redirect(list_url)
    else:
        form = DriverForm(instance=driver, user=request.user, requested_sector=requested_sector)
    return render(request, 'ui/form.html', {'form': form, 'title': f'Editar Motorista: {driver.name}', 'back_url': 'driver_list', 'back_url_url': list_url})


@login_required
@module_permission("fleet.change_driver")
def driver_assign_vehicle(request, pk):
    from apps.fleet.models import Driver
    from apps.fleet.services import assign_driver_to_vehicle

    from apps.fleet.driver_scope import apply_driver_sector_scope
    from urllib.parse import urlencode
    requested_sector = request.GET.get("sector")
    list_url = reverse("driver_list")
    if requested_sector in {"adm", "lei-seca"}:
        list_url += "?" + urlencode({"sector": requested_sector})
    driver = get_object_or_404(
        apply_driver_sector_scope(Driver.objects.all(), request.user, requested_sector),
        pk=pk,
    )

    from apps.fleet.driver_scope import apply_driver_vehicle_scope

    def scope_vehicle_choices(form):
        form.fields["vehicle"].queryset = apply_driver_vehicle_scope(
            form.fields["vehicle"].queryset, request.user, requested_sector,
        ).filter(sector__in=driver.sectors.all())
        return form

    if request.method == 'POST':
        form = scope_vehicle_choices(DriverVehicleAssignmentForm(request.POST))

        if form.is_valid():
            try:
                validate_vehicle_scope(request.user, form.cleaned_data['vehicle'], request.GET.get("sector"))
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
                return redirect(list_url)
    else:
        form = scope_vehicle_choices(DriverVehicleAssignmentForm())

    return render(
        request,
        'ui/form.html',
        {
            'form': form,
            'title': f'Vincular veículo: {driver.name}',
            'back_url': 'driver_list', 'back_url_url': list_url,
        },
    )


@login_required
@module_permission("fleet.add_contract")
def renter_quick_create(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método não permitido.'}, status=405)

    name = (request.POST.get('name') or '').strip()
    if not name:
        return JsonResponse({'error': 'Informe o nome da locadora.'}, status=400)

    renter = Renter.objects.filter(name__iexact=name).first()
    if not renter:
        renter = Renter.objects.create(name=name)

    return JsonResponse({'id': str(renter.id), 'name': renter.name})


@login_required
def workshop_quick_create(request):
    """Cadastro enxuto de oficina para os dois formulários de manutenção."""
    if request.method != "POST":
        return JsonResponse({"error": "Método não permitido."}, status=405)
    from apps.fleet.models import Workshop
    name = (request.POST.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "Informe o nome da oficina."}, status=400)
    workshop, _ = Workshop.objects.get_or_create(name__iexact=name, defaults={"name": name})
    return JsonResponse({"id": str(workshop.id), "name": workshop.name})


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
    """Inclusão principal de veículo: CRLV -> extração -> revisão -> cadastro."""
    if request.GET.get("manual") == "1":
        if request.method == "POST":
            form = VehicleForm(request.POST)
            if form.is_valid():
                vehicle = form.save(commit=False)
                vehicle.created_by = request.user
                vehicle.save()
                plate_str = form.cleaned_data["plate"]
                if plate_str:
                    VehiclePlate.objects.create(vehicle=vehicle, plate=plate_str, kind="CURRENT", starts_on=timezone.now(), changed_by=request.user)
                res_plate_str = form.cleaned_data.get("reserved_plate")
                if res_plate_str:
                    VehiclePlate.objects.create(vehicle=vehicle, plate=res_plate_str, kind="RESERVED", starts_on=timezone.now(), changed_by=request.user)
                messages.success(request, "Veículo cadastrado com sucesso!")
                return redirect("vehicle_list")
        else:
            form = VehicleForm()
        return render(request, "ui/form.html", {
            "form": form,
            "title": "Cadastrar Veículo manualmente",
            "back_url": "vehicle_list",
            "quick_create": True,
        })

    from apps.fleet.services import stage_crlv_document_for_creation, create_vehicle_from_crlv
    upload_form = CRLVUploadForm()
    confirm_form = None
    preview = None
    document = None

    if request.method == "POST" and request.POST.get("step") == "upload":
        upload_form = CRLVUploadForm(request.POST, request.FILES)
        if upload_form.is_valid():
            try:
                document, preview = stage_crlv_document_for_creation(
                    file_obj=upload_form.cleaned_data["file"],
                    user=request.user,
                )
                aliases = {
                    "CHEV": "Chevrolet", "GM": "Chevrolet",
                    "VW": "Volkswagen", "MB": "Mercedes-Benz", "M.BENZ": "Mercedes-Benz",
                }
                brand_value = str(preview.get("brand_raw", "") or "").strip()
                brand_value = aliases.get(brand_value.upper(), brand_value)
                confirm_form = CRLVVehicleCreateForm(initial={
                    "document_id": document.id,
                    "plate": preview.get("plate", ""),
                    "renavam": preview.get("renavam", ""),
                    "chassi": preview.get("chassi", ""),
                    "exercise": preview.get("exercise"),
                    "brand": brand_value,
                    "model": preview.get("model_raw", ""),
                    "version": preview.get("version", ""),
                    "manufacture_year": preview.get("manufacture_year"),
                    "model_year": preview.get("model_year"),
                    "color": preview.get("color", ""),
                    "fuel": preview.get("fuel", ""),
                    "category": preview.get("category", ""),
                    "vehicle_type": preview.get("vehicle_type", ""),
                    "motor": preview.get("motor", ""),
                    "power_cylinder": preview.get("power_cylinder", ""),
                    "gross_weight": preview.get("gross_weight", ""),
                    "cmt": preview.get("cmt", ""),
                    "axles": preview.get("axles", ""),
                    "seating": preview.get("seating", ""),
                    "bodywork": preview.get("bodywork", ""),
                })
            except ValueError as exc:
                upload_form.add_error("file", str(exc))
    elif request.method == "POST":
        confirm_form = CRLVVehicleCreateForm(request.POST)
        if confirm_form.is_valid():
            from apps.fleet.models import Document, AuditLog
            data = confirm_form.cleaned_data.copy()
            document_id = data.pop("document_id")
            document = get_object_or_404(Document, pk=document_id)
            try:
                extraction_audit = AuditLog.objects.filter(
                    entity_type="document",
                    entity_id=document.id,
                    action="CRLV PARA INCLUSÃO DE VEÍCULO",
                ).order_by("-created_at").first()
                extracted_data = dict(extraction_audit.new_values or {}) if extraction_audit else {}
                extracted_data.update({
                    "reviewed": True,
                    "source": "CRLV",
                    "form_values": {k: (str(v) if hasattr(v, "pk") else v) for k, v in data.items()},
                })
                vehicle, _ = create_vehicle_from_crlv(
                    document=document,
                    user=request.user,
                    extracted_data=extracted_data,
                    **data,
                )
            except ValueError as exc:
                confirm_form.add_error(None, str(exc))
            else:
                messages.success(request, f"Veículo {vehicle.plate_history.filter(kind='CURRENT', ends_on__isnull=True).values_list('plate', flat=True).first()} incluído a partir do CRLV.")
                return redirect("vehicle_list")

    return render(request, "ui/vehicle_create_crlv.html", {
        "upload_form": upload_form,
        "confirm_form": confirm_form,
        "preview": preview,
        "document": document,
        "back_url": "vehicle_list",
    })

@login_required
@module_permission("fleet.change_vehicle")
def vehicle_contract_edit(request, pk):
    from apps.fleet.models import Vehicle

    vehicle = get_object_or_404(Vehicle, pk=pk)
    validate_vehicle_scope(request.user, vehicle, request.GET.get("sector"))
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

    from apps.fleet.models import Vehicle
    from uuid import UUID

    # Only the signed-in flow URL establishes a locked vehicle.  A normal
    # POST may contain a selectable vehicle and remains the general flow.
    vehicle_param = request.GET.get('vehicle')
    linked_vehicle = None
    if vehicle_param:
        try:
            linked_vehicle = get_object_or_404(
                apply_sector_scope(Vehicle.objects.select_related('brand', 'model'), request.user, request.GET.get("sector")),
                pk=UUID(str(vehicle_param)),
            )
        except (ValueError, TypeError, AttributeError):
            from django.http import Http404
            raise Http404('Viatura inválida.')

    if request.method == 'POST':
        form = FineForm(
            request.POST,
            initial={"vehicle": linked_vehicle} if linked_vehicle else None,
        )
        if linked_vehicle:
            form.fields['vehicle'].disabled = True
            form.fields['vehicle'].initial = linked_vehicle
            form.instance.vehicle = linked_vehicle
        if form.is_valid():
            if linked_vehicle:
                form.instance.vehicle = linked_vehicle
            fine = form.save(commit=False)
            if linked_vehicle:
                fine.vehicle = linked_vehicle
            fine.created_by = request.user
            fine.save()
            messages.success(request, 'Multa cadastrada com sucesso!')
            return redirect('vehicle_dossier', pk=linked_vehicle.pk) if linked_vehicle else redirect('fine_list')
    else:
        form = FineForm(initial={'vehicle': linked_vehicle} if linked_vehicle else None)
        if linked_vehicle:
            form.fields['vehicle'].disabled = True
    return render(request, 'ui/form.html', {
        'form': form,
        'title': f'Nova multa para a viatura' if linked_vehicle else 'Cadastrar Multa',
        'linked_vehicle': linked_vehicle,
        'back_url': 'vehicle_dossier' if linked_vehicle else 'fine_list',
        'back_url_url': reverse('vehicle_dossier', kwargs={'pk': linked_vehicle.pk}) if linked_vehicle else None,
        'form_action': f"{reverse('fine_create')}?vehicle={linked_vehicle.pk}" if linked_vehicle else None,
    })


@login_required
@module_permission("fleet.change_vehiclefine")
def fine_edit(request, pk):
    # A ação da lista é específica para alterar apenas a situação da multa.
    from django.contrib.messages import get_messages
    list(get_messages(request))

    from apps.fleet.models import VehicleFine
    from .forms import FineStatusForm
    fine = get_object_or_404(VehicleFine.objects.select_related("vehicle"), pk=pk)
    validate_vehicle_scope(request.user, fine.vehicle, request.GET.get("sector"))
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
@module_permission("fleet.change_vehiclefine")
def fine_full_edit(request, pk):
    from apps.fleet.models import VehicleFine

    fine = get_object_or_404(VehicleFine.objects.select_related("vehicle"), pk=pk)
    validate_vehicle_scope(request.user, fine.vehicle, request.GET.get("sector"))
    if request.method == 'POST':
        form = FineForm(request.POST, instance=fine)
        if form.is_valid():
            form.save()
            driver = form.cleaned_data.get('driver')
            if driver:
                from apps.fleet.services import assign_driver_to_vehicle
                assign_driver_to_vehicle(
                    vehicle=fine.vehicle,
                    driver=driver,
                    user=request.user,
                )
            messages.success(request, 'Multa atualizada com sucesso!')
            return redirect('fine_list')
    else:
        form = FineForm(instance=fine)
    return render(
        request,
        'ui/form.html',
        {
            'form': form,
            'title': f'Editar Multa: {fine.auto_number}',
            'back_url': 'fine_list',
        },
    )


@login_required
@module_permission("fleet.add_maintenance")
def maintenance_create(request):
    if "vehicle" in request.GET:
        from .dossier_actions import linked_maintenance_create
        return linked_maintenance_create(request)
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


def _exit_order_plate(vehicle):
    if vehicle is None:
        return None
    record = vehicle.plate_history.filter(kind='CURRENT', ends_on__isnull=True).first()
    return record.plate if record else 'Sem placa'


@login_required
@module_permission("fleet.view_vehicleexitorder")
def exit_order_list(request):
    from apps.fleet.models import VehicleExitOrder, Vehicle, Driver

    from apps.fleet.sector_scope import apply_sector_scope
    qs = VehicleExitOrder.objects.select_related('vehicle__brand', 'vehicle__model', 'driver', 'opened_by', 'closed_by').prefetch_related('vehicle__plate_history')
    qs = qs.filter(vehicle_id__in=apply_sector_scope(Vehicle.objects.all(), request.user, request.GET.get("sector")).values_list("id", flat=True))
    search = request.GET.get('q', '').strip()
    state = request.GET.get('state', '')
    vehicle_id = request.GET.get('vehicle', '')
    driver_id = request.GET.get('driver', '')
    if state in {VehicleExitOrder.State.PENDING, VehicleExitOrder.State.CLOSED}:
        qs = qs.filter(state=state)
    if search:
        qs = qs.filter(
            Q(number__icontains=search)
            | Q(destination__icontains=search)
            | Q(driver__name__icontains=search)
            | Q(vehicle__brand__name__icontains=search)
            | Q(vehicle__model__name__icontains=search)
        )
    for field, raw in (("vehicle_id", vehicle_id), ("driver_id", driver_id)):
        if raw:
            try:
                uuid.UUID(raw)
            except (ValueError, TypeError):
                qs = qs.none()
            else:
                qs = qs.filter(**{field: raw})
    for lookup, raw in (("departed_at__date__gte", request.GET.get("from", "")), ("departed_at__date__lte", request.GET.get("to", ""))):
        if raw and parse_date(raw):
            qs = qs.filter(**{lookup: parse_date(raw)})
    today = timezone.localdate()
    page_obj = Paginator(qs.order_by('-departed_at', '-created_at'), 25).get_page(request.GET.get('page'))
    vehicles = Vehicle.objects.prefetch_related('plate_history').order_by('id')
    vehicle_options = []
    for vehicle in vehicles:
        active_plate = next(
            (
                item.plate for item in vehicle.plate_history.all()
                if item.kind == 'CURRENT' and item.ends_on is None
            ),
            'Sem placa',
        )
        vehicle_options.append((str(vehicle.id), active_plate))
    query = request.GET.copy()
    query.pop('page', None)
    return render(request, 'ui/exit_order_list.html', {
        'page_obj': page_obj, 'order_rows': [(item, _exit_order_plate(item.vehicle)) for item in page_obj],
        'states': VehicleExitOrder.State.choices, 'vehicle_options': vehicle_options,
        'drivers': Driver.objects.filter(active=True).order_by('name'), 'selected_state': state,
        'selected_vehicle': vehicle_id, 'selected_driver': driver_id, 'querystring': query.urlencode(),
        'search': search,
        'active_count': VehicleExitOrder.objects.filter(state=VehicleExitOrder.State.PENDING).count(),
        'in_transit_count': VehicleExitOrder.objects.filter(
            state=VehicleExitOrder.State.PENDING, departed_at__date=today
        ).count(),
        'closed_today_count': VehicleExitOrder.objects.filter(
            state=VehicleExitOrder.State.CLOSED, closed_at__date=today
        ).count(),
    })


@login_required
@module_permission("fleet.add_vehicleexitorder")
def exit_order_create(request):
    from apps.fleet.models import Vehicle
    from apps.fleet.services import open_vehicle_exit_order

    linked_vehicle = None
    raw_vehicle = request.GET.get('vehicle')
    if raw_vehicle:
        try:
            uuid.UUID(raw_vehicle)
        except ValueError:
            raise Http404("Viatura inválida.")
        linked_vehicle = get_object_or_404(
            apply_sector_scope(Vehicle.objects.select_related('brand', 'model').prefetch_related('plate_history'), request.user, request.GET.get("sector")),
            pk=raw_vehicle,
        )
    if request.method == 'POST':
        form = VehicleExitOrderForm(request.POST, initial={'vehicle': linked_vehicle} if linked_vehicle else None)
        if linked_vehicle:
            form.fields['vehicle'].disabled = True
        if form.is_valid():
            vehicle = linked_vehicle or form.cleaned_data['vehicle']
            try:
                order = open_vehicle_exit_order(vehicle_id=vehicle.id, driver=form.cleaned_data['driver'], departed_at=form.cleaned_data['departed_at'], destination=form.cleaned_data['destination'], reason=form.cleaned_data['reason'], notes=form.cleaned_data['notes'], user=request.user)
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, f'{order.number} aberta com sucesso.')
                return redirect('exit_order_detail', pk=order.pk)
    else:
        form = VehicleExitOrderForm(initial={'vehicle': linked_vehicle} if linked_vehicle else None)
        if linked_vehicle:
            form.fields['vehicle'].disabled = True
    return render(request, 'ui/exit_order_form.html', {'form': form, 'linked_vehicle': linked_vehicle, 'linked_vehicle_plate': _exit_order_plate(linked_vehicle) if linked_vehicle else None})


@login_required
@module_permission("fleet.view_vehicleexitorder")
def exit_order_detail(request, pk):
    from apps.fleet.models import AuditLog, VehicleExitOrder
    order = get_object_or_404(VehicleExitOrder.objects.select_related('vehicle__brand', 'vehicle__model', 'driver', 'opened_by', 'closed_by').prefetch_related('vehicle__plate_history'), pk=pk)
    validate_vehicle_scope(request.user, order.vehicle, request.GET.get("sector"))
    audits = AuditLog.objects.filter(
        entity_type='vehicle_exit_order', entity_id=order.id
    ).select_related('user').order_by('created_at')
    return render(request, 'ui/exit_order_detail.html', {
        'order': order,
        'plate': _exit_order_plate(order.vehicle),
        'audits': audits,
        'bdt_rows': exit_order_bdt_rows(order),
        'can_close': order.state == VehicleExitOrder.State.PENDING and order.opened_by_id == request.user.id and (request.user.is_system_creator or request.user.has_perm('fleet.change_vehicleexitorder')),
    })


@login_required
@module_permission("fleet.change_vehicleexitorder")
def exit_order_return(request, pk):
    from apps.fleet.models import VehicleExitOrder
    from apps.fleet.services import close_vehicle_exit_order
    order = get_object_or_404(VehicleExitOrder.objects.select_related('vehicle', 'opened_by'), pk=pk)
    validate_vehicle_scope(request.user, order.vehicle, request.GET.get("sector"))
    if order.opened_by_id != request.user.id:
        raise PermissionDenied('Somente o usuário que abriu a OS pode registrar o retorno.')
    if request.method == 'POST':
        form = VehicleExitOrderReturnForm(request.POST)
        if form.is_valid():
            try:
                close_vehicle_exit_order(order_id=order.id, returned_at=form.cleaned_data['returned_at'], return_notes=form.cleaned_data['return_notes'], user=request.user)
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, 'Retorno registrado e OS encerrada.')
                return redirect('exit_order_detail', pk=order.pk)
    else:
        form = VehicleExitOrderReturnForm()
    return render(request, 'ui/exit_order_return_form.html', {'form': form, 'order': order, 'plate': _exit_order_plate(order.vehicle)})


@login_required
def workshop_quick_create(request):
    from apps.fleet.models import Workshop
    from django.db import transaction

    if request.method != "POST":
        return JsonResponse({"error": "Use POST."}, status=405)

    name = " ".join((request.POST.get("name") or "").split())
    if not name or len(name) > 150:
        return JsonResponse(
            {"error": "Informe um nome com até 150 caracteres."}, status=400
        )

    with transaction.atomic():
        workshop = Workshop.objects.filter(name__iexact=name).order_by("created_at").first()
        if workshop is None:
            workshop = Workshop.objects.create(name=name, active=True)
        elif not workshop.active:
            workshop.active = True
            workshop.save(update_fields=["active", "updated_at"])

    return JsonResponse({"id": str(workshop.pk), "name": workshop.name})
