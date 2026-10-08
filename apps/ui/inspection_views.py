from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import render

from apps.fleet.models import Vehicle, VehicleInspection
from apps.fleet.sector_scope import apply_sector_scope


@login_required
def inspection_list(request):
    user = request.user
    creator = user.is_system_creator
    can_add = creator or user.has_perm("fleet.add_vehicleinspection")
    can_view = creator or user.has_perm("fleet.view_vehicleinspection")
    if not can_add and not can_view:
        raise PermissionDenied

    vehicles = apply_sector_scope(
        Vehicle.objects.filter(active=True)
        .select_related("brand", "model", "sector")
        .prefetch_related("plate_history"),
        user, request.GET.get("sector"),
    ).order_by("brand__name", "model__name", "pk")

    rows = []
    for vehicle in vehicles:
        plate = next(
            (p.plate for p in vehicle.plate_history.all()
             if p.kind == "CURRENT" and p.ends_on is None),
            "Sem placa atual",
        )
        rows.append({"vehicle": vehicle, "plate": plate})

    history = VehicleInspection.objects.none()
    if can_view:
        history = apply_sector_scope(
            VehicleInspection.objects.select_related(
                "vehicle__brand", "vehicle__model", "type", "status"
            ).prefetch_related("vehicle__plate_history"),
            user, request.GET.get("sector"), lookup="vehicle__sector",
        ).order_by("-date", "-created_at", "-pk")
        selected = request.GET.get("vehicle", "")
        if selected:
            # Valida também a seleção com o mesmo escopo da lista.
            from .dossier_actions import _vehicle
            vehicle = _vehicle(request, selected)
            history = history.filter(vehicle=vehicle)

    page = Paginator(history, 20).get_page(request.GET.get("page"))
    return render(request, "ui/inspection_list.html", {
        "vehicle_rows": rows,
        "history_page": page,
        "can_add_inspection": can_add,
        "can_view_inspection": can_view,
        "selected_vehicle": request.GET.get("vehicle", ""),
        "requested_sector": request.GET.get("sector", ""),
    })
