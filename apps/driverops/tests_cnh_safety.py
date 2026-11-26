import tempfile
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from apps.driverops.models import Company, Member, RecordOwner
from apps.fleet.models import Driver, CNHImportJob, AuditLog
from apps.fleet.tenant_scope import Scope,set_scope,reset_scope
from apps.fleet.test_cnh_safety import DATA,upload
from apps.fleet.cnh_jobs import enqueue,claim_next,process


@override_settings(CENTRAL_USER_MANAGEMENT=True, ROOT_URLCONF='config.driver_urls', CNH_BACKGROUND_IMPORTS=True)
class CompanyCNHSafetyTests(TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();override=override_settings(MEDIA_ROOT=self.directory.name)
        override.enable();self.addCleanup(override.disable);self.addCleanup(self.directory.cleanup)
        self.company=Company.objects.create(name='Empresa CNH');self.other=Company.objects.create(name='Outra CNH')
        self.manager=get_user_model().objects.create_user(username='gestor-cnh')
        Member.objects.create(user=self.manager,company=self.company,role=Member.MANAGER)
        self.operator=get_user_model().objects.create_user(username='operador-cnh')
        Member.objects.create(user=self.operator,company=self.company,role=Member.OPERATOR)
        token=set_scope(Scope(company_id=self.company.pk,actor_id=self.manager.pk))
        try:
            self.driver=Driver.objects.create(name=DATA['name'],cpf='123.456.789-00',cnh_number=DATA['cnh_number'])
        finally:reset_scope(token)
    def queue(self,user=None):
        user=user or self.manager
        token=set_scope(Scope(company_id=self.company.pk,actor_id=user.pk))
        try:return enqueue(file_obj=upload(),user=user)
        finally:reset_scope(token)
    def test_worker_owns_outputs_in_original_company_and_returns_to_review(self):
        job=self.queue();claim_next()
        with patch('apps.fleet.cnh.extract_cnh_data',return_value=DATA):process(job.pk)
        job.refresh_from_db();self.assertEqual(job.state,'ready')
        for model,pk in [('fleet.cnhimportjob',job.pk),('fleet.document',job.document_id)]:
            self.assertTrue(RecordOwner.objects.filter(model_label=model,object_id=pk,company=self.company).exists())
        self.client.force_login(self.manager)
        response=self.client.get(reverse('driver_create')+'?import='+str(job.pk));self.assertEqual(response.status_code,200)
        self.assertContains(response,'Abrir documento original')
        outsider=get_user_model().objects.create_user(username='fora-cnh')
        Member.objects.create(user=outsider,company=self.other,role=Member.MANAGER)
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(reverse('cnh_import_status',args=[job.pk])).status_code,404)
        self.assertEqual(self.client.get(reverse('cnh_original',args=[job.document_id])).status_code,404)
        self.assertNotContains(self.client.get(reverse('cnh_import_monitor')),self.manager.username)
    def test_operator_can_import_but_cannot_correct_identity_or_view_monitor(self):
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse('driver_identity_correction',args=[self.driver.pk])).status_code,403)
        self.assertEqual(self.client.get(reverse('cnh_import_monitor')).status_code,403)
        self.assertEqual(self.client.post(reverse('driver_create'),{'step':'upload','file':upload()}).status_code,302)
    def test_company_revocation_stops_pending_import(self):
        job=self.queue();claim_next();Member.objects.filter(user=self.manager).update(active=False)
        process(job.pk);job.refresh_from_db();self.assertEqual(job.state,'failed');self.assertIsNone(job.document_id)
    def test_manager_correction_audit_is_company_owned(self):
        self.client.force_login(self.manager)
        url=reverse('driver_identity_correction',args=[self.driver.pk])
        with patch('apps.fleet.cnh.extract_cnh_data',return_value=DATA):
            response=self.client.post(url,{'step':'upload','file':upload()})
        self.assertEqual(response.status_code,200);document=response.context['document']
        response=self.client.post(url,{'document_id':str(document.pk),'expected_cpf':self.driver.cpf,
            'cpf':DATA['cpf'],'cpf_again':DATA['cpf'],'reason':'Correção conferida no documento original.','confirmed':'on'})
        self.assertEqual(response.status_code,302)
        audit=AuditLog.objects.get(action='CORREÇÃO CPF COM DOCUMENTO')
        self.assertTrue(RecordOwner.objects.filter(model_label='fleet.auditlog',object_id=audit.pk,company=self.company).exists())
        self.driver.refresh_from_db();self.assertEqual(self.driver.cpf,DATA['cpf'])
    def test_confirmation_checkbox_is_required_in_company_mode(self):
        from apps.ui.forms import CNHDriverCreateForm
        with override_settings(CNH_REQUIRE_REVIEW_CONFIRMATION=True):
            form=CNHDriverCreateForm()
            self.assertTrue(form.fields['identity_confirmed'].required)
