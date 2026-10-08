from uuid import UUID

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.accounts.decorators import module_permission
from apps.fleet.models import Vehicle, VehiclePlate, VehicleInspection, AuditLog
from apps.fleet.sector_scope import apply_sector_scope
from apps.fleet.services import ensure_vehicle_active, record_vehicle_inspection
from .forms import MaintenanceForm


class DossierInspectionForm(forms.ModelForm):
    class Meta:
        model = VehicleInspection
        fields = ["date", "type", "status", "inspector_name", "mileage", "notes"]
        labels = {
            "date": "Data e hora",
            "type": "Tipo de vistoria",
            "status": "Situação",
            "inspector_name": "Responsável pela vistoria",
            "mileage": "Quilometragem",
            "notes": "Observações",
        }
        widgets = {
            "date": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={"type": "datetime-local", "class": "form-input"},
            ),
            "mileage": forms.NumberInput(
                attrs={"min": 0, "class": "form-input"},
            ),
            "notes": forms.Textarea(
                attrs={"rows": 3, "class": "form-input"},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("type", "status"):
            self.fields[name].queryset = (
                self.fields[name].queryset.filter(active=True)
            )
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-input")


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


@login_required
@module_permission("fleet.add_vehicleinspection")
def inspection_create(request, vehicle_id):
    from .inspection_mobile import MobileInspectionForm
    from django.utils import timezone

    vehicle = _vehicle(request, vehicle_id)
    form = MobileInspectionForm(
        request.POST if request.method == "POST" else None,
        user=request.user,
        initial={"date": timezone.localtime()},
    )
    form.instance.vehicle = vehicle

    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                locked_vehicle = _vehicle(request, vehicle.pk)
                locked_vehicle = Vehicle.objects.select_for_update().get(
                    pk=locked_vehicle.pk
                )
                values = {
                    key: form.cleaned_data[key]
                    for key in (
                        "date", "type", "status",
                        "inspector_name", "mileage", "notes",
                    )
                }
                inspection = record_vehicle_inspection(
                    vehicle=locked_vehicle,
                    user=request.user,
                    **values,
                )
                inspection.inspection_moment = form.cleaned_data["inspection_moment"]
                inspection.checklist = form.checklist_payload()
                inspection.save(update_fields=[
                    "inspection_moment", "checklist", "updated_at",
                ])
                AuditLog.objects.create(
                    user=request.user,
                    module="veículos",
                    action="CHECKLIST DE VISTORIA",
                    entity_type="vehicle_inspection",
                    entity_id=inspection.pk,
                    new_values={
                        "moment": inspection.inspection_moment,
                        "checklist": inspection.checklist,
                    },
                    reason=inspection.notes,
                )
        except (ValueError, ValidationError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Vistoria registrada com sucesso.")
            return redirect("inspection_list")

    return render(request, "ui/inspection_mobile.html", {
        "form": form,
        "vehicle": vehicle,
        "back_url": reverse("inspection_list"),
    })
