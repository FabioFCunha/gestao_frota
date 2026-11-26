from django import forms
from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.decorators import module_permission
from apps.fleet.driver_scope import apply_driver_sector_scope
from apps.fleet.models import AuditLog, Driver, Vehicle, VehicleExitOrder
from apps.fleet.sector_scope import apply_sector_scope, sector_filter_q, validate_vehicle_scope
from .forms import VehicleExitOrderForm


class ExitOrderEditForm(VehicleExitOrderForm):
    version = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, user, sector, **kwargs):
        super().__init__(*args, **kwargs)
        vehicle_scope = sector_filter_q(user, sector)
        if vehicle_scope:
            self.fields["vehicle"].queryset = self.fields["vehicle"].queryset.filter(
                Q(pk=self.instance.vehicle_id) | vehicle_scope,
            )
        eligible_drivers = apply_driver_sector_scope(Driver.objects.filter(active=True), user, sector)
        self.fields["driver"].queryset = Driver.objects.filter(
            Q(pk=self.instance.driver_id) | Q(pk__in=eligible_drivers.values("pk")),
        ).order_by("name")


def _snapshot(order):
    return {
        "vehicle_id": str(order.vehicle_id),
        "vehicle": VehicleExitOrderForm.label_from_instance(order.vehicle),
        "driver_id": str(order.driver_id),
        "driver": order.driver.name,
        "departed_at": order.departed_at.isoformat(),
        "destination": order.destination,
        "reason": order.reason,
        "notes": order.notes,
    }


def _validate_assignment(form, order, changed):
    vehicle_changed = "vehicle_id" in changed
    if vehicle_changed and order.state == VehicleExitOrder.State.PENDING:
        if VehicleExitOrder.objects.filter(
            vehicle_id=order.vehicle_id, state=VehicleExitOrder.State.PENDING,
        ).exclude(pk=order.pk).exists():
            form.add_error("vehicle", "Esta viatura já possui uma OS pendente de retorno.")

    if apps.is_installed("apps.driverops"):
        trips = apps.get_model("driverops", "Trip").objects.filter(exit_order=order)
        if vehicle_changed and trips.exists():
            form.add_error("vehicle", "Esta OS possui um BDT vinculado à viatura atual.")
        if (
            "driver_id" in changed
            and getattr(settings, "CENTRAL_USER_MANAGEMENT", False)
            and trips.filter(closed_at=None).exists()
        ):
            form.add_error("driver", "Encerre o BDT vinculado antes de trocar o motorista da OS.")


@login_required
@module_permission("fleet.change_vehicleexitorder")
def exit_order_edit(request, pk):
    sector = request.GET.get("sector")
    data = request.POST if request.method == "POST" else None
    with transaction.atomic():
        queryset = VehicleExitOrder.objects.all()
        locked_vehicle_id = None
        if data is not None:
            try:
                vehicle_id = forms.UUIDField(required=False).clean(data.get("vehicle"))
            except forms.ValidationError:
                vehicle_id = None
            if vehicle_id is not None:
                # A abertura de OS e a abertura de BDT pelo app bloqueiam a viatura primeiro.
                locked_vehicle_id = apply_sector_scope(
                    Vehicle.objects.filter(pk=vehicle_id), request.user, sector,
                ).select_for_update(of=("self",)).values_list("pk", flat=True).first()
            queryset = queryset.select_for_update()
        order = get_object_or_404(queryset, pk=pk)
        validate_vehicle_scope(request.user, order.vehicle, sector)
        version = order.updated_at.isoformat()
        before = _snapshot(order)

        if data is not None and "vehicle" not in data:
            data = data.copy()
            data["vehicle"] = order.vehicle_id

        form = ExitOrderEditForm(
            data,
            instance=order,
            initial={"version": version},
            user=request.user,
            sector=sector,
        )

        if request.method == "POST" and form.is_valid():
            if form.cleaned_data["version"] != version:
                form.add_error(
                    None,
                    "Esta OS foi alterada por outro usuário. Reabra a edição para carregar os dados atuais.",
                )
            elif (
                order.returned_at
                and form.cleaned_data["departed_at"] > order.returned_at
            ):
                form.add_error(
                    "departed_at",
                    "A saída não pode ser posterior ao retorno registrado.",
                )
            else:
                after = _snapshot(order)
                changed = [
                    key for key in before if before[key] != after[key]
                ]
                if changed:
                    if "vehicle_id" in changed and order.vehicle_id != locked_vehicle_id:
                        form.add_error("vehicle", "Selecione novamente uma viatura do setor autorizado.")
                    else:
                        _validate_assignment(form, order, changed)
                    if form.errors:
                        return render(request, "ui/exit_order_edit.html", {"form": form, "order": order})
                    order.save(update_fields=[
                        "vehicle", "driver", "departed_at", "destination",
                        "reason", "notes", "updated_at",
                    ])
                    labels = {
                        "vehicle_id": "Viatura",
                        "driver": "Motorista",
                        "departed_at": "Data/hora da saída",
                        "destination": "Destino",
                        "reason": "Motivo",
                        "notes": "Observações",
                    }
                    descriptions = []
                    for key, label in labels.items():
                        if key not in changed:
                            continue
                        display_key = "vehicle" if key == "vehicle_id" else key
                        old, new = before[display_key], after[display_key]
                        if key == "departed_at":
                            from django.utils.dateparse import parse_datetime
                            def display(value):
                                dt = parse_datetime(value)
                                if timezone.is_aware(dt):
                                    dt = timezone.localtime(dt)
                                return dt.strftime("%d/%m/%Y %H:%M")
                            old, new = display(old), display(new)
                        descriptions.append(
                            f"{label}: {old or 'Não informado'} → {new or 'Não informado'}"
                        )
                    AuditLog.objects.create(
                        user=request.user,
                        module="ordens de saída",
                        action="EDIÇÃO OS SAÍDA",
                        entity_type="vehicle_exit_order",
                        entity_id=order.pk,
                        old_values={key: before[key] for key in changed},
                        new_values={key: after[key] for key in changed},
                        reason="\n".join(descriptions),
                    )
                    messages.success(
                        request, "OS atualizada. Alterações registradas na auditoria."
                    )
                else:
                    messages.info(request, "Nenhuma alteração identificada.")
                return redirect("exit_order_detail", pk=order.pk)

    return render(request, "ui/exit_order_edit.html", {
        "form": form, "order": order,
    })
