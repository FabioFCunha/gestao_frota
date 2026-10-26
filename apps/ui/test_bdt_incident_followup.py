import uuid
from contextlib import contextmanager
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.test import TestCase, RequestFactory
from django.utils import timezone

from apps.fleet.bdt_incidents import update_bdt_incident
from apps.fleet.models import (
    AuditLog, BDT, BDTIncidentFollowUp, BDTIncidentUpdate, Sector, Vehicle, VehicleStatus,
)
from apps.fleet.tenant_scope import Scope, set_scope, reset_scope
from apps.ui.views import vehicle_dossier


class BDTIncidentFollowUpTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='gestor-avarias')
        self.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='fleet', codename__in=['change_bdt', 'view_vehicle'],
        ))
        self.adm = Sector.objects.get(slug='adm')
        self.other_sector = Sector.objects.get(slug='lei-seca')
        self.user.sectors.add(self.adm)
        self.vehicle = Vehicle.objects.create(status=VehicleStatus.objects.create(name='Operacional'), sector=self.adm)
        self.bdt = BDT.objects.create(vehicle=self.vehicle, external_id=uuid.uuid4(),
                                     note='O pneu furou na porta da Garagem', started_at=timezone.now(),
                                     started_km='100', ended_km='120')

    def update(self, **kwargs):
        values = dict(bdt_id=self.bdt.pk, vehicle_id=self.vehicle.pk, user=self.user,
                      status='IN_REVIEW', responsible='Administração SEGOV',
                      note='Encaminhado para avaliação.', expected_revision=0)
        values.update(kwargs)
        return update_bdt_incident(**values)

    def test_preserves_source_and_records_each_transition_and_author(self):
        followup = self.update()
        self.update(status='RESOLVED', note='Pneu substituído.', expected_revision=1)
        self.update(status='PENDING', note='Reaberto para nova avaliação.', expected_revision=2)
        self.bdt.refresh_from_db()
        followup.refresh_from_db()
        self.assertEqual(self.bdt.note, 'O pneu furou na porta da Garagem')
        self.assertEqual(self.bdt.started_km, '100')
        self.assertEqual(followup.revision, 3)
        self.assertEqual(followup.status, 'PENDING')
        self.assertEqual(followup.history.count(), 3)
        self.assertEqual(followup.history.first().author, self.user)
        self.assertEqual(AuditLog.objects.filter(entity_id=self.bdt.pk).count(), 3)

    def test_rejects_stale_submission_without_extra_history(self):
        self.update()
        with self.assertRaisesMessage(ValidationError, 'outra pessoa'):
            self.update(status='RESOLVED')
        self.assertEqual(BDTIncidentUpdate.objects.count(), 1)

    def test_requires_status_responsible_and_note(self):
        for changes in ({'status': 'INVALID'}, {'responsible': ' '}, {'note': ' '}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.update(**changes)
        self.assertFalse(BDTIncidentFollowUp.objects.exists())

    def test_read_only_user_cannot_write(self):
        reader = get_user_model().objects.create_user(username='consulta-avarias')
        reader.sectors.add(self.adm)
        with self.assertRaises(PermissionDenied):
            self.update(user=reader)
        self.assertFalse(BDTIncidentUpdate.objects.exists())

    def test_bdt_cannot_be_submitted_under_another_vehicle(self):
        other = Vehicle.objects.create(status=self.vehicle.status, sector=self.adm)
        with self.assertRaises(Http404):
            self.update(vehicle_id=other.pk)

    def test_other_sector_cannot_write(self):
        self.vehicle.sector = self.other_sector
        self.vehicle.save(update_fields=['sector'])
        from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
        with self.assertRaises(DRFPermissionDenied):
            self.update()

    def test_normal_bdt_cannot_start_followup_but_existing_survives_sync(self):
        self.bdt.note = 'Sem avarias'
        self.bdt.save(update_fields=['note'])
        with self.assertRaises(ValidationError):
            self.update()
        self.bdt.note = 'Pneu furado'
        self.bdt.save(update_fields=['note'])
        self.update()
        self.bdt.note = 'Texto atualizado na origem'
        self.bdt.save(update_fields=['note'])
        self.update(status='RESOLVED', expected_revision=1)
        self.assertEqual(BDTIncidentUpdate.objects.count(), 2)

    def test_audit_failure_rolls_back_state_and_history(self):
        with patch.object(AuditLog.objects, 'create', side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):
                self.update()
        self.assertFalse(BDTIncidentFollowUp.objects.exists())
        self.assertFalse(BDTIncidentUpdate.objects.exists())

    def request(self, data=None):
        factory = RequestFactory()
        path = f'/veiculos/{self.vehicle.pk}/?bdt_page=1&sector=adm'
        request = factory.post(path, data) if data is not None else factory.get(path)
        request.user = self.user
        return vehicle_dossier(request, self.vehicle.pk)

    def test_dossier_renders_implicit_pending_and_saved_history_only_in_table(self):
        response = self.request()
        self.assertContains(response, 'Acompanhar')
        self.assertContains(response, 'Pendente')
        self.update(status='RESOLVED', note='Pneu substituído e veículo liberado.')
        response = self.request()
        self.assertContains(response, 'Resolvido')
        self.assertContains(response, 'Pneu substituído e veículo liberado.')
        self.assertNotContains(response, 'Atenção — possíveis sinistros')

    def test_post_preserves_navigation_and_invalid_input(self):
        prefix = f'incident-{self.bdt.pk}'
        data = {'action': 'update_bdt_incident', 'bdt_id': str(self.bdt.pk),
                prefix + '-status': 'IN_REVIEW', prefix + '-responsible': 'Equipe SEGOV',
                prefix + '-note': 'Conferir pneu.', prefix + '-expected_revision': '0'}
        response = self.request(data)
        self.assertEqual(response.status_code, 302)
        self.assertIn('bdt_page=1', response.url)
        self.assertTrue(response.url.endswith('#bdt-utilizacao'))
        data[prefix + '-note'] = ''
        response = self.request(data)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'Equipe SEGOV', status_code=400)
        self.assertEqual(BDTIncidentUpdate.objects.count(), 1)

    def test_read_only_dossier_hides_edit_form(self):
        reader = get_user_model().objects.create_user(username='leitor-prontuario')
        reader.user_permissions.add(Permission.objects.get(content_type__app_label='fleet', codename='view_vehicle'))
        reader.sectors.add(self.adm)
        self.user = reader
        response = self.request()
        self.assertContains(response, 'Ver acompanhamento')
        self.assertNotContains(response, 'Salvar providência')


@skipUnless(apps.is_installed('apps.driverops'), 'Requer configuração com empresas')
class BDTIncidentCompanyTests(TestCase):
    @contextmanager
    def scope(self, company, user):
        token = set_scope(Scope(company_id=company.pk, actor_id=user.pk))
        try:
            yield
        finally:
            reset_scope(token)

    def setUp(self):
        from apps.driverops.models import Company, Member
        self.a = Company.objects.create(name='Empresa A')
        self.b = Company.objects.create(name='Empresa B')
        self.user = get_user_model().objects.create_user(username='gestor-avaria-empresa')
        self.other_user = get_user_model().objects.create_user(username='gestor-outra-empresa')
        Member.objects.create(company=self.a, user=self.user, role=Member.MANAGER)
        Member.objects.create(company=self.b, user=self.other_user, role=Member.MANAGER)
        self.status = VehicleStatus.objects.create(name='Disponível')
        with self.scope(self.a, self.user):
            self.vehicle = Vehicle.objects.create(status=self.status)
            self.bdt = BDT.objects.create(vehicle=self.vehicle, external_id=uuid.uuid4(), note='Pneu furado')

    def test_company_can_update_and_other_company_cannot_read_or_write(self):
        values = dict(bdt_id=self.bdt.pk, vehicle_id=self.vehicle.pk,
                      status='RESOLVED', responsible='Oficina', note='Pneu substituído.', expected_revision=0)
        with self.scope(self.a, self.user):
            update_bdt_incident(user=self.user, **values)
            self.assertEqual(BDTIncidentFollowUp.objects.count(), 1)
        with self.scope(self.b, self.other_user):
            self.assertFalse(BDTIncidentFollowUp.objects.exists())
            self.assertFalse(BDTIncidentUpdate.objects.exists())
            with self.assertRaises(Http404):
                update_bdt_incident(user=self.other_user, **values)

    def test_company_dossier_shows_saved_state_and_history(self):
        with self.scope(self.a, self.user):
            update_bdt_incident(
                bdt_id=self.bdt.pk, vehicle_id=self.vehicle.pk, user=self.user,
                status='RESOLVED', responsible='Oficina', note='Pneu substituído.', expected_revision=0,
            )
            request = RequestFactory().get(f'/veiculos/{self.vehicle.pk}/')
            request.user = self.user
            response = vehicle_dossier(request, self.vehicle.pk)
            self.assertContains(response, 'Resolvido')
            self.assertContains(response, 'Pneu substituído.')

    def test_company_viewer_cannot_change_followup(self):
        from apps.driverops.models import Member
        Member.objects.filter(user=self.user).update(role=Member.VIEWER)
        with self.scope(self.a, self.user), self.assertRaises(PermissionDenied):
            update_bdt_incident(
                bdt_id=self.bdt.pk, vehicle_id=self.vehicle.pk, user=self.user,
                status='RESOLVED', responsible='Oficina', note='Pneu substituído.', expected_revision=0,
            )

    def test_post_requires_csrf_token(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(f'/veiculos/{self.vehicle.pk}/', {
            'action': 'update_bdt_incident', 'bdt_id': str(self.bdt.pk),
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(BDTIncidentFollowUp.objects.exists())
