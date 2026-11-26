import uuid
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.driverops.models import Company, Member
from apps.fleet.models import Driver, Vehicle, VehicleDriverAssignment, BDT, AuditLog, VehicleExitOrder, VehicleStatus
from apps.fleet.tenant_scope import Scope, set_scope, reset_scope


@override_settings(CENTRAL_USER_MANAGEMENT=True, ROOT_URLCONF='config.driver_urls')
class DriverDeleteTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Empresa')
        self.user = get_user_model().objects.create_user(username='gestor-exclusao')
        Member.objects.create(user=self.user, company=self.company, role=Member.MANAGER)
        token = set_scope(Scope(company_id=self.company.pk, actor_id=self.user.pk))
        try:
            self.driver = Driver.objects.create(name='Motorista com histórico', horus_user_id=uuid.uuid4())
            self.vehicle = Vehicle.objects.create(status=VehicleStatus.objects.create(name="Disponível"))
            self.assignment = VehicleDriverAssignment.objects.create(driver=self.driver, vehicle=self.vehicle)
            self.bdt = BDT.objects.create(driver=self.driver, vehicle=self.vehicle, external_id=uuid.uuid4(), ended_at=timezone.now())
        finally:
            reset_scope(token)
        self.client.force_login(self.user)
        self.url = reverse('driver_delete', args=[self.driver.pk])
        self.data = {'reason': 'Motorista desligado da empresa.', 'confirmed': 'on'}

    def test_confirmation_required_and_history_preserved_with_audit(self):
        self.assertContains(self.client.get(self.url), 'Confirmar exclusão')
        self.driver.refresh_from_db(); self.assertTrue(self.driver.active)
        self.assertEqual(self.client.post(self.url, {'reason': self.data['reason']}).status_code, 200)
        self.driver.refresh_from_db(); self.assertTrue(self.driver.active)
        self.assertEqual(self.client.post(self.url, self.data).status_code, 302)
        self.driver.refresh_from_db(); self.assertFalse(self.driver.active)
        self.assignment.refresh_from_db(); self.assertFalse(self.assignment.is_active)
        self.assertIsNotNone(self.assignment.ends_on)
        self.assertTrue(BDT.objects.filter(pk=self.bdt.pk, driver=self.driver).exists())
        self.assertIsNotNone(self.driver.horus_user_id)
        audit = AuditLog.objects.get(action='EXCLUSÃO DE MOTORISTA')
        self.assertEqual(audit.user, self.user)
        self.assertEqual(audit.reason, self.data['reason'])
        self.client.post(self.url, self.data)
        self.assertEqual(AuditLog.objects.filter(action='EXCLUSÃO DE MOTORISTA').count(), 1)
        self.assertNotContains(self.client.get(reverse('driver_list')), self.driver.name)
        self.assertContains(self.client.get(reverse('driver_list')+'?status=inactive'), self.driver.name)

    def test_pending_exit_or_bdt_blocks_removal(self):
        self.bdt.ended_at = None; self.bdt.save()
        self.assertContains(self.client.post(self.url, self.data), 'Encerre o BDT aberto')
        self.bdt.horus_active = False; self.bdt.save()
        order = VehicleExitOrder.objects.create(number='OS-TESTE', vehicle=self.vehicle, driver=self.driver,
            departed_at=timezone.now(), destination='Destino', reason='Serviço', opened_by=self.user)
        self.assertContains(self.client.post(self.url, self.data), 'Encerre a ordem de saída')
        self.driver.refresh_from_db(); self.assertTrue(self.driver.active)
        self.assertFalse(AuditLog.objects.filter(action='EXCLUSÃO DE MOTORISTA').exists())

    def test_active_app_account_must_be_deactivated_first(self):
        user = get_user_model().objects.create_user(username='motorista-app-exclusao')
        Member.objects.create(user=user, driver=self.driver, company=self.company, role=Member.DRIVER)
        self.assertContains(self.client.post(self.url, self.data), 'Desative o acesso')
        self.driver.refresh_from_db(); self.assertTrue(self.driver.active)

    def test_operator_and_other_company_cannot_delete(self):
        operator = get_user_model().objects.create_user(username='operador-exclusao')
        Member.objects.create(user=operator, company=self.company, role=Member.OPERATOR)
        self.client.force_login(operator)
        self.assertEqual(self.client.post(self.url, self.data).status_code, 403)
        self.assertNotContains(self.client.get(reverse('driver_list')), '>Excluir</a>')
        other = Company.objects.create(name='Outra empresa')
        outsider = get_user_model().objects.create_user(username='gestor-outra-exclusao')
        Member.objects.create(user=outsider, company=other, role=Member.MANAGER)
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, self.data).status_code, 404)
        self.driver.refresh_from_db(); self.assertTrue(self.driver.active)
