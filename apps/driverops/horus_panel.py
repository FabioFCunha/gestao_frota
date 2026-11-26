"""Read-only Hórus/OS reconciliation using company-scoped fleet records."""
from collections import defaultdict
from datetime import datetime, time, timedelta

from django.core.paginator import Paginator
from django.db.models import Max
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.fleet.models import BDT, Driver, Vehicle, VehicleExitOrder
from apps.ui.exit_order_bdt import _bdt_metrics, _bdt_mileage


def status_of(bdt):
    if not bdt.started_at or bdt.started_at > timezone.now() or (bdt.ended_at and bdt.ended_at < bdt.started_at):
        return 'inconsistent'
    initial, final = _bdt_mileage(bdt.started_km), _bdt_mileage(bdt.ended_km)
    if initial is None or (bdt.ended_at and (final is None or final < initial)):
        return 'inconsistent'
    if bdt.ended_at:
        return 'closed'
    return 'incomplete' if bdt.horus_active is False else 'open'


LABELS = {'missing': 'Sem BDT localizado', 'open': 'Aberto', 'closed': 'Fechado',
          'inconsistent': 'Dados inconsistentes', 'incomplete': 'Fechamento não informado'}


def horus_dashboard(request):
    today = timezone.localdate()
    def date_param(name, default):
        try:
            return parse_date(request.GET.get(name, '')) or default
        except ValueError:
            return default
    start = date_param('start', today - timedelta(days=29))
    end = date_param('end', today)
    error = ''
    if end < start or (end - start).days > 365:
        error = 'Informe um período de até 366 dias, com início anterior ao fim.'
        start, end = today - timedelta(days=29), today
    lower = timezone.make_aware(datetime.combine(start, time.min))
    upper = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min))
    bdts = list(BDT.objects.filter(started_at__gte=lower, started_at__lt=upper)
                .select_related('vehicle', 'driver').prefetch_related('vehicle__plate_history'))
    # Include missing opening dates by sync date so malformed records are visible.
    bdts += list(BDT.objects.filter(started_at__isnull=True, last_synced_at__gte=lower,
                                   last_synced_at__lt=upper).select_related('vehicle', 'driver')
                 .prefetch_related('vehicle__plate_history'))
    # Previous OS is needed when its BDT opens inside the requested period.
    orders = list(VehicleExitOrder.objects.filter(departed_at__lt=upper, departed_at__lte=timezone.now())
                  .select_related('vehicle', 'driver').prefetch_related('vehicle__plate_history')
                  .order_by('departed_at', 'pk'))
    by_vehicle = defaultdict(list)
    for order in orders:
        by_vehicle[order.vehicle_id].append(order)
    matched = set()
    rows = []
    for bdt in bdts:
        candidates = by_vehicle[bdt.vehicle_id]
        order = next((o for o in reversed(candidates)
                      if bdt.started_at and o.departed_at <= bdt.started_at), None)
        if order and (order.driver_id != bdt.driver_id or
                      (order.returned_at and bdt.started_at > order.returned_at)):
            order = None
        if order:
            matched.add(order.pk)
        state = status_of(bdt)
        rows.append(dict(bdt=bdt, order=order, vehicle=bdt.vehicle, driver=bdt.driver,
                         state=state, label=LABELS[state], at=bdt.started_at or bdt.last_synced_at,
                         **_bdt_metrics(bdt)))
    # A BDT outside the selected dates may still satisfy an OS in this period.
    period_orders = [o for o in orders if lower <= o.departed_at < upper]
    if period_orders:
        from apps.ui.exit_order_bdt import exit_order_bdt_rows
        for order in period_orders:
            if order.pk not in matched and not exit_order_bdt_rows(order):
                rows.append(dict(bdt=None, order=order, vehicle=order.vehicle, driver=order.driver,
                                 state='missing', label=LABELS['missing'], at=order.departed_at))
    for row in rows:
        row['plate'] = plate_label(row['vehicle'])
    vehicle = request.GET.get('vehicle', '')
    driver = request.GET.get('driver', '')
    state = request.GET.get('status', '')
    rows = [r for r in rows if (not vehicle or str(getattr(r['vehicle'], 'pk', '')) == vehicle)
            and (not driver or str(getattr(r['driver'], 'pk', '')) == driver)]
    counts = {key: sum(r['state'] == key for r in rows) for key in LABELS}
    if state:
        rows = [r for r in rows if r['state'] == state]
    rows.sort(key=lambda r: r['at'], reverse=True)
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'driverops/horus_dashboard.html', {
        'page_obj': Paginator(rows, 50).get_page(request.GET.get('page')),
        'start': start.isoformat(), 'end': end.isoformat(), 'error': error,
        'vehicle_filter': vehicle, 'driver_filter': driver, 'status_filter': state,
        'vehicles': [(str(v.pk), plate_label(v)) for v in Vehicle.objects.prefetch_related('plate_history')],
        'drivers': Driver.objects.order_by('name'), 'statuses': LABELS.items(),
        'counts': [(LABELS[k], v) for k, v in counts.items()], 'query': params.urlencode(),
        'last_sync': BDT.objects.aggregate(value=Max('last_synced_at'))['value'],
    })


def plate_label(vehicle):
    if vehicle is None:
        return 'Veículo não vinculado'
    return next((p.plate for p in vehicle.plate_history.all()
                 if p.kind == 'CURRENT' and p.ends_on is None), 'Sem placa atual')
