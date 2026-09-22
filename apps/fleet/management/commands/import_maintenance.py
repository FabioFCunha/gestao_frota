import pandas as pd
import re
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.fleet.models import (
    Vehicle, VehiclePlate, VehicleMileage, Driver, Workshop
)


class Command(BaseCommand):
    help = "Import maintenance/control data from CONTROLE DE MANUTENÇÃO DOS CARRO.xlsx"

    def _parse_km_prox(self, raw):
        """Parse '40 mil' -> 40000, '60mil' -> 60000, 60000 -> 60000"""
        if pd.isna(raw):
            return None
        s = str(raw).strip().lower().replace('.', '').replace(',', '')
        s = s.replace('mil', '').strip()
        try:
            val = int(float(s))
            if val < 1000:
                return val * 1000
            return val
        except (ValueError, TypeError):
            return None

    def handle(self, *args, **kwargs):
        filepath = r'D:\gestao_frotas\CONTROLE DE MANUTENÇÃO DOS CARRO.xlsx'
        df = pd.read_excel(filepath, skiprows=3, header=0)
        df.columns = [
            'SEI', 'MODELO', 'MARCA', 'COR', 'PLACA', 'RENAVAM',
            'LOCADORA', 'MOTORISTA', 'CONTATO', 'KM',
            'KM_PROX_VISTORIA', 'OFICINA', 'OBS'
        ]

        User = get_user_model()
        user = User.objects.filter(is_superuser=True).first()

        matched = 0
        not_found = 0
        km_updated = 0
        renavam_updated = 0
        drivers_created = 0
        workshops_created = 0

        for _, row in df.iterrows():
            placa = str(row.get('PLACA', '')).strip()
            if not placa or placa.lower() == 'nan':
                continue

            plate_record = VehiclePlate.objects.filter(
                plate__iexact=placa, ends_on__isnull=True
            ).select_related('vehicle').first()

            if not plate_record:
                self.stdout.write(self.style.WARNING(
                    f"  [SKIP] Placa '{placa}' não encontrada no sistema."
                ))
                not_found += 1
                continue

            vehicle = plate_record.vehicle
            matched += 1

            # --- Update RENAVAM ---
            renavam_raw = row.get('RENAVAM')
            if pd.notna(renavam_raw):
                renavam_str = str(int(renavam_raw))
                if not vehicle.renavam or vehicle.renavam != renavam_str:
                    vehicle.renavam = renavam_str
                    renavam_updated += 1

            # --- Record Mileage ---
            km_raw = row.get('KM')
            if pd.notna(km_raw):
                try:
                    km = int(float(km_raw))
                    if km > 0:
                        latest = VehicleMileage.objects.filter(vehicle=vehicle).order_by('-date').first()
                        if not latest or latest.mileage != km:
                            VehicleMileage.objects.create(
                                vehicle=vehicle,
                                mileage=km,
                                date=timezone.now(),
                                origin='MANUAL',
                                recorded_by=user,
                                notes="Importado de planilha de controle"
                            )
                            km_updated += 1
                except (ValueError, TypeError):
                    pass

            # --- Driver ---
            motorista = str(row.get('MOTORISTA', '')).strip()
            contato = str(row.get('CONTATO', '')).strip()
            if contato.lower() == 'nan':
                contato = ''
            driver = None
            if motorista and motorista.lower() != 'nan':
                driver = Driver.objects.filter(name__iexact=motorista).first()
                if not driver:
                    driver = Driver.objects.create(
                        name=motorista,
                        phone=contato[:30] if contato else ''
                    )
                    drivers_created += 1
                elif contato and not driver.phone:
                    driver.phone = contato[:30]
                    driver.save(update_fields=['phone'])

            # --- Workshop ---
            oficina = str(row.get('OFICINA', '')).strip()
            if oficina and oficina.lower() != 'nan':
                workshop = Workshop.objects.filter(name__iexact=oficina).first()
                if not workshop:
                    Workshop.objects.create(name=oficina)
                    workshops_created += 1

            # --- Build structured notes ---
            km_prox = self._parse_km_prox(row.get('KM_PROX_VISTORIA'))
            obs = str(row.get('OBS', '')).strip()
            if obs.lower() == 'nan':
                obs = ''

            parts = []
            if motorista and motorista.lower() != 'nan':
                line = f"[MOTORISTA] {motorista}"
                if contato:
                    line += f" | Tel: {contato}"
                parts.append(line)
            if oficina and oficina.lower() != 'nan':
                parts.append(f"[OFICINA] {oficina}")
            if km_prox:
                parts.append(f"[KM_PROX_REVISAO] {km_prox}")
            if obs:
                parts.append(f"[OBS] {obs}")

            # Clear old import data and set new
            existing = vehicle.notes or ''
            # Remove previous import blocks
            clean = re.sub(r'\[MOTORISTA\].*\n?', '', existing)
            clean = re.sub(r'\[OFICINA\].*\n?', '', clean)
            clean = re.sub(r'\[KM_PROX_REVISAO\].*\n?', '', clean)
            clean = re.sub(r'\[OBS\].*\n?', '', clean)
            clean = re.sub(r'\[Planilha\].*\n?', '', clean)
            clean = clean.strip()

            new_notes = '\n'.join(parts)
            if clean:
                new_notes = clean + '\n' + new_notes
            vehicle.notes = new_notes.strip()
            vehicle.save(update_fields=['renavam', 'notes'])

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(self.style.SUCCESS('IMPORTAÇÃO CONCLUÍDA'))
        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(f"  Veículos encontrados:   {matched}")
        self.stdout.write(f"  Não encontrados:        {not_found}")
        self.stdout.write(f"  KM atualizados:         {km_updated}")
        self.stdout.write(f"  RENAVAM atualizados:    {renavam_updated}")
        self.stdout.write(f"  Motoristas criados:     {drivers_created}")
        self.stdout.write(f"  Oficinas criadas:       {workshops_created}")
        self.stdout.write(self.style.SUCCESS('=' * 50))