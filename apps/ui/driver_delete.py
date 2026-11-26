"""Audited driver removal without deleting operational or document history."""
from urllib.parse import urlencode

from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import module_permission
from apps.fleet.driver_scope import apply_driver_sector_scope
from apps.fleet.models import AuditLog, BDT, Driver, VehicleDriverAssignment, VehicleExitOrder


class DriverDeleteForm(forms.Form):
    reason = forms.CharField(label="Motivo da exclusão", min_length=10, max_length=1000,
                             widget=forms.Textarea(attrs={"rows": 3}))
    confirmed = forms.BooleanField(label="Confirmo a exclusão deste motorista da lista de ativos.")


@login_required
@module_permission("fleet.delete_driver")
@require_http_methods(["GET", "POST"])
def driver_delete(request, pk):
    sector = request.GET.get("sector")
    drivers = apply_driver_sector_scope(Driver.objects.all(), request.user, sector)
    driver = get_object_or_404(drivers, pk=pk)
    list_url = reverse("driver_list")
    if sector in {"adm", "lei-seca"}:
        list_url += "?" + urlencode({"sector": sector})
    form = DriverDeleteForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            driver = get_object_or_404(Driver.objects.select_for_update(), pk=driver.pk)
            member = None
            open_trip = False
            if apps.is_installed("apps.driverops"):
                from apps.driverops.models import Member, Trip
                member = Member.objects.select_for_update().filter(driver=driver).first()
                open_trip = bool(member and Trip.objects.filter(member=member, closed_at__isnull=True).exists())
            if not driver.active:
                form.add_error(None, "Este motorista já está inativo.")
            elif VehicleExitOrder.objects.filter(driver=driver, state=VehicleExitOrder.State.PENDING).exists():
                form.add_error(None, "Encerre a ordem de saída pendente antes de excluir o motorista.")
            elif BDT.objects.filter(driver=driver, ended_at__isnull=True).exclude(horus_active=False).exists():
                form.add_error(None, "Encerre o BDT aberto antes de excluir o motorista.")
            elif open_trip:
                form.add_error(None, "Encerre a viagem no aplicativo antes de excluir o motorista.")
            elif member and member.active:
                form.add_error(None, "Desative o acesso deste motorista em Usuários antes de excluir o cadastro.")
            else:
                assignments = VehicleDriverAssignment.objects.filter(driver=driver, is_active=True)
                ended = list(assignments.values_list("pk", flat=True))
                assignments.update(is_active=False, ends_on=timezone.now(), updated_at=timezone.now())
                driver.active = False
                driver.save(update_fields=["active", "updated_at"])
                AuditLog.objects.create(user=request.user, module="motoristas", action="EXCLUSÃO DE MOTORISTA",
                    entity_type="driver", entity_id=driver.pk, old_values={"active": True},
                    new_values={"active": False, "ended_assignments": [str(pk) for pk in ended]},
                    reason=form.cleaned_data["reason"])
                messages.success(request, "Motorista excluído da lista de ativos. Histórico e documentos preservados.")
                return redirect(list_url)
    return render(request, "ui/driver_delete.html", {"driver": driver, "form": form, "back_url_url": list_url})
