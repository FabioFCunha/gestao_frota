from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.fleet.models import AuditLog, VehicleExitOrder
from apps.fleet.sector_scope import validate_vehicle_scope
from apps.accounts.decorators import module_permission
from .forms import VehicleExitOrderForm


def _snapshot(order):
    return {
        "driver_id": str(order.driver_id),
        "driver": order.driver.name,
        "departed_at": order.departed_at.isoformat(),
        "destination": order.destination,
        "reason": order.reason,
        "notes": order.notes,
    }


@login_required
@module_permission("fleet.change_vehicleexitorder")
def exit_order_edit(request, pk):
    from .forms import VehicleExitOrderForm

    # Reutiliza os widgets e validações sem executar o __init__ que exige vehicle.
    class EditForm(forms.ModelForm):
        version = forms.CharField(widget=forms.HiddenInput)

        class Meta(VehicleExitOrderForm.Meta):
            fields = ["driver", "departed_at", "destination", "reason", "notes"]

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            from apps.fleet.driver_scope import apply_driver_sector_scope
            from apps.fleet.models import Driver
            from django.db.models import Q

            self.fields["driver"].queryset = apply_driver_sector_scope(
                Driver.objects.filter(
                    Q(active=True) | Q(pk=self.instance.driver_id)
                ),
                request.user,
                request.GET.get("sector"),
            ).order_by("name")

    with transaction.atomic():
        queryset = VehicleExitOrder.objects.all()
        if request.method == "POST":
            queryset = queryset.select_for_update()
        order = get_object_or_404(queryset, pk=pk)
        validate_vehicle_scope(
            request.user, order.vehicle, request.GET.get("sector")
        )
        version = order.updated_at.isoformat()
        before = _snapshot(order)

        form = EditForm(
            request.POST if request.method == "POST" else None,
            instance=order,
            initial={"version": version},
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
                    order.save(update_fields=[
                        "driver", "departed_at", "destination",
                        "reason", "notes", "updated_at",
                    ])
                    labels = {
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
                        old, new = before[key], after[key]
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
