import pandas as pd
import datetime
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.fleet.models import (
    Vehicle, VehicleStatus, Contract, Renter, Brand, VehicleModel,
    AdministrativeUnit, Base, VehiclePlate
)

class Command(BaseCommand):
    help = "Import vehicles from frotas.xlsx"

    def handle(self, *args, **kwargs):
        df = pd.read_excel('frotas.xlsx')
        User = get_user_model()
        user = User.objects.filter(is_superuser=True).first()
        if not user:
            user = User.objects.create_superuser('admin', 'admin@example.com', 'admin')
        
        VehiclePlate.objects.all().delete()
        Vehicle.objects.all().delete()
        
        status_ativo, _ = VehicleStatus.objects.get_or_create(name='Ativo')
        count = 0
        
        for _, row in df.iterrows():
            if pd.isna(row.get('Placa')): continue
            
            # Extract basic data
            placa_bruta = str(row.get('Placa')).strip()
            
            # Placa can have multiple texts: 'SRX4F02 / TTM3D48 CEDIDO PELA SECC / RESERVA SRX8G52'
            placa = placa_bruta.split('/')[0].strip().split(' ')[0]
            
            # Renter
            locadora_nome = str(row.get('Locadora')).strip()
            renter = None
            if locadora_nome and locadora_nome.lower() != 'nan':
                renter, _ = Renter.objects.get_or_create(name=locadora_nome)
                
            # Contract
            contrato_nome = str(row.get('Contrato')).strip()
            vigencia = str(row.get('Vigência')).strip()
            
            contract = None
            if contrato_nome and contrato_nome.lower() != 'nan':
                starts_on = datetime.date(2022, 1, 1)
                ends_on = datetime.date(2025, 1, 1)
                if vigencia and '-' in vigencia:
                    try:
                        pts = vigencia.split('-')
                        starts_on = datetime.datetime.strptime(pts[0].strip(), '%d/%m/%Y').date()
                        ends_on = datetime.datetime.strptime(pts[1].strip(), '%d/%m/%Y').date()
                    except: pass
                
                contract, _ = Contract.objects.get_or_create(
                    number=contrato_nome,
                    defaults={'renter': renter, 'starts_on': starts_on, 'ends_on': ends_on, 'administrative_status': 'VIGENTE'}
                )
            
            # Brand & Model
            marca = str(row.get('Marca')).strip()
            brand = None
            if marca and marca.lower() != 'nan':
                brand, _ = Brand.objects.get_or_create(name=marca)
                
            modelo = str(row.get('Modelo')).strip()
            model = None
            if modelo and modelo.lower() != 'nan':
                model, _ = VehicleModel.objects.get_or_create(name=modelo, defaults={'brand': brand})
                
            # Unit & Base
            unidade = str(row.get('Unidade Administrativa')).strip()
            unit = None
            if unidade and unidade.lower() != 'nan':
                unit = AdministrativeUnit.objects.filter(name=unidade).first()
                if not unit:
                    import uuid
                    unit = AdministrativeUnit.objects.create(name=unidade, acronym=str(uuid.uuid4())[:8])
                
            base_nome = str(row.get('Baseado')).strip()
            base = None
            if base_nome and base_nome.lower() != 'nan':
                base, _ = Base.objects.get_or_create(name=base_nome, defaults={'unit': unit})
                
            # Other attrs
            cor = str(row.get('Cor')).strip() if not pd.isna(row.get('Cor')) else ''
            if cor.lower() == 'nan': cor = ''
            blindado = str(row.get('Blindado')).strip().upper() == 'SIM'
            acautelamento = str(row.get('Acautelamento')).strip() if not pd.isna(row.get('Acautelamento')) else ''
            if acautelamento.lower() == 'nan': acautelamento = ''
            
            # Create vehicle
            vehicle = Vehicle.objects.create(
                brand=brand,
                model=model,
                color=cor[:50],
                contract=contract,
                renter=renter,
                unit=unit,
                base=base,
                status=status_ativo,
                armored=blindado,
                custody_info=acautelamento,
                created_by=user
            )
            
            # Set plate
            from django.utils import timezone
            VehiclePlate.objects.create(
                vehicle=vehicle,
                plate=placa[:8],
                kind='CURRENT',
                starts_on=timezone.now(),
                changed_by=user
            )
            
            placa_reservada = str(row.get('Placa reservada')).strip()
            if placa_reservada and placa_reservada.lower() not in ['nan', 'xxx', '']:
                VehiclePlate.objects.create(
                    vehicle=vehicle,
                    plate=placa_reservada[:8],
                    kind='RESERVED',
                    starts_on=timezone.now(),
                    changed_by=user
                )
            
            count += 1
                
        self.stdout.write(self.style.SUCCESS(f"Import completed successfully! {count} vehicles loaded."))