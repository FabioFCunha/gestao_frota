import tempfile
from datetime import timedelta
from io import BytesIO, StringIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfWriter
from apps.fleet.models import Driver, Sector, AuditLog, Document, DocumentRelation, CNHImportJob
from apps.fleet.cnh_review import quality_issues, validate_review_values
from apps.ui.cnh_safety import correct_identity

DATA = {'name':'MOTORISTA DE TESTE', 'cpf':'123.456.789-09','cnh_number':'01234567890',
    'birth_date':'1985-02-01','cnh_category':'AB','cnh_expiration':'2030-12-31',
    'cnh_issue_date':'2025-06-05','cnh_first_issue_date':'2005-03-12',
    'mother_name':'MARIA DO MOTORISTA','father_name':'JOSE DO MOTORISTA','text_extraction_succeeded':True}


def upload():
    writer=PdfWriter();writer.add_blank_page(width=300,height=400)
    output=BytesIO();writer.write(output)
    return SimpleUploadedFile('cnh.pdf',output.getvalue(),content_type='application/pdf')


class QualityTests(SimpleTestCase):
    def test_incomplete_and_invalid_reading_is_not_presented_as_complete(self):
        issues=quality_issues({'cpf':'111.111.111-11','cnh_number':'123','birth_date':'2999-01-01'})
        self.assertIn('cpf',issues);self.assertIn('name',issues);self.assertIn('cnh_number',issues);self.assertIn('birth_date',issues)
    def test_dates_and_category_are_checked(self):
        with self.assertRaises(ValueError):validate_review_values({**DATA,'cnh_issue_date':'2031-01-01'})
        with self.assertRaises(ValueError):validate_review_values({**DATA,'cnh_first_issue_date':'1980-01-01'})
        with self.assertRaises(ValueError):validate_review_values({**DATA,'cnh_category':'Z'})
        validate_review_values(DATA)


    def test_expired_license_is_a_warning_not_a_barrier_to_historical_registration(self):
        values={**DATA,'cnh_expiration':'2025-12-31'}
        self.assertIn('cnh_expiration',quality_issues(values))
        validate_review_values(values)


class SafetyTests(TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        override=override_settings(MEDIA_ROOT=self.directory.name, CNH_BACKGROUND_IMPORTS=False)
        override.enable();self.addCleanup(override.disable);self.addCleanup(self.directory.cleanup)
        self.user=get_user_model().objects.create_user(username='cnh-safety')
        self.user.user_permissions.add(*Permission.objects.filter(codename__in=['add_driver','change_driver','correct_driver_identity']))
        self.sector,_=Sector.objects.get_or_create(slug='adm',defaults={'name':'ADM'})
        self.user.sectors.add(self.sector)
        self.driver=Driver.objects.create(name=DATA['name'],cpf='123.456.789-00',cnh_number=DATA['cnh_number'])
        self.driver.sectors.add(self.sector);self.client.force_login(self.user)
        self.url=reverse('driver_cnh',args=[self.driver.pk])+'?sector=adm'
    def stage(self,data=None):
        from apps.fleet.services import stage_cnh_document_for_creation
        with patch('apps.fleet.cnh.extract_cnh_data',return_value=data or DATA):
            return stage_cnh_document_for_creation(file_obj=upload(),user=self.user)[0]
    def correction(self,doc,**changes):
        values=dict(driver=self.driver,document_id=doc.pk,expected_cpf=self.driver.cpf,
            cpf=DATA['cpf'],reason='Correção conferida no PDF original.',user=self.user)
        values.update(changes);return correct_identity(**values)
    def test_controlled_identity_correction_keeps_pk_and_logs_old_and_new(self):
        doc=self.stage();pk=self.driver.pk;self.correction(doc)
        self.driver.refresh_from_db();self.assertEqual(self.driver.pk,pk);self.assertEqual(self.driver.cpf,DATA['cpf'])
        audit=AuditLog.objects.get(action='CORREÇÃO CPF COM DOCUMENTO')
        self.assertEqual(audit.old_values['cpf'],'123.456.789-00');self.assertEqual(audit.user,self.user)
        self.assertTrue(DocumentRelation.objects.filter(document=doc,object_id=pk).exists())
        with self.assertRaises(ValueError):self.correction(doc)
    def test_correction_denies_unprivileged_actor_wrong_person_and_stale_form(self):
        doc=self.stage();other=get_user_model().objects.create_user(username='operator-cnh')
        with self.assertRaises(PermissionDenied):self.correction(doc,user=other)
        with self.assertRaises(ValueError):self.correction(doc,expected_cpf='00000000000')
        doc2=self.stage({**DATA,'name':'OUTRA PESSOA'})
        with self.assertRaises(ValueError):self.correction(doc2)
        self.driver.refresh_from_db();self.assertEqual(self.driver.cpf,'123.456.789-00')
    def test_duplicate_cpf_rolls_back_correction(self):
        Driver.objects.create(name='OUTRO CADASTRO',cpf=DATA['cpf'])
        doc=self.stage()
        with self.assertRaises(IntegrityError):self.correction(doc)
        self.driver.refresh_from_db();self.assertEqual(self.driver.cpf,'123.456.789-00')
        self.assertFalse(DocumentRelation.objects.exists());self.assertFalse(AuditLog.objects.filter(action='CORREÇÃO CPF COM DOCUMENTO').exists())
    def test_pdf_preview_is_private_and_only_uploader_can_read(self):
        doc=self.stage();url=reverse('cnh_original',args=[doc.pk])
        response=self.client.get(url);self.assertEqual(response.status_code,200)
        self.assertEqual(response['X-Frame-Options'],'SAMEORIGIN');self.assertIn('no-store',response['Cache-Control']);response.close()
        other=get_user_model().objects.create_user(username='other-cnh')
        other.user_permissions.add(Permission.objects.get(codename='add_driver'));self.client.force_login(other)
        self.assertEqual(self.client.get(url).status_code,404)
    def test_review_shows_pdf_existing_values_and_read_warnings(self):
        # Mesmo o CPF inválido no PDF pode ser exibido como suspeito; confirmar é bloqueado.
        with patch('apps.fleet.cnh.extract_cnh_data',return_value={**DATA,'cpf':self.driver.cpf,'cnh_category':''}):
            response=self.client.post(self.url,{'step':'upload','file':upload()})
        self.assertEqual(response.status_code,200);self.assertContains(response,'Cadastro atual');self.assertContains(response,'<iframe')
        self.assertContains(response,'Leitura incompleta');self.assertContains(response,'dígitos verificadores inválidos')
        self.assertContains(response,'Corrigir CPF cadastrado')
    def test_async_queue_finishes_before_human_confirmation_and_rejects_duplicate_enqueues(self):
        from apps.fleet.cnh_jobs import enqueue,claim_next,process
        with override_settings(CNH_BACKGROUND_IMPORTS=True):
            response=self.client.post(reverse('driver_create'),{'step':'upload','file':upload()})
        self.assertEqual(response.status_code,302);job=CNHImportJob.objects.get();self.assertFalse(Document.objects.exists())
        self.assertEqual(enqueue(file_obj=upload(),user=self.user).pk,job.pk)
        self.assertEqual(claim_next().pk,job.pk)
        with patch('apps.fleet.cnh.extract_cnh_data',return_value=DATA):process(job.pk)
        job.refresh_from_db();self.assertEqual(job.state,'ready');self.assertIsNotNone(job.duration_ms)
        self.assertEqual(job.document.versions.get().original_filename,'cnh.pdf')
        self.assertFalse(DocumentRelation.objects.exists());self.assertEqual(Driver.objects.count(),1)
        self.assertEqual(self.client.get(reverse('cnh_import_status',args=[job.pk])).status_code,302)
        response=self.client.get(reverse('driver_create')+'?import='+str(job.pk))
        self.assertEqual(response.status_code,200);self.assertContains(response,'<iframe')
        self.assertEqual(self.client.get(reverse('driver_create')+'?import=not-a-uuid').status_code,404)
    def test_failed_job_can_retry_and_revoked_permission_prevents_processing(self):
        from apps.fleet.cnh_jobs import enqueue,claim_next,process,retry
        job=enqueue(file_obj=upload(),user=self.user);claim_next()
        with patch('apps.fleet.cnh.extract_cnh_data',side_effect=RuntimeError('sensitive exception content')):process(job.pk)
        job.refresh_from_db();self.assertEqual(job.state,'failed');self.assertNotIn('sensitive',job.error)
        retry(job);claim_next();self.user.user_permissions.clear()
        process(job.pk);job.refresh_from_db();self.assertEqual(job.state,'failed');self.assertFalse(Document.objects.exists())
    def test_stale_worker_is_recoverable_and_status_is_private(self):
        from apps.fleet.cnh_jobs import enqueue,claim_next
        job=enqueue(file_obj=upload(),user=self.user);claim_next()
        CNHImportJob.objects.filter(pk=job.pk).update(started_at=timezone.now()-timedelta(minutes=6))
        self.assertIsNone(claim_next());job.refresh_from_db();self.assertEqual(job.state,'failed')
        other=get_user_model().objects.create_user(username='other-job')
        self.client.force_login(other);self.assertEqual(self.client.get(reverse('cnh_import_status',args=[job.pk])).status_code,404)

    def test_photo_cache_avoids_ocr_and_temporary_cleanup_keeps_original_document(self):
        from django.core.management import call_command
        from apps.fleet.cnh_jobs import enqueue
        from apps.ui.cnh_photo import document_photo
        doc=self.stage();job=enqueue(file_obj=upload(),user=self.user)
        job.document=doc;job.state='ready';job.photo=b'cached-private-photo';job.save()
        with patch('apps.ui.cnh_photo.extract_cnh_photo',side_effect=RuntimeError('must not run')):
            self.assertEqual(document_photo(doc),b'cached-private-photo')
        job.state='confirmed';job.finished_at=timezone.now()-timedelta(days=8);job.save()
        with patch('apps.ui.cnh_photo.extract_cnh_photo',side_effect=RuntimeError('must not run')):
            self.assertEqual(document_photo(doc),b'cached-private-photo')
        original=doc.versions.get().file
        call_command('cleanup_cnh_imports',stdout=StringIO())
        job.refresh_from_db();self.assertTrue(job.file)
        call_command('cleanup_cnh_imports',apply=True,stdout=StringIO())
        job.refresh_from_db();self.assertFalse(job.file);self.assertTrue(original.storage.exists(original.name))
        self.assertTrue(Document.objects.filter(pk=doc.pk).exists())

    def test_source_version_and_bytes_must_match_the_reviewed_document(self):
        from apps.fleet.models import DocumentVersion
        from apps.fleet.services import cnh_confirmation_source
        doc=self.stage();version=doc.versions.get()
        with version.file.open('wb') as source:
            source.write(b'changed after extraction')
        with self.assertRaisesMessage(ValueError,'PDF foi alterado'):
            cnh_confirmation_source(document_id=doc.pk,user=self.user)
        doc2=self.stage()
        DocumentVersion.objects.create(document=doc2,file=upload(),original_filename='new.pdf',
            file_extension='pdf',file_size=100,uploaded_by=self.user)
        with self.assertRaisesMessage(ValueError,'versão do PDF mudou'):
            cnh_confirmation_source(document_id=doc2.pk,user=self.user)
        doc3=self.stage();doc3.active=False;doc3.save()
        with self.assertRaisesMessage(ValueError,'inativo ou arquivado'):
            cnh_confirmation_source(document_id=doc3.pk,user=self.user)
