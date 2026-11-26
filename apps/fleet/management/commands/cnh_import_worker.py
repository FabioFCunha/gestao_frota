import os
import json
import signal
import subprocess
import sys
import time
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import close_old_connections
from apps.fleet.cnh_jobs import claim_next, fail


class Command(BaseCommand):
    help = 'Processa a fila de CNHs em subprocessos com limite de tempo.'
    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
    def handle(self, *args, **options):
        while True:
            close_old_connections()
            job = claim_next()
            if job:
                process = subprocess.Popen([sys.executable, str(Path(settings.BASE_DIR)/'manage.py'),
                    'process_cnh_import', '--job', str(job.pk)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                try:
                    code = process.wait(timeout=100)
                    if code:
                        fail(job.pk, 'O processador foi interrompido. Tente novamente.')
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    fail(job.pk, 'A leitura excedeu o tempo permitido. Tente novamente ou envie uma cópia mais nítida.')
                job.refresh_from_db()
                self.stdout.write(json.dumps({'job':str(job.pk), 'state':job.state,
                    'duration_ms':job.duration_ms, 'attempts':job.attempts}))
                self.stdout.flush()
            if options['once']:
                return
            if not job:
                time.sleep(2)
