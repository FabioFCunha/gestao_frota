"""Read-only reconciliation plan for Hórus management 125.

Never writes local or Hórus data.  Plate candidates are intentionally not linked.
"""
import os
import re

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.fleet.models import Vehicle, VehiclePlate


def normalize(value):
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


class Command(BaseCommand):
    help = "Dry-run somente leitura da carga Hórus da gestão 125 (ADM)."

    def handle(self, *args, **options):
        try:
            import psycopg
            from dotenv import load_dotenv
            load_dotenv(".env.horus")
            conn = psycopg.connect(
                host=os.getenv("HORUS_DB_HOST"), port=os.getenv("HORUS_DB_PORT", "5432"),
                dbname=os.getenv("HORUS_DB_NAME"), user=os.getenv("HORUS_DB_USER"),
                password=os.getenv("HORUS_DB_PASSWORD"), options="-c default_transaction_read_only=on",
            )
        except Exception as exc:
            raise CommandError("Não foi possível abrir a origem Hórus somente leitura.") from exc
        with conn, conn.cursor() as cursor:
            cursor.execute("SELECT id::text, plate, special_plate FROM fleets WHERE management_id = 125")
            source = cursor.fetchall()
        local_by_uuid = {str(v.horus_fleet_id): v.id for v in Vehicle.objects.filter(horus_fleet_id__isnull=False)}
        plates = list(VehiclePlate.objects.select_related("vehicle").all())
        counts = {"uuid": 0, "plate_candidate": 0, "conflict": 0, "new": 0}
        for fleet_id, plate, special_plate in source:
            if fleet_id in local_by_uuid:
                counts["uuid"] += 1
                result = "UUID confirmado"
            else:
                matched = {p.vehicle_id for p in plates if normalize(p.plate) in {normalize(plate), normalize(special_plate)}}
                if len(matched) == 1:
                    counts["plate_candidate"] += 1
                    result = f"CANDIDATO POR PLACA — exige plano confirmado: {next(iter(matched))}"
                elif len(matched) > 1:
                    counts["conflict"] += 1
                    result = "CONFLITO: múltiplos cadastros locais"
                else:
                    counts["new"] += 1
                    result = "novo cadastro candidato"
            self.stdout.write(f"{fleet_id};{plate or ''};{special_plate or ''};{result}")
        self.stdout.write(self.style.SUCCESS(f"Dry-run concluído: {counts}"))
