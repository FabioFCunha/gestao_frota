from django.utils import timezone
from apps.fleet.models import BDT, VehicleExitOrder


def exit_order_bdt_rows(order):
    # A próxima OS limita a busca para não incluir outra saída da viatura.
    next_departure = (
        VehicleExitOrder.objects.filter(
            vehicle_id=order.vehicle_id,
            departed_at__gt=order.departed_at,
        )
        .order_by("departed_at")
        .values_list("departed_at", flat=True)
        .first()
    )
    end = order.returned_at or timezone.now()
    records = BDT.objects.filter(
        vehicle_id=order.vehicle_id,
        driver_id=order.driver_id,
        started_at__gte=order.departed_at,
        started_at__lte=end,
    )
    if next_departure is not None:
        records = records.filter(started_at__lt=next_departure)

    rows = []
    for bdt in records.order_by("started_at", "pk"):
        if bdt.ended_at is not None:
            status = "Fechado"
        elif bdt.horus_active is False:
            status = "Encerrado na origem; data de fechamento não informada"
        elif bdt.started_at is not None:
            status = "Aberto; fechamento não informado"
        else:
            status = "Situação não informada"
        rows.append({"bdt": bdt, "status": status})
    return rows
