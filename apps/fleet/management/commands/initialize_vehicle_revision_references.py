from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.fleet.models import Vehicle, VehicleMileage


class Command(BaseCommand):
    help = "Inicializa referências fixas de primeira revisão a partir da leitura atual."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Persiste as referências; sem esta opção é dry-run.")
        parser.add_argument("--vehicle-id")
        parser.add_argument("--limit", type=int)

    def handle(self, *args, **options):
        vehicles = Vehicle.objects.filter(revision_reference_km__isnull=True)
        if options["vehicle_id"]:
            vehicles = vehicles.filter(pk=options["vehicle_id"])
        if options["limit"]:
            vehicles = vehicles[:options["limit"]]

        initialized = skipped = 0
        for vehicle in vehicles:
            latest = (
                VehicleMileage.objects.filter(vehicle=vehicle)
                .order_by("-date", "-created_at")
                .first()
            )
            if latest is None:
                skipped += 1
                continue
            if options["apply"]:
                vehicle.revision_reference_km = latest.mileage
                vehicle.revision_reference_at = timezone.now()
                vehicle.revision_reference_source = f"{latest.origin}:{latest.id}"
                vehicle.save(update_fields=[
                    "revision_reference_km",
                    "revision_reference_at",
                    "revision_reference_source",
                    "updated_at",
                ])
            initialized += 1

        mode = "aplicado" if options["apply"] else "dry-run"
        self.stdout.write(f"{mode}: referências={initialized}; sem quilometragem={skipped}")
