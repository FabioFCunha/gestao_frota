"""Associate one reviewed legacy sector, preserving active and historical records."""
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q


class Command(BaseCommand):
    help = 'Simula a adoção de um setor; --company UUID --apply confirma após revisão.'

    def add_arguments(self, parser):
        parser.add_argument('--sector', required=True, choices=['adm', 'lei-seca'])
        parser.add_argument('--company')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        if not getattr(settings, 'CENTRAL_USER_MANAGEMENT', False):
            raise CommandError('Use config.company_settings no banco principal.')
        if options['apply'] and not options['company']:
            raise CommandError('--apply exige --company UUID da empresa revisada.')
        from apps.driverops.models import Company, CompanyVehicle, RecordOwner
        from apps.driverops.ownership import bind_graph
        from apps.fleet.models import Vehicle, Driver, BDT, AuditLog
        from apps.fleet.tenant_scope import current_scope
        if current_scope() is not None:
            raise CommandError('Execute offline, sem escopo de usuário.')
        slug = options['sector']
        management = {'adm': 125, 'lei-seca': 49}[slug]
        vehicles = Vehicle.objects.filter(sector__slug=slug)
        drivers = Driver.objects.filter(sectors__slug=slug).distinct()
        vehicle_ids = set(vehicles.values_list('pk', flat=True))
        driver_ids = set(drivers.values_list('pk', flat=True))
        if not vehicle_ids and not driver_ids:
            raise CommandError('Setor sem veículos e motoristas; nenhuma adoção executada.')

        def guard(obj, seen):
            label = obj._meta.model_name
            if label == 'vehicle' and obj.pk not in vehicle_ids:
                raise CommandError(f'Veículo fora do setor: {obj.pk}. Reconcilie o vínculo antes de aplicar.')
            if label == 'driver' and obj.pk not in driver_ids:
                raise CommandError(f'Motorista sem vínculo com o setor: {obj.pk}.')
            if label == 'bdt' and obj.horus_management_id != management:
                raise CommandError(f'BDT {obj.pk} com origem {obj.horus_management_id}, diferente de {management}.')
            if label in {'documentrelation', 'seiprocessrelation'}:
                target = obj.content_type.model_class()
                key = (target._meta.label_lower, obj.object_id) if target else None
                eligible = (
                    target is Vehicle and obj.object_id in vehicle_ids
                    or target is Driver and obj.object_id in driver_ids
                )
                if not eligible and key not in seen:
                    raise CommandError(f'Documento/processo compartilhado com outro cadastro: {obj.pk}.')

        with transaction.atomic():
            if options['company']:
                company = Company.objects.select_for_update().get(pk=options['company'], active=True)
            else:
                # This temporary company is ALWAYS rolled back with the default simulation.
                company = Company.objects.create(name=f'Simulação do setor {slug}')
            before = set(RecordOwner.objects.filter(company=company).values_list('model_label', 'object_id'))
            seen = set()
            for pk in sorted(vehicle_ids, key=str):
                bind_graph(Vehicle, pk, company.pk, seen, guard=guard)
            for pk in sorted(driver_ids, key=str):
                bind_graph(Driver, pk, company.pk, seen, guard=guard)
            # Vehicle-less imported BDTs are admitted only by explicit source AND driver.
            for pk in BDT.objects.filter(horus_management_id=management).filter(
                Q(vehicle_id__in=vehicle_ids) | Q(vehicle=None, driver_id__in=driver_ids)
            ).values_list('pk', flat=True):
                bind_graph(BDT, pk, company.pk, seen, guard=guard)
            # UUIDs are global identifiers; attach only audits for records in the reviewed graph.
            for pk in AuditLog.objects.filter(entity_id__in={pk for _, pk in seen}).exclude(
                entity_type='company_setup'
            ).values_list('pk', flat=True):
                bind_graph(AuditLog, pk, company.pk, seen, guard=guard)
            for vehicle in vehicles:
                plate = vehicle.plate_history.filter(kind='CURRENT', ends_on=None).values_list('plate', flat=True).first()
                link, _ = CompanyVehicle.objects.get_or_create(company=company, vehicle=vehicle,
                    defaults={'label': plate or 'Veículo cadastrado', 'active': vehicle.active})
                if link.active != vehicle.active:
                    link.active = vehicle.active
                    link.save(update_fields=['active'])
            after = set(RecordOwner.objects.filter(company=company).values_list('model_label', 'object_id'))
            for label, count in sorted(Counter(label for label, _ in after - before).items()):
                self.stdout.write(f'{label}: {count} novas associações')
            self.stdout.write(f'Veículos ativos: {vehicles.filter(active=True).count()}')
            self.stdout.write(f'Veículos inativos: {vehicles.filter(active=False).count()}')
            self.stdout.write(f'Motoristas do setor: {len(driver_ids)}')
            if not options['apply']:
                transaction.set_rollback(True)
        self.stdout.write('Adoção aplicada.' if options['apply'] else 'Simulação concluída; nenhum dado alterado.')
