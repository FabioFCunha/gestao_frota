from django.utils import timezone
from apps.fleet.models import BDT, VehicleExitOrder



def _bdt_mileage(value):
    from decimal import Decimal, InvalidOperation
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        return None
    return int(number)


def _bdt_metrics(bdt):
    initial = _bdt_mileage(bdt.started_km)
    final = _bdt_mileage(bdt.ended_km)
    if initial is None or final is None:
        distance = "Não disponível"
    elif final < initial:
        distance = "Quilometragem inconsistente"
    else:
        distance = f"{final - initial:,}".replace(",", ".") + " km"

    duration_label = "Duração do BDT"
    if not bdt.started_at:
        duration = "Abertura não informada"
    elif bdt.ended_at:
        end = bdt.ended_at
        duration = None
    elif bdt.horus_active is False:
        duration = "Fechamento não informado pela origem"
    else:
        end = timezone.now()
        duration_label = "Tempo decorrido desde a abertura"
        duration = None

    if duration is None:
        seconds = int((end - bdt.started_at).total_seconds())
        if seconds < 0:
            duration = "Datas inconsistentes"
        else:
            minutes = seconds // 60
            days, minutes = divmod(minutes, 1440)
            hours, minutes = divmod(minutes, 60)
            duration = (
                (f"{days} dia(s), " if days else "")
                + f"{hours}h {minutes:02d}min"
            )

    return {
        "distance": distance,
        "duration": duration,
        "duration_label": duration_label,
    }

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
        rows.append({"bdt": bdt, "status": status, **_bdt_metrics(bdt)})
    return rows
