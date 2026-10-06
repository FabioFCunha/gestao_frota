import csv
import re
import unicodedata
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Prefetch

from apps.fleet.models import Vehicle, VehiclePlate


def normalize_text(value):
    if value is None:
        return ""
    value = unicodedata.normalize("NFKD", str(value).strip().upper())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", value)


def normalize_plate(value):
    return re.sub(r"[^A-Z0-9]", "", normalize_text(value))


def normalize_renavam(value):
    return re.sub(r"\D", "", normalize_text(value))


def field(row, *names):
    normalized = {normalize_text(k): v for k, v in row.items()}
    for name in names:
        value = normalized.get(normalize_text(name))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


class Command(BaseCommand):
    help = "Audita uma carga ADM contra a frota existente, sem alterar o banco."

    def add_arguments(self, parser):
        parser.add_argument("--arquivo", required=True, help="CSV exportado do ADM.")
        parser.add_argument(
            "--saida",
            default="adm_import_audit",
            help="Diretório dos relatórios.",
        )

    def handle(self, *args, **options):
        source = Path(options["arquivo"])
        output_dir = Path(options["saida"])
        if not source.exists():
            raise CommandError(f"Arquivo não encontrado: {source}")

        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))

        if not rows:
            raise CommandError("O arquivo ADM não possui registros.")

        plates = Prefetch(
            "plate_history",
            queryset=VehiclePlate.objects.all(),
        )
        vehicles = list(Vehicle.objects.prefetch_related(plates).all())

        by_plate = {}
        by_renavam = {}
        current_plates = set()

        for vehicle in vehicles:
            renavam = normalize_renavam(getattr(vehicle, "renavam", ""))
            if renavam:
                by_renavam.setdefault(renavam, []).append(vehicle)

            for plate in vehicle.plate_history.all():
                normalized = normalize_plate(plate.plate)
                if not normalized:
                    continue
                by_plate.setdefault(normalized, []).append(vehicle)
                if plate.kind == "CURRENT" and plate.ends_on is None:
                    current_plates.add(normalized)

        result = []
        matched_vehicle_ids = set()

        for line_number, row in enumerate(rows, start=2):
            plate = normalize_plate(field(row, "PLACA", "PLACA VEICULO"))
            renavam = normalize_renavam(field(row, "RENAVAM"))
            contract = field(row, "CONTRATO Nº", "CONTRATO", "CONTRATO N")
            renter = field(row, "CONTRATADA", "LOCADORA")
            cnpj = re.sub(r"\D", "", field(row, "CNPJ"))

            plate_matches = by_plate.get(plate, []) if plate else []
            renavam_matches = by_renavam.get(renavam, []) if renavam else []

            action = "REVISAR"
            reason = "SEM_CHAVE"
            vehicle = None

            if len(plate_matches) == 1:
                vehicle = plate_matches[0]
                matched_vehicle_ids.add(str(vehicle.id))
                action = "EXISTENTE"
                reason = "PLACA_ENCONTRADA"
                if renavam and normalize_renavam(vehicle.renavam) and normalize_renavam(vehicle.renavam) != renavam:
                    action = "REVISAR"
                    reason = "CONFLITO_PLACA_RENAVAM"
            elif len(plate_matches) > 1:
                action = "REVISAR"
                reason = "PLACA_DUPLICADA_NO_BANCO"
            elif len(renavam_matches) == 1:
                vehicle = renavam_matches[0]
                matched_vehicle_ids.add(str(vehicle.id))
                action = "VINCULAR_RENAVAM"
                reason = "RENAVAM_ENCONTRADO_PLACA_DIFERENTE"
            elif len(renavam_matches) > 1:
                action = "REVISAR"
                reason = "RENAVAM_DUPLICADO_NO_BANCO"
            elif plate or renavam:
                action = "CRIAR"
                reason = "NAO_ENCONTRADO"

            current_plate = ""
            current_renavam = ""
            active = ""
            vehicle_id = ""

            if vehicle:
                vehicle_id = str(vehicle.id)
                current_renavam = getattr(vehicle, "renavam", "") or ""
                active = "SIM" if vehicle.active else "NAO"
                current = next(
                    (
                        p for p in vehicle.plate_history.all()
                        if p.kind == "CURRENT" and p.ends_on is None
                    ),
                    None,
                )
                current_plate = current.plate if current else ""

            result.append({
                "linha_adm": line_number,
                "acao": action,
                "motivo": reason,
                "placa_adm": plate,
                "renavam_adm": renavam,
                "contrato_adm": contract,
                "contratada_adm": renter,
                "cnpj_adm": cnpj,
                "vehicle_id": vehicle_id,
                "placa_atual": current_plate,
                "renavam_atual": current_renavam,
                "ativo_atual": active,
            })

        for vehicle in vehicles:
            if str(vehicle.id) in matched_vehicle_ids:
                continue
            current = next(
                (
                    p for p in vehicle.plate_history.all()
                    if p.kind == "CURRENT" and p.ends_on is None
                ),
                None,
            )
            result.append({
                "linha_adm": "",
                "acao": "FORA_DA_CARGA",
                "motivo": "VEICULO_EXISTENTE_NAO_ENCONTRADO_NO_ADM",
                "placa_adm": "",
                "renavam_adm": "",
                "contrato_adm": "",
                "contratada_adm": "",
                "cnpj_adm": "",
                "vehicle_id": str(vehicle.id),
                "placa_atual": current.plate if current else "",
                "renavam_atual": getattr(vehicle, "renavam", "") or "",
                "ativo_atual": "SIM" if vehicle.active else "NAO",
            })

        fields = [
            "linha_adm", "acao", "motivo", "placa_adm", "renavam_adm",
            "contrato_adm", "contratada_adm", "cnpj_adm", "vehicle_id",
            "placa_atual", "renavam_atual", "ativo_atual",
        ]
        output_dir.mkdir(parents=True, exist_ok=True)
        report = output_dir / "adm_comparacao.csv"

        with report.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
            writer.writeheader()
            writer.writerows(result)

        summary = {}
        for item in result:
            summary[item["acao"]] = summary.get(item["acao"], 0) + 1

        self.stdout.write(self.style.SUCCESS("Auditoria ADM concluída. Nenhuma alteração foi feita no banco."))
        self.stdout.write(f"Registros ADM: {len(rows)}")
        for action in sorted(summary):
            self.stdout.write(f"{action}: {summary[action]}")
        self.stdout.write(f"Relatório: {report}")
