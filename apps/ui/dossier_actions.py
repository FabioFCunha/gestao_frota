from uuid import UUID

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.fleet.models import Vehicle, VehiclePlate, AuditLog
from apps.fleet.sector_scope import apply_sector_scope
from apps.fleet.services import ensure_vehicle_active
from .forms import MaintenanceForm


def _vehicle(request, vehicle_id):
    try:
        vehicle_id = UUID(str(vehicle_id))
    except (ValueError, TypeError, AttributeError):
        raise Http404("Viatura inválida.")

    qs = apply_sector_scope(
        Vehicle.objects.filter(active=True)
        .select_related("brand", "model", "sector")
        .prefetch_related("plate_history"),
        request.user,
        request.GET.get("sector"),
    )
    return get_object_or_404(qs, pk=vehicle_id)


def _render_form(request, form, vehicle, title):
    return render(request, "ui/form.html", {
        "form": form,
        "title": title,
        "linked_heading": title + " para a viatura",
        "linked_vehicle": vehicle,
        "back_url_url": reverse("vehicle_dossier", kwargs={"pk": vehicle.pk}),
        "form_action": request.get_full_path(),
    })


def linked_maintenance_create(request):
    vehicle = _vehicle(request, request.GET.get("vehicle"))
    plate = next(
        (p.plate for p in vehicle.plate_history.all()
         if p.kind == VehiclePlate.CURRENT and p.ends_on is None),
        None,
    )
    if not plate:
        raise Http404("Viatura sem placa atual.")

    form = MaintenanceForm(
        request.POST if request.method == "POST" else None,
        initial={"plate": plate},
    )
    form.fields["plate"].disabled = True
    form.instance.vehicle = vehicle

    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                locked_vehicle = _vehicle(request, vehicle.pk)
                locked_vehicle = Vehicle.objects.select_for_update().get(
                    pk=locked_vehicle.pk
                )
                ensure_vehicle_active(locked_vehicle)
                maintenance = form.save(commit=False)
                maintenance.vehicle = locked_vehicle
                maintenance.save()
                AuditLog.objects.create(
                    user=request.user,
                    module="veículos",
                    action="REGISTRO DE MANUTENÇÃO",
                    entity_type="maintenance",
                    entity_id=maintenance.pk,
                    new_values={
                        "vehicle_id": str(locked_vehicle.pk),
                        "type": maintenance.type.name,
                        "status": maintenance.status.name,
                    },
                    reason=maintenance.notes,
                )
        except (ValueError, ValidationError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Manutenção registrada com sucesso.")
            return redirect("vehicle_dossier", pk=vehicle.pk)

    return _render_form(request, form, vehicle, "Nova manutenção")
