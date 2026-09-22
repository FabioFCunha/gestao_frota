import pandas as pd
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.fleet.models import (
    Vehicle, VehiclePlate, VehicleFine, VehicleFineStatus
)


class Command(BaseCommand):
    help = "Import fines from SITUAÇÃO DAS MULTAS.xlsx"

    def handle(self, *args, **kwargs):
        filepath = r'D:\gestao_frotas\SITUAÇÃO DAS MULTAS.xlsx'
        df = pd.read_excel(filepath, skiprows=1, header=0)
        df.columns = ['PLACA', 'PROCESSO', 'AUTO', 'ORGAO', 'SITUACAO', 'DATA']

        User = get_user_model()
        user = User.objects.filter(is_superuser=True).first()

        # Create fine statuses
        status_map = {}
        for status_name in df['SITUACAO'].dropna().unique():
            name = str(status_name).strip()
            if name and name.lower() != 'nan':
                obj, _ = VehicleFineStatus.objects.get_or_create(name=name)
                status_map[name.upper()] = obj

        created = 0
        skipped_plate = 0
        skipped_dup = 0

        for _, row in df.iterrows():
            placa = str(row.get('PLACA', '')).strip()
            auto = str(row.get('AUTO', '')).strip()
            if not placa or placa.lower() == 'nan' or not auto or auto.lower() == 'nan':
                continue

            # Find vehicle by plate (any plate, current or not)
            plate_record = VehiclePlate.objects.filter(
                plate__iexact=placa
            ).select_related('vehicle').first()

            if not plate_record:
                # Auto-create vehicle for this plate
                from apps.fleet.models import VehicleStatus
                status_ativo, _ = VehicleStatus.objects.get_or_create(name='Ativo')
                vehicle = Vehicle.objects.create(
                    status=status_ativo,
                    created_by=user,
                    notes='[AUTO] Veículo criado automaticamente a partir da planilha de multas'
                )
                VehiclePlate.objects.create(
                    vehicle=vehicle,
                    plate=placa,
                    kind='CURRENT',
                    starts_on=timezone.now(),
                    changed_by=user
                )
                self.stdout.write(self.style.WARNING(
                    f"  [NEW] Veículo criado para placa '{placa}'"
                ))
            else:
                vehicle = plate_record.vehicle

            # Skip duplicates
            if VehicleFine.objects.filter(auto_number=auto, vehicle=vehicle).exists():
                skipped_dup += 1
                continue

            # Status
            situacao = str(row.get('SITUACAO', 'VERIFICAR')).strip().upper()
            status = status_map.get(situacao)
            if not status:
                status, _ = VehicleFineStatus.objects.get_or_create(name=situacao)
                status_map[situacao] = status

            # Date
            data = row.get('DATA')
            if pd.notna(data):
                if isinstance(data, pd.Timestamp):
                    date_val = timezone.make_aware(data.to_pydatetime())
                else:
                    date_val = timezone.now()
            else:
                date_val = timezone.now()

            # Agency
            orgao = str(row.get('ORGAO', '')).strip()
            if orgao.lower() == 'nan':
                orgao = ''

            # Process (SEI)
            processo = str(row.get('PROCESSO', '')).strip()
            if processo.lower() == 'nan':
                processo = ''

            VehicleFine.objects.create(
                vehicle=vehicle,
                auto_number=auto,
                agency=orgao,
                status=status,
                date=date_val,
                notes=f"Processo: {processo}" if processo else '',
                created_by=user
            )
            created += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(self.style.SUCCESS('IMPORTAÇÃO DE MULTAS CONCLUÍDA'))
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(f"  Multas criadas:         {created}")
        self.stdout.write(f"  Placas não encontradas: {skipped_plate}")
        self.stdout.write(f"  Duplicadas ignoradas:   {skipped_dup}")
        self.stdout.write(self.style.SUCCESS('=' * 50))