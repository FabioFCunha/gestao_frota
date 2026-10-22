"""Read-only availability report; never prints customer keys or CDN URLs."""
import json
from django.core.management.base import BaseCommand
from apps.fleet.vehicle_images import normalize_vehicle, probe_image


class Command(BaseCommand):
    help = 'Consulta metadados IMAGIN e lista fallbacks; não altera veículos nem baixa imagens.'

    def add_arguments(self, parser):
        parser.add_argument('--samples', action='store_true', help='Testa Corolla, Onix e BYD King sem consultar o banco.')
        parser.add_argument('--company', help='UUID da empresa; obrigatório sem --samples.')

    def handle(self, *args, **options):
        from django.core.management.base import CommandError
        if options['samples']:
            for brand, model in [('Toyota', 'Corolla'), ('CHEV', 'ONIX 10MT LT2'), ('BYD', 'King')]:
                self.stdout.write(json.dumps({'marca':brand, 'modelo':model,
                    'normalizado':normalize_vehicle(brand,model), 'resultado':probe_image(brand,model)}, ensure_ascii=False))
            return
        if not options['company']:
            raise CommandError('Informe --company UUID para consultar somente a empresa desejada, ou --samples.')
        import uuid
        from apps.driverops.models import Company
        from apps.fleet.models import Vehicle, VehiclePlate
        from apps.fleet.tenant_scope import Scope, set_scope, reset_scope
        try:
            company = Company.objects.get(pk=uuid.UUID(options['company']))
        except (ValueError, Company.DoesNotExist) as exc:
            raise CommandError('Empresa não encontrada.') from exc
        token = set_scope(Scope(company_id=company.pk))
        cache = {}
        total = 0
        try:
            for vehicle in Vehicle.objects.filter(active=True).select_related('brand','model').prefetch_related('plate_history'):
                plate = next((p.plate for p in vehicle.plate_history.all() if p.kind == VehiclePlate.CURRENT and p.ends_on is None), None)
                if not plate:  # Same set displayed on the dashboard.
                    continue
                make = vehicle.brand.name if vehicle.brand else ''
                model = vehicle.model.name if vehicle.model else ''
                key = normalize_vehicle(make,model,vehicle.model_year)
                if key not in cache:
                    cache[key] = probe_image(make,model,vehicle.model_year)
                result = cache[key]
                if result != 'image':
                    total += 1
                    self.stdout.write(json.dumps({'id':str(vehicle.pk),'placa':plate,'marca':make,
                        'modelo':model,'ano':vehicle.model_year,'motivo':result}, ensure_ascii=False))
            self.stdout.write(f'Total com fallback: {total}')
        finally:
            reset_scope(token)
