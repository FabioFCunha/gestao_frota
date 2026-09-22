from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.fleet.models import AdministrativeUnit, Driver, VehicleDriverAssignment


class Command(BaseCommand):
    help = "Substitui o cadastro de motoristas pelos condutores de uma planilha Excel."

    def add_arguments(self, parser):
        parser.add_argument("source", type=Path, help="Caminho da planilha de condutores (.xlsx).")

    def handle(self, *args, **options):
        source = options["source"]
        if not source.is_file():
            raise CommandError(f"Planilha não encontrada: {source}")

        try:
            from openpyxl import load_workbook
        except ImportError as error:
            raise CommandError("Instale a dependência openpyxl para importar a planilha.") from error

        workbook = load_workbook(source, read_only=True, data_only=True)
        worksheet = workbook.active
        rows = list(worksheet.iter_rows(values_only=True))
        workbook.close()

        if not rows:
            raise CommandError("A planilha está vazia.")

        columns = {str(value).strip(): index for index, value in enumerate(rows[0]) if value is not None}
        required_columns = {"CnhCondutor", "Categoria", "Registro", "Nome", "Unidade", "Validade", "Telefone", "Status"}
        missing_columns = required_columns - columns.keys()
        if missing_columns:
            raise CommandError(f"Colunas obrigatórias ausentes: {', '.join(sorted(missing_columns))}")

        drivers = []
        registrations = set()
        for row_number, row in enumerate(rows[1:], start=2):
            name = self.value(row, columns, "Nome")
            registration = self.value(row, columns, "Registro")
            if not name or not registration:
                raise CommandError(f"Linha {row_number}: nome e registro são obrigatórios.")
            if registration in registrations:
                raise CommandError(f"Linha {row_number}: registro duplicado ({registration}).")
            registrations.add(registration)

            drivers.append({
                "name": name,
                "registration": registration,
                "unit_name": self.value(row, columns, "Unidade"),
                "phone": self.value(row, columns, "Telefone"),
                "cnh_number": self.cnh_value(row[columns["CnhCondutor"]]),
                "cnh_category": self.value(row, columns, "Categoria"),
                "cnh_expiration": self.date_value(row[columns["Validade"]]),
                "active": self.value(row, columns, "Status").upper() == "ATIVO",
            })

        with transaction.atomic():
            VehicleDriverAssignment.objects.all().delete()
            Driver.objects.all().delete()

            units = {}
            for item in drivers:
                unit_name = item.pop("unit_name")
                unit = None
                if unit_name:
                    unit = units.get(unit_name)
                    if unit is None:
                        unit, _ = AdministrativeUnit.objects.get_or_create(
                            acronym=unit_name,
                            defaults={"name": unit_name},
                        )
                        units[unit_name] = unit
                Driver.objects.create(unit=unit, **item)

        self.stdout.write(self.style.SUCCESS(f"Cadastro substituído com {len(drivers)} condutores da planilha."))

    @staticmethod
    def value(row, columns, name):
        value = row[columns[name]]
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def date_value(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        return value

    @staticmethod
    def cnh_value(value):
        number = str(value).strip()
        return number.zfill(11) if number.isdigit() else number
