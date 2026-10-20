"""Integration coverage of the existing fleet UI/API under company isolation."""
import importlib
import tempfile
from contextlib import contextmanager
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Count, Subquery
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from apps.fleet.models import (Vehicle, VehicleStatus, VehiclePlate, Driver, Document,
    DocumentType, DocumentStatus, DocumentVersion, DocumentRelation, Renter, Contract, AuditLog)
from apps.fleet.tenant_scope import Scope, set_scope, reset_scope, current_scope
from apps.ui.forms import DriverForm, CRLVVehicleCreateForm, VehiclePositionForm
from .models import Company, Member, CompanyVehicle, RecordOwner
from .management_forms import MemberForm


@contextmanager
def scope(company, actor):
    token = set_scope(Scope(company_id=company.pk, actor_id=actor.pk))
    try:
        yield
    finally:
        reset_scope(token)


class TenantTests(TestCase):
    def setUp(self):
        self.a = Company.objects.create(name='Transportes Alfa')
        self.b = Company.objects.create(name='Transportes Beta')
        User = get_user_model()
        self.ua = User.objects.create_user(username='gestor-alfa', password='Senha-segura-123')
        self.ub = User.objects.create_user(username='gestor-beta', password='Senha-segura-123')
        Member.objects.create(company=self.a, user=self.ua, role=Member.MANAGER)
        Member.objects.create(company=self.b, user=self.ub, role=Member.MANAGER)
        self.status = VehicleStatus.objects.create(name='Disponível')
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.tmp.name)
        self.settings_override.enable()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.settings_override.disable)
        with scope(self.a, self.ua):
            self.va = Vehicle.objects.create(status=self.status, created_by=self.ua)
            VehiclePlate.objects.create(vehicle=self.va, plate='ABC1D23', kind='CURRENT', changed_by=self.ua)
            self.da = Driver.objects.create(name='Motorista Alfa')
        with scope(self.b, self.ub):
            self.vb = Vehicle.objects.create(status=self.status, created_by=self.ub)
            VehiclePlate.objects.create(vehicle=self.vb, plate='XYZ9Z99', kind='CURRENT', changed_by=self.ub)
            self.db = Driver.objects.create(name='Motorista Beta')
        self.client.force_login(self.ua)

    def test_lazy_querysets_caches_counts_aggregates_subqueries_and_iterators(self):
        lazy = Vehicle.objects.all()  # Constructed with no request scope.
        with scope(self.a, self.ua):
            self.assertEqual([v.pk for v in lazy], [self.va.pk])
            self.assertEqual(lazy.count(), 1)
            self.assertFalse(lazy.filter(pk=self.vb.pk).exists())
            self.assertEqual(lazy.aggregate(total=Count('pk'))['total'], 1)
            self.assertEqual(list(lazy.values_list('pk', flat=True).iterator()), [self.va.pk])
            self.assertEqual(VehiclePlate.objects.filter(vehicle_id__in=Subquery(lazy.values('pk'))).count(), 1)
        with scope(self.b, self.ub):
            self.assertEqual([v.pk for v in lazy], [self.vb.pk])
        self.assertIsNone(current_scope())

    def test_original_ui_all_modules_open_and_foreign_details_are_hidden(self):
        for path in ('/', '/veiculos/', '/motoristas/', '/manutencoes/', '/multas/', '/vistorias/', '/contratos/', '/ordens-saida/'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'XYZ9Z99')
                self.assertContains(response, 'Transportes Alfa')
        response = self.client.get(reverse('vehicle_dossier', kwargs={'pk': self.va.pk}))
        self.assertEqual(response.status_code, 200)
        vehicle_list = self.client.get('/veiculos/')
        self.assertNotContains(vehicle_list, 'Veículo Institucional')
        self.assertNotContains(vehicle_list, 'SEM SETOR')
        self.assertEqual(self.client.get(reverse('vehicle_dossier', kwargs={'pk': self.vb.pk})).status_code, 404)
        self.assertEqual(self.client.get(reverse('driver_edit', kwargs={'pk': self.db.pk})).status_code, 404)
        self.assertIsNone(current_scope())

    def test_legacy_api_class_level_queryset_is_scoped(self):
        api = APIClient()
        api.force_authenticate(self.ua)
        response = api.get('/api/vehicles/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn(str(self.vb.pk), str(response.data))
        self.assertIn(str(self.va.pk), str(response.data))
        self.assertEqual(api.get(f'/api/vehicles/{self.vb.pk}/').status_code, 404)
        self.assertIsNone(current_scope())

    def test_form_choices_and_pdf_fields_do_not_require_institutional_sectors(self):
        with scope(self.a, self.ua):
            self.assertNotIn('sectors', DriverForm(user=self.ua).fields)
            self.assertNotIn('sector', CRLVVehicleCreateForm().fields)
            self.assertNotIn('sector', VehiclePositionForm().fields)
            choices = MemberForm(company=self.a).fields['existing_driver'].queryset
            self.assertTrue(choices.filter(pk=self.da.pk).exists())
            self.assertFalse(choices.filter(pk=self.db.pk).exists())

    def test_bridge_new_vehicle_and_plate_are_available_for_driver_authorization(self):
        link = CompanyVehicle.objects.get(vehicle=self.va)
        self.assertEqual(link.company, self.a)
        self.assertEqual(link.label, 'ABC1D23')
        self.assertEqual(CompanyVehicle.objects.filter(vehicle=self.va).count(), 1)

    def test_save_update_delete_and_forged_foreign_keys(self):
        with scope(self.a, self.ua):
            self.assertEqual(Vehicle.objects.filter(pk=self.vb.pk).update(active=False), 0)
            self.assertEqual(Vehicle.objects.filter(pk=self.vb.pk).delete()[0], 0)
            with self.assertRaises(PermissionDenied):
                self.vb.delete()
            with self.assertRaises(PermissionDenied):
                self.vb.active = False
                self.vb.save()
            with self.assertRaises(PermissionDenied):
                VehiclePlate.objects.create(vehicle=self.vb, plate='QQQ1D23')
            with self.assertRaises(PermissionDenied):
                VehiclePlate.objects.filter(vehicle=self.va).update(vehicle=self.vb)
            with self.assertRaises(PermissionDenied):
                self.status.save()
        self.vb.refresh_from_db()
        self.assertTrue(self.vb.active)

    def test_private_catalogs_and_shared_catalog_write_protection(self):
        with scope(self.a, self.ua):
            own = VehicleStatus.objects.create(name='Status Alfa')
            self.assertEqual(VehicleStatus.objects.filter(pk=self.status.pk).update(name='No'), 0)
        with scope(self.b, self.ub):
            self.assertFalse(VehicleStatus.objects.filter(pk=own.pk).exists())
            self.assertTrue(VehicleStatus.objects.filter(pk=self.status.pk).exists())

    def test_direct_pdf_download_and_generic_document_links_are_isolated(self):
        with scope(self.a, self.ua):
            document = Document.objects.create(title='CNH Alfa', document_type=DocumentType.objects.create(name='CNH'), status=DocumentStatus.objects.create(name='Ativo'), created_by=self.ua)
            DocumentVersion.objects.create(document=document, file=SimpleUploadedFile('cnh.pdf', b'%PDF-1.4 teste'), original_filename='cnh.pdf', file_size=14, uploaded_by=self.ua)
            DocumentRelation.objects.create(document=document, content_type=ContentType.objects.get_for_model(Driver), object_id=self.da.pk, created_by=self.ua)
            with self.assertRaises(PermissionDenied):
                DocumentRelation.objects.create(document=document, content_type=ContentType.objects.get_for_model(Driver), object_id=self.db.pk, created_by=self.ua)
        url = f'/api/documents/{document.pk}/download/'
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.ub)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get('/media/documents/cnh.pdf').status_code, 403)

    def test_pdf_staging_preserves_original_and_audit_with_company_owner(self):
        from apps.fleet.services import stage_cnh_document_for_creation
        extracted = {'name': 'Motorista Alfa', 'cpf': '12345678901', 'cnh_number': '12345678902', 'raw_text': 'CNH teste'}
        with scope(self.a, self.ua), patch('apps.fleet.cnh.extract_cnh_data', return_value=extracted):
            document, values = stage_cnh_document_for_creation(file_obj=SimpleUploadedFile('cnh.pdf', b'%PDF-1.4 teste'), user=self.ua)
            self.assertEqual(values, extracted)
            self.assertEqual(document.versions.count(), 1)
            self.assertTrue(AuditLog.objects.filter(entity_id=document.pk).exists())
        with scope(self.b, self.ub):
            self.assertFalse(Document.objects.filter(pk=document.pk).exists())
            self.assertFalse(AuditLog.objects.filter(entity_id=document.pk).exists())

    def test_manager_can_link_pdf_driver_and_disable_access_without_privilege_escalation(self):
        response = self.client.post('/api/driver/management/', {'action': 'member', 'name': 'Motorista Alfa', 'username': 'alfa-driver', 'role': 'driver', 'password1': 'Senha-segura-987', 'password2': 'Senha-segura-987', 'existing_driver': str(self.da.pk)})
        self.assertEqual(response.status_code, 302)
        member = Member.objects.get(user__username='alfa-driver')
        self.assertEqual(member.driver, self.da)
        self.assertFalse(member.user.is_staff)
        response = self.client.post('/api/driver/management/', {'action': 'access', 'member': member.pk, 'active': 'false'})
        self.assertEqual(response.status_code, 302)
        member.refresh_from_db()
        self.assertFalse(member.active)
        foreign = Member.objects.get(user=self.ub)
        self.assertEqual(self.client.post('/api/driver/management/', {'action': 'access', 'member': foreign.pk, 'active': 'false'}).status_code, 404)

    def test_no_membership_driver_and_platform_boundaries(self):
        for path in ('/usuarios/', '/perfis/', '/admin/', '/api/sync/vehicles/'):
            self.assertEqual(self.client.get(path).status_code, 403)
        stranger = get_user_model().objects.create_user(username='sem-empresa')
        self.client.force_login(stranger)
        self.assertEqual(self.client.get('/').status_code, 403)
        stranger_member = Member.objects.create(user=stranger, company=self.a, driver=self.da, role=Member.DRIVER)
        self.assertEqual(self.client.get('/veiculos/').status_code, 403)
        stranger_member.active = False
        stranger_member.save()
        self.assertEqual(self.client.get('/api/driver/app/').status_code, 403)

    def test_platform_creates_company_and_first_manager_in_one_form(self):
        admin = get_user_model().objects.create_superuser(username='dono', password='Senha-segura-123')
        self.client.force_login(admin)
        self.assertEqual(self.client.get('/').url, '/api/driver/management/')
        response = self.client.post('/api/driver/management/', {'action': 'company', 'company_name': 'Nova Empresa', 'manager_name': 'Gestor Novo', 'email': 'gestor@example.com', 'username': 'novo-gestor', 'password1': 'Senha-segura-987', 'password2': 'Senha-segura-987'})
        self.assertEqual(response.status_code, 302)
        member = Member.objects.get(user__username='novo-gestor')
        self.assertEqual(member.company.name, 'Nova Empresa')
        self.assertEqual(member.role, Member.MANAGER)
        self.assertFalse(member.user.is_superuser)
        self.client.force_login(member.user)
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/api/driver/app/').url, '/')

    def test_migration_claims_only_explicit_roots_and_rejects_conflicting_graphs(self):
        migration = importlib.import_module('apps.driverops.migrations.0003_claim_existing_records')
        from django.apps import apps
        from django.db import connection
        RecordOwner.objects.all().delete()
        unlinked = Driver.objects.create(name='Sem vínculo')
        from types import SimpleNamespace
        migration.claim_existing(apps, SimpleNamespace(connection=connection))
        self.assertTrue(RecordOwner.objects.filter(company=self.a, object_id=self.va.pk).exists())
        self.assertFalse(RecordOwner.objects.filter(object_id=unlinked.pk).exists())
        link = CompanyVehicle.objects.get(vehicle=self.va)
        with self.assertRaises(PermissionDenied):
            link.company = self.b
            link.save()
        link.refresh_from_db()
        self.assertEqual(link.company, self.a)

    def test_cnh_upload_review_confirmation_and_foreign_document_rejection(self):
        extraction = {'name': 'Motorista PDF', 'cpf': '52998224725', 'cnh_number': '12345678901',
                      'cnh_category': 'AB', 'cnh_expiration': '', 'birth_date': '', 'cnh_issue_date': '', 'cnh_first_issue_date': '', 'text_extraction_succeeded': True, 'raw_text': 'CNH teste'}
        with patch('apps.fleet.cnh.extract_cnh_data', return_value=extraction):
            response = self.client.post('/motoristas/novo/', {'step': 'upload', 'file': SimpleUploadedFile('cnh.pdf', b'%PDF-1.4 teste')})
        self.assertEqual(response.status_code, 200)
        document = response.context['document']
        values = {'document_id': str(document.pk), 'name': 'Motorista PDF', 'cpf': '52998224725', 'cnh_number': '12345678901', 'cnh_category': 'AB'}
        self.client.force_login(self.ub)
        self.assertEqual(self.client.post('/motoristas/novo/', values).status_code, 404)
        self.client.force_login(self.ua)
        response = self.client.post('/motoristas/novo/', values)
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None))
        with scope(self.a, self.ua):
            driver = Driver.objects.get(name='Motorista PDF')
            self.assertEqual(driver.sectors.count(), 0)
            self.assertTrue(DocumentRelation.objects.filter(document=document, object_id=driver.pk).exists())
        with scope(self.b, self.ub):
            self.assertFalse(Driver.objects.filter(name='Motorista PDF').exists())

    def test_crlv_upload_review_confirmation_and_app_vehicle_bridge(self):
        extracted = {'plate': 'DEF2G34', 'exercise': 2026, 'brand_raw': 'VW', 'model_raw': 'POLO', 'raw_text': 'CRLV teste'}
        with patch('apps.fleet.crlv.extract_crlv_data', return_value=extracted):
            response = self.client.post('/veiculos/novo/', {'step': 'upload', 'file': SimpleUploadedFile('crlv.pdf', b'%PDF-1.4 teste')})
        self.assertEqual(response.status_code, 200)
        document = response.context['document']
        values = {'document_id': str(document.pk), 'plate': 'DEF2G34', 'exercise': '2026',
                  'brand': 'VW', 'model': 'POLO', 'status': str(self.status.pk)}
        self.client.force_login(self.ub)
        self.assertEqual(self.client.post('/veiculos/novo/', values).status_code, 404)
        self.client.force_login(self.ua)
        response = self.client.post('/veiculos/novo/', values)
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None))
        link = CompanyVehicle.objects.get(company=self.a, label='DEF2G34')
        with scope(self.a, self.ua):
            self.assertIsNone(link.vehicle.sector_id)
            self.assertTrue(DocumentRelation.objects.filter(document=document, object_id=link.vehicle_id).exists())
        with scope(self.b, self.ub):
            self.assertFalse(Vehicle.objects.filter(pk=link.vehicle_id).exists())

    def test_password_reset_rejects_foreign_account_and_audits_without_password(self):
        self.assertEqual(self.client.post('/api/driver/management/', {'action': 'password', 'member': Member.objects.get(user=self.ub).pk, 'new_password1': 'Nova-senha-987', 'new_password2': 'Nova-senha-987'}).status_code, 404)
        other = get_user_model().objects.create_user(username='gestor-auxiliar')
        member = Member.objects.create(user=other, company=self.a, role=Member.MANAGER)
        response = self.client.post('/api/driver/management/', {'action': 'password', 'member': member.pk, 'new_password1': 'Nova-senha-987', 'new_password2': 'Nova-senha-987'})
        self.assertEqual(response.status_code, 302)
        other.refresh_from_db()
        self.assertTrue(other.check_password('Nova-senha-987'))
        self.assertNotIn('Nova-senha-987', str(list(AuditLog.objects.values())))

    def test_shared_catalog_reverse_joins_and_counts_do_not_cross_companies(self):
        from apps.fleet.models import Brand
        brand = Brand.objects.create(name='Marca Compartilhada')
        self.va.brand = brand
        self.va.save(update_fields=['brand'])
        self.vb.brand = brand
        self.vb.save(update_fields=['brand'])
        with scope(self.a, self.ua):
            self.assertEqual(Brand.objects.annotate(total=Count('vehicle')).get(pk=brand.pk).total, 1)
            self.assertEqual(list(Brand.objects.filter(pk=brand.pk).values_list('vehicle__pk', flat=True)), [self.va.pk])
            self.assertFalse(Brand.objects.filter(vehicle__pk=self.vb.pk).exists())
            # A join through our vehicle's public brand must not fan out into another fleet.
            self.assertEqual(list(Vehicle.objects.filter(pk=self.va.pk).values_list('brand__vehicle__pk', flat=True)), [self.va.pk])

    @override_settings(DEBUG=True)
    def test_company_login_accepts_username_and_requires_password_even_in_debug(self):
        self.ua.email = "gestor-alfa@example.com"
        self.ua.save(update_fields=["email"])
        self.client.logout()
        response = self.client.get('/entrar/')
        self.assertContains(response, 'Login ou e-mail')
        self.assertContains(response, 'type="text"')
        response = self.client.post('/entrar/', {'username': self.ua.email, 'password': 'incorreta'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        response = self.client.post('/entrar/', {'username': self.ua.username, 'password': 'Senha-segura-123'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/')

    def test_manager_login_ignores_driver_app_next_and_preserves_desktop_links(self):
        for destination in ('/api/driver/management/', '/api/driver/app/', '/api/driver/panel/', 'http://testserver/api/driver/management/'):
            with self.subTest(destination=destination):
                self.client.logout()
                response = self.client.post('/entrar/', {'username': self.ua.username, 'password': 'Senha-segura-123', 'next': destination})
                self.assertRedirects(response, '/', fetch_redirect_response=False)
        self.client.logout()
        response = self.client.post('/entrar/', {'username': self.ua.username, 'password': 'Senha-segura-123', 'next': '/veiculos/'})
        self.assertRedirects(response, '/veiculos/', fetch_redirect_response=False)

    def test_already_authenticated_manager_login_does_not_reuse_driver_next(self):
        response = self.client.get('/entrar/?next=/api/driver/management/')
        self.assertRedirects(response, '/', fetch_redirect_response=False)

    def test_driver_login_always_opens_app_even_with_desktop_next(self):
        user = get_user_model().objects.create_user(username='motorista-login', password='Senha-segura-123')
        Member.objects.create(company=self.a, user=user, driver=self.da, role=Member.DRIVER)
        self.client.logout()
        response = self.client.post('/entrar/', {'username': user.username, 'password': 'Senha-segura-123', 'next': '/'})
        self.assertRedirects(response, '/api/driver/app/', fetch_redirect_response=False)
