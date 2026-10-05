from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime

from apps.fleet.models import BDT, Vehicle, VehicleMileage
from apps.fleet.sync_bdt import sync_bdt_mileage
from apps.fleet.utils import normalize_km


class Command(BaseCommand):
    help = "Reconcilia a quilometragem operacional histórica dos BDTs."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--vehicle-id")
        parser.add_argument("--since", help="Data/hora ISO do início da seleção")
        parser.add_argument("--only-missing", action="store_true")

    def handle(self, *args, **opts):
        qs = BDT.objects.filter(ended_at__isnull=False).select_related("vehicle").order_by("ended_at", "created_at")
        if opts["vehicle_id"]:
            qs = qs.filter(vehicle_id=opts["vehicle_id"])
        if opts["since"]:
            since = parse_datetime(opts["since"])
            if since is None:
                self.stderr.write("--since deve ser uma data ISO válida")
                return
            qs = qs.filter(ended_at__gte=since)
        if opts["only_missing"]:
            qs = qs.exclude(
                external_id__in=VehicleMileage.objects.filter(
                    origin=VehicleMileage.INTEGRACAO
                ).values("external_id")
            )
        if opts["limit"]:
            qs = qs[:opts["limit"]]

        result = {"selecionados": 0, "criados": 0, "atualizados": 0, "ignorados": 0, "inconsistentes": 0}
        dry_run = opts["dry_run"]
        for bdt in qs:
            result["selecionados"] += 1
            start, end = normalize_km(bdt.started_km), normalize_km(bdt.ended_km)
            if not bdt.vehicle_id or start is None or end is None or start < 0 or end < 0 or end < start or end != int(end):
                result["inconsistentes"] += 1
                continue
            existing = VehicleMileage.objects.filter(origin=VehicleMileage.INTEGRACAO, external_id=str(bdt.external_id)).first()
            if dry_run:
                if existing:
                    result["atualizados"] += 1
                else:
                    result["criados"] += 1
                continue
            before = existing
            sync_bdt_mileage(bdt)
            after = VehicleMileage.objects.get(origin=VehicleMileage.INTEGRACAO, external_id=str(bdt.external_id))
            result["atualizados" if before else "criados"] += 1
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")
