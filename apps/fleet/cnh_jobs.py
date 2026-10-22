"""Fila durável de leitura de CNH; confirmação humana permanece separada."""
import hashlib
import logging
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .models import CNHImportJob, AuditLog, Driver
from .tenant_scope import Scope, current_scope, set_scope, reset_scope

logger = logging.getLogger(__name__)


@transaction.atomic
def enqueue(*, file_obj, user, driver=None, sector=''):
    from .pdf_validation import identification_pdf_reader
    permission = 'fleet.change_driver' if driver else 'fleet.add_driver'
    if not user.has_perm(permission):
        raise PermissionDenied
    if not file_obj.name.lower().endswith('.pdf'):
        raise ValueError('Envie a CNH em PDF.')
    if file_obj.size > getattr(settings, 'DOCUMENT_MAX_UPLOAD_SIZE', 10 * 1024 * 1024):
        raise ValueError('O arquivo excede o limite permitido.')
    file_obj.seek(0)
    raw = file_obj.read()
    identification_pdf_reader(raw)
    file_obj.seek(0)
    # Serializa reenvios do mesmo usuário sem manter a transação durante OCR.
    get_user_model().objects.select_for_update().get(pk=user.pk)
    scope = current_scope()
    company = scope.company_id if scope else None
    sha = hashlib.sha256(raw).hexdigest()
    previous = CNHImportJob.objects.filter(created_by=user, driver=driver, company_uuid=company,
        sha256=sha, state__in=['pending','running']).order_by('-created_at').first()
    if previous:
        return previous
    if CNHImportJob.objects.filter(created_by=user, state__in=['pending','running']).count() >= 5:
        raise ValueError('Há cinco PDFs em processamento para seu usuário. Aguarde a conclusão antes de enviar mais arquivos.')
    return CNHImportJob.objects.create(created_by=user, driver=driver, company_uuid=company,
        sector=sector if sector in ('adm','lei-seca') else '', file=file_obj, sha256=sha, original_filename=file_obj.name)


@transaction.atomic
def claim_next():
    from django.db import connection
    if current_scope() is not None:
        raise PermissionDenied('O processador deve executar offline.')
    # Uma interrupção do processo não deixa a tela aguardando indefinidamente.
    CNHImportJob.objects.filter(state='running', started_at__lt=timezone.now()-timedelta(minutes=5)).update(
        state='failed', error='A leitura foi interrompida. Tente novamente.', finished_at=timezone.now())
    jobs = CNHImportJob.objects.filter(state='pending').order_by('created_at')
    jobs = jobs.select_for_update(skip_locked=True) if connection.features.has_select_for_update_skip_locked else jobs.select_for_update()
    job = jobs.first()
    if job:
        job.state = 'running'
        job.started_at = timezone.now()
        job.finished_at = None
        job.attempts += 1
        job.save(update_fields=['state','started_at','finished_at','attempts','updated_at'])
    return job


def fail(job_id, message):
    now = timezone.now()
    running = CNHImportJob.objects.filter(pk=job_id, state='running').values('started_at').first()
    if running:
        elapsed = round((now-running['started_at']).total_seconds()*1000) if running['started_at'] else None
        CNHImportJob.objects.filter(pk=job_id, state='running').update(
            state='failed', error=message[:500], finished_at=now, duration_ms=elapsed)


def process(job_id):
    if current_scope() is not None:
        raise PermissionDenied('O processador deve executar offline.')
    job = CNHImportJob.objects.select_related('created_by').get(pk=job_id, state='running')
    token = set_scope(Scope(company_id=job.company_uuid, actor_id=job.created_by_id)) if job.company_uuid else None
    start = time.monotonic()
    try:
        user = job.created_by
        if not user.is_active:
            raise ValueError('O usuário não está mais ativo.')
        if job.company_uuid:
            from apps.driverops.models import Member
            if not Member.objects.filter(user=user, company_id=job.company_uuid, company__active=True,
                active=True, role__in=Member.DESKTOP_ROLES).exists():
                raise ValueError('O acesso à empresa foi alterado; envie o documento novamente após regularizar o acesso.')
        permission = 'fleet.change_driver' if job.driver_id else 'fleet.add_driver'
        if not user.has_perm(permission):
            raise ValueError('Seu acesso à importação foi alterado.')
        driver = None
        if job.driver_id:
            from .driver_scope import apply_driver_sector_scope
            driver = apply_driver_sector_scope(Driver.objects.all(), user, job.sector).get(pk=job.driver_id)
        from .services import stage_cnh_document_for_creation
        with transaction.atomic(), job.file.open('rb') as file:
            from django.core.files.base import File
            wrapped = File(file, name=job.original_filename or job.file.name.rsplit('/', 1)[-1])
            document, _ = stage_cnh_document_for_creation(file_obj=wrapped, user=user, driver=driver)
            locked = CNHImportJob.objects.select_for_update().get(pk=job.pk, state='running')
            from apps.ui.cnh_photo import extract_cnh_photo
            file.seek(0)
            locked.photo = extract_cnh_photo(file.read()) or b''
            locked.document = document
            locked.state = 'ready'
            locked.error = ''
            locked.duration_ms = round((time.monotonic()-start)*1000)
            locked.finished_at = timezone.now()
            locked.save(update_fields=['document','photo','state','error','duration_ms','finished_at','updated_at'])
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else 'Não foi possível ler o documento. Tente novamente ou envie outra cópia.'
        fail(job.pk, message)
        CNHImportJob.objects.filter(pk=job.pk).update(duration_ms=round((time.monotonic()-start)*1000))
        logger.warning('cnh_import_failed job=%s error_type=%s', job.pk, type(exc).__name__)
    finally:
        if token is not None:
            reset_scope(token)


def retry(job):
    with transaction.atomic():
        locked = CNHImportJob.objects.select_for_update().get(pk=job.pk)
        if locked.state != 'failed':
            raise ValueError('Apenas leituras com falha podem ser repetidas.')
        if not locked.file:
            raise ValueError('O arquivo temporário expirou. Envie o PDF novamente.')
        if locked.attempts >= 3:
            raise ValueError('Foram feitas três tentativas. Envie outra cópia do PDF.')
        locked.state = 'pending'
        locked.error = ''
        locked.started_at = locked.finished_at = None
        locked.save(update_fields=['state','error','started_at','finished_at','updated_at'])
