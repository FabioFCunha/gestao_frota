from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.db import transaction
from apps.fleet.models import CNHImportJob
from apps.fleet.tenant_scope import current_scope


class Command(BaseCommand):
    help = 'Remove cópias temporárias concluídas com mais de 7 dias; mantém documentos confirmados e auditoria. Simula sem --apply.'
    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
    def handle(self, *args, **options):
        if current_scope() is not None:
            raise CommandError('Execute offline.')
        jobs = CNHImportJob.objects.filter(state__in=['ready','confirmed','failed'],
            finished_at__lt=timezone.now()-timedelta(days=7)).exclude(file='')
        identifiers = list(jobs.values_list('pk', flat=True))
        count = len(identifiers)
        if options['apply']:
            for pk in identifiers:
                with transaction.atomic():
                    job = jobs.select_for_update().filter(pk=pk).first()
                    if job:
                        job.file.delete(save=False)
                        CNHImportJob.objects.filter(pk=job.pk).update(file='', photo=None)
        self.stdout.write(f'Cópias temporárias: {count}. ' + ('Remoção aplicada.' if options['apply'] else 'Somente simulação.'))
