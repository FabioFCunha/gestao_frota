from django.core.management.base import BaseCommand
from apps.fleet.cnh_jobs import process


class Command(BaseCommand):
    help = 'Processa uma CNH já reservada pelo worker.'
    def add_arguments(self, parser):
        parser.add_argument('--job', required=True)
    def handle(self, *args, **options):
        process(options['job'])
