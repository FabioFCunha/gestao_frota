from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from apps.fleet.horus_sync import HorusBDTSyncer
from apps.fleet.models import Vehicle, VehiclePlate


class Command(BaseCommand):
    help = "Sincroniza as viaturas de uma gestão específica do Hórus."

    def add_arguments(self, parser):
        parser.add_argument("--management-id", type=int, default=125)
        parser.add_argument("--management-name", type=str, default="SEGOV - ADM")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Consulta o Hórus e compara com o Gestão de Frotas, sem gravar.",
        )

    @staticmethod
    def _normalize_plate(value):
        return "".join(str(value or "").upper().split()).replace("-", "")

    def _compare_with_local(self, fleets):
        horus_ids = [fleet["id"] for fleet in fleets]
        vehicles_by_horus_id = {
            str(vehicle.horus_fleet_id): vehicle
            for vehicle in Vehicle.objects.filter(horus_fleet_id__in=horus_ids)
        }

        current_plates = (
            VehiclePlate.objects.filter(
                kind=VehiclePlate.CURRENT, ends_on__isnull=True
            ).select_related("vehicle")
        )
        vehicles_by_plate = {}
        for record in current_plates:
            key = self._normalize_plate(record.plate)
            if key:
                vehicles_by_plate.setdefault(key, []).append(record.vehicle)

        result = []
        for fleet in fleets:
            fleet_id = str(fleet["id"])
            plate = (fleet["plate"] or "").strip().upper()
            plate_key = self._normalize_plate(plate)
            uuid_vehicle = vehicles_by_horus_id.get(fleet_id)
            plate_matches = vehicles_by_plate.get(plate_key, []) if plate_key else []
            unique_plate_matches = {
                str(vehicle.id): vehicle for vehicle in plate_matches
            }

            if len(unique_plate_matches) > 1:
                action = "CONFLITO_PLACA_DUPLICADA_LOCAL"
                vehicle = uuid_vehicle
            elif uuid_vehicle is not None and plate_matches:
                plate_vehicle = next(iter(unique_plate_matches.values()))
                if plate_vehicle.id != uuid_vehicle.id:
                    action = "CONFLITO_UUID_PLACA"
                else:
                    current_plate = (
                        uuid_vehicle.plate_history.filter(
                            kind=VehiclePlate.CURRENT, ends_on__isnull=True
                        ).first()
                    )
                    action = (
                        "EXISTENTE"
                        if current_plate
                        and self._normalize_plate(current_plate.plate) == plate_key
                        else "ATUALIZAR_PLACA"
                    )
                vehicle = uuid_vehicle
            elif uuid_vehicle is not None:
                action = "EXISTENTE"
                vehicle = uuid_vehicle
            elif plate_matches:
                action = "VINCULAR_PLACA"
                vehicle = plate_matches[0]
            else:
                action = "CRIAR"
                vehicle = None

            result.append({"fleet": fleet, "action": action, "vehicle": vehicle})

        return result

    def handle(self, *args, **options):
        management_id = options["management_id"]
        management_name = options["management_name"]
        dry_run = options["dry_run"]

        try:
            syncer = HorusBDTSyncer(dry_run=dry_run)

            with syncer._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'fleets'
                          AND column_name = 'management_id'
                        """
                    )
                    if cursor.fetchone() is None:
                        raise CommandError(
                            "A tabela public.fleets do Hórus não possui management_id. "
                            "Não é seguro inferir a gestão por placa ou BDT."
                        )

                    cursor.execute(
                        """
                        SELECT f.id, f.plate, f.special_plate
                        FROM public.fleets f
                        WHERE f.management_id = %s
                        ORDER BY f.plate NULLS LAST, f.id
                        """,
                        [management_id],
                    )
                    fleets = [
                        {"id": row[0], "plate": row[1], "special_plate": row[2]}
                        for row in cursor.fetchall()
                    ]

            self.stdout.write(
                f"Hórus | Gestão {management_id} | {management_name}"
            )
            self.stdout.write(f"Viaturas encontradas no Hórus: {len(fleets)}")

            if not fleets:
                self.stdout.write(
                    self.style.WARNING(
                        "Nenhuma viatura encontrada para esta gestão. "
                        "Nenhum dado foi alterado."
                    )
                )
                return

            if dry_run:
                comparison = self._compare_with_local(fleets)
                counts = Counter(item["action"] for item in comparison)

                self.stdout.write("")
                self.stdout.write("Comparação com Gestão de Frotas:")
                for action in (
                    "EXISTENTE",
                    "ATUALIZAR_PLACA",
                    "VINCULAR_PLACA",
                    "CRIAR",
                    "CONFLITO_UUID_PLACA",
                    "CONFLITO_PLACA_DUPLICADA_LOCAL",
                ):
                    self.stdout.write(f"- {action}: {counts.get(action, 0)}")

                self.stdout.write("")
                self.stdout.write("Detalhamento:")
                for item in comparison:
                    fleet = item["fleet"]
                    vehicle = item["vehicle"]
                    local_id = str(vehicle.id) if vehicle else "-"
                    self.stdout.write(
                        f"- {item['action']} | {fleet['plate'] or '(sem placa)'} | "
                        f"Hórus {fleet['id']} | Local {local_id}"
                    )

                self.stdout.write("")
                self.stdout.write(
                    self.style.SUCCESS(
                        "DRY-RUN concluído. Nenhuma viatura foi enviada para o Gestão de Frotas."
                    )
                )
                return

            created = 0
            updated = 0

            for fleet in fleets:
                response = syncer._post_data(
                    "vehicles",
                    {
                        "external_id": fleet["id"],
                        "plate": (fleet["plate"] or "").strip().upper(),
                        "special_plate": fleet["special_plate"] or "",
                        "management_name": management_name,
                    },
                )
                syncer._require_response(
                    response, "vehicles", 1, vehicle_id=fleet["id"]
                )

                if response["result"] == "created":
                    created += 1
                else:
                    updated += 1

            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Sincronização concluída."))
            self.stdout.write(f"Gestão Hórus: {management_id} - {management_name}")
            self.stdout.write(f"Encontradas: {len(fleets)}")
            self.stdout.write(f"Criadas: {created}")
            self.stdout.write(f"Atualizadas: {updated}")

        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(str(exc)) from exc
