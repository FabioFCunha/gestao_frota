"""Explicit, transactional adoption of legacy fleet records. Dry-run by default."""
from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = 'Simula a associação dos registros legados sem empresa; --apply confirma a adoção.'

    def add_arguments(self, parser):
        parser.add_argument('--company', required=True)
        parser.add_argument('--adopt-all-unowned', action='store_true')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        if not getattr(settings, 'CENTRAL_USER_MANAGEMENT', False):
            raise CommandError('Use config.company_settings no banco principal, nunca no banco isolado do piloto.')
        if not options['adopt_all_unowned']:
            raise CommandError('Confirme explicitamente --adopt-all-unowned após revisar a origem dos dados.')
        from apps.driverops.models import Company, CompanyVehicle, RecordOwner
        from apps.driverops.ownership import bind_graph
        from apps.fleet.tenant_scope import GLOBAL, CATALOG, TenantModel
        from apps.fleet.models import Vehicle
        company = Company.objects.get(pk=options['company'], active=True)
        with transaction.atomic():
            Company.objects.select_for_update().get(pk=company.pk)
            for model in apps.get_app_config('fleet').get_models():
                label = model._meta.label_lower
                if not issubclass(model, TenantModel) or label in GLOBAL | CATALOG:
                    continue
                claimed = RecordOwner.objects.filter(model_label=label).values('object_id')
                queryset = model.objects.exclude(pk__in=claimed)
                if model._meta.model_name == 'auditlog':
                    queryset = queryset.exclude(entity_type='company_setup')
                count = queryset.count()
                for pk in list(queryset.values_list('pk', flat=True)):
                    bind_graph(model, pk, company.pk)
                if count:
                    self.stdout.write(f'{label}: {count}')
            for vehicle in Vehicle.objects.filter(pk__in=RecordOwner.objects.filter(company=company, model_label='fleet.vehicle').values('object_id')):
                plate = vehicle.plate_history.filter(kind='CURRENT', ends_on=None).values_list('plate', flat=True).first()
                CompanyVehicle.objects.get_or_create(company=company, vehicle=vehicle, defaults={'label': plate or 'Veículo cadastrado'})
            if not options['apply']:
                transaction.set_rollback(True)
        self.stdout.write('Adoção aplicada.' if options['apply'] else 'Simulação concluída; nenhuma associação foi mantida. Use --apply somente após revisão.')
