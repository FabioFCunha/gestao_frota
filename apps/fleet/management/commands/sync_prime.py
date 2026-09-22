import requests
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import get_user_model
from apps.fleet.models import VehiclePlate, VehicleMileage
import time

class Command(BaseCommand):
    help = "Sincroniza quilometragem via API Prime Benefícios (Sisatec)"

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=1, help='Dias para retroagir (padrão: 1)')
        parser.add_argument('--codigo', type=str, default='9225', help='Código do cliente')
        parser.add_argument('--key', type=str, default='3CD2824D5314FFD73F4231C9CB1AFC3E3E5D52C2', help='Chave de API')

    def handle(self, *args, **options):
        codigo = options['codigo']
        key = options['key']
        days = options['days']
        
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        d_inicio = start_date.strftime('%m-%d-%Y')
        d_fim = end_date.strftime('%m-%d-%Y')
        
        self.stdout.write(f"Iniciando sincronização Prime ({d_inicio} a {d_fim})...")
        
        User = get_user_model()
        system_user = User.objects.filter(is_superuser=True).first()
        
        pagina = 1
        has_more = True
        total_created = 0
        total_errors = 0
        
        while has_more:
            url = f"https://ws.sisatec.com.br/api/abastecimento/byData/{codigo}/{key}/{d_inicio}/{d_fim}/{pagina}"
            self.stdout.write(f"Buscando página {pagina}...")
            
            try:
                response = requests.get(url, timeout=15)
                
                if response.status_code == 401:
                    self.stdout.write(self.style.ERROR(f"Erro 401: {response.text} (Verifique se o token é válido ou se há bloqueio de IP)"))
                    break
                    
                response.raise_for_status()
                data = response.json()
                
                # If API returns a dict with a list, or just a list
                items = data.get('abastecimentos', data) if isinstance(data, dict) else data
                
                if not items:
                    break
                    
                for item in items:
                    placa = str(item.get('placa', '')).strip().upper()
                    km_raw = item.get('quilometragem', item.get('km', 0))
                    data_abastecimento_raw = item.get('dataHora', item.get('data', ''))
                    
                    try:
                        km = int(float(km_raw))
                    except (ValueError, TypeError):
                        continue
                        
                    if not placa or km <= 0:
                        continue
                        
                    # Find vehicle
                    plate_record = VehiclePlate.objects.filter(plate__iexact=placa).select_related('vehicle').first()
                    if not plate_record:
                        continue
                        
                    vehicle = plate_record.vehicle
                    
                    # Avoid duplicate KM logs
                    latest_km = VehicleMileage.objects.filter(vehicle=vehicle).order_by('-date').first()
                    if latest_km and latest_km.mileage >= km:
                        # Already have this or higher KM recorded
                        continue
                        
                    # Create new mileage record
                    VehicleMileage.objects.create(
                        vehicle=vehicle,
                        mileage=km,
                        date=timezone.now(),  # Ideally parse data_abastecimento_raw
                        origin='INTEGRACAO',
                        recorded_by=system_user,
                        notes=f"Abastecimento Prime: ID {item.get('id', item.get('nsu', ''))}"
                    )
                    total_created += 1
                
                # Check pagination (assuming items < limit means end, usually limit is 50 or 100)
                if len(items) < 50:
                    has_more = False
                else:
                    pagina += 1
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Erro ao acessar API: {str(e)}"))
                total_errors += 1
                break
                
            time.sleep(1) # rate limit prevention

        self.stdout.write(self.style.SUCCESS('=' * 50))
        self.stdout.write(self.style.SUCCESS(f'SINCRONIZAÇÃO CONCLUÍDA'))
        self.stdout.write(f'Registros de KM criados: {total_created}')
        if total_errors > 0:
            self.stdout.write(self.style.WARNING(f'Erros de conexão: {total_errors}'))
        self.stdout.write(self.style.SUCCESS('=' * 50))