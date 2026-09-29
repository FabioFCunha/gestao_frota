from datetime import date, datetime
from decimal import Decimal
import re

import pandas as pd
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.fleet.models import (
    Brand, Contract, Renter, Vehicle, VehicleHistory,
    VehicleModel, VehiclePlate, VehicleStatus,
)

REQUIRED_COLUMNS = [
    "CONTRATO Nº", "CONTRATADA", "PLACA", "RENAVAN", "CNPJ",
    "DATA RECEBIMENTO DA VTR", "TIPO", "Marca", "Modelo",
    "SITUAÇÃO GERAL", "ABASTECIMENTO", "INFRAÇÕES",
    "DATA DE VERIFICAÇÃO", "SITUAÇÃO",
]

def clean(value):
    if value is None or pd.isna(value):
        return ""
    value = str(value).strip()
    return "" if value.lower() in {"nan", "nat", "none"} else value

def normalize_contract(value):
    value = re.sub(r"\s+", " ", clean(value).replace("\xa0", " ")).strip()
    return re.sub(r"\s*/\s*", "/", value)

def normalize_renter(value):
    return re.sub(r"\s+", " ", clean(value).replace(chr(96), "'")).strip()

def normalize_plate(value):
    return re.sub(r"[^A-Z0-9]", "", clean(value).upper())[:8]

def normalize_renavam(value):
    value = clean(value).upper().replace(" ", "")
    if not value:
        return ""
    if re.fullmatch(r"\d+", value):
        return value
    try:
        number = Decimal(value.replace(",", "."))
        if number == number.to_integral_value():
            return str(number.quantize(Decimal("1")).to_integral_value())
    except Exception:
        pass
    return value

def normalize_cnpj(value):
    digits = re.sub(r"\D", "", clean(value))
    if len(digits) != 14:
        return ""
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"

def parse_date(value):
    value = clean(value)
    if not value:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()

def status_name(raw):
    value = clean(raw).upper()
    mapping = {
        "OPERANTE": "Ativo",
        "INOPERANTE, MANUTENÇÃO": "Em manutenção",
        "CONTRATO ENCERRADO": "Contrato encerrado",
    }
    return mapping.get(value, value.title() if value else "Ativo")

class Command(BaseCommand):
    help = "Carga inicial da frota da Lei Seca a partir de Excel."

    def add_arguments(self, parser):
        parser.add_argument("--arquivo", required=True, help="Caminho do arquivo Excel.")
        parser.add_argument("--dry-run", action="store_true", help="Valida sem gravar dados.")
        parser.add_argument("--sheet", default=0, help="Índice ou nome da planilha.")

    def handle(self, *args, **options):
        filepath = options["arquivo"]
        dry_run = options["dry_run"]
        sheet = int(options["sheet"]) if str(options["sheet"]).isdigit() else options["sheet"]

        try:
            df = pd.read_excel(filepath, sheet_name=sheet, dtype=str)
        except Exception as exc:
            raise CommandError(f"Não foi possível ler o Excel: {exc}")

        df.columns = [clean(c) for c in df.columns]
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise CommandError("Colunas obrigatórias ausentes: " + ", ".join(missing))

        df = df[REQUIRED_COLUMNS]
        rows, seen, duplicates = [], set(), []
        for excel_row, (_, row) in enumerate(df.iterrows(), start=2):
            plate = normalize_plate(row["PLACA"])
            if not plate:
                continue
            if plate in seen:
                duplicates.append(plate)
            seen.add(plate)
            rows.append((excel_row, row, plate))

        User = get_user_model()
        user = User.objects.filter(is_superuser=True).first()
        if not user:
            raise CommandError("Nenhum superusuário encontrado. A carga não será executada.")

        stats = {
            "rows": len(rows), "unique_plates": len(seen), "created": 0,
            "updated": 0, "plates_created": 0, "contracts_found": 0,
            "contracts_missing": 0, "renters_created": 0, "brands_created": 0,
            "models_created": 0, "status_created": 0, "history_created": 0,
            "warnings": 0, "errors": 0,
        }
        missing_contracts, warnings = set(), []

        def warn(message):
            warnings.append(message)
            stats["warnings"] += 1

        def get_renter(name, cnpj):
            if not name:
                return None
            renter = Renter.objects.filter(name__iexact=name).first()
            if not renter:
                renter = Renter.objects.create(name=name, cnpj=cnpj or None)
                stats["renters_created"] += 1
            elif cnpj and not renter.cnpj:
                renter.cnpj = cnpj
                renter.save(update_fields=["cnpj", "updated_at"])
            return renter

        def get_contract(number, renter):
            if not number:
                return None
            contract = Contract.objects.filter(number=number).first()
            if contract:
                stats["contracts_found"] += 1
                if renter and contract.renter_id != renter.id:
                    contract.renter = renter
                    contract.save(update_fields=["renter", "updated_at"])
                return contract
            missing_contracts.add(number)
            stats["contracts_missing"] += 1
            return None

        def get_brand(name):
            if not name:
                return None
            brand, created = Brand.objects.get_or_create(name=name)
            if created:
                stats["brands_created"] += 1
            return brand

        def get_model(name, brand):
            if not name or not brand:
                return None
            model = VehicleModel.objects.filter(brand=brand, name__iexact=name).first()
            if not model:
                model = VehicleModel.objects.create(name=name, brand=brand)
                stats["models_created"] += 1
            return model

        def get_status(raw):
            obj, created = VehicleStatus.objects.get_or_create(name=status_name(raw))
            if created:
                stats["status_created"] += 1
            return obj

        def find_vehicle(plate, renavam):
            plate_record = VehiclePlate.objects.filter(
                plate__iexact=plate
            ).select_related("vehicle").first()
            renavam_vehicle = Vehicle.objects.filter(renavam=renavam).first() if renavam else None
            if plate_record and renavam_vehicle and plate_record.vehicle_id != renavam_vehicle.id:
                raise ValueError(
                    f"Conflito: placa {plate} e RENAVAM {renavam} apontam para veículos diferentes."
                )
            return plate_record.vehicle if plate_record else renavam_vehicle

        def add_snapshot(vehicle, snapshot):
            latest = VehicleHistory.objects.filter(
                vehicle=vehicle, field="lei_seca_import"
            ).order_by("-created_at").first()
            if latest and latest.new_value == snapshot:
                return
            VehicleHistory.objects.create(
                vehicle=vehicle,
                field="lei_seca_import",
                old_value=latest.new_value if latest else None,
                new_value=snapshot,
                reason="Carga inicial da frota Lei Seca via Excel",
                changed_by=user,
            )
            stats["history_created"] += 1

        def process():
            for excel_row, row, plate in rows:
                try:
                    contract_number = normalize_contract(row["CONTRATO Nº"])
                    renter_name = normalize_renter(row["CONTRATADA"])
                    raw_cnpj = clean(row["CNPJ"])
                    cnpj = normalize_cnpj(raw_cnpj)
                    if raw_cnpj and not cnpj:
                        warn(
                            f"Linha {excel_row} / {plate}: CNPJ '{raw_cnpj}' "
                            "não foi gravado porque o Excel o apresentou em formato "
                            "científico/incompleto."
                        )

                    renter = get_renter(renter_name, cnpj)
                    contract = get_contract(contract_number, renter)
                    renavam = normalize_renavam(row["RENAVAN"])
                    brand = get_brand(clean(row["Marca"]))
                    model = get_model(clean(row["Modelo"]), brand)
                    status = get_status(row["SITUAÇÃO GERAL"])
                    vehicle = find_vehicle(plate, renavam)

                    if vehicle is None:
                        vehicle = Vehicle(
                            brand=brand, model=model, renavam=renavam or None,
                            contract=contract, renter=renter, status=status,
                            created_by=user,
                        )
                        if not contract and contract_number:
                            vehicle.notes = (
                                f"[LEI SECA] Contrato informado na planilha: {contract_number}. "
                                "Contrato ainda não localizado no sistema."
                            )
                        vehicle.save()
                        stats["created"] += 1
                    else:
                        changed = []
                        if brand and vehicle.brand_id != brand.id:
                            vehicle.brand = brand; changed.append("brand")
                        if model and vehicle.model_id != model.id:
                            vehicle.model = model; changed.append("model")
                        if renavam and vehicle.renavam != renavam:
                            conflict = Vehicle.objects.filter(renavam=renavam).exclude(pk=vehicle.pk).exists()
                            if conflict:
                                warn(f"Linha {excel_row} / {plate}: RENAVAM {renavam} já pertence a outro veículo.")
                            else:
                                vehicle.renavam = renavam; changed.append("renavam")
                        if contract and vehicle.contract_id != contract.id:
                            vehicle.contract = contract; changed.append("contract")
                        if renter and vehicle.renter_id != renter.id:
                            vehicle.renter = renter; changed.append("renter")
                        if vehicle.status_id != status.id:
                            vehicle.status = status; changed.append("status")
                        if changed:
                            vehicle.save(update_fields=changed + ["updated_at"])
                            stats["updated"] += 1

                    active_plate = VehiclePlate.objects.filter(
                        vehicle=vehicle, kind=VehiclePlate.CURRENT, ends_on__isnull=True
                    ).order_by("-starts_on").first()

                    if not active_plate:
                        VehiclePlate.objects.create(
                            vehicle=vehicle, plate=plate, kind=VehiclePlate.CURRENT,
                            starts_on=timezone.now(), changed_by=user,
                        )
                        stats["plates_created"] += 1
                    elif active_plate.plate.upper() != plate:
                        raise ValueError(
                            f"Veículo encontrado para {plate}, mas sua placa atual é "
                            f"{active_plate.plate}. Nenhuma alteração de placa foi feita."
                        )

                    received = parse_date(row["DATA RECEBIMENTO DA VTR"])
                    verified = parse_date(row["DATA DE VERIFICAÇÃO"])
                    snapshot = {
                        "contrato": contract_number,
                        "contratada": renter_name,
                        "placa": plate,
                        "renavam": renavam,
                        "cnpj": cnpj,
                        "data_recebimento_vtr": received.isoformat() if received else None,
                        "tipo": clean(row["TIPO"]),
                        "marca": clean(row["Marca"]),
                        "modelo": clean(row["Modelo"]),
                        "situacao_geral": clean(row["SITUAÇÃO GERAL"]),
                        "abastecimento": clean(row["ABASTECIMENTO"]),
                        "infracoes": clean(row["INFRAÇÕES"]),
                        "data_verificacao": verified.isoformat() if verified else None,
                        "situacao": clean(row["SITUAÇÃO"]),
                    }
                    add_snapshot(vehicle, snapshot)

                except Exception as exc:
                    stats["errors"] += 1
                    raise CommandError(f"Erro na linha {excel_row} / placa {plate}: {exc}")

        if dry_run:
            before = stats.copy()
            with transaction.atomic():
                process()
                transaction.set_rollback(True)
            stats = before
        else:
            with transaction.atomic():
                process()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 64))
        self.stdout.write(self.style.SUCCESS("CARGA INICIAL LEI SECA " + ("(DRY-RUN)" if dry_run else "CONCLUÍDA")))
        self.stdout.write(self.style.SUCCESS("=" * 64))
        for label, key in [
            ("Linhas válidas", "rows"), ("Placas distintas", "unique_plates"),
            ("Veículos criados", "created"), ("Veículos atualizados", "updated"),
            ("Placas criadas", "plates_created"), ("Contratos localizados", "contracts_found"),
            ("Contratos ausentes", "contracts_missing"), ("Contratadas criadas", "renters_created"),
            ("Marcas criadas", "brands_created"), ("Modelos criados", "models_created"),
            ("Situações criadas", "status_created"), ("Históricos registrados", "history_created"),
            ("Avisos", "warnings"), ("Erros", "errors"),
        ]:
            self.stdout.write(f"{label:24} {stats[key]}")

        if duplicates:
            self.stdout.write(self.style.WARNING(
                "Placas repetidas no Excel: " + ", ".join(sorted(set(duplicates)))
            ))
        if missing_contracts:
            self.stdout.write(self.style.WARNING(
                "Contratos não localizados: " + ", ".join(sorted(missing_contracts))
            ))
            self.stdout.write(self.style.WARNING(
                "Nenhuma vigência foi inventada. Veículos sem contrato localizado "
                "ficam sem FK de contrato até o cadastro correto existir."
            ))
        for message in warnings:
            self.stdout.write(self.style.WARNING("AVISO: " + message))
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN: nenhuma alteração foi persistida no banco."))
